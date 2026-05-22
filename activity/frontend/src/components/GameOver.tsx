import { useEffect, useRef } from 'react'
import { useGameStore } from '../store/gameStore'

const CONFETTI_COLORS = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#FED766', '#2AB7CA',
  '#F0B429', '#E040FB', '#00BCD4', '#8BC34A', '#FF5722',
]

function Confetti() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = window.innerWidth
    canvas.height = window.innerHeight

    const pieces = Array.from({ length: 80 }, () => ({
      x: Math.random() * canvas.width,
      y: -20,
      vx: (Math.random() - 0.5) * 3,
      vy: Math.random() * 3 + 2,
      rotation: Math.random() * 360,
      rotationSpeed: (Math.random() - 0.5) * 5,
      color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
      size: Math.random() * 8 + 4,
    }))

    let alive = true
    function animate() {
      if (!alive || !ctx || !canvas) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      pieces.forEach((p) => {
        p.x += p.vx
        p.y += p.vy
        p.vy += 0.05 // gravity
        p.rotation += p.rotationSpeed
        if (p.y > canvas.height) {
          p.y = -20
          p.x = Math.random() * canvas.width
        }
        ctx.save()
        ctx.translate(p.x, p.y)
        ctx.rotate((p.rotation * Math.PI) / 180)
        ctx.fillStyle = p.color
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size / 2)
        ctx.restore()
      })
      requestAnimationFrame(animate)
    }
    animate()
    return () => {
      alive = false
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none"
      style={{ zIndex: 0 }}
    />
  )
}

export function GameOver() {
  const gameResults = useGameStore((s) => s.gameResults)
  const boliAwards = useGameStore((s) => s.boliAwards)
  const players = useGameStore((s) => s.players)

  const top3 = gameResults.slice(0, 3)
  const rest = gameResults.slice(3)

  const PODIUM_ORDER = [1, 0, 2] // 2nd, 1st, 3rd for visual podium
  const PODIUM_HEIGHTS = ['h-24', 'h-36', 'h-16']
  const PODIUM_MEDALS = ['🥈', '🥇', '🥉']

  return (
    <div className="relative flex flex-col items-center min-h-screen bg-gradient-to-b from-gray-900 via-purple-900/20 to-gray-900 p-6 overflow-hidden">
      <Confetti />

      <div className="relative z-10 w-full max-w-lg">
        <h1 className="text-4xl font-extrabold text-white text-center mb-2">Game Over!</h1>
        <p className="text-gray-400 text-center mb-8">Final Results</p>

        {/* Podium */}
        {top3.length >= 2 && (
          <div className="flex items-end justify-center gap-3 mb-8">
            {PODIUM_ORDER.filter((i) => top3[i]).map((rankIdx, pos) => {
              const result = top3[rankIdx]
              if (!result) return null
              const player = players[result.discord_id]
              return (
                <div
                  key={result.discord_id}
                  className="flex flex-col items-center gap-2 animate-slide-up"
                  style={{ animationDelay: `${pos * 0.15}s` }}
                >
                  <img
                    src={player?.avatar_url || 'https://cdn.discordapp.com/embed/avatars/0.png'}
                    alt={result.username}
                    className="w-14 h-14 rounded-full border-4 border-yellow-400 shadow-lg"
                    onError={(e) => {
                      ;(e.target as HTMLImageElement).src =
                        'https://cdn.discordapp.com/embed/avatars/0.png'
                    }}
                  />
                  <span className="text-white text-sm font-bold truncate max-w-[80px] text-center">
                    {result.username}
                  </span>
                  <span className="text-yellow-300 text-xs font-bold">{result.final_score}pt</span>
                  <div
                    className={`${PODIUM_HEIGHTS[pos]} w-20 bg-gray-700 rounded-t-xl flex flex-col items-center justify-start pt-2 gap-1`}
                  >
                    <span className="text-2xl">{PODIUM_MEDALS[pos]}</span>
                    {boliAwards[result.discord_id] > 0 && (
                      <span className="text-yellow-400 text-xs font-bold">
                        +{boliAwards[result.discord_id]} Boli
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Full results list */}
        {rest.length > 0 && (
          <div className="bg-gray-800 rounded-2xl p-4 mb-6">
            {rest.map((result) => (
              <div
                key={result.discord_id}
                className="flex items-center gap-3 py-2 border-b border-gray-700 last:border-0"
              >
                <span className="text-gray-400 text-sm w-6 text-center">{result.rank}.</span>
                <img
                  src={players[result.discord_id]?.avatar_url || 'https://cdn.discordapp.com/embed/avatars/0.png'}
                  alt={result.username}
                  className="w-8 h-8 rounded-full"
                  onError={(e) => {
                    ;(e.target as HTMLImageElement).src =
                      'https://cdn.discordapp.com/embed/avatars/0.png'
                  }}
                />
                <span className="text-white text-sm flex-1">{result.username}</span>
                <span className="text-yellow-300 text-sm font-bold">{result.final_score}pt</span>
                {boliAwards[result.discord_id] > 0 && (
                  <span className="text-green-400 text-xs">
                    +{boliAwards[result.discord_id]} Boli
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        <p className="text-gray-500 text-center text-sm">
          Boli points have been awarded! Run <code className="text-gray-300">/mypoints</code> to see your total.
        </p>
      </div>
    </div>
  )
}
