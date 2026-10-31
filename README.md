# Bamboozled

A chaos-trivia Discord bot: players take turns answering questions, draw Bamboozle cards, spin the Wheel of Mayhem and try to survive the Mist. It ships as two parts in this repo:

| Part | Folder | Needed? |
|---|---|---|
| Slash-command bot (`/bamboozled ...`, Survival, Fastest Fingers, stats) | repo root (`bot.py`) | Yes |
| Discord Activity (`/bamboozled-activity`, a React app plus a FastAPI backend) | `activity/` | Optional |

Bamboozled is a standalone project: it keeps its own results, stats and leaderboards and shares nothing with any other bot.

## Setup

All configuration lives in one file, `.env`, created from `.env.example`. Every variable in it has a comment saying where to find the value.

### 1. Use your existing Discord application

This guide assumes the Bamboozled application already exists in the [Developer Portal](https://discord.com/developers/applications) and the bot is already in your server. Open that application and:

1. **Bot** tab: click **Reset Token** and copy it into `DISCORD_TOKEN` (the old token stops working). No privileged intents are needed.
2. If the bot was invited without the `applications.commands` scope, re-invite it from **OAuth2 > URL Generator** (scopes `bot` and `applications.commands`).

### Where to find each `.env` value

Copy `.env.example` to `.env`, then fill it in from the table. "Portal" means the [Developer Portal](https://discord.com/developers/applications) page for your Bamboozled application.

| Variable | Needed for | How to get it |
|---|---|---|
| `DISCORD_TOKEN` | Bot (required) | Portal > **Bot** > **Reset Token**. It is shown once; copy it immediately. |
| `DISCORD_APPLICATION_ID` | Activity | Portal > **General Information** > **Application ID** (a 17-19 digit number). |
| `DISCORD_CLIENT_ID` | Activity backend | Same Application ID as above. |
| `VITE_DISCORD_CLIENT_ID` | Activity frontend | Same Application ID again. These three must be identical. |
| `DISCORD_CLIENT_SECRET` | Activity backend | Portal > **OAuth2** > **Client Secret** > **Reset Secret**. Shown once; keep it private. |
| `ACTIVITY_BACKEND_URL` | Activity | Where the backend is reachable from the bot. Same machine: `http://localhost:8000`. Hosted: its public `https://` URL, with no trailing slash. |
| `VITE_BACKEND_URL` | Activity frontend | The backend's websocket address as seen from inside Discord. Local: `ws://localhost:8000`. Hosted: `wss://` plus the backend host. Rebuild the frontend after changing it. |
| `DB_PATH` | Activity backend | Your choice. The default `data/bamboozled_activity.db` is fine. |
| `BAMBOOZLED_DB_PATH` | Bot (optional) | Where the bot keeps its SQLite database. Default `data/bamboozled.db`. |
| `LOG_TO_FILE` | Bot (optional) | `1` (default) also writes `logs/bamboozled.log`; set `0` in containers and under systemd (the unit already captures stdout in `logs/bot.log`). |
| `BAMBOOZLED_DEBUG` | Activity backend (optional) | `1` turns on the interactive API docs. Leave unset in production. |
| `ACTIVITY_CORS_ORIGINS` | Activity backend (optional) | Comma-separated allowed origins. Default: the local dev server and this application's Discord proxy host. |

For the bot alone, only `DISCORD_TOKEN` is required. The Discord IDs and secrets above are one-time copies from the Portal, and Reset Token / Reset Secret invalidate the previous value.

### 2. Run the bot

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env: set DISCORD_TOKEN (the rest is optional)
python bot.py
```

You should see `Synced N slash command(s)` and `Bamboozled bot is ready!`. Global slash commands can take up to an hour to appear the first time. For instant registration while testing, sync to one server (see the comment in `setup_hook` in `bot.py`).

Try `/bamboozled help`, then `/bamboozled join` and `/bamboozled start`.

Run the tests with `pip install -r requirements-dev.txt && python -m pytest`. They run fully offline; the two tests that call the live OpenTDB API are marked `network` and skipped by default (`python -m pytest -m network` runs them).

The database is created and upgraded automatically at start-up by numbered migrations in `bamboozled/db/migrations/`.

### 3. Keep it running on a server (Linux, systemd)

```bash
git clone <your-repo-url> ~/bamboozled-bot && cd ~/bamboozled-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env
mkdir -p logs
# edit YOUR_USER and the paths in bamboozled.service, then:
sudo cp bamboozled.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bamboozled
tail -f logs/bot.log
```

To update: `git pull && sudo systemctl restart bamboozled`.

## Game server (the Activity's backend)

The new server runs in the same process as the bot and replaces the old `activity/backend` once the new web app
exists (Phase 4). Protocol: [docs/protocol.md](docs/protocol.md).

```bash
pip install -r requirements.txt
# try it without Discord: fake sign-in, loopback only, refuses to start in production
BAMBOOZLED_DEV_AUTH=1 BAMBOOZLED_ENV=dev python -m bamboozled      # http://127.0.0.1:8480/api/health
```
With `BAMBOOZLED_DEV_AUTH=1` a client signs in with the token `dev:<user_id>:<name>` and any instance id. It is refused
when `BAMBOOZLED_ENV=prod` or when SSM configuration is active, it only listens on 127.0.0.1, and it logs a warning
every minute. Without it the server verifies every player against Discord (needs `DISCORD_APPLICATION_ID`,
`DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`). Other settings: `BAMBOOZLED_PORT` (8480), `BAMBOOZLED_WEB_DIST` (built web
app, default `web_dist/`), `ORIGIN_VERIFY` (shared header value CloudFront sends).

Load check: `python tools/load_test.py` (20 rooms x 6 players for 10 minutes; `--seconds 60` for a quick run).

## Commands

| Command | What it does |
|---|---|
| App Launcher **Launch**, or `/play` | Launches the Activity from this channel. Also the **Play again** button on a result card |
| `/stats [user] [mode]` | Stats (private reply). Names are looked up from Discord when shown, never stored |
| `/leaderboard [mode] [scope]` | Top players in this server or everywhere (`/quizstats` is the old name, kept for one release) |
| `/privacy status`, `opt_out`, `opt_in` | See, or leave. Opting out asks you to confirm within 60 seconds, deletes your results and stats, and refuses while you are in a running game. Opting back in waits a few days and restores nothing |
| `/help` | What it is and how to start |
| `/bamboozled-admin ...` | `panel` (settings by category), `set`, `get`, `reset`, `status`, `rooms`, `export`, `import`, `testing on|off`. Bot owner, or members of the role in `system.panel_role` |
| `/bamboozled`, `/fff`, `/survival` | The old text games, registered only while `feature.text_mode` is on. Retired after cutover |

When a game ends the bot posts one result card (podium and scores, no mentions, never anyone who opted out) with a
**Play again** button. It skips quietly, logging once, if it cannot post in that channel.

## Settings and privacy

Every setting is declared once in `bamboozled/settings/registry.py` (label, bounds, choices, default). The admin panel,
`/bamboozled-admin set`, import and export all read it, the game server reads values at use time (a change applies to the
next room at once), and each change records who made it. Unknown keys stop start-up. `system.testing_guilds` marks
servers whose games are not recorded and post no card.

Privacy state lives in its own file, `privacy.db` next to the database (`BAMBOOZLED_PRIVACY_DB_PATH` to move it), and is never
purged. The bot stores Discord ids and results only; a purge removes a user's result rows, stat lines and any match left
empty, in one transaction.

## Discord Activity (optional)

The Activity is the same game in an embedded Discord window. `/bamboozled-activity` makes the bot ask the backend for a session and posts a launch button.

### A. Enable the Activity on your existing application

In the same application (skip any step that is already done):

1. **General Information**: copy the **Application ID** into `DISCORD_APPLICATION_ID`, `DISCORD_CLIENT_ID` and `VITE_DISCORD_CLIENT_ID` (all three the same).
2. **OAuth2**: **Reset Secret**, copy it into `DISCORD_CLIENT_SECRET`.
3. **Activities > Settings**: enable Activities.
4. **Activities > URL Mappings**: add a root mapping `/` pointing at the host serving the built frontend, and `/api` pointing at the backend host (without `https://`). The mapping is what lets the Activity reach your servers from inside Discord.
5. **Activities > Settings > Entry Point** (the Activity's launch command) is created by Discord automatically. `bot.py` already preserves it when syncing commands.

### B. Run the backend

```bash
cd activity/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

It reads the root `.env` (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DB_PATH`). Check `http://localhost:8000/health`.

### C. Build and host the frontend

```bash
cd activity/frontend
npm install
npm run dev        # local development on http://localhost:5173 (proxies /api to :8000)
npm run build      # production bundle in dist/, host it on any static host
```

`VITE_*` values come from the root `.env` and are baked in at build time, so rebuild after changing them. Local dev can be exposed to Discord with a tunnel such as `cloudflared tunnel --url http://localhost:5173`; put that tunnel host in the `/` URL mapping.

Point `ACTIVITY_BACKEND_URL` at the backend so the bot can create sessions, then restart the bot. The websocket address in `VITE_BACKEND_URL` has to be reachable from inside Discord, so either allow that host in the URL mappings or route it through the `/api` mapping, and test it in a real Discord client.

## Customising

- `game_engine/constants.py`: `SAFE_OPENTDB_CATEGORY_IDS` (allowed question categories).
- `data/custom_questions.json`: fallback questions used when OpenTDB is unreachable. Read at fetch time, no restart needed.

## Data and backups

The bot's SQLite database is `data/bamboozled.db` (override with `BAMBOOZLED_DB_PATH`), created on first start and git-ignored. It stores Discord ids and results only; names and avatars are looked up from Discord when shown and never saved. The Activity backend uses `DB_PATH`. Back up by copying the files.

## Troubleshooting

| Problem | Fix |
|---|---|
| `RuntimeError: DISCORD_TOKEN not set` | `.env` is missing or not in the folder you start the bot from |
| `/bamboozled` does not appear | Wait up to an hour for global sync; check the bot was invited with `applications.commands` |
| `/bamboozled-activity` says backend not configured | Set `ACTIVITY_BACKEND_URL` and `DISCORD_APPLICATION_ID`, restart the bot |
| Activity loads but cannot connect | Check the URL mappings and `VITE_BACKEND_URL`; rebuild the frontend after editing `.env` |
| Bot posts "restarted mid-game" notice | Expected after a restart during a game |
| `Too Many Requests` from OpenTDB | The bot retries once, then uses `custom_questions.json` |
