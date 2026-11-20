"""Find Short candidates.

Inside Claude, the chat model reads the transcript and picks moments itself, then calls
add_shorts. This heuristic is the fallback for the CLI and for a first suggestion:
it prefers dense, self-contained runs of sentences that start on a question or a strong opener.
"""

from __future__ import annotations

from .models import Sentence, Short, Transcript

HOOK_STARTS = ("why", "how", "what", "here's", "the secret", "nobody", "stop", "never", "the biggest", "if you")


def _score(group: list[Sentence]) -> float:
    dur = group[-1].end - group[0].start
    words = sum(len(s.text.split()) for s in group)
    density = words / dur if dur else 0  # words per second; energetic speech scores higher
    first = group[0].text.lower()
    hook = 1.5 if first.startswith(HOOK_STARTS) or first.endswith("?") else 1.0
    return density * hook


def suggest(transcript: Transcript, count: int = 5, min_len: float = 15, max_len: float = 60) -> list[Short]:
    sents = transcript.sentences()
    candidates: list[tuple[float, int, int]] = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            dur = sents[j].end - sents[i].start
            if dur > max_len:
                break
            if dur >= min_len:
                candidates.append((_score(sents[i : j + 1]), i, j))
    candidates.sort(reverse=True)
    picked: list[Short] = []
    used: list[tuple[float, float]] = []
    for _, i, j in candidates:
        a, b = sents[i].start, sents[j].end
        if any(a < ub and b > ua for ua, ub in used):
            continue
        used.append((a, b))
        title = sents[i].text[:60].rstrip(" ,.")
        picked.append(Short(title=title, start=a, end=b, hook=sents[i].text))
        if len(picked) >= count:
            break
    return sorted(picked, key=lambda s: s.start)
