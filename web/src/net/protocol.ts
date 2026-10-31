/** Wire types for docs/protocol.md. The server decides everything; these only describe what arrives. */

export type Mode = 'bamboozled' | 'fff' | 'survival'
export type Phase = 'lobby' | 'playing' | 'results'

export interface Member {
  user_id: number
  name: string
  avatar_url: string
  ready: boolean
  connected: boolean
  spectator: boolean
  host: boolean
}

export interface Question {
  text: string
  answers: string[]
  category: string
  difficulty: string
  qtype: string
}

export interface PendingDecision {
  kind: 'answer' | 'draw' | 'spin' | 'pick_target' | 'pick_rule' | 'monkey'
  actor: number
  deadline_ms: number
  options: number[] | null
  can_skip: boolean
  which: 'chance' | 'wango' | null
  purpose: 'switcheroo' | 'gift' | null
}

export interface BzPlayer { user_id: number; score: number | null; silenced: boolean; golden_pass: boolean; sombrero: boolean; streak: number }
export interface BzReveal { kind: string; player: number; correct_index: number; chosen: number | null; timed_out: boolean; forfeit: boolean }
export interface BzView {
  mode: 'bamboozled'
  you: number | null
  stage: 'turns' | 'endgame'
  round: number
  total_rounds: number
  over: boolean
  champion: number | null
  turn_player: number
  mist: boolean
  players: BzPlayer[]
  law: { id: number; name: string; permanent: boolean } | null
  pending: PendingDecision | null
  waiting_question: boolean
  deadline_ms: number | null
  question: Question | null
  reveal: BzReveal | null
}

export interface FffPlayer { user_id: number; score: number; locked: boolean }
export interface FffReveal { index: number; correct_index: number; winners: number[]; answers: Record<string, number>; order: number[] }
export interface FffView {
  mode: 'fff'
  you: number | null
  over: boolean
  q_index: number
  total_q: number
  players: FffPlayer[]
  waiting_question: boolean
  deadline_ms: number | null
  question: Question | null
  your_answer: number | null
  reveal: FffReveal | null
}

export interface SurvivalReveal { correct_index: number; chosen: number | null; right: boolean }
export interface SurvivalView {
  mode: 'survival'
  you: number | null
  player: number
  streak: number
  over: boolean
  reason: 'wrong' | 'timeout' | 'quit' | 'error' | null
  waiting_question: boolean
  deadline_ms: number | null
  question: Question | null
  reveal: SurvivalReveal | null
}

export type GameView = BzView | FffView | SurvivalView

export interface ResultRow { user_id: number; rank: number; score: number; correct: number; details: Record<string, unknown> }
export interface BoardRow { user_id: number; streak: number; over: boolean; reason: string | null }

export interface RoomState {
  phase: Phase
  mode: Mode
  you: number
  role: 'player' | 'spectator'
  host: number | null
  server_now_ms: number
  deadline_ms: number | null
  config: { rounds: number | null; difficulty: string | null; category: string | null }
  min_players: number
  max_players: number
  can_start: boolean
  members: Member[]
  game: GameView | null
  board: BoardRow[] | null
  results: ResultRow[] | null
}

export interface Envelope<T = unknown> { v: 1; t: string; id?: string; seq: number; d: T }
export interface ServerError { code: string; message: string }
export interface GameEvent { kind: string; payload: Record<string, unknown> }

export type ClientMessage =
  | { t: 'READY'; d: { ready: boolean } }
  | { t: 'SET_MODE'; d: { mode: Mode } }
  | { t: 'SET_CONFIG'; d: { rounds?: number | null; difficulty?: string | null; category?: string | null } }
  | { t: 'START' | 'DRAW_CARD' | 'SPIN' | 'FORFEIT' | 'LEAVE' | 'REMATCH' | 'PING' | 'RESYNC'; d?: Record<string, never> }
  | { t: 'ANSWER'; d: { index: number } }
  | { t: 'PICK_TARGET'; d: { user_id: number | null } }
  | { t: 'PICK_RULE'; d: { rule_id: number } }
  | { t: 'MONKEY'; d: { choice: 'belly' | 'tail' } }

/** Close codes (docs/protocol.md). */
export const CLOSE = {
  NOT_AUTHENTICATED: 4401,
  FORBIDDEN: 4403,
  UNKNOWN_INSTANCE: 4404,
  REPLACED: 4409,
  TOO_MANY: 4429,
  RESTART: 1012,
  TRY_LATER: 1013,
} as const

export const LAWS: { id: number; name: string; description: string; permanent: boolean }[] = [
  { id: 1, name: 'Speed Tax', description: 'Correct in under 5 seconds? Lose 25 points anyway.', permanent: false },
  { id: 2, name: 'Slow Burn', description: 'Take over 20 seconds and miss? Lose 50 extra points.', permanent: false },
  { id: 3, name: 'Double Jeopardy', description: 'Wrong answers cost 100 points for everyone.', permanent: false },
  { id: 4, name: 'Hot Streak', description: 'Two correct answers in a row earns 75 bonus points.', permanent: false },
  { id: 5, name: 'Karma Tax', description: 'First place loses 50 points at the start of their turn.', permanent: false },
  { id: 6, name: 'Underdog Boost', description: 'Last place gains 50 points at the start of their turn.', permanent: false },
  { id: 7, name: 'Timeout Terror', description: 'Timeouts cost 200 points for everyone.', permanent: false },
  { id: 8, name: 'Lucky Last', description: 'The last seat to answer correctly earns 100 bonus points.', permanent: false },
  { id: 9, name: 'Streak Breaker', description: 'The leader draws a Wango card instead of a Chance card.', permanent: false },
  { id: 10, name: 'Mist Magnet', description: 'Permanent: the Mist lasts 4 turns.', permanent: true },
  { id: 11, name: 'Sombrero Curse', description: 'Permanent: the Sombrero penalty rises to 50 points.', permanent: true },
]

export const WHEEL_SEGMENTS = [
  'Ladder of Chance', 'Tax Season', 'Gift of the Bamboozle', 'Full Reversal',
  'Mystic Mist', 'Bonus Round', 'Wango Again', "Monkey's Choice",
] as const

export const MODE_INFO: Record<Mode, { title: string; blurb: string; players: string; icon: string }> = {
  bamboozled: {
    title: 'Bamboozled', icon: '🎡', players: '2 to 10 players, take turns',
    blurb: 'Answer a question, then draw a card, spin the wheel of mayhem and survive the Mist.',
  },
  fff: {
    title: 'Fastest Fingers First', icon: '⚡', players: '2 to 10 players, all at once',
    blurb: 'Everyone gets the same question. The fastest correct answer scores the most.',
  },
  survival: {
    title: 'Survival', icon: '💀', players: '1 or more, each plays solo',
    blurb: 'Keep your streak alive. One wrong answer or timeout ends your run. Others can watch.',
  },
}
