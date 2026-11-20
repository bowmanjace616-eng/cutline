"""Burned-in captions as ASS subtitles, timed to the cut (not the source)."""

from __future__ import annotations

from .models import CaptionStyle, Range, Word
from .rough_cut import map_time


def _ass_color(rrggbb: str) -> str:
    r, g, b = rrggbb[0:2], rrggbb[2:4], rrggbb[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def build_ass(words: list[Word], keep: list[Range], style: CaptionStyle, width: int, height: int) -> str:
    """Words are in source time; keep is the list of source ranges in the output, in order."""
    mapped: list[tuple[str, float, float]] = []
    for w in words:
        a, b = map_time(w.start, keep), map_time(w.end, keep)
        if a is None and b is None:
            continue  # word was cut
        a = a if a is not None else b
        b = b if b is not None else a + 0.2
        mapped.append((_esc(w.text), a, max(b, a + 0.05)))

    vertical = height > width
    size = style.size if vertical else int(style.size * 0.6)
    margin_v = int(height * (0.28 if vertical else 0.08))
    upper = style.preset in ("bold", "karaoke")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{size},{_ass_color(style.color)},&H000000FF,&H00000000,&H64000000,{-1 if upper else 0},0,0,0,100,100,0,0,1,{6 if upper else 3},2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    n = max(1, style.words_per_line)
    for i in range(0, len(mapped), n):
        group = mapped[i : i + n]
        texts = [g[0].upper() if upper else g[0] for g in group]
        if style.preset == "karaoke":
            hl = _ass_color(style.highlight)
            for k, (_, a, b) in enumerate(group):
                end = group[k + 1][1] if k + 1 < len(group) else b
                parts = [f"{{\\c{hl}}}{t}{{\\r}}" if j == k else t for j, t in enumerate(texts)]
                lines.append(f"Dialogue: 0,{_ts(a)},{_ts(end)},Default,,0,0,0,,{' '.join(parts)}")
        else:
            lines.append(f"Dialogue: 0,{_ts(group[0][1])},{_ts(group[-1][2])},Default,,0,0,0,,{' '.join(texts)}")
    return header + "\n".join(lines) + "\n"
