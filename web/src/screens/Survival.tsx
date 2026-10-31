import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchMyStats } from '../app/api'
import { send } from '../app/connection'
import { PlayerChip } from '../components/game'
import type { AnswerState } from '../components/game'
import { Banner, Button } from '../components/ui'
import { useAnswerKeys, useMembers } from '../hooks'
import type { Member, RoomState, SurvivalView } from '../net/protocol'
import { useStore } from '../state/store'
import { QuestionCard } from './shared'

const REASON: Record<string, string> = {
  wrong: 'Wrong answer', timeout: 'Time ran out', quit: 'You gave up', error: 'A question could not be loaded',
}

export default function SurvivalScreen({ room }: { room: RoomState }) {
  const g = room.game as SurvivalView | null
  const { byId } = useMembers()
  const lastQuestion = useStore((s) => s.lastQuestion)
  const board = room.board ?? []
  const [prevBest, setPrevBest] = useState<number | null>(null)
  const fetched = useRef(false)

  // your best streak before this run, for the summary (read once, when the run starts)
  useEffect(() => {
    if (!g || fetched.current) return
    fetched.current = true
    fetchMyStats('survival').then((s) => setPrevBest(s.best_streak)).catch(() => setPrevBest(0))
  }, [g])

  const playing = !!g && !g.over
  useAnswerKeys(playing && !!g?.question, g?.question?.answers.length ?? 0, (i) => send({ t: 'ANSWER', d: { index: i } }))

  const states = useMemo<Partial<Record<number, AnswerState>>>(() => {
    if (!g?.reveal || !lastQuestion || g.question) return {}
    const out: Partial<Record<number, AnswerState>> = {}
    lastQuestion.answers.forEach((_, i) => { out[i] = i === g.reveal!.correct_index ? 'correct' : 'dim' })
    if (g.reveal.chosen !== null && g.reveal.chosen !== g.reveal.correct_index) out[g.reveal.chosen] = 'wrong'
    return out
  }, [g, lastQuestion])

  const memberFor = (id: number): Member => byId.get(id) ?? { user_id: id, name: 'A player', avatar_url: '', ready: false, connected: true, spectator: false, host: false }
  const standings = [...board].sort((a, b) => b.streak - a.streak || a.user_id - b.user_id)
  const newBest = !!g && g.over && prevBest !== null && g.streak > prevBest && g.streak > 0 && (g.reason === 'wrong' || g.reason === 'timeout')

  return (
    <main id="main" className="page">
      {g ? (
        <section className="card col" aria-label="Your run">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div>
              <p className="muted">Streak</p>
              <p className="streak" role="status" aria-live="polite" data-testid="streak">{g.streak}</p>
            </div>
            {prevBest !== null && <p className="muted">Your best: {prevBest}</p>}
          </div>
          <div className="streak-meter" aria-hidden="true"><div className="streak-fill" style={{ width: `${Math.min(100, (g.streak / 20) * 100)}%` }} /></div>
        </section>
      ) : (
        <Banner tone="info" icon="👀">You are watching. The board shows everyone's streak live.</Banner>
      )}

      {g && g.waiting_question && !g.over && <section className="card" aria-busy="true"><p role="status">Loading your next question…</p></section>}

      {g && (g.question || (g.reveal && lastQuestion)) && !g.over && (
        <QuestionCard question={(g.question ?? lastQuestion)!} deadlineMs={g.question ? g.deadline_ms : null} states={states}
          interactive={!!g.question} label="on your run" onPick={(i) => send({ t: 'ANSWER', d: { index: i } })}
          footer={<div className="row" style={{ justifyContent: 'space-between' }}>
            <span role="status">One wrong answer or timeout ends the run.</span>
            <Button tone="ghost" onClick={() => send({ t: 'FORFEIT' })}>Give up</Button>
          </div>} />
      )}

      {g && g.over && (
        <section className="card col center" aria-label="Run summary">
          <h2>{newBest ? '🏆 New personal best!' : 'Run over'}</h2>
          <p className="streak">{g.streak}</p>
          <p role="status">{REASON[g.reason ?? 'wrong']}.{g.reveal && lastQuestion && g.reason === 'wrong' ? ` The answer was ${lastQuestion.answers[g.reveal.correct_index]}.` : ''}</p>
          {prevBest !== null && !newBest && <p className="muted">Your best is {Math.max(prevBest, 0)}.</p>}
          {g.reason === 'quit' && <p className="muted">Giving up never counts as a personal best.</p>}
          <p className="muted">Waiting for the others to finish…</p>
        </section>
      )}

      <section aria-labelledby="board-h" className="col">
        <h2 id="board-h">Live board</h2>
        <ol className="members" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {standings.map((r) => (
            <li key={r.user_id}>
              <PlayerChip member={memberFor(r.user_id)} me={r.user_id === room.you} score={r.streak} compact active={!r.over} />
              <span className="sr-only">{r.over ? 'run over' : 'still alive'}</span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  )
}
