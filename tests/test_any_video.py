"""Uploads with no speech (scenery, b-roll) must take text edits, and transcription must not depend on PyAV."""

import asyncio
import json
import subprocess

import pytest

from cutline import agent, overlays, project as P, transcribe as T
from cutline.server import mcp


def call(name, **args):
    return asyncio.run(mcp.call_tool(name, args))


def clip(path, audio: bool):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x305070:size=640x360:rate=30:duration=5"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "anoisesrc=d=5:a=0.02", "-shortest", "-c:a", "aac"]
    subprocess.run(cmd + ["-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)
    return str(path)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CUTLINE_HOME", str(tmp_path / "home"))
    return tmp_path


def gold_pixels(path, t):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return sum(1 for i in range(0, len(raw), 3) if raw[i] > 200 and 150 < raw[i + 1] < 230 and raw[i + 2] < 90)


def test_silent_clip_gets_arial_golden_text(home):
    p = P.create(clip(home / "lake.mp4", audio=False))
    out = json.loads(call("add_text", project_id=p.id, text="what a beautiful lake", start=0, end=5,
                          font="Arial", color="golden yellow").content[0].text)
    t = P.load(p.id).edits.texts[0]
    assert t.color == "FFC000"
    assert t.font in overlays.installed_fonts()
    if t.font != "Arial":
        assert "font_note" in out and "Arial" in out["font_note"]
    call("render", project_id=p.id, what="long")
    assert gold_pixels(P.load(p.id).outputs["long"], 2.5) > 200


def test_font_lookup():
    have = overlays.installed_fonts()
    assert overlays.resolve_font(have[0]) == (have[0], None)
    assert overlays.resolve_font(have[0].upper())[0] == have[0]
    got, note = overlays.resolve_font("Definitely Not A Font")
    assert got and "isn't installed" in note


def test_audio_decoded_without_pyav(home):
    assert T.load_audio(clip(home / "silent.mp4", audio=False)) is None
    a = T.load_audio(clip(home / "wind.mp4", audio=True))
    assert a.dtype.name == "float32" and 4.5 * T.SAMPLE_RATE < a.size < 5.5 * T.SAMPLE_RATE


def test_transcribe_passes_samples_not_a_path(home, monkeypatch):
    """faster-whisper only touches PyAV when given a path; we always hand it decoded samples."""
    seen = {}

    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio, **k):
            seen["type"] = type(audio).__name__
            return iter([]), type("Info", (), {"language": "en"})()

    fw = pytest.importorskip("faster_whisper")
    monkeypatch.setattr(fw, "WhisperModel", FakeModel)
    assert T.transcribe(clip(home / "wind.mp4", audio=True)).words == []
    assert seen["type"] == "ndarray"
    assert T.transcribe(clip(home / "silent.mp4", audio=False)).words == []  # no audio: empty, no error


def test_prompt_covers_any_video():
    s = agent.SYSTEM
    assert "need no transcript" in s and "add_text with their" in s
