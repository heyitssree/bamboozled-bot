import { useCallback, useEffect, useRef, useState } from 'react'
import { audio } from '../audio/AudioManager'
import { useGameStore } from '../store/gameStore'

const LETTER_LABELS = ['A', 'B', 'C', 'D']

const ANSWER_BUTTON_BASE =
  'relative w-full text-left px-5 py-4 rounded-xl font-semibold text-base transition-all border-2 active:scale-95 disabled:cursor-not-allowed'

export function QuestionCard() {
  const currentQuestion = useGameStore((s) => s.currentQuestion)
  const phase = useGameStore((s) => s.phase)
  const currentPlayerId = useGameStore((s) => s.currentPlayerId)
  const myPlayerId = useGameStore((s) => s.myPlayerId)
  const mistActive = useGameStore((s) => s.mistActive)
  const players = useGameStore((s) => s.players)
  const timePerQuestion = useGameStore((s) => s.timePerQuestion)
  const sendMessage = useGameStore((s) => s.sendMessage)
  const wheelResult = useGameStore((s) => s.wheelResult)

  const [selected, setSelected] = useState<number | null>(null)
  const [timeLeft, setTimeLeft] = useState(timePerQuestion)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isReveal = phase === 'reveal'
  const isMyTurn = myPlayerId === currentPlayerId
  const myPlayer = players[myPlayerId]
  const isBlind = myPlayer?.blind_answer_active ?? false

  // Reset on new question
  useEffect(() => {
    setSelected(null)
    setTimeLeft(timePerQuestion)
  }, [currentQuestion?.text, timePerQuestion])

  // Countdown timer
  useEffect(() => {
    if (isReveal || selected !== null) {
      if (timerRef.current) clearInterval(timerRef.current)
      return
    }
    timerRef.current = setInterval(() => {
      setTimeLeft((t) => {
        if (t <= 1) {
          clearInterval(timerRef.current!)
          audio.play('tick').catch(() => undefined)
          return 0
        }
        if (t <= 6) audio.play('tick').catch(() => undefined)
        return t - 1
      })
    }, 1000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [isReveal, selected, currentQuestion?.text])

  const handleAnswer = useCallback(
    (idx: number) => {
      if (!isMyTurn || selected !== null || isReveal) return
      setSelected(idx)
      sendMessage({ type: 'ANSWER_SUBMITTED', answer_index: idx })
    },
    [isMyTurn, selected, isReveal, sendMessage],
  )

  if (!currentQuestion) return null

  const correctIndex = isReveal ? (currentQuestion.correct_index ?? -1) : -1
  const timerPercent = (timeLeft / timePerQuestion) * 100
  const timerColor =
    timeLeft > 10 ? 'bg-green-500' : timeLeft > 5 ? 'bg-yellow-500' : 'bg-red-500'

  const goldenMonkey = wheelResult?.outcome === 'GOLDEN_MONKEY'

  return (
    <div className="flex flex-col min-h-screen bg-gray-900 p-4">
      {/* Header bar */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-gray-400 text-sm">
          {currentQuestion.category} · {currentQuestion.difficulty}
        </div>
        {goldenMonkey && (
          <div className="text-yellow-400 text-sm font-bold animate-pulse">🐒 2× Points!</div>
        )}
        {mistActive && (
          <div className="text-blue-400 text-sm font-bold animate-pulse">🌫️ Mystic Mist</div>
        )}
      </div>

      {/* Timer bar */}
      <div className="w-full h-2 bg-gray-700 rounded-full mb-6 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-1000 ${timerColor}`}
          style={{ width: `${timerPercent}%` }}
        />
      </div>

      {/* Question */}
      <div className="flex-1 flex flex-col justify-center">
        <div className="bg-gray-800 rounded-2xl p-6 mb-6 text-center">
          <p className="text-white text-xl font-semibold leading-relaxed">
            {currentQuestion.text}
          </p>
          {!isMyTurn && currentPlayerId && players[currentPlayerId] && (
            <p className="text-gray-500 text-sm mt-3">
              Waiting for {players[currentPlayerId].username}...
            </p>
          )}
        </div>

        {/* Answer buttons */}
        <div className="grid grid-cols-2 gap-3">
          {currentQuestion.shuffled_answers.map((answer, idx) => {
            let style = 'bg-gray-700 border-gray-600 text-white hover:bg-gray-600 hover:border-gray-500'

            if (isReveal) {
              if (idx === correctIndex) {
                style = 'bg-green-700 border-green-500 text-white'
              } else if (idx === selected) {
                style = 'bg-red-700 border-red-500 text-white'
              } else {
                style = 'bg-gray-700 border-gray-700 text-gray-500 opacity-50'
              }
            } else if (selected === idx) {
              style = 'bg-purple-700 border-purple-500 text-white'
            } else if (selected !== null) {
              style = 'bg-gray-700 border-gray-700 text-gray-500 opacity-50'
            }

            const blurred = isBlind && !isReveal && selected === null

            return (
              <button
                key={idx}
                onClick={() => handleAnswer(idx)}
                disabled={!isMyTurn || selected !== null || isReveal}
                className={`${ANSWER_BUTTON_BASE} ${style}`}
              >
                <span className="text-gray-400 font-bold mr-2 text-sm">{LETTER_LABELS[idx]}</span>
                <span className={blurred ? 'blur-sm select-none' : ''}>{answer}</span>
                {isReveal && idx === correctIndex && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2">✓</span>
                )}
                {isReveal && idx === selected && idx !== correctIndex && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2">✗</span>
                )}
              </button>
            )
          })}
        </div>

        {isBlind && !isReveal && (
          <p className="text-center text-yellow-400 text-sm mt-3">
            🙈 Blind Answer active — pick without seeing the options!
          </p>
        )}
      </div>
    </div>
  )
}
