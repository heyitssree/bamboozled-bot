/** Screen gallery (mock build only): every screen in every state, rendered from fixtures with no server.
 *  http://localhost:5173/?screen=bz-my-question  (see the ids below). Used by the axe run and the screenshot tests. */
import type { FatalInfo } from '../net/client'
import type { BzView, FffView, Member, Question, RoomState, SurvivalView } from '../net/protocol'
import { useStore } from '../state/store'

const NOW = () => Date.now()
const Q: Question = { text: 'Which planet in our solar system has the shortest day?', answers: ['Jupiter', 'Mars', 'Mercury', 'Neptune'], category: 'Science', difficulty: 'medium', qtype: 'multiple' }
const NAMES = ['Alice', 'Bob', 'Carol', 'Dave', 'Erin', 'Frank']

export const member = (i: number, over: Partial<Member> = {}): Member => ({
  user_id: i + 1, name: NAMES[i], avatar_url: '', ready: i % 2 === 0, connected: true, spectator: false, host: i === 0, ...over,
})
const members = (n: number, over: (i: number) => Partial<Member> = () => ({})) => Array.from({ length: n }, (_, i) => member(i, over(i)))

function room(over: Partial<RoomState> & { n?: number; you?: number } = {}): RoomState {
  const { n = 3, you = 1, ...rest } = over
  return {
    phase: 'lobby', mode: 'bamboozled', you, role: 'player', host: 1, server_now_ms: NOW(), deadline_ms: null,
    config: { rounds: 5, difficulty: null, category: null }, min_players: 2, max_players: 10, can_start: you === 1 && n >= 2,
    members: members(n), game: null, board: null, results: null, ...rest,
  }
}

const bz = (over: Partial<BzView> = {}, n = 3): BzView => ({
  mode: 'bamboozled', you: 1, stage: 'turns', round: 2, total_rounds: 5, over: false, champion: null, turn_player: 1, mist: false,
  players: Array.from({ length: n }, (_, i) => ({ user_id: i + 1, score: 500 - i * 75, silenced: false, golden_pass: false, sombrero: false, streak: 0 })),
  law: null, pending: null, waiting_question: false, deadline_ms: null, question: null, reveal: null, ...over,
})
const pend = (kind: NonNullable<BzView['pending']>['kind'], actor = 1, extra: Partial<NonNullable<BzView['pending']>> = {}): NonNullable<BzView['pending']> =>
  ({ kind, actor, deadline_ms: NOW() + 24_000, options: null, can_skip: false, which: null, purpose: null, ...extra })

const fff = (over: Partial<FffView> = {}): FffView => ({
  mode: 'fff', you: 1, over: false, q_index: 2, total_q: 10,
  players: [1, 2, 3, 4].map((id, i) => ({ user_id: id, score: 275 - i * 75, locked: false })),
  waiting_question: false, deadline_ms: NOW() + 8_000, question: Q, your_answer: null, reveal: null, ...over,
})

const surv = (over: Partial<SurvivalView> = {}): SurvivalView => ({
  mode: 'survival', you: 1, player: 1, streak: 6, over: false, reason: null, waiting_question: false, deadline_ms: NOW() + 12_000, question: Q, reveal: null, ...over,
})

export interface Fixture {
  id: string
  group: string
  visual?: boolean
  dialog?: 'settings' | 'stats'
  room?: RoomState
  fatal?: FatalInfo
  boot?: 'not_in_discord' | 'sign_in_failed' | 'loading'
  conn?: 'reconnecting'
  interrupted?: boolean
  roomClosed?: boolean
  lastQuestion?: Question
  toast?: string
  motion?: 'reduce'
  events?: { kind: string; payload: Record<string, unknown> }[]
  state?: 'joining'
}

const fatal = (kind: FatalInfo['kind'], code = kind as string, message = ''): FatalInfo => ({ kind, code, message })

