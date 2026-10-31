import { useMemo } from 'react'
import { send } from '../app/connection'
import { PlayerChip, Scoreboard } from '../components/game'
import type { AnswerState } from '../components/game'
import { Banner } from '../components/ui'
import { useAnswerKeys, useMembers } from '../hooks'
import type { FffView, Member, RoomState } from '../net/protocol'
import { useStore } from '../state/store'
import { EventFeed, QuestionCard } from './shared'

const LETTER = 'ABCD'

export default function FffScreen({ room }: { room: RoomState }) {
  const g = room.game as FffView
  const { byId, name } = useMembers()
  const lastQuestion = useStore((s) => s.lastQuestion)
  const me = room.you
  const spectator = room.role === 'spectator'
  const mine = g.players.find((p) => p.user_id === me)
  const open = !!g.question
  const canAnswer = open && !spectator && !!mine && g.your_answer === null
  useAnswerKeys(canAnswer, g.question?.answers.length ?? 0, (i) => send({ t: 'ANSWER', d: { index: i } }))

  const states = useMemo<Partial<Record<number, AnswerState>>>(() => {
    if (g.question) {
      const out: Partial<Record<number, AnswerState>> = {}
      if (g.your_answer !== null) g.question.answers.forEach((_, i) => { out[i] = i === g.your_answer ? 'locked' : 'dim' })
      return out
    }
    if (g.reveal && lastQuestion) {
      const out: Partial<Record<number, AnswerState>> = {}
      lastQuestion.answers.forEach((_, i) => { out[i] = i === g.reveal!.correct_index ? 'correct' : 'dim' })
      const mineAnswer = g.reveal.answers[String(me)]
      if (mineAnswer !== undefined && mineAnswer !== g.reveal.correct_index) out[mineAnswer] = 'wrong'
      return out
    }
    return {}
  }, [g.question, g.your_answer, g.reveal, lastQuestion, me])

  const chipFor = (id: number): Member => byId.get(id) ?? { user_id: id, name: 'A player', avatar_url: '', ready: false, connected: true, spectator: false, host: false }
  const reveal = g.reveal
  const shown = g.question ?? (reveal ? lastQuestion : null)

  return (
    <main id="main" className="page">
      <p className="round-banner" role="status">Question {Math.min(g.q_index + 1, g.total_q)} of {g.total_q}</p>
      <Scoreboard label="Players and who has locked in">
        {g.players.map((p) => (
          <PlayerChip key={p.user_id} member={chipFor(p.user_id)} score={p.score} me={p.user_id === me} compact
            badges={{ locked: open && p.locked, disconnected: !chipFor(p.user_id).connected }} />
        ))}
      </Scoreboard>

      {g.waiting_question && <section className="card" aria-busy="true"><p role="status">Next question coming up…</p></section>}

      {shown && (
        <QuestionCard question={shown} deadlineMs={g.question ? g.deadline_ms : null} states={states} interactive={canAnswer} label="to answer"
          onPick={(i) => send({ t: 'ANSWER', d: { index: i } })}
          footer={g.question ? (
            <p role="status">
              {spectator ? 'You are watching this round.'
                : g.your_answer !== null ? `Locked in ${LETTER[g.your_answer]}. Waiting for the others… (${g.players.filter((p) => p.locked).length}/${g.players.length} in)`
                : mine ? 'Pick fast: speed decides the points (keys 1 to 4).' : 'You are out of this game.'}
            </p>
          ) : undefined} />
      )}

      {reveal && !g.question && (
        <section className="card col" aria-label="Round result">
          <h2>Round result</h2>
          {reveal.order.length === 0 && <p role="status">Nobody answered. Tough question!</p>}
          {reveal.order.length > 0 && reveal.winners.length === 0 && <p role="status">Nobody got it right.</p>}
          {reveal.winners.length > 0 && (
            <ol aria-label="Correct answers, fastest first" style={{ margin: 0, paddingLeft: 'var(--sp-5)' }}>
              {reveal.winners.map((id, i) => (
                <li key={id}><strong>{id === me ? 'You' : name(id)}</strong> <span aria-hidden="true">{i === 0 ? '🥇' : '✔'}</span> +{i === 0 ? 100 : 75} points</li>
              ))}
            </ol>
          )}
          {!spectator && mine && !(String(me) in reveal.answers) && (
            <Banner tone="warn">You did not answer in time. Two missed questions in a row and you are removed.</Banner>
          )}
          {reveal.winners.length > 1 && <p className="muted">Ties on speed go to whoever locked in first.</p>}
        </section>
      )}
      <EventFeed kinds={['player_left']} />
    </main>
  )
}
