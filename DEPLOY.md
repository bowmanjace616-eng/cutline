# Putting Cutline online

Cutline runs as one Docker container (the site, the editor, the API and FFmpeg together) with a
disk for uploads and renders. The setup here targets [Fly.io](https://fly.io), the cheapest host we
found that can run video processing with a persistent disk.

## Cost (Fly.io prices as of November 2026)

| Piece | Size | Price |
| --- | --- | --- |
| Server | shared-cpu-2x, 2 GB RAM | $13.39/month if always on, less with auto-stop |
| Disk | 10 GB volume | $1.50/month |
| Bandwidth | first viewers | $0.02/GB out (North America, Europe) |
| Domain (optional) | e.g. a .com | about $10 to $15/year at any registrar |

`fly.toml` turns on auto-stop, so the server sleeps when nobody is on the site and you pay compute
only while it's in use. Expect roughly $5 to $16 a month during a small beta. A cheaper option is
`memory = "1gb"` and `size = "shared-cpu-1x"` in `fly.toml` ($6.70/month always on), which is fine for
short clips but slower for long videos.

Chat editing calls the Claude API and is billed by Anthropic per use, separately from hosting.

## One-time setup (about 15 minutes)

1. Create a Fly.io account at fly.io and add a card (required after the free trial).
2. Install flyctl (`brew install flyctl` or `curl -L https://fly.io/install.sh | sh`) and run `fly auth login`.
3. From this repo: `fly launch --copy-config --no-deploy`. Pick an app name; the site will be at
   `https://<name>.fly.dev`.
4. Set secrets (these never go in the repo or in chat):
   - `fly secrets set ANTHROPIC_API_KEY=...` turns on chat editing. Get a key at console.anthropic.com.
   - `fly secrets set CUTLINE_ACCESS_CODE=...` makes the editor invite-only. Pick any phrase and share it
     with beta testers. The marketing pages and waitlist stay public.
5. `fly deploy`. The first build takes a few minutes.

## Automatic deploys

`.github/workflows/deploy.yml` runs the tests and then deploys `main` to Fly on every push to `main`
(and on demand from the Actions tab). It needs one repository secret, set up once:

1. In the Fly dashboard (fly.io/dashboard), open the app **cutline-b1svdw** > **Tokens** > **Create token**
   (a deploy token for this app only). Or run `fly tokens create deploy -a cutline-b1svdw`. Copy the token.
2. On GitHub, open the repo > **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
   Name: `FLY_API_TOKEN`. Value: the token. Save.
3. Open the **Actions** tab > **Deploy to Fly** > **Run workflow** (branch `main`) to ship the current `main`.

If Fly's own GitHub integration was used to launch the app, it may be watching a different branch
(the first launch deployed the `flyio-new-files` branch). GitHub Actions is the one source of deploys
now, so `main` is always what's live. `https://cutline-app.com/healthz` shows the commit that is live under `version`.

## Custom domain

Buy the domain at any registrar, then run `fly certs add yourdomain.com` and add the DNS records it
prints at your registrar. HTTPS is set up automatically.

## Settings

| Variable | Default | What it does |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | none | Turns on chat editing |
| `CUTLINE_ACCESS_CODE` | none | Invite code for the editor and API |
| `CUTLINE_RETENTION_DAYS` | 7 | Uploads and renders older than this are deleted (0 keeps them) |
| `CUTLINE_MAX_JOBS` | 1 | Renders that run at once; others wait their turn |
| `CUTLINE_MAX_UPLOAD_MB` | 2048 | Largest upload |
| `CUTLINE_WHISPER_MODEL` | base | Speech model size (base, small, medium) |

Waitlist sign-ups are saved on the server disk in `/data/waitlist.jsonl`. Read them with
`fly ssh console -C "cat /data/waitlist.jsonl"`.
