import { useGameStore } from '../store/gameStore'
import { PlayerAvatar } from './PlayerAvatar'

interface Props {
  compact?: boolean
}

export function Scoreboard({ compact = false }: Props) {
  const players = useGameStore((s) => s.players)
  const joinOrder = useGameStore((s) => s.joinOrder)
  const currentPlayerId = useGameStore((s) => s.currentPlayerId)
  const mistActive = useGameStore((s) => s.mistActive)

  const sorted = [...joinOrder]
    .filter((id) => players[id])
    .map((id) => players[id])
    .sort((a, b) => b.score - a.score)

  if (compact) {
    return (
      <div className="bg-gray-800/80 rounded-xl p-3 flex flex-col gap-2 min-w-[160px]">
        <h3 className="text-white font-bold text-sm text-center">Scores</h3>
        {sorted.map((p, i) => (
          <div
            key={p.discord_id}
            className={`flex items-center gap-2 rounded-lg px-2 py-1 ${
              p.discord_id === currentPlayerId ? 'bg-yellow-500/20' : ''
            }`}
          >
            <span className="text-gray-400 text-xs w-4">{i + 1}.</span>
            <img
              src={p.avatar_url || 'https://cdn.discordapp.com/embed/avatars/0.png'}
              alt={p.username}
              className="w-6 h-6 rounded-full"
              onError={(e) => {
                ;(e.target as HTMLImageElement).src = 'https://cdn.discordapp.com/embed/avatars/0.png'
              }}
            />
            <span className="text-white text-xs flex-1 truncate">
              {p.has_sombrero ? '🪅 ' : ''}{p.username}
            </span>
            <span className="text-yellow-300 text-xs font-bold">
              {mistActive ? '???' : p.score}
            </span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="bg-gray-800 rounded-2xl p-6 w-full max-w-md mx-auto">
      <h2 className="text-white font-bold text-xl text-center mb-4">Scoreboard</h2>
      {mistActive && (
        <div className="text-center text-blue-300 text-sm mb-3 animate-pulse">
          🌫️ Mystic Mist — scores hidden!
        </div>
      )}
      <div className="flex flex-col gap-3">
        {sorted.map((p, i) => (
          <div
            key={p.discord_id}
            className={`flex items-center gap-3 rounded-xl px-4 py-3 transition-all ${
              i === 0
                ? 'bg-yellow-500/20 border border-yellow-500/40'
                : i === 1
                ? 'bg-gray-600/40 border border-gray-500/30'
                : i === 2
                ? 'bg-orange-900/20 border border-orange-700/30'
                : 'bg-gray-700/40'
            } ${p.discord_id === currentPlayerId ? 'ring-2 ring-yellow-400' : ''}`}
          >
            <span className="text-2xl w-8 text-center">
              {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i + 1}.`}
            </span>
            <PlayerAvatar player={p} size="sm" />
            <div className="flex-1">
              <div className="text-white font-medium text-sm">
                {p.has_sombrero ? '🪅 ' : ''}{p.username}
              </div>
              {p.consecutive_correct >= 2 && (
                <div className="text-orange-400 text-xs">
                  🔥 {p.consecutive_correct} streak!
                </div>
              )}
            </div>
            <div className="text-right">
              <div className="text-yellow-300 font-bold text-lg">
                {mistActive ? '???' : p.score}
              </div>
              <div className="text-gray-400 text-xs">points</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
