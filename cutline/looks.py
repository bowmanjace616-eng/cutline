"""Color and lighting: turn a ColorGrade into an FFmpeg filter chain.

The chain runs on the source frames before the cut is applied, so a grade's start/end are
source seconds, like every other time in a project.
"""

from __future__ import annotations

import re

from .models import ColorGrade

# Base numbers for each look. Explicit values passed with a preset override these.
PRESETS: dict[str, dict] = {
    "none": {},
    "darker": {"brightness": -0.06, "gamma": 0.8, "contrast": 1.05},
    "much_darker": {"brightness": -0.12, "gamma": 0.65, "contrast": 1.08},
    "brighter": {"brightness": 0.05, "gamma": 1.15},
    "warm": {"warmth": 0.35, "saturation": 1.05},
    "cool": {"warmth": -0.35},
    "cinematic": {"contrast": 1.12, "saturation": 0.9, "gamma": 0.95, "vignette": 0.35},
    "moody": {"brightness": -0.04, "contrast": 1.15, "saturation": 0.8, "gamma": 0.85, "vignette": 0.5},
    "night": {"brightness": -0.08, "gamma": 0.7, "saturation": 0.75, "warmth": -0.45, "vignette": 0.4},
    "golden_hour": {"warmth": 0.55, "saturation": 1.12, "contrast": 1.04, "gamma": 1.03},
    "vivid": {"saturation": 1.35, "contrast": 1.08},
    "vintage": {"saturation": 0.75, "warmth": 0.3, "contrast": 0.92, "vignette": 0.3},
    "black_and_white": {"saturation": 0.0, "contrast": 1.1},
}
# Extra filters a preset adds on top of the numbers (things the sliders can't express).
_EXTRA = {
    "cinematic": "colorbalance=rs=-0.04:bs=0.06:rh=0.06:bh=-0.05",  # teal shadows, warm highlights
    "vintage": "curves=preset=vintage",
}

ALIASES = {"dark": "darker", "bw": "black_and_white", "b&w": "black_and_white", "mono": "black_and_white",
           "teal_orange": "cinematic", "film": "cinematic", "sunset": "golden_hour", "bright": "brighter"}


def preset_name(name: str) -> str:
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    key = ALIASES.get(key, key)
    if key not in PRESETS:
        raise ValueError(f"Unknown look '{name}'. Try one of: {', '.join(PRESETS)}")
    return key


def build(preset: str | None = None, start: float | None = None, end: float | None = None, **values) -> ColorGrade:
    """A grade from a preset plus explicit overrides (None values are ignored)."""
    base: dict = {}
    if preset:
        preset = preset_name(preset)
        base = dict(PRESETS[preset])
    base.update({k: v for k, v in values.items() if v is not None})
    g = ColorGrade(preset=preset, start=start, end=end, **base)
    _check(g)
    return g


def _check(g: ColorGrade) -> None:
    limits = {"brightness": (-1, 1), "contrast": (0, 3), "saturation": (0, 3), "gamma": (0.1, 4),
              "warmth": (-1, 1), "vignette": (0, 1)}
    for k, (lo, hi) in limits.items():
        v = getattr(g, k)
        if not lo <= v <= hi:
            raise ValueError(f"{k}={v} is out of range ({lo} to {hi})")
    if g.start is not None and g.end is not None and g.end <= g.start:
        raise ValueError("The look's end must be after its start")


def is_neutral(g: ColorGrade) -> bool:
    return (g.brightness == 0 and g.contrast == 1 and g.saturation == 1 and g.gamma == 1
            and g.warmth == 0 and g.vignette == 0 and g.preset not in _EXTRA)


def _filters(g: ColorGrade) -> list[str]:
    out = []
    if g.warmth:
        # colortemperature: lower kelvin = warmer. 6500K is neutral.
        out.append(f"colortemperature=temperature={6500 - 3000 * g.warmth:.0f}:pl=0.5")
    if g.preset in _EXTRA:
        out.append(_EXTRA[g.preset])
    if (g.brightness, g.contrast, g.saturation, g.gamma) != (0, 1, 1, 1):
        out.append(
            f"eq=brightness={g.brightness:.3f}:contrast={g.contrast:.3f}:saturation={g.saturation:.3f}:gamma={g.gamma:.3f}"
        )
    if g.vignette:
        out.append(f"vignette=angle={0.15 + 0.55 * g.vignette:.3f}")
    if g.start is not None or g.end is not None:
        a = g.start if g.start is not None else 0
        b = g.end if g.end is not None else 1e9
        out = [f + (":" if "=" in f else "=") + f"enable='between(t,{a:.3f},{b:.3f})'" for f in out]
    return out


def filter_chain(grades: list[ColorGrade]) -> str | None:
    """Comma-joined FFmpeg filters for all grades, or None when nothing changes."""
    parts = [f for g in grades if not is_neutral(g) for f in _filters(g)]
    return ",".join(parts) if parts else None
