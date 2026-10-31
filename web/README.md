# Bamboozled web app (the Discord Activity GUI)

React + TypeScript + Vite + Zustand. One app for all three modes. It shows what the server decided and sends intents;
no game rule lives here. Protocol: `docs/protocol.md` at the repository root.

```
src/
  sdk/        discord.ts (Embedded App SDK), mock.ts (stand-in for dev and tests). Nothing else imports the SDK (lint rule).
  net/        the only thing that talks to the server: AUTH frame, 30 s ping, backoff + jitter, seq-gap resync, clock offset
  state/      one Zustand store, fed only by STATE and EVENT frames; settings (theme, motion, sound)
  components/ the design system: Button, IconButton, Avatar, PlayerChip, TimerRing, AnswerButton, FlipCard, Wheel,
              Scoreboard, Podium, Modal, Toast, Banner, Tabs, Toggle, Skeleton
  screens/    Splash (sign-in and every error), Lobby, Bamboozled, Fff, Survival, Results, Stats, Settings
  styles/     tokens.css is the only place colours, type, spacing, radii and motion are defined
  audio/      sound cues synthesised with the Web Audio API (nothing to download or license)
  app/        App shell, connection (SDK -> client -> store), fixtures (screen gallery, mock builds only)
tests/        unit (Vitest) | e2e, a11y, visual (Playwright, real Python server, mock Discord)
```

## Run it without Discord
```bash
# terminal 1: the real server with the fake sign-in (loopback only; refuses to start in production)
BAMBOOZLED_DEV_AUTH=1 BAMBOOZLED_ENV=dev python -m bamboozled
# terminal 2
cd web && npm install && VITE_MOCK_DISCORD=1 npm run dev
# open several tabs:  http://localhost:5173/?user=alice&instance=test1   ...&user=bob...   (alice, bob, carol, dave)
# the screen gallery (every screen in every state, no server needed):  http://localhost:5173/?screen=bz-my-question
```
Inside Discord the app uses relative URLs only (`/api/...`, `wss://<host>/api/ws`), so everything goes through the
Activity's URL mapping. Production builds contain no mock or gallery code (checked by `npm run size`).

## Checks
| Command | What it does |
|---|---|
| `npm run typecheck`, `npm run lint` | strict TypeScript; ESLint (React hooks, only `sdk/discord.ts` may import the Discord SDK) |
| `npm test` | Vitest: network client with a fake socket and timers, store replay, settings, SDK adapters, components, every screen |
| `npm run test:e2e` | Playwright, 2 to 4 browser contexts against the real server: a full game of each mode, drop a socket mid-question, late joiner, host leaves, a real server restart, settings, keyboard |
| `npm run test:a11y` | axe on every screen in every state, dark and light; fails on serious or critical findings |
| `npm run test:visual` | screenshots at 360, 768 and 1280 px against the approved baselines (macOS-rendered; other systems skip the pixel comparison), plus no sideways scroll at 320 px and 44 px touch targets |
| `npm run build && npm run size` | initial JavaScript under 250 KB gzipped, each mode its own chunk, no mock code |
| `npm run lighthouse` | mobile, simulated slow 4G and 4x CPU: performance, accessibility, FCP, LCP, blocking time, JS transferred |

Update baselines after an intended visual change with `npm run test:visual -- --update-snapshots` and review the images.

## Design notes
* **Never colour alone.** Correct and wrong carry an icon and a word; the turn marker says "Turn"; locked says "Locked in".
* **Motion** comes from server events (wheel, card flip, streak). Reduced motion (system setting or the toggle in Settings)
  shows every result at once.
* **Sound** starts after the first tap and has a mute toggle remembered for the session. All cues are synthesised here.
* **Theme**: dark by default, light from the system, manual override in Settings. Brand assets are an owner input: a
  neutral palette that passes contrast is used until they arrive.
* Fonts: the system font stack (nothing third-party is loaded).
