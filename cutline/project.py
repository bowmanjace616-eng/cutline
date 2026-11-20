"""Project store and the editing operations the MCP tools and CLI share."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from . import captions, media, render, rough_cut, shorts
from .models import CaptionStyle, Project, Range, Short


def home() -> Path:
    p = Path(os.environ.get("CUTLINE_HOME", Path.home() / ".cutline")) / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dir(pid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8,32}", pid):
        raise ValueError(f"Bad project id: {pid}")
    return home() / pid


def save(p: Project) -> None:
    d = _dir(p.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(p.model_dump_json(indent=2))


def load(pid: str) -> Project:
    f = _dir(pid) / "project.json"
    if not f.exists():
        raise ValueError(f"No project {pid}")
    return Project.model_validate_json(f.read_text())


def create(source: str) -> Project:
    src = str(Path(source).expanduser().resolve())
    if not Path(src).is_file():
        raise ValueError(f"File not found: {source}")
    p = Project(id=uuid.uuid4().hex[:12], source=src, media=media.probe(src))
    p.edits.keep = [Range(start=0.0, end=p.media.duration)]
    save(p)
    return p


def analyze(p: Project, do_transcribe: bool = True, min_silence: float = 0.6) -> Project:
    if p.media.has_audio:
        p.silences = media.detect_silences(p.source, min_duration=min_silence)
        if do_transcribe:
            from .transcribe import transcribe

            p.transcript = transcribe(p.source)
    replan(p)
    return p


def replan(p: Project, remove_fillers: bool = True, padding: float = 0.15) -> Project:
    p.edits.keep = rough_cut.plan_keep(
        p.media.duration, p.silences, p.transcript, p.edits.removed, remove_fillers, padding
    )
    save(p)
    return p


def remove(p: Project, ranges: list[Range]) -> Project:
    p.edits.removed = rough_cut.merge(p.edits.removed + ranges)
    p.edits.keep = rough_cut.subtract(p.edits.keep, ranges)
    save(p)
    return p


def restore(p: Project, ranges: list[Range]) -> Project:
    p.edits.removed = rough_cut.subtract(p.edits.removed, ranges)
    return replan(p)


def set_shorts(p: Project, items: list[Short]) -> Project:
    for s in items:
        if not (0 <= s.start < s.end <= p.media.duration + 0.01):
            raise ValueError(f"Short '{s.title}' has a bad range {s.start}-{s.end}")
    p.edits.shorts = items
    save(p)
    return p


def suggest_shorts(p: Project, count: int = 5) -> list[Short]:
    if not p.transcript or not p.transcript.words:
        raise ValueError("Needs a transcript first: run analyze with transcription")
    return shorts.suggest(p.transcript, count=count)


def set_captions(p: Project, style: CaptionStyle) -> Project:
    p.edits.captions = style
    save(p)
    return p


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "short"


def render_long(p: Project, preview: bool = False, burn_captions: bool = False) -> str:
    d = _dir(p.id)
    out = str(d / ("preview.mp4" if preview else "long_cut.mp4"))
    ass = None
    if burn_captions and p.transcript:
        ass = str(d / "long.ass")
        Path(ass).write_text(
            captions.build_ass(p.transcript.words, p.edits.keep, p.edits.captions,
                               p.media.width or 1920, p.media.height or 1080)
        )
    render.render(p.source, p.edits.keep, out, ass_path=ass, has_audio=p.media.has_audio, preview=preview)
    p.outputs["preview" if preview else "long"] = out
    save(p)
    return out


def render_shorts(p: Project, captions_on: bool = True) -> list[str]:
    d = _dir(p.id)
    outs = []
    for i, s in enumerate(p.edits.shorts, 1):
        keep = rough_cut.clip_to(p.edits.keep, Range(start=s.start, end=s.end))
        if not keep:
            continue
        ass = None
        if captions_on and p.transcript:
            ass = str(d / f"short_{i}.ass")
            Path(ass).write_text(captions.build_ass(p.transcript.words, keep, p.edits.captions, 1080, 1920))
        out = str(d / f"short_{i:02d}_{_slug(s.title)}.mp4")
        render.render(p.source, keep, out, vertical=True, ass_path=ass, has_audio=p.media.has_audio)
        p.outputs[f"short_{i}"] = out
        outs.append(out)
    save(p)
    return outs


def summary(p: Project) -> dict:
    kept = sum(r.duration for r in p.edits.keep)
    return {
        "project_id": p.id,
        "source": p.source,
        "original_seconds": round(p.media.duration, 2),
        "cut_seconds": round(kept, 2),
        "removed_seconds": round(p.media.duration - kept, 2),
        "cuts": max(0, len(p.edits.keep) - 1),
        "silences_found": len(p.silences),
        "transcribed_words": len(p.transcript.words) if p.transcript else 0,
        "shorts": [s.model_dump() for s in p.edits.shorts],
        "outputs": p.outputs,
    }
