"""Color grades and animated text overlays: unit checks on the filters/ASS, then real renders measured by pixel."""

import asyncio
import json
import subprocess

import pytest

from cutline import looks, overlays, project as P
from cutline.models import Range, TextAnim, TextOverlay
from cutline.server import mcp


@pytest.fixture
def gray(tmp_path, monkeypatch):
    """6s mid-gray 640x360 clip with audio: easy to measure brightness and find text by colour."""
    monkeypatch.setenv("CUTLINE_HOME", str(tmp_path / "home"))
    out = tmp_path / "gray.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=30:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=6",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(out),
    ], check=True)
    return str(out)


def frame(path: str, t: float) -> tuple[int, int, bytes]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                        "-of", "json", path], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return s["width"], s["height"], raw


def mean_luma(raw: bytes) -> float:
    px = len(raw) // 3
    return sum(0.299 * raw[i] + 0.587 * raw[i + 1] + 0.114 * raw[i + 2] for i in range(0, len(raw), 3 * 7)) / (px / 7)


def sky_blue_x(w: int, h: int, raw: bytes) -> float | None:
    """Mean x of sky-blue-tinted pixels (blue well above red on a neutral gray clip), or None if hardly any."""
    xs = []
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if b > r + 25 and g > r + 15:
            xs.append((i // 3) % w)
    return sum(xs) / len(xs) if len(xs) > 30 else None


def call(name, **args):
    return asyncio.run(mcp.call_tool(name, args))


def test_presets_and_filters():
    g = looks.build("darker")
    assert g.brightness < 0 and g.gamma < 1
    assert looks.build("Dark", brightness=-0.2).brightness == -0.2  # alias + override
    chain = looks.filter_chain([g])
    assert chain.startswith("eq=brightness=-0.060")
    timed = looks.filter_chain([looks.build("warm", start=1, end=2)])
    assert "colortemperature" in timed and "enable='between(t,1.000,2.000)'" in timed
    assert looks.filter_chain([looks.build("none")]) is None
    with pytest.raises(ValueError):
        looks.build("sparkly")
    with pytest.raises(ValueError):
        looks.build(brightness=4)


def test_colors():
    assert overlays.parse_color("sky blue") == "87CEEB"
    assert overlays.parse_color("SkyBlue") == "87CEEB"
    assert overlays.parse_color("#87ceeb") == "87CEEB"
    assert overlays.parse_color("rgb(135, 206, 235)") == "87CEEB"
    assert overlays.parse_color("#fff") == "FFFFFF"
    with pytest.raises(ValueError):
        overlays.parse_color("blurple")


def test_slide_events_move_right_to_left():
    t = overlays.check(TextOverlay(
        id="text1", text="what a beautiful location", start=1, end=4, color="sky blue",
        animate_in=TextAnim(style="slide", direction="right", seconds=0.5),
        animate_out=TextAnim(style="slide", direction="left", seconds=0.5),
    ))
    ass = overlays.build_ass([t], [Range(start=0, end=6)], 1920, 1080, 30)
    lines = [ln for ln in ass.splitlines() if ln.startswith("Dialogue")]
    xs = [float(ln.split("\\pos(")[1].split(",")[0]) for ln in lines]
    assert len(lines) == 15 + 1 + 15  # a frame-by-frame entrance and exit around one hold event
    assert xs[0] > 960 and xs[15] == 960 and xs[-1] < 960  # starts right, rests centred, leaves left
    assert all(a >= b for a, b in zip(xs, xs[1:]))  # only ever moves left
    assert "\\1a&HFF&" not in lines[15] and "\\1a&HFF&" in lines[-1]  # opaque while holding, gone at the end
    assert lines[0].split(",")[1] == "0:00:01.00" and lines[-1].split(",")[2] == "0:00:04.00"
    assert "&H00EBCE87" in ass  # sky blue in ASS BGR order


def test_text_follows_the_cut():
    t = TextOverlay(id="a", text="hi", start=3, end=5)
    keep = [Range(start=0, end=2), Range(start=4, end=6)]
    assert overlays.span(t, keep) == (2.0, 3.0)  # 3-4 was cut, so it starts where 4.0 lands
    assert overlays.span(TextOverlay(id="b", text="x", start=2.2, end=3.8), keep) is None
    assert overlays.source_time(2.5, keep) == 4.5


def test_tools_and_render(gray):
    p = P.create(gray)
    pid = p.id
    call("set_color_grade", project_id=pid, preset="darker")
    out = json.loads(call("add_text", project_id=pid, text="what a beautiful location", start=0.5, end=5.0,
                          color="#87CEEB", size=72, outline=0, shadow=0, animate_in="slide", in_from="right",
                          animate_out="slide", out_to="left", in_seconds=1.0, out_seconds=1.0).content[0].text)
    assert out["added"] == "text1" and out["texts"][0]["in"] == "slide right"
    call("render", project_id=pid, what="long")
    path = P.load(pid).outputs["long"]

    # darker everywhere: the gray background drops well below 128
    w, h, still = frame(path, 2.5)
    assert mean_luma(still) < 110

    # sky blue text: right of centre while coming in, centred while holding, left of centre on the way out
    x_in = sky_blue_x(*frame(path, 0.85))
    x_hold = sky_blue_x(*frame(path, 2.5))
    x_out = sky_blue_x(*frame(path, 4.6))
    assert x_in and x_hold and x_out, (x_in, x_hold, x_out)
    assert x_in > x_hold + 10 and x_out < x_hold - 10
    assert abs(x_hold - w / 2) < 20
    assert sky_blue_x(*frame(path, 5.5)) is None  # gone after the end

    # update + remove
    call("update_text", project_id=pid, text_id="text1", changes={"color": "red", "animate_in": {"style": "pop"}})
    t = P.load(pid).edits.texts[0]
    assert t.color == "FF3B30" and t.animate_in.style == "pop" and t.animate_in.direction == "right"
    call("remove_text", project_id=pid, text_id="all")
    call("set_color_grade", project_id=pid, preset="none")
    p = P.load(pid)
    assert p.edits.texts == [] and p.edits.grades == []


def test_text_and_grade_in_shorts(gray):
    p = P.create(gray)
    P.set_shorts(p, [__import__("cutline.models", fromlist=["Short"]).Short(title="s", start=0, end=6)])
    call("set_color_grade", project_id=p.id, preset="black_and_white")
    call("add_text", project_id=p.id, text="HELLO", start=0, end=6, color="sky blue", animate_in="none",
         animate_out="none", applies_to="shorts")
    call("render", project_id=p.id, what="all")
    p = P.load(p.id)
    w, h, raw = frame(p.outputs["short_1"], 3)
    assert (w, h) == (1080, 1920) and sky_blue_x(w, h, raw) is not None
    # long cut skips a shorts-only text
    assert sky_blue_x(*frame(p.outputs["long"], 3)) is None


def test_bad_inputs(gray):
    p = P.create(gray)
    for kw in ({"position": "upside"}, {"animate_in": "explode"}, {"in_from": "diagonal"}, {"start": 4, "end": 2}):
        args = {"project_id": p.id, "text": "x", "start": 1, "end": 2, **kw}
        with pytest.raises(Exception):
            call("add_text", **args)
