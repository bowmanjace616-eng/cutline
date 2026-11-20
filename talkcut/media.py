"""FFmpeg helpers: probing and silence detection."""

from __future__ import annotations

import json
import re
import subprocess

from .models import MediaInfo, Range


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe(path: str) -> MediaInfo:
    r = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {r.stderr.strip()}")
    data = json.loads(r.stdout)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    audio = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
    fps = None
    if video and video.get("avg_frame_rate", "0/0") != "0/0":
        n, d = video["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else None
    return MediaInfo(
        duration=float(data["format"]["duration"]),
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=fps,
        has_audio=audio is not None,
    )


_START = re.compile(r"silence_start: (-?[\d.]+)")
_END = re.compile(r"silence_end: (-?[\d.]+)")


def detect_silences(path: str, noise_db: float = -35.0, min_duration: float = 0.6) -> list[Range]:
    """Return silent stretches longer than min_duration seconds."""
    r = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null", "-",
    ])
    out: list[Range] = []
    start: float | None = None
    for line in r.stderr.splitlines():
        if m := _START.search(line):
            start = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) and start is not None:
            out.append(Range(start=start, end=float(m.group(1))))
            start = None
    if start is not None:  # silence runs to the end of the file
        out.append(Range(start=start, end=probe(path).duration))
    return out
