"""Web app: upload, auto edit, file serving, waitlist, and the chat loop with a fake Claude client."""

import subprocess
import time
from types import SimpleNamespace as NS

import pytest
from starlette.testclient import TestClient

from cutline import agent, project as P, web


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CUTLINE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    return TestClient(web.app)


@pytest.fixture
def clip(tmp_path):
    out = tmp_path / "my talk.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=8",
        "-filter_complex", "[1:a]volume='if(between(t,0,3)+between(t,5,8),1,0)':eval=frame[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(out),
    ], check=True)
    return out


def wait(c, pid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f"/api/projects/{pid}").json()
        if s["job"]["state"] != "running":
            return s
        time.sleep(0.3)
    raise AssertionError("job did not finish")


def test_pages(client):
    assert "Cutline" in client.get("/").text
    assert 'id="upload-view"' in client.get("/app").text
    assert client.get("/static/app.js").status_code == 200


def test_upload_auto_and_download(client, clip):
    with clip.open("rb") as f:
        r = client.post("/api/projects", files={"video": ("my talk.mp4", f, "video/mp4")})
    assert r.status_code == 200, r.text
    s = r.json()
    pid = s["project_id"]
    assert "source" not in s and s["filename"] == "my_talk.mp4"
    assert s["chat_enabled"] is False

    r = client.post(f"/api/projects/{pid}/auto", json={"shorts": 2, "transcribe": False})
    assert r.status_code == 200
    s = wait(client, pid)
    assert s["job"]["state"] == "done", s["job"]
    assert s["removed_seconds"] > 1.0
    url = s["outputs"]["long"]
    v = client.get(url)
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and len(v.content) > 1000
    assert "attachment" in client.get(url + "&download=1").headers["content-disposition"]


def test_rejects_bad_uploads_and_paths(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with bad.open("rb") as f:
        assert client.post("/api/projects", files={"video": ("notes.txt", f, "text/plain")}).status_code == 400
    assert client.get("/files/abcdef123456/../../etc/passwd").status_code == 404
    assert client.get("/files/nothex/x.mp4").status_code == 404
    assert client.get("/api/projects/abcdef123456").status_code == 404


def test_chat_needs_key(client, clip):
    with clip.open("rb") as f:
        pid = client.post("/api/projects", files={"video": ("a.mp4", f, "video/mp4")}).json()["project_id"]
    r = client.post(f"/api/projects/{pid}/chat", json={"message": "cut the intro"})
    assert r.status_code == 503


def test_waitlist(client):
    assert client.post("/api/waitlist", json={"email": "nope"}).status_code == 400
    assert client.post("/api/waitlist", json={"email": "a@b.co", "channel": "@me"}).json() == {"ok": True}
    assert "a@b.co" in (P.home().parent / "waitlist.jsonl").read_text()


class FakeClaude:
    """Calls remove_ranges, then render, then answers."""

    def __init__(self):
        self.calls = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        step = len(self.calls)
        if step == 1:
            return NS(stop_reason="tool_use", content=[
                _block(type="tool_use", id="t1", name="remove_ranges", input={"ranges": [{"start": 0, "end": 1}]}),
            ])
        if step == 2:
            return NS(stop_reason="tool_use", content=[
                _block(type="tool_use", id="t2", name="render", input={"what": "long", "preview": True}),
            ])
        return NS(stop_reason="end_turn", content=[_block(type="text", text="Cut the first second.")])


def _block(**kw):
    return NS(**kw, model_dump=lambda exclude_none=True: dict(kw))


def test_agent_loop(client, clip):
    p = P.create(str(clip))
    fake = FakeClaude()
    reply, msgs = agent.chat(p.id, [], "drop the first second", client=fake)
    assert reply == "Cut the first second."
    names = {t["name"] for t in fake.calls[0]["tools"]}
    assert "remove_ranges" in names and "create_project" not in names
    # tool results went back with the project id injected and no errors
    results = [m for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert all(not r["is_error"] for m in results for r in m["content"]), results
    p = P.load(p.id)
    assert p.edits.removed and "preview" in p.outputs


def test_agent_reports_tool_errors(client):
    out, err = agent.run_tool("get_project", {}, "abcdef123456")
    assert err and "No project" in out
