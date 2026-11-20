"""AI scene edits through the Higgsfield API: "put my car in space", "make the car red", "swap the background".

Flow: trim the source moment to a short clip -> upload it -> submit a video-edit job -> poll -> download.
Docs: https://docs.higgsfield.ai/docs  (auth header: "Authorization: Key <id>:<secret>").

Set HIGGSFIELD_API_KEY_ID and HIGGSFIELD_API_KEY_SECRET (keys from https://console.higgsfield.ai).
API usage is billed per second from a prepaid balance, separate from higgsfield.ai app credits.
"""

from __future__ import annotations

import os
import random
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = os.environ.get("HIGGSFIELD_BASE_URL", "https://api.higgsfield.ai")

# name -> (endpoint, source-length limits in seconds, how the source video is passed)
MODELS = {
    "kling-o3": ("kling-video/o3/video-edit", (3.0, 15.5), "video_urls"),
    "kling-omni": ("kling-video/omni/video-edit", (3.0, 10.0), "video_urls"),
    # Seedance limits are not stated in the docs; 4-15s is a conservative guess until tested.
    "seedance": ("bytedance/seedance-2.5/video-edit", (4.0, 15.0), "video_url"),
}
DEFAULT_MODEL = "kling-o3"
TERMINAL = {"completed", "failed", "nsfw", "canceled"}


class GenerativeError(RuntimeError):
    pass


@dataclass
class EditResult:
    request_id: str
    status: str
    video_url: str | None
    local_path: str | None = None


def _auth() -> dict[str, str]:
    kid, secret = os.environ.get("HIGGSFIELD_API_KEY_ID"), os.environ.get("HIGGSFIELD_API_KEY_SECRET")
    if not kid or not secret:
        raise GenerativeError(
            "AI scene edits need a Higgsfield API key: set HIGGSFIELD_API_KEY_ID and "
            "HIGGSFIELD_API_KEY_SECRET (create one at https://console.higgsfield.ai)."
        )
    return {"Authorization": f"Key {kid}:{secret}"}


class HiggsfieldClient:
    def __init__(self, http: httpx.Client | None = None, sleep=time.sleep):
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=60)
        self.sleep = sleep

    def upload(self, path: str, content_type: str = "video/mp4") -> str:
        """Upload a local file and return its public URL for use as a model input."""
        r = self.http.post("/files/generate-upload-url", json={"content_type": content_type}, headers=_auth())
        r.raise_for_status()
        info = r.json()
        with open(path, "rb") as f:
            # Presigned URL: send only the headers it asks for, never our API credentials.
            put = httpx.put(info["upload_url"], content=f.read(), headers=info.get("upload_headers") or {}, timeout=300)
        put.raise_for_status()
        return info["public_url"]

    def submit_edit(self, video_url: str, prompt: str, model: str = DEFAULT_MODEL,
                    image_urls: list[str] | None = None, quality: str | None = None) -> str:
        if model not in MODELS:
            raise GenerativeError(f"Unknown model '{model}'. Choose from: {', '.join(MODELS)}")
        endpoint, _, field = MODELS[model]
        body: dict = {"prompt": prompt, field: [video_url] if field == "video_urls" else video_url}
        if image_urls:
            body["image_urls"] = image_urls[:4]
        if quality:
            body["resolution" if model == "seedance" else "mode"] = quality
        r = self.http.post(f"/{endpoint}", json=body, headers={**_auth(), "Idempotency-Key": str(uuid.uuid4())})
        if r.status_code >= 400:
            raise GenerativeError(f"Higgsfield rejected the edit ({r.status_code}): {r.text[:500]}")
        return r.json()["request_id"]

    def wait(self, request_id: str, timeout: float = 900) -> EditResult:
        delay, waited = 2.0, 0.0
        while True:
            r = self.http.get(f"/requests/{request_id}/status", headers=_auth())
            r.raise_for_status()
            data = r.json()
            status = data.get("status", "unknown")
            if status in TERMINAL:
                if status != "completed":
                    raise GenerativeError(f"Edit {status}: {data.get('error') or 'no details'}")
                return EditResult(request_id, status, (data.get("video") or {}).get("url"))
            if waited > timeout:
                raise GenerativeError(f"Edit still {status} after {int(timeout)}s (request {request_id})")
            pause = delay + random.uniform(0, 0.5)
            self.sleep(pause)
            waited += pause
            delay = min(delay * 1.5, 10.0)

    def download(self, url: str, out_path: str) -> str:
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return out_path


def trim(source: str, start: float, end: float, out_path: str) -> str:
    """Cut the moment to edit into its own MP4 (the edit models take short clips)."""
    r = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", source,
        "-t", f"{end - start:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", out_path,
    ], capture_output=True, text=True)
    if r.returncode != 0:
        raise GenerativeError(f"Could not trim source: {r.stderr[-500:]}")
    return out_path


def check_length(model: str, seconds: float) -> None:
    lo, hi = MODELS[model][1]
    if not lo <= seconds <= hi:
        raise GenerativeError(f"{model} edits clips of {lo:g}-{hi:g}s; this one is {seconds:.1f}s")


def edit_scene(source: str, start: float, end: float, prompt: str, out_path: str,
               model: str = DEFAULT_MODEL, quality: str | None = None,
               client: HiggsfieldClient | None = None) -> EditResult:
    check_length(model, end - start)
    client = client or HiggsfieldClient()
    clip = str(Path(out_path).with_suffix(".source.mp4"))
    trim(source, start, end, clip)
    url = client.upload(clip)
    rid = client.submit_edit(url, prompt, model=model, quality=quality)
    result = client.wait(rid)
    if not result.video_url:
        raise GenerativeError(f"Edit {rid} finished without a video URL")
    result.local_path = client.download(result.video_url, out_path)
    return result
