import { create } from 'zustand'
import type { ConnStatus, FatalInfo } from '../net/client'
import type { GameEvent, Question, RoomState, ServerError } from '../net/protocol'
import type { Settings } from './settings'
import { applySettings, loadSettings, saveSettings } from './settings'

export interface UiEvent { id: number; kind: string; payload: Record<string, unknown> }
export interface Toast { id: number; tone: 'error' | 'info'; text: string }
export interface Me { id: number; name: string }

export type Boot =
  | { phase: 'loading' }
  | { phase: 'ready' }
  | { phase: 'error'; kind: 'not_in_discord' | 'sign_in_failed'; message: string }

interface AppState {
  boot: Boot
  conn: ConnStatus
  fatal: FatalInfo | null
  interrupted: boolean         // the server restarted under us
  roomClosed: boolean
  me: Me | null
  room: RoomState | null
  lastQuestion: Question | null
  events: UiEvent[]
  toasts: Toast[]
  announcement: string
  settings: Settings
  clockOffset: number

  setBoot(boot: Boot): void
  setMe(me: Me): void
  setConn(conn: ConnStatus): void
  setFatal(fatal: FatalInfo | null): void
  applyState(room: RoomState): void
  pushEvent(event: GameEvent): void
  bye(reason: string): void
  serverError(error: ServerError): void
  toast(text: string, tone?: Toast['tone']): void
  dismissToast(id: number): void
  announce(text: string): void
  setSettings(patch: Partial<Settings>): void
  setClockOffset(ms: number): void
  reset(): void
}

let nextId = 1
const MAX_EVENTS = 40
const QUIET_ERRORS = new Set(['not_your_turn', 'bad_phase', 'already_answered']) // races between eager taps: no toast

/** Friendly wording for the server's error codes; every message says what happened and what to do. */
export const ERROR_TEXT: Record<string, string> = {
  not_host: 'Only the host can do that.',
  not_enough_players: 'You need more players to start this mode.',
  mode_disabled: 'That mode is switched off right now.',
  bad_config: 'That setting is out of range for this mode.',
  too_late: 'Too late: time was already up.',
  spectator: 'You are watching this game. You can join the next one.',
  rate_limited: 'Slow down a little: too many taps at once.',
  frame_too_big: 'That message was too large.',
}

const initial = () => ({
  boot: { phase: 'loading' } as Boot, conn: 'idle' as ConnStatus, fatal: null, interrupted: false, roomClosed: false,
  me: null, room: null, lastQuestion: null, events: [], toasts: [], announcement: '', clockOffset: 0,
})

export const useStore = create<AppState>((set, get) => ({
  ...initial(),
  settings: loadSettings(),

  setBoot: (boot) => set({ boot }),
  setMe: (me) => set({ me }),
  setConn: (conn) => set({ conn }),
  setFatal: (fatal) => set({ fatal }),
  applyState: (room) => {
    const q = room.game && 'question' in room.game ? room.game.question : null
    set((s) => ({
      room, conn: 'open', interrupted: false, roomClosed: false, fatal: null,
      lastQuestion: q ?? (room.phase === 'playing' ? s.lastQuestion : null),
    }))
  },
  pushEvent: (event) => {
    set((s) => ({ events: [...s.events, { id: nextId++, kind: event.kind, payload: event.payload }].slice(-MAX_EVENTS) }))
    // a message from the people running the bot ("restarting in 5 minutes"): show it to everyone in the room
    if (event.kind === 'admin_message' && typeof event.payload.text === 'string') get().toast(event.payload.text, 'info')
  },
  bye: (reason) => {
    if (reason === 'server_restart') set({ interrupted: true })
    else if (reason === 'room_closed') set({ roomClosed: true })
  },
  serverError: (error) => {
    if (QUIET_ERRORS.has(error.code)) return
    get().toast(ERROR_TEXT[error.code] ?? error.message ?? 'Something went wrong. Please try again.')
  },
  toast: (text, tone = 'error') => set((s) => ({ toasts: [...s.toasts, { id: nextId++, tone, text }].slice(-3) })),
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  announce: (announcement) => set({ announcement }),
  setSettings: (patch) => {
    const settings = { ...get().settings, ...patch }
    saveSettings(settings)
    applySettings(settings)
    set({ settings })
  },
  setClockOffset: (clockOffset) => set({ clockOffset }),
  reset: () => set({ ...initial(), settings: loadSettings() }),
}))

/** Server time in ms, corrected by the offset learned from STATE frames. */
export function serverNow(): number {
  return Date.now() + useStore.getState().clockOffset
}
