# Bamboozled

A chaos-trivia Discord bot: players take turns answering questions, draw Bamboozle cards, spin the Wheel of Mayhem and try to survive the Mist. It ships as two parts in this repo:

| Part | Folder | Needed? |
|---|---|---|
| Slash-command bot (`/bamboozled ...`, Survival, Fastest Fingers, stats) | repo root (`bot.py`) | Yes |
| Discord Activity (`/bamboozled-activity`, a React app plus a FastAPI backend) | `activity/` | Optional |

Boli Points sharing with the Navi bot is optional too. Bamboozled runs fine on its own.

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
| `NAVI_DB_PATH` | Boli sharing, same machine | Absolute path to Navi's database file. In Navi it is the `DB_PATH` value, default `<navi-bot>/data/navi.db`. Leave empty to disable. |
| `BOT_INTERNAL_API_URL` | Boli sharing, Activity games | Navi's API address: `http://<host-or-ip>:8080`, where 8080 is Navi's `API_SERVER_PORT`. Use `http://localhost:8080` if both run on one machine. |
| `BOT_INTERNAL_SECRET` | Boli sharing, Activity games | You make it up. Run `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` and paste the same value into this `.env` and into Navi's `BOT_INTERNAL_SECRET`. |

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

Run the tests with `python -m unittest tests.test_all`. Two tests call the live OpenTDB API and fail when it is unreachable or rate limited.

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

It reads the root `.env` (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DB_PATH`, `BOT_INTERNAL_*`). Check `http://localhost:8000/health`.

### C. Build and host the frontend

```bash
cd activity/frontend
npm install
npm run dev        # local development on http://localhost:5173 (proxies /api to :8000)
npm run build      # production bundle in dist/, host it on any static host
```

`VITE_*` values come from the root `.env` and are baked in at build time, so rebuild after changing them. Local dev can be exposed to Discord with a tunnel such as `cloudflared tunnel --url http://localhost:5173`; put that tunnel host in the `/` URL mapping.

Point `ACTIVITY_BACKEND_URL` at the backend so the bot can create sessions, then restart the bot. The websocket address in `VITE_BACKEND_URL` has to be reachable from inside Discord, so either allow that host in the URL mappings or route it through the `/api` mapping, and test it in a real Discord client.

## Boli Points with Navi (optional)

Bamboozled can pay out Boli Points in the Navi bot, a separate project. There are two independent routes. Leave both unset to disable.

- **Same machine as Navi:** set `NAVI_DB_PATH` to Navi's SQLite file. At the end of each game the bot writes awards straight into it with plain SQL. A missing path or file is ignored; the bot never crashes because of it.
- **Activity games:** set `BOT_INTERNAL_API_URL` to Navi's API (port 8080 by default) and `BOT_INTERNAL_SECRET` to the same value as in Navi's `.env`.

| Component | Amount |
|---|---|
| Participation | `round(20 x difficulty_multiplier)` |
| Per correct answer | `correct_answers x 3` |
| Winner bonus | `round(50 x dm)` |
| 2nd place (3+ players) | `round(20 x dm)` |
| 3rd place (5+ players) | `round(10 x dm)` |
| Score bonus | `max(0, score) // 50` |
| Negative score penalty | `max(score // 100, -20)` |

Multipliers: Easy 0.75, Medium 1.0, Hard 1.5, Mixed 1.0. Only positive totals are written.

## Customising

- `game_engine/constants.py`: `BAMBOOZLE_RULE_FILTER_ENABLED` (profanity screen on player-typed rules) and `SAFE_OPENTDB_CATEGORY_IDS` (allowed question categories).
- `data/custom_questions.json`: fallback questions used when OpenTDB is unreachable. Read at fetch time, no restart needed.

## Data and backups

The bot's SQLite database is `db/bamboozled.db`, created on first start and git-ignored. The Activity backend uses `DB_PATH`. Back up by copying the files.

## Troubleshooting

| Problem | Fix |
|---|---|
| `RuntimeError: DISCORD_TOKEN not set` | `.env` is missing or not in the folder you start the bot from |
| `/bamboozled` does not appear | Wait up to an hour for global sync; check the bot was invited with `applications.commands` |
| `/bamboozled-activity` says backend not configured | Set `ACTIVITY_BACKEND_URL` and `DISCORD_APPLICATION_ID`, restart the bot |
| Activity loads but cannot connect | Check the URL mappings and `VITE_BACKEND_URL`; rebuild the frontend after editing `.env` |
| Boli not arriving in Navi | Check `NAVI_DB_PATH` exists, or that the two `BOT_INTERNAL_SECRET` values match |
| Bot posts "restarted mid-game" notice | Expected after a restart during a game |
| `Too Many Requests` from OpenTDB | The bot retries once, then uses `custom_questions.json` |
