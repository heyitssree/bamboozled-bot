import { useEffect, useRef, useState } from 'react'
import { useGameStore } from '../store/gameStore'
import type { WheelOutcome } from '../types'

const SEGMENTS: Array<{ outcome: WheelOutcome; label: string; color: string; icon: string }> = [
  { outcome: 'NORMAL', label: 'Normal', color: '#4B5563', icon: '⭐' },
  { outcome: 'BAMBOOZLE', label: 'Bamboozle!', color: '#DC2626', icon: '🃏' },
  { outcome: 'GOLDEN_MONKEY', label: 'Golden Monkey', color: '#D97706', icon: '🐒' },
  { outcome: 'MYSTIC_MIST', label: 'Mystic Mist', color: '#2563EB', icon: '🌫️' },
  { outcome: 'SOMBRERO', label: 'El Sombrero', color: '#7C3AED', icon: '🪅' },
  { outcome: 'NORMAL', label: 'Normal', color: '#4B5563', icon: '⭐' }, // duplicate for even spacing
]

const OUTCOME_COLORS: Record<WheelOutcome, string> = {
  NORMAL: 'text-gray-300',
  BAMBOOZLE: 'text-red-400',
  GOLDEN_MONKEY: 'text-yellow-400',
  MYSTIC_MIST: 'text-blue-400',
  SOMBRERO: 'text-purple-400',
}

const OUTCOME_BG: Record<WheelOutcome, string> = {
  NORMAL: 'bg-gray-700',
  BAMBOOZLE: 'bg-red-900/50',
  GOLDEN_MONKEY: 'bg-yellow-900/50',
  MYSTIC_MIST: 'bg-blue-900/50',
  SOMBRERO: 'bg-purple-900/50',
}

export function WheelOfMayhem() {
  const wheelResult = useGameStore((s) => s.wheelResult)
  const currentPlayerId = useGameStore((s) => s.currentPlayerId)
  const players = useGameStore((s) => s.players)
  const sendMessage = useGameStore((s) => s.sendMessage)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [spinning, setSpinning] = useState(true)
  const [revealed, setRevealed] = useState(false)
  const rotationRef = useRef(0)
  const animFrameRef = useRef<number>(0)

  const currentPlayer = currentPlayerId ? players[currentPlayerId] : null

  useEffect(() => {
    if (!wheelResult) return

    // Find which segment index matches the result
    const segIdx = SEGMENTS.findIndex((s) => s.outcome === wheelResult.outcome)
    const segAngle = (2 * Math.PI) / SEGMENTS.length
    const targetAngle = segIdx * segAngle

    // Spin: start fast, decelerate to land on result
    const totalRotation = Math.PI * 2 * 8 + (Math.PI * 2 - targetAngle) // 8 full spins + land
    const duration = 3000
    const startTime = performance.now()
    const startRotation = rotationRef.current

    function animate(now: number) {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      // Cubic ease-out
      const eased = 1 - Math.pow(1 - progress, 3)
      rotationRef.current = startRotation + totalRotation * eased
      drawWheel(rotationRef.current)

      if (progress < 1) {
        animFrameRef.current = requestAnimationFrame(animate)
      } else {
        setSpinning(false)
        setTimeout(() => setRevealed(true), 300)
      }
    }

    animFrameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(animFrameRef.current)
  }, [wheelResult])

  function drawWheel(rotation: number) {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const cx = canvas.width / 2
    const cy = canvas.height / 2
    const r = cx - 8

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    const segAngle = (2 * Math.PI) / SEGMENTS.length

    SEGMENTS.forEach((seg, i) => {
      const startAngle = rotation + i * segAngle
      const endAngle = startAngle + segAngle

      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.arc(cx, cy, r, startAngle, endAngle)
      ctx.closePath()
      ctx.fillStyle = seg.color
      ctx.fill()
      ctx.strokeStyle = '#1F2937'
      ctx.lineWidth = 2
      ctx.stroke()

      // Icon text
      ctx.save()
      ctx.translate(cx, cy)
      ctx.rotate(startAngle + segAngle / 2)
      ctx.translate(r * 0.65, 0)
      ctx.rotate(Math.PI / 2)
      ctx.font = '18px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(seg.icon, 0, 0)
      ctx.restore()
    })

    // Pointer triangle at top
    ctx.beginPath()
    ctx.moveTo(cx - 10, 0)
    ctx.lineTo(cx + 10, 0)
    ctx.lineTo(cx, 24)
    ctx.closePath()
    ctx.fillStyle = '#FBBF24'
    ctx.fill()
  }

  // Initial draw
  useEffect(() => {
    drawWheel(0)
  }, [])

  const outcome = wheelResult?.outcome
  const colorClass = outcome ? OUTCOME_COLORS[outcome] : 'text-white'
  const bgClass = outcome ? OUTCOME_BG[outcome] : 'bg-gray-800'

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-900 p-6">
      <div className="text-center mb-4">
        <h2 className="text-white text-xl font-bold">🎡 Wheel of Mayhem</h2>
        {currentPlayer && (
          <p className="text-gray-400 text-sm mt-1">
            {currentPlayer.username}'s turn
          </p>
        )}
      </div>

      <div className="relative mb-6">
        <canvas
          ref={canvasRef}
          width={280}
          height={280}
          className="drop-shadow-2xl"
        />
      </div>

      {revealed && wheelResult && (
        <div className={`${bgClass} rounded-2xl p-6 text-center animate-slide-up max-w-sm w-full mb-6`}>
          <div className="text-4xl mb-2">
            {SEGMENTS.find((s) => s.outcome === wheelResult.outcome)?.icon ?? '⭐'}
          </div>
          <div className={`text-2xl font-extrabold ${colorClass}`}>
            {wheelResult.label}
          </div>
          {wheelResult.outcome === 'SOMBRERO' && wheelResult.affected_player_id && players[wheelResult.affected_player_id] && (
            <p className="text-gray-300 text-sm mt-2">
              🪅 {players[wheelResult.affected_player_id].username} gets the sombrero!
            </p>
          )}
          {wheelResult.outcome === 'MYSTIC_MIST' && (
            <p className="text-gray-300 text-sm mt-2">Scores are hidden for the next 3 turns!</p>
          )}
          {wheelResult.outcome === 'GOLDEN_MONKEY' && (
            <p className="text-gray-300 text-sm mt-2">Correct answer = double points!</p>
          )}
          {wheelResult.outcome === 'BAMBOOZLE' && (
            <p className="text-gray-300 text-sm mt-2">Wrong answer = draw a Bamboozle Card!</p>
          )}
        </div>
      )}

      {revealed && (
        <button
          onClick={() => sendMessage({ type: 'WHEEL_ACK' })}
          className="px-8 py-3 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded-xl transition-all active:scale-95"
        >
          Continue →
        </button>
      )}

      {spinning && (
        <div className="text-gray-400 animate-pulse text-sm">The wheel is spinning...</div>
      )}
    </div>
  )
}
