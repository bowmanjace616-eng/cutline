"""Speech to text with word timestamps.

Uses faster-whisper locally (pip install 'cutline[transcribe]'). A hosted provider
(Deepgram, AssemblyAI) can be added behind the same function for production.

Audio is decoded with the FFmpeg binary the renderer already uses, not with PyAV. faster-whisper's own
loader calls PyAV with an argument (`metadata_errors`) that newer PyAV releases removed, which broke
every transcription with "open() got an unexpected keyword argument 'metadata_errors'".
"""

from __future__ import annotations

import os
import subprocess

from .models import Transcript, Word

SAMPLE_RATE = 16000  # what Whisper models expect


def load_audio(path: str):
    """Decode the first audio track to 16 kHz mono float32. Returns None if the file has no audio."""
    import numpy as np

    from .media import probe

    if not probe(path).has_audio:
        return None
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-map", "0:a:0", "-vn",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Couldn't read the audio: {r.stderr.decode(errors='replace').strip()[-300:]}")
    if not r.stdout:
        return None
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def transcribe(path: str, model_size: str | None = None) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Transcription needs faster-whisper: pip install 'cutline[transcribe]'") from e

    audio = load_audio(path)
    if audio is None or audio.size < SAMPLE_RATE // 10:  # no audio track, or under 0.1s of it
        return Transcript(language=None, words=[])
    model = WhisperModel(model_size or os.environ.get("CUTLINE_WHISPER_MODEL", "base"), compute_type="int8")
    segments, info = model.transcribe(audio, word_timestamps=True, vad_filter=True)
    words = [
        Word(text=w.word.strip(), start=float(w.start), end=float(w.end))
        for seg in segments
        for w in (seg.words or [])
        if w.word.strip()
    ]
    return Transcript(language=info.language, words=words)
