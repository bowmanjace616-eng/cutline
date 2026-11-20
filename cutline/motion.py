"""Motion graphics and transitions, rendered with FFmpeg (no extra services).

Overlays are animated titles, lower thirds and punch-in zooms. Transitions join clips with
crossfades, wipes, slides and zooms. Everything is timed in output seconds.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .models import Overlay, Range

TRANSITIONS = {
    "fade": "fade",
    "dissolve": "dissolve",
    "fadeblack": "fadeblack",
    "wipe": "wipeleft",
    "slide": "slideleft",
    "smooth": "smoothleft",
    "zoom": "zoomin",
    "circle": "circleopen",
    "blur": "hblur",
}

_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font() -> str:
    env = os.environ.get("CUTLINE_FONT")
    for f in ([env] if env else []) + _FONT_CANDIDATES:
        if f and Path(f).exists():
            return f
    return "DejaVu Sans"


def _esc_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _ramp(s: float, dur: float) -> str:
    """0 -> 1 over dur seconds from s, eased out (cubic)."""
    return f"(1-pow(1-min(1,max(0,(t-{s:.3f})/{dur:.3f})),3))"


def _alpha(s: float, e: float, f: float = 0.35) -> str:
    return (
        f"if(lt(t,{s:.3f}),0,if(lt(t,{s + f:.3f}),(t-{s:.3f})/{f},"
        f"if(lt(t,{e - f:.3f}),1,if(lt(t,{e:.3f}),({e:.3f}-t)/{f},0))))"
    )


def _textfile(text: str, workdir: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".txt", dir=workdir)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def overlay_filters(overlays: list[Overlay], width: int, height: int, workdir: str) -> list[str]:
    """FFmpeg video filters for the overlays, in order. Text goes through files to avoid escaping bugs."""
    font = _esc_path(_font())
    vertical = height > width
    out: list[str] = []
    for o in sorted(overlays, key=lambda o: (o.kind != "zoom", o.start)):  # zooms first, text on top
        s, e = o.start, max(o.end, o.start + 0.5)
        en = f"between(t,{s:.3f},{e:.3f})"
        if o.kind == "zoom":
            z = f"(1+{o.zoom - 1:.3f}*{_ramp(s, 0.25)}*between(t,{s:.3f},{e:.3f}))"
            out.append(f"scale=w='ceil(iw*{z}/2)*2':h='ceil(ih*{z}/2)*2':eval=frame")
            out.append(f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2")
        elif o.kind == "title":
            size = int(height * (0.065 if vertical else 0.09))
            tf = _esc_path(_textfile(o.text, workdir))
            rise = f"(1-{_ramp(s, 0.45)})*{int(height * 0.04)}"
            out.append(
                f"drawtext=fontfile='{font}':textfile='{tf}':fontsize={size}:fontcolor=white:"
                f"borderw={max(2, size // 18)}:bordercolor=black@0.6:shadowx=0:shadowy={size // 14}:shadowcolor=black@0.4:"
                f"x=(w-tw)/2:y='(h-th)/2-{int(height * 0.08)}+{rise}':alpha='{_alpha(s, e)}':enable='{en}'"
            )
            if o.subtitle:
                tf2 = _esc_path(_textfile(o.subtitle, workdir))
                out.append(
                    f"drawtext=fontfile='{font}':textfile='{tf2}':fontsize={int(size * 0.45)}:fontcolor=white@0.9:"
                    f"x=(w-tw)/2:y='(h)/2+{rise}':alpha='{_alpha(s + 0.15, e)}':enable='{en}'"
                )
        elif o.kind == "lower_third":
            size = int(height * (0.035 if vertical else 0.05))
            pad = int(size * 0.45)
            left = int(width * 0.05)
            y = int(height * (0.70 if vertical else 0.76))
            slide = f"{left}-(tw+{left + pad * 2})*(1-{_ramp(s, 0.4)})"
            tf = _esc_path(_textfile(o.text, workdir))
            out.append(
                f"drawtext=fontfile='{font}':textfile='{tf}':fontsize={size}:fontcolor=black:box=1:"
                f"boxcolor=white@0.95:boxborderw={pad}:x='{slide}':y={y}:alpha='{_alpha(s, e, 0.2)}':enable='{en}'"
            )
            if o.subtitle:
                tf2 = _esc_path(_textfile(o.subtitle, workdir))
                slide2 = f"{left}-(tw+{left + pad * 2})*(1-{_ramp(s + 0.12, 0.4)})"
                out.append(
                    f"drawtext=fontfile='{font}':textfile='{tf2}':fontsize={int(size * 0.62)}:fontcolor=white:box=1:"
                    f"boxcolor=0x1F6FEB@0.95:boxborderw={int(pad * 0.8)}:x='{slide2}':y={y + size + pad * 2 + 4}:"
                    f"alpha='{_alpha(s + 0.12, e, 0.2)}':enable='{en}'"
                )
        else:
            raise ValueError(f"Unknown overlay kind: {o.kind}")
    return out


def montage(
    source: str,
    segments: list[Range],
    out_path: str,
    transition: str = "fade",
    seconds: float = 0.5,
    has_audio: bool = True,
    vertical: bool = False,
    overlays: list[Overlay] | None = None,
    size: tuple[int, int] | None = None,
    fps: int = 30,
) -> str:
    """Join source segments with a transition between each pair."""
    if not segments:
        raise ValueError("No segments to join")
    if transition not in TRANSITIONS:
        raise ValueError(f"Unknown transition '{transition}'. Choose from: {', '.join(TRANSITIONS)}")
    t = max(0.1, min(seconds, min(s.duration for s in segments) / 2 - 0.01))
    workdir = tempfile.mkdtemp(prefix="cutline-")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for s in segments:
        cmd += ["-ss", f"{s.start:.3f}", "-t", f"{s.duration:.3f}", "-i", source]

    w, h = (1080, 1920) if vertical else (size or (1920, 1080))
    norm = (
        f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={w}:{h}"
        if vertical
        else f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    )
    parts = []
    for i in range(len(segments)):
        parts.append(f"[{i}:v]fps={fps},{norm},setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]")

    vlast, alast, elapsed = "v0", "a0", segments[0].duration
    for i in range(1, len(segments)):
        offset = elapsed - t
        parts.append(f"[{vlast}][v{i}]xfade=transition={TRANSITIONS[transition]}:duration={t:.3f}:offset={offset:.3f}[vx{i}]")
        vlast = f"vx{i}"
        if has_audio:
            parts.append(f"[{alast}][a{i}]acrossfade=d={t:.3f}[ax{i}]")
            alast = f"ax{i}"
        elapsed = offset + segments[i].duration

    post = overlay_filters(overlays or [], w, h, workdir)
    parts.append(f"[{vlast}]" + (",".join(post) if post else "null") + "[v]")

    script = Path(workdir) / "graph.txt"
    script.write_text(";".join(parts))
    cmd += ["-filter_complex_script", str(script), "-map", "[v]"]
    if has_audio:
        cmd += ["-map", f"[{alast}]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg montage failed: {r.stderr.strip()[-2000:]}")
    return out_path
