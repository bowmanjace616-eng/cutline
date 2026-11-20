"""AI scene edits against a fake Higgsfield API (no network, no credits)."""

import json
import subprocess

import httpx
import pytest

from cutline import generative, media, project as P


@pytest.fixture
def video(tmp_path, monkeypatch):
    monkeypatch.setenv("CUTLINE_HOME", str(tmp_path / "home"))
    out = tmp_path / "car.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=12",
        "-f", "lavfi", "-i", "sine=duration=12", "-c:v", "libx264", "-preset", "ultrafast", "-shortest", str(out),
    ], check=True)
    return str(out)


@pytest.fixture
def fake_api(monkeypatch, video):
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "kid")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "secret")
    calls = {"submit": None, "polls": 0, "put_headers": None}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Key kid:secret"
        if req.url.path == "/files/generate-upload-url":
            return httpx.Response(200, json={"upload_url": "https://upload.test/put", "public_url": "https://cdn.test/src.mp4",
                                             "upload_headers": {"Content-Type": "video/mp4"}})
        if req.url.path == "/kling-video/o3/video-edit":
            calls["submit"] = json.loads(req.content)
            return httpx.Response(200, json={"status": "queued", "request_id": "r1"})
        if req.url.path == "/requests/r1/status":
            calls["polls"] += 1
            if calls["polls"] < 3:
                return httpx.Response(200, json={"status": "in_progress", "request_id": "r1"})
            return httpx.Response(200, json={"status": "completed", "request_id": "r1",
                                             "video": {"url": "https://cdn.test/out.mp4"}})
        return httpx.Response(404)

    def fake_put(url, content, headers, timeout):
        assert "authorization" not in {k.lower() for k in headers}  # never leak our key to the presigned URL
        calls["put_headers"] = headers
        return httpx.Response(200, request=httpx.Request("PUT", url))

    class FakeStream:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield open(video, "rb").read()

    monkeypatch.setattr(generative.httpx, "put", fake_put)
    monkeypatch.setattr(generative.httpx, "stream", FakeStream)
    client = generative.HiggsfieldClient(
        http=httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler)), sleep=lambda s: None
    )
    return client, calls


def test_ai_edit_end_to_end(video, fake_api):
    client, calls = fake_api
    p = P.create(video)
    e = P.ai_edit(p, 2.0, 8.0, "Put the car in outer space, keep its motion", client=client)
    assert calls["submit"] == {"prompt": "Put the car in outer space, keep its motion",
                               "video_urls": ["https://cdn.test/src.mp4"]}
    assert calls["polls"] == 3
    assert e.request_id == "r1" and media.probe(e.output).duration > 0
    trimmed = e.output.replace(".mp4", ".source.mp4")
    assert media.probe(trimmed).duration == pytest.approx(6.0, abs=0.2)
    assert P.summary(P.load(p.id))["ai_edits"][0]["prompt"].startswith("Put the car")


def test_length_limits(video, fake_api):
    client, _ = fake_api
    p = P.create(video)
    with pytest.raises(generative.GenerativeError, match="3-10s"):
        P.ai_edit(p, 0, 11.5, "red car", model="kling-omni", client=client)


def test_missing_key(video, monkeypatch):
    monkeypatch.delenv("HIGGSFIELD_API_KEY_ID", raising=False)
    monkeypatch.delenv("HIGGSFIELD_API_KEY_SECRET", raising=False)
    with pytest.raises(generative.GenerativeError, match="API key"):
        generative._auth()


def test_seedance_body_shape(fake_api, monkeypatch):
    client, _ = fake_api
    seen = {}

    def handler(req):
        seen["path"], seen["body"] = req.url.path, json.loads(req.content)
        return httpx.Response(200, json={"request_id": "r2"})

    client.http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    client.submit_edit("https://cdn.test/a.mp4", "make it red", model="seedance", quality="720p")
    assert seen == {"path": "/bytedance/seedance-2.5/video-edit",
                    "body": {"prompt": "make it red", "video_url": "https://cdn.test/a.mp4", "resolution": "720p"}}
