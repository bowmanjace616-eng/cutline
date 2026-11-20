"""Speech to text with word timestamps.

Uses faster-whisper locally (pip install 'cutline[transcribe]'). A hosted provider
(Deepgram, AssemblyAI) can be added behind the same function for production.
"""

from __future__ import annotations

import os

from .models import Transcript, Word


def transcribe(path: str, model_size: str | None = None) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Transcription needs faster-whisper: pip install 'cutline[transcribe]'") from e

    model = WhisperModel(model_size or os.environ.get("CUTLINE_WHISPER_MODEL", "base"), compute_type="int8")
    segments, info = model.transcribe(path, word_timestamps=True, vad_filter=True)
    words = [
        Word(text=w.word.strip(), start=float(w.start), end=float(w.end))
        for seg in segments
        for w in (seg.words or [])
        if w.word.strip()
    ]
    return Transcript(language=info.language, words=words)