export const FIXTURES: Fixture[] = [
  // sign-in and errors
  { id: 'splash-loading', group: 'splash', boot: 'loading', visual: true },
  { id: 'splash-joining', group: 'splash', state: 'joining' },
  { id: 'splash-not-in-discord', group: 'splash', boot: 'not_in_discord', visual: true },
  { id: 'splash-auth-failed', group: 'splash', fatal: fatal('auth', 'bad_token', 'Discord did not accept your sign-in.') },
  { id: 'splash-not-in-instance', group: 'splash', fatal: fatal('forbidden', 'not_in_instance', 'You are not part of this Activity session.') },
  { id: 'splash-opted-out', group: 'splash', fatal: fatal('forbidden', 'opted_out') },
  { id: 'splash-unknown-instance', group: 'splash', fatal: fatal('unknown_instance') },
  { id: 'splash-full', group: 'splash', fatal: fatal('full', 'server_full') },
  { id: 'splash-maintenance', group: 'splash', fatal: fatal('maintenance', 'maintenance') },
  { id: 'splash-replaced', group: 'splash', fatal: fatal('replaced') },
  // lobby
  { id: 'lobby-host', group: 'lobby', visual: true, room: room({ n: 4 }) },
  { id: 'lobby-player', group: 'lobby', visual: true, room: room({ n: 4, you: 2, can_start: false }) },
  { id: 'lobby-below-minimum', group: 'lobby', room: room({ n: 1, can_start: false }) },
  { id: 'lobby-spectator', group: 'lobby', room: room({ n: 3, you: 6, role: 'spectator', members: [...members(3), member(5, { spectator: true, ready: false })], can_start: false }) },
  { id: 'lobby-reconnecting', group: 'lobby', conn: 'reconnecting', room: room({ n: 3, members: members(3, (i) => (i === 1 ? { connected: false } : {})) }) },
  { id: 'lobby-fff', group: 'lobby', room: room({ n: 3, mode: 'fff', config: { rounds: 10, difficulty: 'hard', category: 'History' } }) },
  { id: 'lobby-survival', group: 'lobby', room: room({ n: 2, mode: 'survival', min_players: 1 }) },
  // bamboozled
  { id: 'bz-loading-question', group: 'bamboozled', room: room({ phase: 'playing', game: bz({ waiting_question: true }) }) },
  { id: 'bz-my-question', group: 'bamboozled', visual: true, room: room({ phase: 'playing', game: bz({ question: Q, pending: pend('answer'), deadline_ms: NOW() + 24_000 }) }) },
  { id: 'bz-waiting-question', group: 'bamboozled', room: room({ phase: 'playing', you: 2, game: bz({ you: 2, question: Q, pending: pend('answer', 1) }) }) },
  { id: 'bz-reveal-correct', group: 'bamboozled', visual: true, lastQuestion: Q,
    room: room({ phase: 'playing', game: bz({ pending: pend('draw', 1, { which: 'chance' }), reveal: { kind: 'turn', player: 1, correct_index: 2, chosen: 2, timed_out: false, forfeit: false } }) }) },
  { id: 'bz-reveal-wrong', group: 'bamboozled', lastQuestion: Q,
    room: room({ phase: 'playing', game: bz({ pending: pend('draw', 1, { which: 'wango' }), reveal: { kind: 'turn', player: 1, correct_index: 2, chosen: 0, timed_out: false, forfeit: false } }) }) },
  { id: 'bz-reveal-timeout', group: 'bamboozled', lastQuestion: Q,
    room: room({ phase: 'playing', game: bz({ reveal: { kind: 'turn', player: 1, correct_index: 2, chosen: null, timed_out: true, forfeit: false } }) }) },
  { id: 'bz-draw-card', group: 'bamboozled', events: [{ kind: 'card_drawn', payload: { player: 1, deck: 'chance', card: 'Lucky Llama' } }], motion: 'reduce',
    room: room({ phase: 'playing', game: bz({ pending: pend('draw', 1, { which: 'chance' }) }) }) },
  { id: 'bz-spin', group: 'bamboozled', visual: true, motion: 'reduce', events: [{ kind: 'wheel_result', payload: { player: 1, segment: 'Tax Season' } }],
    room: room({ phase: 'playing', game: bz({ pending: pend('spin') }) }) },
  { id: 'bz-pick-swap', group: 'bamboozled', room: room({ phase: 'playing', game: bz({ pending: pend('pick_target', 1, { options: [2, 3], can_skip: true, purpose: 'switcheroo' }) }) }) },
  { id: 'bz-pick-steal', group: 'bamboozled', room: room({ phase: 'playing', game: bz({ pending: pend('pick_target', 1, { options: [2, 3], purpose: 'gift' }) }) }) },
  { id: 'bz-pick-law', group: 'bamboozled', visual: true, room: room({ phase: 'playing', game: bz({ pending: pend('pick_rule') }) }) },
  { id: 'bz-monkey', group: 'bamboozled', visual: true, room: room({ phase: 'playing', game: bz({ pending: pend('monkey') }) }) },
  { id: 'bz-monkey-waiting', group: 'bamboozled', room: room({ phase: 'playing', you: 2, game: bz({ you: 2, pending: pend('monkey', 1) }) }) },
  { id: 'bz-mist', group: 'bamboozled', visual: true, room: room({ phase: 'playing', game: bz({ mist: true, question: Q, pending: pend('answer') }) }) },
  { id: 'bz-law-and-badges', group: 'bamboozled', room: room({ phase: 'playing', game: bz({ law: { id: 3, name: 'Double Jeopardy', permanent: false }, question: Q, pending: pend('answer'),
    players: [{ user_id: 1, score: 500, silenced: false, golden_pass: true, sombrero: true, streak: 2 }, { user_id: 2, score: 425, silenced: true, golden_pass: false, sombrero: false, streak: 0 }, { user_id: 3, score: 350, silenced: false, golden_pass: false, sombrero: false, streak: 0 }] }) }) },
  { id: 'bz-endgame', group: 'bamboozled', room: room({ phase: 'playing', game: bz({ stage: 'endgame', pending: pend('spin', 2), turn_player: 2 }) }) },
  { id: 'bz-spectator', group: 'bamboozled', room: room({ phase: 'playing', you: 6, role: 'spectator', game: bz({ you: 6, question: Q, pending: pend('answer') }) }) },
  { id: 'bz-reconnecting', group: 'bamboozled', conn: 'reconnecting', room: room({ phase: 'playing', game: bz({ question: Q, pending: pend('answer') }) }) },
  // fastest fingers
  { id: 'fff-open', group: 'fff', visual: true, room: room({ phase: 'playing', mode: 'fff', game: fff(), n: 4 }) },
  { id: 'fff-locked', group: 'fff', visual: true, room: room({ phase: 'playing', mode: 'fff', n: 4, game: fff({ your_answer: 1, players: [1, 2, 3, 4].map((id, i) => ({ user_id: id, score: 275 - i * 75, locked: id !== 4 })) }) }) },
  { id: 'fff-reveal', group: 'fff', visual: true, lastQuestion: Q,
    room: room({ phase: 'playing', mode: 'fff', n: 4, game: fff({ question: null, deadline_ms: null, reveal: { index: 2, correct_index: 2, winners: [2, 1], answers: { '1': 2, '2': 2, '3': 0 }, order: [2, 1, 3] } }) }) },
  { id: 'fff-reveal-too-late', group: 'fff', lastQuestion: Q,
    room: room({ phase: 'playing', mode: 'fff', n: 4, game: fff({ question: null, deadline_ms: null, reveal: { index: 2, correct_index: 2, winners: [2], answers: { '2': 2 }, order: [2] } }) }) },
  { id: 'fff-nobody', group: 'fff', lastQuestion: Q, room: room({ phase: 'playing', mode: 'fff', game: fff({ question: null, deadline_ms: null, reveal: { index: 2, correct_index: 2, winners: [], answers: {}, order: [] } }) }) },
  { id: 'fff-spectator', group: 'fff', room: room({ phase: 'playing', mode: 'fff', you: 6, role: 'spectator', game: fff({ you: 6 }) }) },
  // survival
  { id: 'surv-playing', group: 'survival', visual: true, room: room({ phase: 'playing', mode: 'survival', game: surv(), board: [{ user_id: 1, streak: 6, over: false, reason: null }, { user_id: 2, streak: 9, over: false, reason: null }, { user_id: 3, streak: 2, over: true, reason: 'wrong' }] }) },
  { id: 'surv-reveal-wrong', group: 'survival', lastQuestion: Q, room: room({ phase: 'playing', mode: 'survival', game: surv({ question: null, deadline_ms: null, over: true, reason: 'wrong', reveal: { correct_index: 2, chosen: 0, right: false } }), board: [{ user_id: 1, streak: 6, over: true, reason: 'wrong' }] }) },
  { id: 'surv-over-timeout', group: 'survival', visual: true, room: room({ phase: 'playing', mode: 'survival', game: surv({ question: null, deadline_ms: null, over: true, reason: 'timeout' }), board: [{ user_id: 1, streak: 6, over: true, reason: 'timeout' }, { user_id: 2, streak: 9, over: false, reason: null }] }) },
  { id: 'surv-gave-up', group: 'survival', room: room({ phase: 'playing', mode: 'survival', game: surv({ question: null, deadline_ms: null, over: true, reason: 'quit' }), board: [{ user_id: 1, streak: 6, over: true, reason: 'quit' }] }) },
  { id: 'surv-spectating', group: 'survival', room: room({ phase: 'playing', mode: 'survival', you: 6, role: 'spectator', game: null, board: [{ user_id: 1, streak: 4, over: false, reason: null }, { user_id: 2, streak: 9, over: false, reason: null }] }) },
  // results
  { id: 'results-win', group: 'results', visual: true, room: room({ phase: 'results', n: 4, results: [{ user_id: 2, rank: 1, score: 1150, correct: 5, details: {} }, { user_id: 1, rank: 2, score: 940, correct: 4, details: {} }, { user_id: 3, rank: 3, score: 610, correct: 2, details: {} }, { user_id: 4, rank: 4, score: 120, correct: 1, details: { left: 'afk' } }] }) },
  { id: 'results-tie', group: 'results', room: room({ phase: 'results', results: [{ user_id: 1, rank: 1, score: 800, correct: 4, details: {} }, { user_id: 2, rank: 2, score: 800, correct: 3, details: {} }] }) },
  { id: 'results-player-view', group: 'results', room: room({ phase: 'results', you: 3, results: [{ user_id: 2, rank: 1, score: 900, correct: 4, details: {} }, { user_id: 3, rank: 2, score: 400, correct: 2, details: {} }] }) },
  { id: 'results-survival', group: 'results', room: room({ phase: 'results', mode: 'survival', results: [{ user_id: 2, rank: 1, score: 9, correct: 9, details: { reason: 'wrong' } }, { user_id: 1, rank: 2, score: 6, correct: 6, details: { reason: 'quit' } }] }) },
  { id: 'results-empty', group: 'results', room: room({ phase: 'results', results: [] }) },
  // dialogs and overlays
  { id: 'dialog-settings', group: 'dialogs', dialog: 'settings', visual: true, room: room() },
  { id: 'dialog-stats', group: 'dialogs', dialog: 'stats', room: room() },
  { id: 'overlay-interrupted', group: 'overlays', interrupted: true, conn: 'reconnecting', room: room({ phase: 'playing', game: bz({ question: Q, pending: pend('answer') }) }) },
  { id: 'overlay-room-closed', group: 'overlays', roomClosed: true, room: room() },
  { id: 'overlay-toast', group: 'overlays', toast: 'Only the host can do that.', room: room({ n: 3, you: 2, can_start: false }) },
]

