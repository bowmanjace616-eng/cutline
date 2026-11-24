"""Chat editing for the web app: Claude drives the same tools the MCP connector exposes.

The tool list comes from the MCP server at runtime, so anything added there (motion graphics,
AI scene edits, ...) shows up in the web chat with no extra code here.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from .server import mcp

MODEL = os.environ.get("CUTLINE_MODEL", "claude-opus-5-5")
MAX_STEPS = 25
# Tools that only make sense in the connector: the web app already made the project from the upload.
HIDDEN = {"create_project"}

SYSTEM = """You are Cutline, an AI video editor for YouTubers and short-form creators, working inside a web app.
The creator has uploaded one video; its project_id is {pid}. Every tool takes that project_id: always pass it.
Work only on that uploaded video. There is no sample, demo or stock footage: never refer to, suggest or fall back on
any example clip or another project, and never describe content that is not in the creator's own transcript.

How to work:
- If the project has no transcript yet, call analyze first.
- Read the transcript before choosing cuts or Shorts. Cut and Short times are seconds in the ORIGINAL source.
- Good Shorts are 15-60s, self-contained, open on a hook and end on a payoff.
- You can also change the picture: set_color_grade for lighting and color (darker, brighter, warmer, cinematic,
  black and white...), and add_text for custom on-screen words in any font, size, color and position, with motion
  graphics (fade, slide in from / out to any side, pop, zoom, blur, typewriter). If the creator gives no timing for
  text, show it near the start of the video for about 3-4 seconds and say when it appears.
- After changing the edit, render what changed (render what="long", "shorts" or "all") so the creator can watch it.
- Anything that costs money (ai_edit_scene) needs the creator's explicit yes in this chat first.
- Reply in plain, short sentences: say what you changed and what to look at. No markdown tables."""


def tool_specs() -> list[dict]:
    specs = []
    for t in asyncio.run(mcp.list_tools()):
        if t.name in HIDDEN:
            continue
        specs.append({"name": t.name, "description": t.description or "", "input_schema": t.input_schema})
    return specs


_PID_TOOLS: set[str] | None = None


def _needs_pid() -> set[str]:
    global _PID_TOOLS
    if _PID_TOOLS is None:
        _PID_TOOLS = {t["name"] for t in tool_specs() if "project_id" in t["input_schema"].get("properties", {})}
    return _PID_TOOLS


def run_tool(name: str, args: dict, pid: str) -> tuple[str, bool]:
    """Call one MCP tool. Returns (result text, is_error)."""
    if name in HIDDEN:
        return f"{name} is not available in the web app", True
    if name in _needs_pid():
        args = {**args, "project_id": pid}
    try:
        result = asyncio.run(mcp.call_tool(name, args))
    except Exception as e:  # tool errors come wrapped; show Claude the real reason
        cause = e.__cause__ or e
        return f"{type(cause).__name__}: {cause}", True
    return _as_text(result), False


def _as_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if content is not None:
        parts = [getattr(c, "text", "") for c in content]
        structured = getattr(result, "structured_content", None)
        if structured is not None and not any(parts):
            return json.dumps(structured)
        return "\n".join(p for p in parts if p)
    if isinstance(result, tuple):  # (content blocks, structured)
        return json.dumps(result[1]) if result[1] is not None else _as_text(result[0])
    if isinstance(result, list):
        return "\n".join(getattr(c, "text", str(c)) for c in result)
    return json.dumps(result) if not isinstance(result, str) else result


def has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def chat(pid: str, history: list[dict], user_text: str, client=None, on_tool=None) -> tuple[str, list[dict]]:
    """One creator turn. `history` is the stored API message list; returns (reply, new history)."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    messages = history + [{"role": "user", "content": user_text}]
    tools = tool_specs()
    for _ in range(MAX_STEPS):
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM.format(pid=pid),
            tools=tools,
            messages=messages,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        content = [b.model_dump(exclude_none=True) for b in resp.content]
        messages.append({"role": "assistant", "content": content})
        if resp.stop_reason == "refusal":
            return "Sorry, I can't help with that edit.", messages
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return text or "Done.", messages
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            if on_tool:
                on_tool(b.name)
            out, err = run_tool(b.name, dict(b.input or {}), pid)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out[:20000], "is_error": err})
        messages.append({"role": "user", "content": results})
    return "I stopped after a lot of steps. Tell me what to do next.", messages
