import { create } from 'zustand'
import type {
  CardState,
  GamePhase,
  GameResult,
  PlayerState,
  QuestionState,
  ServerGameState,
  WheelResultState,
} from '../types'

interface GameStore {
  // Connection
  ws: WebSocket | null
  sessionId: string
  myPlayerId: string
  isConnected: boolean

  // Game state
  phase: GamePhase
  players: Record<string, PlayerState>
  joinOrder: string[]
  hostId: string
  currentQuestion: QuestionState | null
  currentPlayerId: string | null
  wheelResult: WheelResultState | null
  activeCard: CardState | null
  mistActive: boolean
  roundNumber: number
  totalRounds: number
  answersThisRound: Record<string, number>
  timePerQuestion: number

  // Game over
  gameResults: GameResult[]
  boliAwards: Record<string, number>

  // Actions
  setWs: (ws: WebSocket) => void
  setSessionId: (id: string) => void
  setMyPlayerId: (id: string) => void
  setConnected: (v: boolean) => void
  applyStateUpdate: (state: ServerGameState) => void
  setGameOver: (results: GameResult[], boliAwards: Record<string, number>, state: ServerGameState) => void
  sendMessage: (msg: object) => void
}

export const useGameStore = create<GameStore>((set, get) => ({
  ws: null,
  sessionId: '',
  myPlayerId: '',
  isConnected: false,

  phase: 'connecting',
  players: {},
  joinOrder: [],
  hostId: '',
  currentQuestion: null,
  currentPlayerId: null,
  wheelResult: null,
  activeCard: null,
  mistActive: false,
  roundNumber: 1,
  totalRounds: 10,
  answersThisRound: {},
  timePerQuestion: 30,

  gameResults: [],
  boliAwards: {},

  setWs: (ws) => set({ ws }),
  setSessionId: (id) => set({ sessionId: id }),
  setMyPlayerId: (id) => set({ myPlayerId: id }),
  setConnected: (v) => set({ isConnected: v }),

  applyStateUpdate: (s: ServerGameState) => {
    const phase = s.phase.toLowerCase() as GamePhase
    set({
      phase,
      players: s.players,
      joinOrder: s.join_order,
      hostId: s.host_id,
      currentQuestion: s.current_question,
      currentPlayerId: s.current_player_id,
      wheelResult: s.wheel_result,
      activeCard: s.active_card,
      mistActive: s.mist_active,
      roundNumber: s.round_number,
      totalRounds: s.total_rounds,
      answersThisRound: s.answers_this_round,
      timePerQuestion: s.config.time_per_question,
    })
  },

  setGameOver: (results, boliAwards, state) => {
    set({
      gameResults: results,
      boliAwards,
      phase: 'ended',
      players: state.players,
    })
  },

  sendMessage: (msg) => {
    const { ws } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  },
}))
