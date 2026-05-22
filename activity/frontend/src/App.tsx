import { useEffect, useState } from 'react'
import { setupDiscord, getAvatarUrl, type DiscordUser } from './discord'
import { useWebSocket } from './hooks/useWebSocket'
import { useGameStore } from './store/gameStore'
import { audio } from './audio/AudioManager'
import { Lobby } from './components/Lobby'
import { WheelOfMayhem } from './components/WheelOfMayhem'
import { QuestionCard } from './components/QuestionCard'
import { BamboozleCard } from './components/BamboozleCard'
import { Scoreboard } from './components/Scoreboard'
import { GameOver } from './components/GameOver'
import './index.css'

// Sound preload list
const SOUNDS = [
  'wheel_spin', 'correct', 'wrong', 'golden_monkey',
  'bamboozle', 'mist', 'sombrero', 'game_over', 'tick',
]

interface SetupState {
  loading: boolean
  error: string | null
  user: DiscordUser | null
  sessionId: string
}

// --- Inner component that actually uses the WS hook (needs sessionId & playerId) ---
function Game({ user, sessionId }: { user: DiscordUser; sessionId: string }) {
  const avatarUrl = getAvatarUrl(user.id, user.avatar)
  useWebSocket(sessionId, user.id, user.username, avatarUrl)

  const phase = useGameStore((s) => s.phase)
  const setMyPlayerId = useGameStore((s) => s.setMyPlayerId)
  const setSessionId = useGameStore((s) => s.setSessionId)
  const sendMessage = useGameStore((s) => s.sendMessage)
  const currentPlayerId = useGameStore((s) => s.currentPlayerId)
  const myPlayerId = useGameStore((s) => s.myPlayerId)

  useEffect(() => {
    setMyPlayerId(user.id)
    setSessionId(sessionId)
  }, [user.id, sessionId])

  // NEXT_TURN after reveal — only current player / host sends it
  useEffect(() => {
    if (phase === 'reveal') {
      const t = setTimeout(() => {
        if (myPlayerId === currentPlayerId) {
          sendMessage({ type: 'NEXT_TURN' })
        }
      }, 3000)
      return () => clearTimeout(t)
    }
  }, [phase])

  if (phase === 'connecting') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <div className="text-center">
          <div className="text-white text-xl animate-pulse mb-2">Connecting...</div>
          <div className="text-gray-500 text-sm">Joining session {sessionId}</div>
        </div>
      </div>
    )
  }

  if (phase === 'lobby') return <Lobby />
  if (phase === 'ended') return <GameOver />

  return (
    <div className="flex min-h-screen bg-gray-900">
      {/* Main content */}
      <div className="flex-1">
        {phase === 'wheel' && <WheelOfMayhem />}
        {(phase === 'question' || phase === 'reveal') && <QuestionCard />}
        {phase === 'card' && <BamboozleCard />}
      </div>

      {/* Sidebar scoreboard */}
      <div className="w-44 p-3 border-l border-gray-700 flex flex-col">
        <Scoreboard compact />
      </div>
    </div>
  )
}

export default function App() {
  const [setup, setSetup] = useState<SetupState>({
    loading: true,
    error: null,
    user: null,
    sessionId: '',
  })

  useEffect(() => {
    // Preload sounds (non-blocking)
    audio.preload(SOUNDS).catch(() => undefined)

    async function init() {
      try {
        const user = await setupDiscord()

        // Read session_id from URL search params (injected by the launcher)
        const params = new URLSearchParams(window.location.search)
        const sessionId = params.get('session_id') ?? ''
        if (!sessionId) {
          throw new Error('No session_id in URL. Launch Bamboozled via /bamboozled-activity.')
        }

        setSetup({ loading: false, error: null, user, sessionId })
      } catch (err) {
        setSetup({
          loading: false,
          error: err instanceof Error ? err.message : (typeof err === 'string' ? err : JSON.stringify(err)) || 'Unknown error',
          user: null,
          sessionId: '',
        })
      }
    }

    init()
  }, [])

  if (setup.loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <div className="text-white text-xl animate-pulse">Loading Bamboozled...</div>
      </div>
    )
  }

  if (setup.error || !setup.user) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 p-6">
        <div className="text-center max-w-md">
          <div className="text-4xl mb-4">😬</div>
          <h1 className="text-white text-2xl font-bold mb-2">Oops!</h1>
          <p className="text-red-400">{setup.error}</p>
        </div>
      </div>
    )
  }

  return <Game user={setup.user} sessionId={setup.sessionId} />
}
