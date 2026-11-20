"""Render an edit list with FFmpeg: keep only the chosen ranges, optionally reframe to 9:16 and burn captions."""

from __future__ import annotations

import os
import subprocess
import tempfile

from .models import Range


def _between(ranges: list[Range]) -> str:
    return "+".join(f"between(t,{r.start:.3f},{r.end:.3f})" for r in ranges)


def render(
    source: str,
    keep: list[Range],
    out_path: str,
    vertical: bool = False,
    ass_path: str | None = None,
    has_audio: bool = True,
    preview: bool = False,
    extra_filters: list[str] | None = None,
) -> str:
    """Write out_path containing only the keep ranges of source, in order."""
    if not keep:
        raise ValueError("Nothing to render: the keep list is empty")
    sel = _between(keep)
    v = f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB"
    if vertical:
        v += ",crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    elif preview:
        v += ",scale=-2:480"
    if extra_filters:
        v += "," + ",".join(extra_filters)
    if ass_path:
        esc = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        v += f",ass='{esc}'"
    graph = v + "[v]"
    if has_audio:
        graph += f";[0:a]aselect='{sel}',asetpts=N/SR/TB[a]"

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(graph)
        script = f.name
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source,
        "-filter_complex_script", script, "-map", "[v]",
    ]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium",
        "-crf", "30" if preview else "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(script)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {r.stderr.strip()[-2000:]}")
    return out_path
