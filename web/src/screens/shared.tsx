import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { audio } from '../audio/manager'
import { describeEvent } from '../app/events'
import { AnswerButton, TimerRing } from '../components/game'
import type { AnswerState } from '../components/game'
import { useClockAnnouncements, useMembers, useWindowCountdown } from '../hooks'
import type { Question } from '../net/protocol'
import { useStore } from '../state/store'

/** A question with its four answers. Used by all three modes. */
export function QuestionCard({ question, deadlineMs, states, interactive, onPick, footer, label }: {
  question: Question
  deadlineMs: number | null
  states?: Partial<Record<number, AnswerState>>
  interactive: boolean
  onPick?: (index: number) => void
  footer?: ReactNode
  label: string
}) {
  const clock = useWindowCountdown(deadlineMs)
  useClockAnnouncements(clock?.seconds, interactive, label, () => audio.play('tick'))
  return (
    <section className="card question" aria-label="Question">
      <div className="question-head">
        <div className="grow">
          <p className="question-meta">{[question.category, question.difficulty].filter(Boolean).join(' · ')}</p>
          <h2 className="question-text">{question.text}</h2>
        </div>
        {clock && <TimerRing seconds={clock.seconds} fraction={clock.fraction} />}
      </div>
      <div className="answers" role="group" aria-label="Answers">
        {question.answers.map((text, i) => (
          <AnswerButton key={i} index={i} text={text} state={states?.[i] ?? 'idle'} disabled={!interactive || (states?.[i] ?? 'idle') !== 'idle'}
            onClick={() => onPick?.(i)} />
        ))}
      </div>
      {footer}
    </section>
  )
}

/** The last few things that happened, in words. */
export function EventFeed({ kinds }: { kinds?: string[] }) {
  const events = useStore((s) => s.events)
  const { name } = useMembers()
  const announce = useStore((s) => s.announce)
  const lines = events
    .filter((e) => !kinds || kinds.includes(e.kind))
    .map((e) => ({ id: e.id, text: describeEvent(e.kind, e.payload, name) }))
    .filter((l): l is { id: number; text: string } => !!l.text)
    .slice(-4)
  const newest = lines[lines.length - 1]
  useEffect(() => { if (newest) announce(newest.text) }, [newest?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!lines.length) return null
  return (
    <ol className="muted feed" aria-label="What just happened" style={{ margin: 0, paddingLeft: 'var(--sp-5)' }}>
      {lines.map((l) => <li key={l.id}>{l.text}</li>)}
    </ol>
  )
}

/** Keeps a value shown for a while after the event that produced it. */
export function useTransient<T>(value: T | null, ms: number): T | null {
  const [shown, setShown] = useState<T | null>(null)
  useEffect(() => {
    if (value === null) return
    setShown(value)
    const t = setTimeout(() => setShown(null), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return shown
}
