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
| `set_color_grade` | Lighting and color: presets (`darker`, `warm`, `cinematic`, `night`, `black_and_white`...) or brightness, contrast, saturation, gamma, warmth, vignette; whole video or a time range |
| `add_text` / `update_text` / `remove_text` | Custom on-screen text in any font, size, color and position, with motion: fade, slide in from / out to any side, pop, zoom, blur, typewriter |
| `list_fonts` | Fonts installed on the server |
| `render` | Long cut, Shorts (1080x1920, captions burned in), or a fast 480p preview |
| `get_project` | Current lengths, cuts, Shorts, output files |

## Web app

To put it online, see [DEPLOY.md](DEPLOY.md) (Fly.io, about $5 to $16/month).

`cutline-web` serves the marketing site at `/`, the Studio showcase at `/studio`, and the editor (a chat center) at `/app`:

- Upload a video (drag and drop), then Cutline cuts silences and ums and makes captioned Shorts automatically.
- Watch the long cut and each Short in the browser, and download the MP4s.
- **Edit by chatting**: "cut the sponsor read", "give me 2 more Shorts", "karaoke captions". Claude drives
  the same tools the MCP connector exposes (the list is read from the MCP server, so new tools show up in
  the chat automatically). Needs `ANTHROPIC_API_KEY` set on the server; without it, the rest of the app
  still works and the chat box says it's off.
- Waitlist form on the landing page writes to `$CUTLINE_HOME/waitlist.jsonl`.

```bash
pip install -e '.[web,transcribe]'
cutline-web                           # http://localhost:8080
docker build -t cutline . && docker run -p 8080:8080 -v cutline-data:/data cutline
```

Code: `cutline/web.py` (Starlette API + background jobs), `cutline/agent.py` (Claude tool loop),
`cutline/site/` (plain HTML/CSS/JS, no build step; no sample footage, every edit runs on the creator's own upload). The landing page is a single static file, so it can
also go on GitHub Pages; set `<meta name="cutline-api">` in `site/index.html` to the app's URL.

Not built yet: accounts and sign-in, per-user storage limits, billing, and a real job queue (jobs run in
threads, so one server handles a handful of creators at once).

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
