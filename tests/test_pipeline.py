"""End-to-end tests on a synthetic video: tone bursts separated by silence stand in for speech."""

import asyncio
import subprocess

import pytest

from cutline import media, project as P, rough_cut
from cutline.models import Range, Short, Transcript, Word

# 0-3s tone, 3-5s silence, 5-9s tone, 9-12s silence, 12-16s tone  (16s total, 5s silent)
TONE = "between(t,0,3)+between(t,5,9)+between(t,12,16)"


@pytest.fixture
def video(tmp_path, monkeypatch):
    monkeypatch.setenv("CUTLINE_HOME", str(tmp_path / "home"))
    out = tmp_path / "talk.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=16",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=16",
        "-filter_complex", f"[1:a]volume='if({TONE},1,0)':eval=frame[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(out),
    ], check=True)
    return str(out)


def fake_transcript() -> Transcript:
    words = [
        ("Why", 0.2), ("do", 0.6), ("um", 1.0), ("videos", 1.6), ("work?", 2.4),
        ("Because", 5.2), ("hooks", 6.0), ("matter.", 7.0),
        ("Here's", 12.2), ("the", 13.0), ("proof.", 14.0),
    ]
    return Transcript(words=[Word(text=t, start=s, end=s + 0.35) for t, s in words])


def test_silences(video):
    found = media.detect_silences(video, min_duration=0.6)
    assert len(found) == 2
    assert found[0].start == pytest.approx(3.0, abs=0.1) and found[0].end == pytest.approx(5.0, abs=0.1)


def test_range_math():
    keep = rough_cut.subtract([Range(start=0, end=10)], [Range(start=2, end=3), Range(start=5, end=6)])
    assert [(r.start, r.end) for r in keep] == [(0, 2), (3, 5), (6, 10)]
    assert rough_cut.map_time(4.0, keep) == pytest.approx(3.0)
    assert rough_cut.map_time(2.5, keep) is None


def test_rough_cut_and_shorts(video):
    p = P.create(video)
    P.analyze(p, do_transcribe=False)
    p.transcript = fake_transcript()
    P.replan(p)
    s = P.summary(p)
    # ~5s of silence minus padding, plus the "um"
    assert 3.5 < s["removed_seconds"] < 5.5, s

    P.remove(p, [Range(start=12, end=16)])  # creator: "drop the last bit"
    assert P.summary(p)["cut_seconds"] < s["cut_seconds"] - 3

    long_out = P.render_long(p)
    assert media.probe(long_out).duration == pytest.approx(P.summary(p)["cut_seconds"], abs=0.3)

    p.edits.captions.preset = "karaoke"
    P.set_shorts(p, [Short(title="Why videos work", start=0, end=9)])
    (short_out,) = P.render_shorts(p)
    info = media.probe(short_out)
    assert (info.width, info.height) == (1080, 1920)
    assert 5 < info.duration < 8  # 9s window minus the silence gap and the um


def test_restore(video):
    p = P.create(video)
    P.analyze(p, do_transcribe=False)
    before = P.summary(p)["cut_seconds"]
    P.remove(p, [Range(start=0, end=2)])
    P.restore(p, [Range(start=0, end=2)])
    assert P.summary(p)["cut_seconds"] == pytest.approx(before)


def test_mcp_tools_registered():
    from cutline.server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"create_project", "analyze", "get_transcript", "remove_ranges", "add_shorts", "render"} <= names
