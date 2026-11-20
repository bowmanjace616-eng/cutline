"""Turn silences, filler words and user cuts into the list of ranges to keep."""

from __future__ import annotations

import re

from .models import Range, Transcript

FILLERS = {"um", "uh", "erm", "uhm", "hmm", "ah", "er", "mm"}


def _norm(text: str) -> str:
    return re.sub(r"[^\w']", "", text.lower())


def merge(ranges: list[Range], gap: float = 0.0) -> list[Range]:
    out: list[Range] = []
    for r in sorted(ranges, key=lambda r: r.start):
        if out and r.start <= out[-1].end + gap:
            out[-1] = Range(start=out[-1].start, end=max(out[-1].end, r.end))
        else:
            out.append(Range(start=r.start, end=r.end))
    return out


def subtract(base: list[Range], cuts: list[Range]) -> list[Range]:
    """base minus cuts."""
    result = [Range(start=r.start, end=r.end) for r in base]
    for c in merge(cuts):
        nxt: list[Range] = []
        for r in result:
            if c.end <= r.start or c.start >= r.end:
                nxt.append(r)
                continue
            if c.start > r.start:
                nxt.append(Range(start=r.start, end=c.start))
            if c.end < r.end:
                nxt.append(Range(start=c.end, end=r.end))
        result = nxt
    return result


def filler_ranges(transcript: Transcript) -> list[Range]:
    return [Range(start=w.start, end=w.end) for w in transcript.words if _norm(w.text) in FILLERS]


def plan_keep(
    duration: float,
    silences: list[Range],
    transcript: Transcript | None = None,
    removed: list[Range] | None = None,
    remove_fillers: bool = True,
    padding: float = 0.15,
    min_keep: float = 0.25,
) -> list[Range]:
    """Keep everything except silences (shrunk by padding so speech isn't clipped),
    filler words, and ranges the creator asked to remove."""
    cuts: list[Range] = []
    for s in silences:
        a = s.start + padding if s.start > 0 else 0.0
        b = s.end - padding if s.end < duration else duration
        if b > a:
            cuts.append(Range(start=a, end=b))
    if transcript and remove_fillers:
        cuts += filler_ranges(transcript)
    cuts += removed or []
    keep = subtract([Range(start=0.0, end=duration)], cuts)
    keep = merge(keep, gap=0.05)
    return [r for r in keep if r.duration >= min_keep]


def map_time(t: float, keep: list[Range]) -> float | None:
    """Source time -> output time after the cut, or None if t was cut."""
    offset = 0.0
    for r in keep:
        if r.start <= t <= r.end:
            return offset + (t - r.start)
        offset += r.duration
    return None


def clip_to(keep: list[Range], window: Range) -> list[Range]:
    """The parts of keep that fall inside window (used to cut silences out of a Short)."""
    out = []
    for r in keep:
        a, b = max(r.start, window.start), min(r.end, window.end)
        if b > a:
            out.append(Range(start=a, end=b))
    return out
