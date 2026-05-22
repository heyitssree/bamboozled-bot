import type { PlayerState } from '../types'

interface Props {
  player: PlayerState
  size?: 'sm' | 'md' | 'lg'
  showScore?: boolean
  isCurrent?: boolean
}

const SIZE_CLASSES = {
  sm: 'w-8 h-8 text-xs',
  md: 'w-12 h-12 text-sm',
  lg: 'w-16 h-16 text-base',
}

export function PlayerAvatar({ player, size = 'md', showScore = false, isCurrent = false }: Props) {
  const sizeClass = SIZE_CLASSES[size]
  const ringClass = isCurrent ? 'ring-4 ring-yellow-400 ring-offset-2 ring-offset-gray-900' : ''
  const dimClass = !player.is_connected ? 'opacity-40' : ''

  return (
    <div className={`flex flex-col items-center gap-1 ${dimClass}`}>
      <div className="relative">
        <img
          src={player.avatar_url || `https://cdn.discordapp.com/embed/avatars/0.png`}
          alt={player.username}
          className={`${sizeClass} rounded-full object-cover ${ringClass}`}
          onError={(e) => {
            ;(e.target as HTMLImageElement).src = 'https://cdn.discordapp.com/embed/avatars/0.png'
          }}
        />
        {player.has_sombrero && (
          <span className="absolute -top-2 -right-1 text-base leading-none">🪅</span>
        )}
        {player.frozen_turns > 0 && (
          <span className="absolute -bottom-1 -right-1 text-xs leading-none">❄️</span>
        )}
        {!player.is_connected && (
          <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center">
            <span className="text-xs">✕</span>
          </div>
        )}
      </div>
      <span className="text-white text-xs font-medium truncate max-w-[4rem] text-center">
        {player.username}
      </span>
      {player.consecutive_correct >= 2 && (
        <span className="text-xs text-orange-400">{'🔥'.repeat(Math.min(player.consecutive_correct, 3))}</span>
      )}
      {showScore && (
        <span className="text-yellow-300 font-bold text-xs">{player.score}pt</span>
      )}
    </div>
  )
}
