"""MCP connector: these tools let Claude edit a creator's video by conversation.

Claude does the reasoning (which moments make good Shorts, which part is "the sponsor bit");
this server does the video work. Run locally with stdio, or as a remote connector over HTTP:

    cutline-mcp                 # stdio, for Claude Desktop / Claude Code
    cutline-mcp --http 8000     # streamable HTTP, for a remote connector
"""

from __future__ import annotations

import sys
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from . import looks, overlays
from . import project as P
from .models import CaptionStyle, Range, Short, TextAnim, TextOverlay

mcp = MCPServer(
    name="cutline",
    instructions=(
        "Cutline edits any video: talking heads, b-roll, scenery, gameplay. For speech-driven edits the flow is: create_project -> analyze -> review get_transcript "
        "-> remove_ranges for anything the creator wants gone -> pick 3-5 strong, self-contained moments "
        "of 15-60s (start on a hook, end on a payoff) and call add_shorts -> render. All times are seconds "
        "in the ORIGINAL source video. Edits are non-destructive; nothing is re-encoded until render. "
        "Beyond cuts: set_color_grade changes lighting and color (darker, warmer, cinematic...), add_text puts "
        "custom titles on screen in any font, size, color and position, with motion (fade, slide in/out from any "
        "side, pop, zoom, blur, typewriter). Looks and text apply to the long cut and the Shorts. Text and looks "
        "need no transcript, so they work on clips with no speech. When the creator gives the exact words to show "
        "(even if they call them captions), use add_text; captions are only the automatic spoken-word subtitles."
    ),
)


@mcp.tool()
def create_project(source_path: str) -> dict:
    """Start a project from a video file on the server. Returns the project id and media info."""
    p = P.create(source_path)
    return {"project_id": p.id, **p.media.model_dump()}


@mcp.tool()
def analyze(project_id: str, transcribe: bool = True, min_silence_seconds: float = 0.6) -> dict:
    """Detect silences, transcribe with word timestamps, and plan the rough cut (silences and ums removed)."""
    p = P.analyze(P.load(project_id), do_transcribe=transcribe, min_silence=min_silence_seconds)
    return P.summary(p)


@mcp.tool()
def get_transcript(project_id: str, start: float = 0.0, end: float | None = None) -> list[dict]:
    """Timestamped sentences from the source, to find moments to cut or turn into Shorts."""
    p = P.load(project_id)
    if not p.transcript:
        raise ValueError("No transcript yet: run analyze first")
    return [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
        for s in p.transcript.sentences()
        if s.end >= start and (end is None or s.start <= end)
    ]


@mcp.tool()
def remove_ranges(project_id: str, ranges: list[Range]) -> dict:
    """Cut these source ranges from the long-form edit (e.g. a sponsor read or a tangent)."""
    return P.summary(P.remove(P.load(project_id), ranges))


@mcp.tool()
def restore_ranges(project_id: str, ranges: list[Range]) -> dict:
    """Undo earlier remove_ranges calls for these source ranges."""
    return P.summary(P.restore(P.load(project_id), ranges))


@mcp.tool()
def tune_rough_cut(project_id: str, remove_fillers: bool = True, padding_seconds: float = 0.15) -> dict:
    """Re-plan the automatic cut. Larger padding leaves more breathing room around speech."""
    return P.summary(P.replan(P.load(project_id), remove_fillers, padding_seconds))


@mcp.tool()
def suggest_shorts(project_id: str, count: int = 5) -> list[dict]:
    """A quick heuristic shortlist of Short candidates. Prefer reading the transcript and choosing yourself."""
    return [s.model_dump() for s in P.suggest_shorts(P.load(project_id), count)]


@mcp.tool()
def add_shorts(project_id: str, shorts: list[Short]) -> dict:
    """Set the Shorts to make: each has a title and a start/end in source seconds (15-60s works best)."""
    return P.summary(P.set_shorts(P.load(project_id), shorts))


@mcp.tool()
def set_caption_style(
    project_id: str, preset: str = "bold", color: str = "FFFFFF", highlight: str = "FFD400", words_per_line: int = 3
) -> dict:
    """Caption look for Shorts. preset: bold (uppercase, heavy outline), clean, or karaoke (active word highlighted)."""
    style = CaptionStyle(preset=preset, color=color, highlight=highlight, words_per_line=words_per_line)
    return P.summary(P.set_captions(P.load(project_id), style))


@mcp.tool()
def set_color_grade(
    project_id: str,
    preset: Annotated[str | None, Field(description=(
        "Starting look: " + ", ".join(looks.PRESETS) + ". 'none' removes all looks. "
        "Numbers you also pass override the preset's."))] = None,
    brightness: Annotated[float | None, Field(description="-1..1, 0 = unchanged. -0.05 is a gentle darken.")] = None,
    contrast: Annotated[float | None, Field(description="0..3, 1 = unchanged")] = None,
    saturation: Annotated[float | None, Field(description="0..3, 0 = black and white, 1 = unchanged")] = None,
    gamma: Annotated[float | None, Field(description="0.1..4, 1 = unchanged; below 1 darkens shadows and midtones")] = None,
    warmth: Annotated[float | None, Field(description="-1 (cool/blue) .. 1 (warm/orange), 0 = unchanged")] = None,
    vignette: Annotated[float | None, Field(description="0..1 darkened corners")] = None,
    start: Annotated[float | None, Field(description="Source seconds; leave empty for the whole video")] = None,
    end: Annotated[float | None, Field(description="Source seconds; leave empty for the whole video")] = None,
) -> dict:
    """Change lighting and color: darker/brighter, contrast, saturation, warm/cool, film looks, vignette.

    Without start/end the look replaces any earlier one and covers the whole video; with them it is added for
    that stretch only. Text overlays are not affected. Render afterwards to see it."""
    g = looks.build(preset, start, end, brightness=brightness, contrast=contrast, saturation=saturation,
                    gamma=gamma, warmth=warmth, vignette=vignette)
    return P.summary(P.set_grade(P.load(project_id), g))


