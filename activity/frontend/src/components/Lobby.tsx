import { useGameStore } from '../store/gameStore'
import { PlayerAvatar } from './PlayerAvatar'

export function Lobby() {
  const players = useGameStore((s) => s.players)
  const joinOrder = useGameStore((s) => s.joinOrder)
  const hostId = useGameStore((s) => s.hostId)
  const myPlayerId = useGameStore((s) => s.myPlayerId)
  const totalRounds = useGameStore((s) => s.totalRounds)
  const sendMessage = useGameStore((s) => s.sendMessage)

  const connectedPlayers = joinOrder.filter((id) => players[id]?.is_connected)
  const isHost = myPlayerId === hostId
  const canStart = connectedPlayers.length >= 2

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gradient-to-b from-purple-900 via-gray-900 to-gray-900 p-6">
      <div className="text-center mb-8">
        <h1 className="text-5xl font-extrabold text-white mb-2">
          🎪 Bamboozled!
        </h1>
        <p className="text-purple-300 text-lg">The trivia game where anything can happen</p>
      </div>

      <div className="bg-gray-800/80 rounded-2xl p-6 w-full max-w-lg mb-6 backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white font-bold text-lg">Players</h2>
          <span className="text-gray-400 text-sm">{connectedPlayers.length} joined</span>
        </div>

        {connectedPlayers.length === 0 ? (
          <div className="text-center py-8">
            <div className="text-gray-500 animate-pulse">Waiting for players to join...</div>
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-4">
            {connectedPlayers.map((id) => (
              <div key={id} className="flex flex-col items-center gap-1 animate-fade-in">
                <PlayerAvatar player={players[id]} size="lg" />
                {id === hostId && (
                  <span className="text-yellow-400 text-xs font-bold">HOST</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-gray-800/60 rounded-xl px-6 py-3 mb-6 text-sm text-gray-300 flex gap-6">
        <span>📋 {totalRounds} rounds</span>
        <span>⏱️ 30s per question</span>
        <span>🎯 Mixed difficulty</span>
      </div>

      {isHost ? (
        <button
          onClick={() => sendMessage({ type: 'START_GAME' })}
          disabled={!canStart}
          className={`px-10 py-4 rounded-2xl font-bold text-xl transition-all ${
            canStart
              ? 'bg-purple-600 hover:bg-purple-500 text-white shadow-lg shadow-purple-900/50 active:scale-95'
              : 'bg-gray-700 text-gray-500 cursor-not-allowed'
          }`}
        >
          {canStart ? '🚀 Start Game' : `Need ${2 - connectedPlayers.length} more player(s)`}
        </button>
      ) : (
        <div className="text-gray-400 text-center animate-pulse">
          Waiting for the host to start the game...
        </div>
      )}
    </div>
  )
}
