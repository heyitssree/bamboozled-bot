import { useEffect, useState } from 'react'
import { useGameStore } from '../store/gameStore'
import type { CardType } from '../types'

const CARD_THEMES: Record<CardType, { bg: string; border: string; icon: string }> = {
  POINT_THIEF: { bg: 'bg-red-900', border: 'border-red-500', icon: '💰' },
  FREEZE: { bg: 'bg-blue-900', border: 'border-blue-500', icon: '❄️' },
  DOUBLE_DOWN: { bg: 'bg-orange-900', border: 'border-orange-500', icon: '⬇️' },
  BLIND_ANSWER: { bg: 'bg-purple-900', border: 'border-purple-500', icon: '🙈' },
  REVERSE: { bg: 'bg-green-900', border: 'border-green-500', icon: '🔄' },
}

export function BamboozleCard() {
  const activeCard = useGameStore((s) => s.activeCard)
  const sendMessage = useGameStore((s) => s.sendMessage)
  const [flipped, setFlipped] = useState(false)

  useEffect(() => {
    if (activeCard) {
      setFlipped(false)
      const t = setTimeout(() => setFlipped(true), 600)
      return () => clearTimeout(t)
    }
  }, [activeCard?.card_type])

  if (!activeCard) return null

  const theme = CARD_THEMES[activeCard.card_type]

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-900 p-6">
      <h2 className="text-white text-2xl font-bold mb-8">🃏 Bamboozle Card!</h2>

      {/* Flip container */}
      <div
        className="relative w-64 h-80 mb-8"
        style={{ perspective: '1000px' }}
      >
        <div
          className="w-full h-full transition-all duration-700"
          style={{
            transformStyle: 'preserve-3d',
            transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
          }}
        >
          {/* Card back */}
          <div
            className="absolute inset-0 rounded-2xl border-2 border-gray-600 bg-gray-800 flex items-center justify-center"
            style={{ backfaceVisibility: 'hidden' }}
          >
            <div className="text-6xl">🃏</div>
          </div>

          {/* Card front */}
          <div
            className={`absolute inset-0 rounded-2xl border-2 ${theme.border} ${theme.bg} flex flex-col items-center justify-center p-6 gap-4`}
            style={{
              backfaceVisibility: 'hidden',
              transform: 'rotateY(180deg)',
            }}
          >
            <div className="text-6xl">{theme.icon}</div>
            <div className="text-white text-2xl font-extrabold text-center">
              {activeCard.label}
            </div>
            <div className="text-gray-300 text-sm text-center leading-relaxed">
              {activeCard.description}
            </div>
          </div>
        </div>
      </div>

      {flipped && (
        <button
          onClick={() => sendMessage({ type: 'CARD_ACK' })}
          className="px-8 py-3 bg-purple-600 hover:bg-purple-500 text-white font-bold rounded-xl transition-all active:scale-95 animate-fade-in"
        >
          Got it →
        </button>
      )}
    </div>
  )
}
