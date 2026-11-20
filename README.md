# Cutline

Edit long videos and make Shorts by talking to Claude. Upload a talking-head video, and Claude
cuts silences and filler words, removes what you ask, picks Short-worthy moments, and renders a
clean long cut plus vertical Shorts with captions.

## How it fits together

```
Claude (chat)  --MCP tools-->  cutline server  -->  FFmpeg / Whisper  -->  long_cut.mp4, short_01.mp4 ...
   reasoning:                     edit list (JSON):
   which moments, what to cut     keep ranges, removed ranges, shorts, caption style
```

Claude does the thinking; the server does the video work. Every edit is stored as an edit list over
the original file, so changes are instant and undoable until you render.

## MCP tools

| Tool | What it does |
| --- | --- |
| `create_project` | Start from a video file |
| `analyze` | Find silences, transcribe with word timestamps, plan the rough cut |
| `get_transcript` | Timestamped sentences, so Claude can find moments |
| `remove_ranges` / `restore_ranges` | Cut or bring back parts ("drop the sponsor read") |
| `tune_rough_cut` | Re-plan with more or less breathing room, fillers on or off |
| `suggest_shorts` / `add_shorts` | Heuristic shortlist, or Claude's own picks |
| `set_caption_style` | `bold`, `clean`, or `karaoke` (active word highlighted) |
| `render` | Long cut, Shorts (1080x1920, captions burned in), or a fast 480p preview |
| `get_project` | Current lengths, cuts, Shorts, output files |

## Run it

Needs Python 3.11+ and FFmpeg with libass.

```bash
pip install -e '.[transcribe,dev]'
pytest                                # end-to-end tests on a synthetic video

cutline auto my_video.mp4             # no chat: rough cut + 5 Shorts
cutline-mcp                           # MCP over stdio (Claude Desktop / Claude Code)
cutline-mcp --http 8000               # MCP over HTTP, for a remote connector
```

Claude Desktop config (`claude_desktop_config.json`):

```json
{ "mcpServers": { "cutline": { "command": "cutline-mcp" } } }
```

Then ask: "Make a project from ~/Videos/episode12.mp4, clean it up, cut the sponsor read, and give me
4 Shorts with karaoke captions."

## Status and next steps

Working: silence and filler removal, user cuts, Shorts with silence removed inside them, 9:16 center
crop, three caption styles, MCP server, CLI.

Next:
1. Upload page with signed URLs to object storage (the server currently reads local files).
2. Face-tracked reframing instead of center crop.
3. Hosted transcription (Deepgram or AssemblyAI) for speed; Whisper stays as the local option.
4. Titles, descriptions and chapters; Premiere / Resolve export (EDL/XML).
5. Background job queue so long renders don't block a tool call.
