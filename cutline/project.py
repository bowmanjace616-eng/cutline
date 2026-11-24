"""Project store and the editing operations the MCP tools and CLI share."""

from __future__ import annotations

import os
import threading
import re
import uuid
from pathlib import Path

from . import captions, looks, media, overlays, render, rough_cut, shorts
from .models import CaptionStyle, ColorGrade, Project, Range, Short, TextOverlay


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
    # Write then rename, so a reader never sees a half-written file while a render is saving.
    tmp = d / f"project.json.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp.write_text(p.model_dump_json(indent=2))
    os.replace(tmp, d / "project.json")


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


def set_grade(p: Project, grade: ColorGrade) -> Project:
    """A grade with no start/end replaces every look; a timed one is added on top."""
    if grade.start is None and grade.end is None:
        p.edits.grades = [] if looks.is_neutral(grade) else [grade]
    elif not looks.is_neutral(grade):
        p.edits.grades.append(grade)
    save(p)
    return p


def add_text(p: Project, t: TextOverlay) -> Project:
    overlays.check(t)
    if not (0 <= t.start < p.media.duration + 0.01):
        raise ValueError(f"Text starts at {t.start}s but the video is {p.media.duration:.1f}s long")
    t.end = min(t.end, p.media.duration)
    p.edits.texts = [x for x in p.edits.texts if x.id != t.id] + [t]
    save(p)
    return p


def next_text_id(p: Project) -> str:
    used = {x.id for x in p.edits.texts}
    i = 1
    while f"text{i}" in used:
        i += 1
    return f"text{i}"


def update_text(p: Project, text_id: str, changes: dict) -> Project:
    cur = next((x for x in p.edits.texts if x.id == text_id), None)
    if cur is None:
        raise ValueError(f"No text '{text_id}'. Existing: {', '.join(x.id for x in p.edits.texts) or 'none'}")
    data = cur.model_dump()
    for k, v in changes.items():
        if k in ("animate_in", "animate_out") and isinstance(v, dict):
            data[k] = {**data[k], **v}
        elif k != "id":
            data[k] = v
    return add_text(p, TextOverlay.model_validate(data))


def remove_text(p: Project, text_id: str) -> Project:
    before = len(p.edits.texts)
    p.edits.texts = [] if text_id == "all" else [x for x in p.edits.texts if x.id != text_id]
    if text_id != "all" and len(p.edits.texts) == before:
        raise ValueError(f"No text '{text_id}'")
    save(p)
    return p


def _overlay_ass(p: Project, keep: list[Range], name: str, width: int, height: int, which: str) -> str | None:
    texts = [t for t in p.edits.texts if t.applies_to in ("all", which)]
    body = overlays.build_ass(texts, keep, width, height, p.media.fps) if texts else None
    if body is None:
        return None
    path = _dir(p.id) / name
    path.write_text(body)
    return str(path)


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
    over = _overlay_ass(p, p.edits.keep, "long_text.ass", p.media.width or 1920, p.media.height or 1080, "long")
    render.render(p.source, p.edits.keep, out, ass_path=ass, has_audio=p.media.has_audio, preview=preview,
                  grade=looks.filter_chain(p.edits.grades), overlay_ass=over)
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
        over = _overlay_ass(p, keep, f"short_{i}_text.ass", 1080, 1920, "shorts")
        render.render(p.source, keep, out, vertical=True, ass_path=ass, has_audio=p.media.has_audio,
                      grade=looks.filter_chain(p.edits.grades), overlay_ass=over)
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
        "looks": [g.model_dump(exclude_none=True) for g in p.edits.grades],
        "texts": [
            {"id": t.id, "text": t.text, "start": t.start, "end": t.end, "position": t.position, "color": t.color,
             "font": t.font, "in": f"{t.animate_in.style} {t.animate_in.direction}",
             "out": f"{t.animate_out.style} {t.animate_out.direction}", "applies_to": t.applies_to}
            for t in p.edits.texts
        ],
        "outputs": p.outputs,
    }