const BY_ID = new Map(FIXTURES.map((f) => [f.id, f]))
export const fixtureById = (id: string) => BY_ID.get(id)

/** Canned REST answers so the stats dialog has something to show without a server. */
export function installFakeApi(): void {
  const real = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
    if (url.startsWith('/api/me/stats')) return json({ games: 12, wins: 5, best_score: 1320, total_score: 9800, best_streak: 11 })
    if (url.startsWith('/api/leaderboard')) {
      return json({ rows: [
        { user_id: 2, name: 'Bob', wins: 9, games: 14, total_score: 12400, correct_answers: 9, total_questions: 10, avg_response_ms: 1840, streak: 14, difficulty: 'hard' },
        { user_id: 1, name: 'Alice', wins: 5, games: 12, total_score: 9800, correct_answers: 8, total_questions: 10, avg_response_ms: 2210, streak: 11, difficulty: 'medium' },
      ] })
    }
    return real(input, init)
  }
}

/** Put the store into a fixture's state. Events are pushed shortly after mount so animations see them as new. */
export function applyFixture(f: Fixture): void {
  const st = useStore.getState()
  st.reset()
  st.setMe({ id: f.room?.you ?? 1, name: NAMES[(f.room?.you ?? 1) - 1] })
  st.setBoot(f.boot === 'not_in_discord' ? { phase: 'error', kind: 'not_in_discord', message: '' }
    : f.boot === 'sign_in_failed' ? { phase: 'error', kind: 'sign_in_failed', message: 'Discord did not confirm the sign-in.' }
      : f.boot === 'loading' ? { phase: 'loading' } : { phase: 'ready' })
  if (f.fatal) st.setFatal(f.fatal)
  if (f.room) st.applyState(f.room)
  if (f.conn) st.setConn(f.conn)
  if (f.interrupted) st.bye('server_restart')
  if (f.roomClosed) st.bye('room_closed')
  if (f.lastQuestion) useStore.setState({ lastQuestion: f.lastQuestion })
  if (f.motion) st.setSettings({ motion: f.motion })
  if (f.conn) st.setConn(f.conn)
  if (f.toast) st.toast(f.toast)
  if (f.events) setTimeout(() => f.events!.forEach((e) => useStore.getState().pushEvent(e)), 60)
}