_ANIM_DOC = "Animation: " + ", ".join(overlays.ANIMS) + ". 'slide' moves and fades; the others stay in place."


@mcp.tool()
def add_text(
    project_id: str,
    text: Annotated[str, Field(description="Words to show. Use \\n for a line break.")],
    start: Annotated[float, Field(description="When it appears, in seconds (see `timeline`)")],
    end: Annotated[float, Field(description="When it is gone, in seconds (see `timeline`)")],
    timeline: Annotated[str, Field(description=(
        "'source' = times in the original upload (default, like cuts and Shorts); 'cut' = times in the "
        "edited long video the creator is watching"))] = "source",
    position: Annotated[str, Field(description="One of: " + ", ".join(overlays.POSITIONS))] = "center",
    x: Annotated[float | None, Field(description="0..1 across the frame; with y, centres the text on that point")] = None,
    y: Annotated[float | None, Field(description="0..1 down the frame")] = None,
    font: Annotated[str, Field(description=(
        "Font family, e.g. Arial, Montserrat, Roboto. Common fonts that aren't installed (Arial, Helvetica, "
        "Times New Roman...) map to an identical-looking free font; list_fonts shows everything"))] = "Inter",
    size: Annotated[int, Field(description="Text height in px on a 1080p frame (scaled to each output). "
                                           "60 small, 96 title, 140 big, 200 huge")] = 96,
    color: Annotated[str, Field(description="Hex like #87CEEB or a name like 'sky blue'")] = "FFFFFF",
    bold: bool = True,
    italic: bool = False,
    outline: Annotated[float, Field(description="Outline thickness in px, 0 for none")] = 3.0,
    outline_color: str = "000000",
    shadow: Annotated[float, Field(description="Drop shadow distance in px, 0 for none")] = 2.0,
    background: Annotated[str | None, Field(description="Color of a box behind the text, or empty for none")] = None,
    animate_in: Annotated[str, Field(description=_ANIM_DOC)] = "fade",
    in_from: Annotated[str, Field(description="For slide: the side it comes in FROM: left, right, up, down")] = "right",
    animate_out: Annotated[str, Field(description=_ANIM_DOC)] = "fade",
    out_to: Annotated[str, Field(description="For slide: the side it leaves TOWARD: left, right, up, down")] = "left",
    in_seconds: Annotated[float, Field(description="Length of the entrance")] = 0.6,
    out_seconds: Annotated[float, Field(description="Length of the exit")] = 0.6,
    slide_distance: Annotated[float, Field(description="How far a slide travels, as a fraction of the frame")] = 0.15,
    applies_to: Annotated[str, Field(description="all, long (long cut only) or shorts (Shorts only)")] = "all",
) -> dict:
    """Put custom text on screen (titles, callouts, lower thirds) with motion graphics.

    Example, "fade in from the right and fade out to the left": animate_in="slide", in_from="right",
    animate_out="slide", out_to="left". Returns the project summary; the new text's id is in `added`.
    Render afterwards to see it."""
    p = P.load(project_id)
    font, font_note = overlays.resolve_font(font)
    if timeline not in ("source", "cut"):
        raise ValueError("timeline must be 'source' or 'cut'")
    if timeline == "cut":
        start, end = overlays.source_time(start, p.edits.keep), overlays.source_time(end, p.edits.keep)
    t = TextOverlay(
        id=P.next_text_id(p), text=text, start=start, end=end, position=position, x=x, y=y, font=font,
        size=size, color=color, bold=bold, italic=italic, outline=outline, outline_color=outline_color,
        shadow=shadow, background=background or None,
        animate_in=TextAnim(style=animate_in, direction=in_from, seconds=in_seconds, distance=slide_distance),
        animate_out=TextAnim(style=animate_out, direction=out_to, seconds=out_seconds, distance=slide_distance),
        applies_to=applies_to,
    )
    out = {"added": t.id, **P.summary(P.add_text(p, t))}
    if font_note:
        out["font_note"] = font_note + ". Tell the creator."
    return out


@mcp.tool()
def update_text(project_id: str, text_id: str, changes: dict) -> dict:
    """Change an existing text overlay. `changes` uses add_text's stored field names: text, start, end
    (source seconds), position, x, y, font, size, color, bold, italic, outline, outline_color, shadow, background,
    applies_to, and animate_in / animate_out as {"style", "direction", "seconds", "distance"}."""
    return P.summary(P.update_text(P.load(project_id), text_id, changes))


@mcp.tool()
def remove_text(project_id: str, text_id: str) -> dict:
    """Delete a text overlay by id, or every one with text_id="all"."""
    return P.summary(P.remove_text(P.load(project_id), text_id))


@mcp.tool()
def list_fonts() -> list[str]:
    """Font families installed on this server, for add_text's `font`."""
    return overlays.installed_fonts()


@mcp.tool()
def render(project_id: str, what: str = "all", preview: bool = False) -> dict:
    """Render outputs. what: long, shorts, or all. preview=True makes a fast 480p long-form preview."""
    p = P.load(project_id)
    if what in ("long", "all"):
        P.render_long(p, preview=preview)
    if what in ("shorts", "all") and not preview:
        P.render_shorts(p)
    return P.summary(p)


@mcp.tool()
def get_project(project_id: str) -> dict:
    """Current state of a project: lengths, cuts, Shorts and rendered files."""
    return P.summary(P.load(project_id))


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--http":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
        mcp.run("streamable-http", port=port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
