"""Cutline web app: landing page, upload, one-click auto edit, chat editing, downloads.

    cutline-web                  # http://localhost:8080
    cutline-web --port 9000

Chat editing needs ANTHROPIC_API_KEY in the server's environment. Everything else (upload,
auto edit, Shorts, downloads) works without it.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import agent, project as P

SITE = Path(__file__).parent / "site"
MAX_UPLOAD_MB = int(os.environ.get("CUTLINE_MAX_UPLOAD_MB", "2048"))
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
RETENTION_DAYS = float(os.environ.get("CUTLINE_RETENTION_DAYS", "7"))
# Renders are CPU and memory heavy; a small server should run one or two at a time and queue the rest.
_slots = threading.BoundedSemaphore(max(1, int(os.environ.get("CUTLINE_MAX_JOBS", "1"))))
_jobs: dict[str, dict] = {}  # project id -> {"state", "step", "error"}
_lock = threading.Lock()


# ---- beta access code: when CUTLINE_ACCESS_CODE is set, uploads and edits need it ----

def _access_code() -> str:
    return os.environ.get("CUTLINE_ACCESS_CODE", "").strip()


def _has_access(request: Request) -> bool:
    code = _access_code()
    return not code or hmac.compare_digest(request.cookies.get("cutline_code", ""), code)


class AccessGate(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if (path.startswith("/api/projects") or path.startswith("/files/")) and not _has_access(request):
            return JSONResponse({"error": "Enter your beta access code first", "need_code": True}, status_code=401)
        return await call_next(request)


def _uploads() -> Path:
    d = P.home().parent / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_job(pid: str, **kw) -> None:
    with _lock:
        _jobs.setdefault(pid, {"state": "idle", "step": "", "error": None}).update(kw)


def _job(pid: str) -> dict:
    with _lock:
        return dict(_jobs.get(pid, {"state": "idle", "step": "", "error": None}))


def _busy(pid: str) -> bool:
    return _job(pid)["state"] == "running"


def _err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


def _state(pid: str) -> dict:
    p = P.load(pid)
    s = P.summary(p)
    s.pop("source", None)  # don't leak server paths to the browser
    s["filename"] = Path(p.source).name.split("_", 1)[-1]
    s["outputs"] = {
        k: f"/files/{pid}/{Path(v).name}?t={int(Path(v).stat().st_mtime)}"
        for k, v in p.outputs.items()
        if Path(v).exists()
    }
    s["job"] = _job(pid)
    s["chat"] = [m for m in _load_chat(pid) if m["role"] in ("user", "assistant")]
    s["chat_enabled"] = agent.has_key()
    return s


# ---- chat history: what the creator sees, plus the raw API messages for the next turn ----

def _chat_file(pid: str) -> Path:
    return P._dir(pid) / "chat.json"


def _load_chat(pid: str) -> list[dict]:
    f = _chat_file(pid)
    return json.loads(f.read_text())["visible"] if f.exists() else []


def _load_api(pid: str) -> list[dict]:
    f = _chat_file(pid)
    return json.loads(f.read_text())["api"] if f.exists() else []


def _save_chat(pid: str, visible: list[dict], api: list[dict]) -> None:
    # Write then rename: the page polls state while a chat turn saves, and must never read a half-written file.
    f = _chat_file(pid)
    tmp = f.with_name(f"chat.json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"visible": visible, "api": api}))
    os.replace(tmp, f)


# ---- background jobs ----

def _run(pid: str, fn) -> None:
    def work():
        try:
            if not _slots.acquire(blocking=False):
                _set_job(pid, step="Waiting for a free editor")
                _slots.acquire()
            try:
                fn()
            finally:
                _slots.release()
            _set_job(pid, state="done", step="")
        except Exception as e:  # surface the reason in the UI
            _set_job(pid, state="error", step="", error=str(e))

    _set_job(pid, state="running", step="Starting", error=None)
    threading.Thread(target=work, daemon=True).start()


def _auto(pid: str, shorts: int, captions: str, transcribe: bool) -> None:
    p = P.load(pid)
    _set_job(pid, step="Finding silences" + (" and transcribing" if transcribe else ""))
    try:
        p = P.analyze(p, do_transcribe=transcribe)
    except (ImportError, RuntimeError) as e:
        if "faster-whisper" not in str(e) and isinstance(e, RuntimeError):
            raise
        # Whisper not installed on this server: still cut silences.
        p = P.analyze(p, do_transcribe=False)
    _set_job(pid, step="Rendering the long cut")
    P.render_long(p)
    if p.transcript and p.transcript.words and shorts:
        _set_job(pid, step=f"Making {shorts} Shorts with captions")
        P.set_shorts(p, P.suggest_shorts(p, shorts))
        p.edits.captions.preset = captions
        P.save(p)
        P.render_shorts(p)


def _chat_turn(pid: str, text: str) -> None:
    visible = _load_chat(pid)
    visible.append({"role": "user", "text": text, "at": time.time()})
    _save_chat(pid, visible, _load_api(pid))
    _set_job(pid, step="Thinking")
    try:
        reply, api = agent.chat(pid, _load_api(pid), text, on_tool=lambda n: _set_job(pid, step=_step_label(n)))
    except Exception as e:
        reply, api = f"Something went wrong: {e}", _load_api(pid)
    visible.append({"role": "assistant", "text": reply, "at": time.time()})
    _save_chat(pid, visible, api)


def _step_label(tool: str) -> str:
    return {
        "analyze": "Transcribing and finding silences",
        "get_transcript": "Reading the transcript",
        "remove_ranges": "Cutting",
        "restore_ranges": "Restoring",
        "add_shorts": "Picking Shorts",
        "suggest_shorts": "Picking Shorts",
        "render": "Rendering",
        "set_color_grade": "Adjusting color and lighting",
        "add_text": "Adding text",
        "update_text": "Updating text",
        "remove_text": "Removing text",
        "list_fonts": "Checking fonts",
        "ai_edit_scene": "Generating the AI scene edit",
        "make_montage": "Building the montage",
    }.get(tool, tool.replace("_", " ").capitalize())


# ---- routes ----

async def upload(request: Request) -> JSONResponse:
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD_MB * 1024 * 1024:
        return _err(f"That file is over {MAX_UPLOAD_MB} MB", 413)
    form = await request.form(max_part_size=MAX_UPLOAD_MB * 1024 * 1024)
    f = form.get("video")
    if f is None or not getattr(f, "filename", None):
        return _err("Attach a video file")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(f.filename).name)[-80:]
    if Path(name).suffix.lower() not in VIDEO_EXT:
        return _err("Upload an MP4, MOV, MKV or WebM video")
    dest = _uploads() / f"{int(time.time() * 1000)}_{name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(f.file, out, 1024 * 1024)
    await f.close()
    try:
        p = P.create(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        return _err(f"Couldn't read that video: {e}")
    return JSONResponse(_state(p.id))


async def get_state(request: Request) -> JSONResponse:
    try:
        return JSONResponse(_state(request.path_params["pid"]))
    except ValueError as e:
        return _err(str(e), 404)


async def auto(request: Request) -> JSONResponse:
    pid = request.path_params["pid"]
    try:
        P.load(pid)
    except ValueError as e:
        return _err(str(e), 404)
    if _busy(pid):
        return _err("Still working on the last request", 409)
    body = await request.json() if await request.body() else {}
    shorts = max(0, min(10, int(body.get("shorts", 3))))
    captions = body.get("captions", "bold")
    if captions not in ("bold", "clean", "karaoke"):
        captions = "bold"
    _run(pid, lambda: _auto(pid, shorts, captions, bool(body.get("transcribe", True))))
    return JSONResponse(_state(pid))


async def chat(request: Request) -> JSONResponse:
    pid = request.path_params["pid"]
    try:
        P.load(pid)
    except ValueError as e:
        return _err(str(e), 404)
    if not agent.has_key():
        return _err("Chat editing isn't switched on for this server yet (it needs a Claude API key).", 503)
    if _busy(pid):
        return _err("Still working on the last request", 409)
    text = str((await request.json()).get("message", "")).strip()[:4000]
    if not text:
        return _err("Type what you want changed")
    _run(pid, lambda: _chat_turn(pid, text))
    return JSONResponse(_state(pid))


async def waitlist(request: Request) -> JSONResponse:
    body = await request.json()
    email = str(body.get("email", "")).strip()[:200]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return _err("Enter a valid email")
    rec = {"email": email, "channel": str(body.get("channel", ""))[:200], "at": time.time()}
    with (P.home().parent / "waitlist.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return JSONResponse({"ok": True})


async def files(request: Request):
    pid, name = request.path_params["pid"], request.path_params["name"]
    try:
        d = P._dir(pid)
    except ValueError:
        return _err("Not found", 404)
    f = (d / name).resolve()
    if f.parent != d.resolve() or not f.is_file() or f.suffix != ".mp4":
        return _err("Not found", 404)
    download = request.query_params.get("download") is not None
    return FileResponse(f, media_type="video/mp4", filename=name if download else None)


async def access(request: Request) -> JSONResponse:
    if request.method == "POST":
        code = str((await request.json()).get("code", "")).strip()
        if not _access_code() or not hmac.compare_digest(code, _access_code()):
            return _err("That code didn't work", 403)
        r = JSONResponse({"required": True, "ok": True})
        r.set_cookie("cutline_code", code, max_age=60 * 60 * 24 * 90, httponly=True, samesite="lax",
                     secure=request.url.scheme == "https")
        return r
    return JSONResponse({"required": bool(_access_code()), "ok": _has_access(request)})


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "chat_enabled": agent.has_key(),
                         "version": os.environ.get("CUTLINE_VERSION", "unknown"), "text_tools": True})


# ---- cleanup: uploads and renders older than CUTLINE_RETENTION_DAYS are deleted ----

def cleanup(now: float | None = None) -> int:
    cutoff = (now or time.time()) - RETENTION_DAYS * 86400
    removed = 0
    for d in P.home().iterdir():
        last = max((f.stat().st_mtime for f in d.iterdir()), default=d.stat().st_mtime) if d.is_dir() else 0
        if d.is_dir() and last < cutoff and not _busy(d.name):
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    for f in _uploads().iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def _cleanup_loop() -> None:
    while True:
        try:
            cleanup()
        except Exception:
            pass
        time.sleep(3600)


async def app_page(request: Request):
    return FileResponse(SITE / "app.html")


async def studio_page(request: Request):
    return FileResponse(SITE / "studio.html")


async def content_page(request: Request):
    return FileResponse(SITE / "content.html")


async def home_page(request: Request):
    return FileResponse(SITE / "index.html")


routes = [
    Route("/", home_page),
    Route("/studio", studio_page),
    Route("/content", content_page),
    Route("/app", app_page),
    Route("/app/", lambda r: RedirectResponse("/app")),
    Route("/api/projects", upload, methods=["POST"]),
    Route("/api/projects/{pid}", get_state),
    Route("/api/projects/{pid}/auto", auto, methods=["POST"]),
    Route("/api/projects/{pid}/chat", chat, methods=["POST"]),
    Route("/api/waitlist", waitlist, methods=["POST"]),
    Route("/api/access", access, methods=["GET", "POST"]),
    Route("/healthz", health),
    Route("/files/{pid}/{name}", files),
    Mount("/static", StaticFiles(directory=SITE), name="static"),
]

app = Starlette(routes=routes, middleware=[Middleware(AccessGate)])


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(prog="cutline-web")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    a = ap.parse_args()
    if RETENTION_DAYS > 0:
        threading.Thread(target=_cleanup_loop, daemon=True).start()
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
