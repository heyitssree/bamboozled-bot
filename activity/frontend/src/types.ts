export type GamePhase = 'connecting' | 'lobby' | 'wheel' | 'question' | 'card' | 'reveal' | 'ended'

export type WheelOutcome = 'NORMAL' | 'BAMBOOZLE' | 'GOLDEN_MONKEY' | 'MYSTIC_MIST' | 'SOMBRERO'
export type CardType = 'POINT_THIEF' | 'FREEZE' | 'DOUBLE_DOWN' | 'BLIND_ANSWER' | 'REVERSE'

export interface PlayerState {
  discord_id: string
  username: string
  avatar_url: string
  score: number
  has_sombrero: boolean
  consecutive_correct: number
  is_connected: boolean
  frozen_turns: number
  double_down_active: boolean
  blind_answer_active: boolean
  reverse_active: boolean
}

export interface QuestionState {
  text: string
  shuffled_answers: string[]
  correct_index?: number   // only present in REVEAL phase
  category: string
  difficulty: string
}

export interface WheelResultState {
  outcome: WheelOutcome
  label: string
  affected_player_id: string | null
}

export interface CardState {
  card_type: CardType
  label: string
  description: string
}

export interface GameConfig {
  total_rounds: number
  category: string | null
  difficulty: string
  time_per_question: number
}

export interface ServerGameState {
  session_id: string
  guild_id: string
  channel_id: string
  phase: string
  players: Record<string, PlayerState>
  join_order: string[]
  host_id: string
  current_question: QuestionState | null
  current_player_id: string | null
  wheel_result: WheelResultState | null
  active_card: CardState | null
  mist_active: boolean
  mist_turns_remaining: number
  round_number: number
  total_rounds: number
  answers_this_round: Record<string, number>
  config: GameConfig
}

export interface GameResult {
  discord_id: string
  username: string
  final_score: number
  rank: number
  boli_awarded: number
}

// WebSocket message discriminated union — client → server
export type ClientMessage =
  | { type: 'PLAYER_JOIN'; username: string; avatar_url: string }
  | { type: 'START_GAME' }
  | { type: 'WHEEL_ACK' }
  | { type: 'ANSWER_SUBMITTED'; answer_index: number }
  | { type: 'CARD_ACK' }
  | { type: 'NEXT_TURN' }

// WebSocket message discriminated union — server → client
export type ServerMessage =
  | { type: 'STATE_UPDATE'; state: ServerGameState }
  | { type: 'SOUND_CUE'; sound: string }
  | { type: 'GAME_OVER'; results: GameResult[]; boli_awards: Record<string, number>; state: ServerGameState }
  | { type: 'ERROR'; message: string }
