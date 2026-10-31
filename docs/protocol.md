# Game server protocol (v1)

One WebSocket per player: `wss://<app_id>.discordsays.com/api/ws` (relative: `/api/ws`). JSON text frames, at most
4 KB each, at most 10 messages a second per player. The server is the only authority: clients send *intents*, never
state, and everything a client may see arrives as a per-player view.

## Envelope
`{"v": 1, "t": "<TYPE>", "id": "<client message id, optional>", "seq": <server counter>, "d": { ... }}`

* A message with an `id` is idempotent: sending the same `id` again is answered with `ACK {id, duplicate: true}` and
  not applied twice (the last 64 ids per connection are remembered).
* `seq` counts the server's messages on this connection (1, 2, 3...). A gap means a message was lost: send `RESYNC`
  and the server answers with a full `STATE`. A reconnect always starts with a full `STATE`.
* Deadlines are absolute server timestamps in `deadline_ms`; `server_now_ms` (in every `STATE`) lets the client correct
  its clock. The client never decides a timeout.

## Connecting
1. Open the socket. Your **first** frame, within 5 seconds, must be `AUTH {access_token, instance_id}`. The token never
   goes in the URL.
2. The server asks Discord who you are and whether you are really inside that Activity instance, and takes your name,
   avatar, server and channel from Discord. Nothing about you is read from a client message.
3. On success you receive a `STATE`. On failure you receive `ERROR {code, message}` and the socket closes.

| Close code | Meaning |
|---|---|
| 4401 | not authenticated (bad or missing token, timeout, malformed first frame) |
| 4403 | signed in, but not allowed: not in this instance, opted out, no server channel |
| 4404 | Discord does not know this Activity instance |
| 4409 | the same user signed in from another window (you receive `BYE {reason: "kicked"}` first) |
| 4429 | too many messages / too slow to keep up |
| 1012 | the server is restarting or in maintenance (`BYE {reason: "server_restart"}`) |
| 1013 | try again later (server full, Discord unavailable) |

## Client to server
| Type | Payload | Who / when |
|---|---|---|
| `READY` | `{ready: bool}` | players, lobby |
| `SET_MODE` | `{mode: "bamboozled"\|"fff"\|"survival"}` | host, lobby |
| `SET_CONFIG` | `{rounds?, difficulty?, category?}` | host, lobby (rounds: Bamboozled 3-20, FFF 5-30) |
| `START` | `{}` | host, lobby; Bamboozled and FFF need 2 players, Survival 1 |
| `ANSWER` | `{index: 0-3}` | the player being asked (FFF: every player, once) |
| `DRAW_CARD`, `SPIN` | `{}` | the player whose card or spin it is |
| `PICK_TARGET` | `{user_id}` (`null` = skip, Switcheroo only) | the player choosing |
| `PICK_RULE` | `{rule_id: 1-11}` | the player who drew Bamboozle |
| `MONKEY` | `{choice: "belly"\|"tail"}` | the player facing the Golden Monkey |
| `FORFEIT` | `{}` | the active player, on a normal Bamboozled turn; Survival: give up |
| `LEAVE` | `{}` | stop playing and watch (ends your Survival run) |
| `REMATCH` | `{}` | host, results screen: back to the lobby |
| `PING`, `RESYNC` | `{}` | any; `PING` answers `PONG`, `RESYNC` answers a full `STATE` |

Unknown message types are ignored. A malformed frame gets `ERROR {code}` (`bad_json`, `bad_frame`, `bad_payload`,
`frame_too_big`, `rate_limited`) and the socket stays open. Every message has a strict schema: unknown fields are rejected.

## Server to client
| Type | Payload |
|---|---|
| `STATE` | the full view for *you* (below); sent on every change and on (re)connect |
| `EVENT` | `{kind, payload}`: an animation cue (`wheel_result`, `card_drawn`, `steal`, `mist_on`, ...). Never needed to rebuild state |
| `ERROR` | `{code, message}`: `not_host`, `bad_phase`, `not_your_turn`, `spectator`, `bad_index`, `bad_target`, `bad_rule`, `bad_choice`, `too_late`, `already_answered`, `not_enough_players`, `mode_disabled`, `bad_config`, ... |
| `ACK` | `{id, duplicate: true}` |
| `PONG` | `{server_now_ms}` |
| `BYE` | `{reason: "server_restart" \| "room_closed" \| "kicked"}` |

### STATE
```
phase            "lobby" | "playing" | "results"
mode, config     the chosen mode and {rounds, difficulty, category}
you, role        your user id; "player" or "spectator"
host             user id of the host
members[]        {user_id, name, avatar_url, ready, connected, spectator, host}
min_players, max_players, can_start
server_now_ms, deadline_ms
game             the engine's view for you (see below), or null in the lobby
board            Survival only: [{user_id, streak, over, reason}] for everyone
results          after a game: [{user_id, rank, score, correct, details}]
```
`game` for **Bamboozled**: `stage`, `round`, `total_rounds`, `turn_player`, `players[]` (`score` is `null` while the Mist is
up), `law`, `pending {kind, actor, deadline_ms, options, can_skip, which, purpose}` (`which`: chance or wango for a draw; `purpose`: switcheroo or gift for a target pick), `question` (never the correct index), `reveal`.
For **FFF**: `players[] {user_id, score, locked}`, `q_index`, `total_q`, `question`, `your_answer` (only yours), `reveal`.
For **Survival** (your own run): `streak`, `question`, `reveal`, `reason`.
The correct answer first appears in `reveal`, after the answer is in.

## Rooms and seats
One room per Activity instance. The first player is the host. A player who joins a running game, or a full lobby,
is a spectator. A disconnect keeps your seat for `activity.reconnect_grace_seconds` (30 s); after that your seat is
dropped, the engine removes you from the game, and if you return you are a spectator. A second window for the same user
replaces the first. Idle lobbies close after 15 minutes, idle games after 30.

## REST (all under `/api`)
`GET /health` -> `{status}` (no auth). `POST /oauth/token {code}` -> `{access_token}` (rate-limited per IP and per code).
`GET /me/stats?mode=` and `GET /leaderboard?mode=&scope=server|global` need `Authorization: Bearer <token>` and
`X-Instance-Id`. No CORS: the app is same-origin through Discord's proxy mapping.
