"""MCP connector: these tools let Claude edit a creator's video by conversation.

Claude does the reasoning (which moments make good Shorts, which part is "the sponsor bit");
this server does the video work. Run locally with stdio, or as a remote connector over HTTP:

    talkcut-mcp                 # stdio, for Claude Desktop / Claude Code
    talkcut-mcp --http 8000     # streamable HTTP, for a remote connector
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from . import project as P
from .models import CaptionStyle, Range, Short

mcp = MCPServer(
    name="talkcut",
    instructions=(
        "Talkcut edits talking-head videos. Typical flow: create_project -> analyze -> review get_transcript "
        "-> remove_ranges for anything the creator wants gone -> pick 3-5 strong, self-contained moments "
        "of 15-60s (start on a hook, end on a payoff) and call add_shorts -> render. All times are seconds "
        "in the ORIGINAL source video. Edits are non-destructive; nothing is re-encoded until render."
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
