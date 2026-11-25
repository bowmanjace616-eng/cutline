"""Render an edit list with FFmpeg: keep only the chosen ranges, optionally reframe to 9:16 and burn captions."""

from __future__ import annotations

import os
import subprocess
import tempfile

from .models import Range


AUDIO_RATE = 48000
_FRAME = 4  # bytes per sample frame: 16-bit stereo


def _between(ranges: list[Range]) -> str:
    return "+".join(f"between(t,{r.start:.3f},{r.end:.3f})" for r in ranges)


def cut_audio(source: str, keep: list[Range], raw_path: str) -> str:
    """Write the keep ranges of source's audio, back to back, as raw 48 kHz 16-bit stereo PCM.

    One short FFmpeg read per range, each padded or trimmed to its exact sample count so the audio
    never drifts from the video. This replaces the `aselect` filter, which keeps every sample (cuts
    nothing) in some FFmpeg 8 builds, and it holds only one range in memory at a time.
    """
    with open(raw_path, "wb") as f:
        for r in keep:
            want = round((r.end - r.start) * AUDIO_RATE) * _FRAME
            start = f.tell()
            res = subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{r.start:.6f}", "-i", source,
                 "-t", f"{r.end - r.start:.6f}", "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(AUDIO_RATE),
                 "-f", "s16le", "-"],
                stdout=f, stderr=subprocess.PIPE, check=False,
            )
            if res.returncode != 0:
                raise RuntimeError(f"ffmpeg audio cut failed: {res.stderr.decode(errors='replace').strip()[-1000:]}")
            got = f.tell() - start
            if got > want:
                f.truncate(start + want)
                f.seek(start + want)
            elif got < want:
                f.write(b"\0" * (want - got))
    return raw_path


def render(
    source: str,
    keep: list[Range],
    out_path: str,
    vertical: bool = False,
    ass_path: str | None = None,
    has_audio: bool = True,
    preview: bool = False,
    grade: str | None = None,
    overlay_ass: str | None = None,
) -> str:
    """Write out_path containing only the keep ranges of source, in order.

    grade: FFmpeg filters applied to source frames first (source-time `enable` works there).
    overlay_ass: custom text/motion overlays, burned last so they sit above captions.
    """
    if not keep:
        raise ValueError("Nothing to render: the keep list is empty")
    sel = _between(keep)
    v = "[0:v]" + (f"{grade}," if grade else "") + f"select='{sel}',setpts=N/FRAME_RATE/TB"
    if vertical:
        v += ",crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    elif preview:
        v += ",scale=-2:480"
    for path in (ass_path, overlay_ass):
        if path:
            esc = path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            v += f",ass='{esc}'"
    graph = v + "[v]"

    # Inline graph works on every FFmpeg. Very long edit lists go through a file: `-/filter_complex` on
    # FFmpeg 7+, since `-filter_complex_script` is gone from newer releases.
    tmp: list[str] = []
    try:
        if len(graph) < 100_000:
            fc = ["-filter_complex", graph]
        else:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
                f.write(graph)
            tmp.append(f.name)
            fc = ["-/filter_complex", f.name]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source]
        if has_audio:
            raw = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False, dir=os.path.dirname(out_path) or None)
            raw.close()
            tmp.append(raw.name)
            cut_audio(source, keep, raw.name)
            cmd += ["-f", "s16le", "-ar", str(AUDIO_RATE), "-ac", "2", "-i", raw.name]
        cmd += [*fc, "-map", "[v]"]
        if has_audio:
            cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "160k"]
        cmd += [
            "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium",
            "-crf", "30" if preview else "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        for t in tmp:
            os.unlink(t)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {r.stderr.strip()[-2000:]}")
    return out_path
