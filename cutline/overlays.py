"""Custom text overlays with motion, written as ASS subtitles and burned in by FFmpeg/libass.

Animations are baked frame by frame (one event per frame while text moves), so any easing,
direction or mix of slide/fade/scale/blur is possible without a motion-graphics engine.
"""

from __future__ import annotations

import math
import re

from .models import Range, TextAnim, TextOverlay
from .rough_cut import clip_to, map_time

ANIMS = ("none", "fade", "slide", "pop", "zoom", "blur", "typewriter")
DIRECTIONS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1),
              "top": (0, -1), "bottom": (0, 1), "none": (0, 0)}
# position -> (ASS alignment, x, y) as fractions of the frame
POSITIONS = {
    "center": (5, 0.5, 0.5), "top": (8, 0.5, 0.07), "bottom": (2, 0.5, 0.93),
    "left": (4, 0.05, 0.5), "right": (6, 0.95, 0.5),
    "top_left": (7, 0.05, 0.07), "top_right": (9, 0.95, 0.07),
    "bottom_left": (1, 0.05, 0.93), "bottom_right": (3, 0.95, 0.93),
    "lower_third": (1, 0.06, 0.84),
}

NAMED_COLORS = {
    "white": "FFFFFF", "black": "000000", "red": "FF3B30", "orange": "FF9500", "yellow": "FFD400",
    "gold": "FFD700", "green": "34C759", "lime": "32CD32", "teal": "008080", "cyan": "00FFFF",
    "sky blue": "87CEEB", "light blue": "ADD8E6", "baby blue": "89CFF0", "blue": "1E6FFF",
    "navy": "000080", "royal blue": "4169E1", "cutline blue": "2E5A8C", "purple": "AF52DE",
    "violet": "8F00FF", "pink": "FF2D92", "hot pink": "FF69B4", "magenta": "FF00FF",
    "brown": "8B5A2B", "grey": "8E8E93", "gray": "8E8E93", "silver": "C0C0C0", "cream": "FFF5D6",
    "beige": "F5F5DC", "mint": "98FF98", "coral": "FF7F50", "lavender": "E6E6FA", "turquoise": "40E0D0",
}


def parse_color(value: str) -> str:
    """'#87CEEB', '87ceeb', 'sky blue', 'skyblue' or 'rgb(135,206,235)' -> '87CEEB'."""
    v = value.strip().lower()
    if m := re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v):
        return "".join(f"{min(255, int(c)):02X}" for c in m.groups())
    h = v.lstrip("#")
    if re.fullmatch(r"[0-9a-f]{6}", h):
        return h.upper()
    if re.fullmatch(r"[0-9a-f]{3}", h):
        return "".join(c * 2 for c in h).upper()
    named = {re.sub(r"[\s_-]", "", k): c for k, c in NAMED_COLORS.items()}
    key = re.sub(r"[\s_-]", "", v)
    if key in named:
        return named[key]
    raise ValueError(f"Unknown color '{value}'. Use a hex code like #87CEEB or a name like 'sky blue'")


def check(t: TextOverlay) -> TextOverlay:
    if not t.text.strip():
        raise ValueError("Text can't be empty")
    if t.end <= t.start:
        raise ValueError(f"Text '{t.text}' must end after it starts ({t.start}-{t.end})")
    if t.position not in POSITIONS:
        raise ValueError(f"Unknown position '{t.position}'. Use one of: {', '.join(POSITIONS)}")
    for c in ("color", "outline_color", "background"):
        if getattr(t, c) is not None:
            setattr(t, c, parse_color(getattr(t, c)))
    for a in (t.animate_in, t.animate_out):
        a.style = a.style.lower()
        a.direction = a.direction.lower()
        if a.style not in ANIMS:
            raise ValueError(f"Unknown animation '{a.style}'. Use one of: {', '.join(ANIMS)}")
        if a.direction not in DIRECTIONS:
            raise ValueError(f"Unknown direction '{a.direction}'. Use left, right, up or down")
        if not 0 <= a.seconds <= 10:
            raise ValueError("Animation seconds must be between 0 and 10")
    if t.applies_to not in ("all", "long", "shorts"):
        raise ValueError("applies_to must be all, long or shorts")
    if not 8 <= t.size <= 600:
        raise ValueError("size must be between 8 and 600")
    return t


# ---------- ASS writing ----------

def _bgr(rrggbb: str) -> str:
    return f"{rrggbb[4:6]}{rrggbb[2:4]}{rrggbb[0:2]}".upper()


def _cs(t: float) -> int:
    return max(0, int(round(t * 100)))


def _ts(cs: int) -> str:
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _esc(text: str) -> str:
    text = text.replace("\\N", "\n").replace("\\n", "\n")  # a literal backslash-n means a line break
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\r", "").replace("\n", "\\N")


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_in(p: float) -> float:
    return p ** 3


def _back_out(p: float) -> float:  # overshoots a little, for "pop"
    c = 1.70158
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def _state(anim: TextAnim, p: float, entering: bool) -> dict:
    """Look of the text at progress p (0 = hidden end of the animation, 1 = fully settled)."""
    s = {"opacity": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0, "blur": 0.0, "reveal": 1.0}
    if anim.style == "none":
        return s
    e = _ease_out(p) if entering else 1 - _ease_in(1 - p)
    if anim.style in ("fade", "slide", "pop", "zoom", "blur"):
        if anim.style != "slide" or anim.fade:
            s["opacity"] = e
    if anim.style == "slide":
        dx, dy = DIRECTIONS[anim.direction]
        s["dx"], s["dy"] = dx * anim.distance * (1 - e), dy * anim.distance * (1 - e)
    elif anim.style == "pop":
        s["scale"] = 0.5 + 0.5 * (_back_out(p) if entering else e)
    elif anim.style == "zoom":
        s["scale"] = 1.35 - 0.35 * e
    elif anim.style == "blur":
        s["blur"] = 14 * (1 - e)
    elif anim.style == "typewriter":
        s["reveal"] = p
    return s


def _alpha(base: int, opacity: float) -> str:
    """Combine a layer's own transparency (0 opaque..255 clear) with the animation's opacity."""
    a = 255 - (255 - base) * max(0.0, min(1.0, opacity))
    return f"&H{int(round(a)):02X}&"


def _style_line(name: str, t: TextOverlay, scale: float) -> str:
    box = t.background is not None
    outline_col = t.background if box else t.outline_color
    border = (12 if box else t.outline) * scale
    return (
        f"Style: {name},{t.font},{max(1, round(t.size * scale))},&H00{_bgr(t.color)},&H00FFFFFF,"
        f"&H00{_bgr(outline_col)},&H80000000,{-1 if t.bold else 0},{-1 if t.italic else 0},0,0,100,100,0,0,"
        f"{3 if box else 1},{border:.1f},{t.shadow * scale:.1f},5,40,40,40,1"
    )


def _events(name: str, t: TextOverlay, a: float, b: float, w: int, h: int, fps: float) -> list[str]:
    """Dialogue lines for one overlay shown from a to b (output seconds)."""
    if t.x is not None and t.y is not None:
        an, fx, fy = 5, t.x, t.y
    else:
        an, fx, fy = POSITIONS[t.position]
    text = _esc(t.text)
    dur = b - a
    tin, tout = t.animate_in.seconds, t.animate_out.seconds
    if t.animate_in.style == "none":
        tin = 0.0
    if t.animate_out.style == "none":
        tout = 0.0
    if tin + tout > dur:  # short overlay: squeeze the animations to fit
        k = dur / (tin + tout)
        tin, tout = tin * k, tout * k
    base_out = 0x00
    base_shadow = 0x80

    def line(c0: int, c1: int, st: dict) -> str | None:
        if c1 <= c0:
            return None
        x = (fx + st["dx"]) * w
        y = (fy + st["dy"]) * h
        tags = f"\\an{an}\\pos({x:.1f},{y:.1f})"
        tags += f"\\1a{_alpha(0, st['opacity'])}\\3a{_alpha(base_out, st['opacity'])}\\4a{_alpha(base_shadow, st['opacity'])}"
        if st["scale"] != 1.0:
            tags += f"\\fscx{st['scale'] * 100:.1f}\\fscy{st['scale'] * 100:.1f}"
        if st["blur"] > 0.05:
            tags += f"\\blur{st['blur']:.1f}"
        body = text
        if st["reveal"] < 1.0:
            n = round(len(t.text) * st["reveal"])
            shown, rest = _esc(t.text[:n]), _esc(t.text[n:])
            body = shown + ("{\\alpha&HFF&}" + rest if rest else "")
        return f"Dialogue: 1,{_ts(c0)},{_ts(c1)},{name},,0,0,0,,{{{tags}}}{body}"

    out: list[str] = []

    def animate(t0: float, length: float, anim: TextAnim, entering: bool) -> None:
        frames = max(1, math.ceil(length * fps))
        for k in range(frames):
            c0 = _cs(t0 + length * k / frames)
            c1 = _cs(t0 + length * (k + 1) / frames)
            # entering ends fully settled (p=1); leaving ends fully gone (p=0)
            p = (k + 1) / frames if entering else 1 - (k + 1) / frames
            ln = line(c0, c1, _state(anim, p, entering))
            if ln:
                out.append(ln)

    if tin > 0:
        animate(a, tin, t.animate_in, True)
    hold = line(_cs(a + tin), _cs(b - tout), _state(TextAnim(style="none"), 1, True))
    if hold:
        out.append(hold)
    if tout > 0:
        animate(b - tout, tout, t.animate_out, False)
    return out


def span(t: TextOverlay, keep: list[Range]) -> tuple[float, float] | None:
    """Where a source-timed overlay lands in an output made of `keep`, or None if all of it was cut."""
    parts = clip_to(keep, Range(start=t.start, end=t.end))
    if not parts:
        return None
    return map_time(parts[0].start, keep), map_time(parts[-1].end, keep)


def build_ass(texts: list[TextOverlay], keep: list[Range], width: int, height: int, fps: float | None) -> str | None:
    """An ASS file with every overlay that appears in this output, or None if there are none."""
    fps = fps or 30.0
    fps = min(max(fps, 12.0), 60.0)
    scale = min(width, height) / 1080
    styles, events = [], []
    for i, t in enumerate(texts):
        sp = span(t, keep)
        if sp is None:
            continue
        name = f"T{i}"
        styles.append(_style_line(name, t, scale))
        events += _events(name, t, sp[0], sp[1], width, height, fps)
    if not events:
        return None
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        + "\n".join(styles)
        + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events)
        + "\n"
    )


def source_time(t: float, keep: list[Range]) -> float:
    """Output (cut) seconds -> source seconds, for creators who give times from the edited video."""
    offset = 0.0
    for r in keep:
        if t <= offset + r.duration:
            return r.start + (t - offset)
        offset += r.duration
    return keep[-1].end if keep else t
