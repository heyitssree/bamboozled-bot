import { useEffect, useMemo, useState } from 'react'
import { send } from '../app/connection'
import { Avatar, FlipCard, PlayerChip, Scoreboard, Wheel } from '../components/game'
import type { AnswerState } from '../components/game'
import { Banner, Button } from '../components/ui'
import { useAnswerKeys, useLatestEvent, useMembers, useReducedMotion, useWindowCountdown } from '../hooks'
import type { BzView, Member, RoomState } from '../net/protocol'
import { LAWS } from '../net/protocol'
import { EventFeed, QuestionCard, useTransient } from './shared'
import { useStore } from '../state/store'

const CARD_ICON: Record<string, string> = {
  'Lucky Llama': '🦙', Switcheroo: '🔀', 'Double Down': '⬇️', 'Spin the Wheel': '🎡', 'Golden Pass': '🎫', Bamboozle: '🃏',
  'Wango Classic': '🎡', 'The Silence': '🤫', 'Reverse Uno': '🔄', 'The Sombrero': '🪅', 'Double Wango': '🃏', 'Mystic Mist': '🌫️',
}

function Countdown({ deadline }: { deadline: number | null }) {
  const c = useWindowCountdown(deadline)
  return c ? <span className="muted" role="timer" aria-label={`${c.seconds} seconds left`}>{c.seconds}s left</span> : null
}

export default function BamboozledScreen({ room }: { room: RoomState }) {
  const g = room.game as BzView
  const { byId, name } = useMembers()
  const reduced = useReducedMotion()
  const lastQuestion = useStore((s) => s.lastQuestion)
  const me = room.you
  const pending = g.pending
  const myDecision = pending?.actor === me
  const actorName = pending ? name(pending.actor) : name(g.turn_player)
  const [picked, setPicked] = useState<number | null>(null)

  useEffect(() => { setPicked(null) }, [g.question?.text, g.reveal])

  const wheelEvent = useLatestEvent(['wheel_result'])
  const [wheel, setWheel] = useState<{ result: string | null; id: number }>({ result: null, id: 0 })
  useEffect(() => { if (wheelEvent) setWheel({ result: String(wheelEvent.payload.segment), id: wheelEvent.id }) }, [wheelEvent])
  const cardEvent = useLatestEvent(['card_drawn'])
  const card = useTransient(cardEvent ? { name: String(cardEvent.payload.card), deck: String(cardEvent.payload.deck), id: cardEvent.id } : null, 3200)
  const [flipped, setFlipped] = useState(false)
  useEffect(() => { setFlipped(false); if (card) { const t = setTimeout(() => setFlipped(true), reduced ? 0 : 60); return () => clearTimeout(t) } }, [card?.id, reduced]) // eslint-disable-line react-hooks/exhaustive-deps

  const answering = pending?.kind === 'answer' && !!g.question
  const askKeys = answering && myDecision && picked === null
  useAnswerKeys(askKeys, g.question?.answers.length ?? 0, (i) => { setPicked(i); send({ t: 'ANSWER', d: { index: i } }) })

  const states = useMemo<Partial<Record<number, AnswerState>>>(() => {
    const out: Partial<Record<number, AnswerState>> = {}
    if (picked !== null && answering) out[picked] = 'selected'
    return out
  }, [picked, answering])

  const revealStates = useMemo<Partial<Record<number, AnswerState>>>(() => {
    if (!g.reveal || !lastQuestion) return {}
    const out: Partial<Record<number, AnswerState>> = {}
    lastQuestion.answers.forEach((_, i) => { out[i] = i === g.reveal!.correct_index ? 'correct' : 'dim' })
    if (g.reveal.chosen !== null && g.reveal.chosen !== g.reveal.correct_index) out[g.reveal.chosen] = 'wrong'
    return out
  }, [g.reveal, lastQuestion])

  const chip = (p: BzView['players'][number]) => {
    const m: Member = byId.get(p.user_id) ?? { user_id: p.user_id, name: 'A player', avatar_url: '', ready: false, connected: true, spectator: false, host: false }
    return (
      <PlayerChip key={p.user_id} member={m} me={p.user_id === me} score={p.score} hideScore={g.mist} compact
        active={(pending?.actor ?? g.turn_player) === p.user_id}
        badges={{ silenced: p.silenced, goldenPass: p.golden_pass, sombrero: p.sombrero, disconnected: !m.connected }} />
    )
  }

  const who = (id: number) => (id === me ? 'You' : name(id))
  return (
    <main id="main" className={`page${g.mist ? ' mist' : ''}`}>
      <p className="round-banner" role="status">
        {g.stage === 'endgame' ? 'Sudden Bamboozle' : `Round ${Math.min(g.round, g.total_rounds)} of ${g.total_rounds}`}
      </p>
      <div className="scoreboard-wrap">
        <Scoreboard>{g.players.map(chip)}</Scoreboard>
        {g.mist && <Banner tone="info" icon="🌫️">The Mystic Mist hides every score for now.</Banner>}
      </div>
      {g.law && <div className="law-banner"><span aria-hidden="true">⚖️</span><span><strong>{g.law.name}</strong>{g.law.permanent ? ' (permanent)' : ''} is in force.</span></div>}

      <div className="stage">
        {g.waiting_question && <section className="card" aria-busy="true"><p role="status">Fetching a question for {who(g.turn_player)}…</p></section>}

        {answering && g.question && (
          <QuestionCard question={g.question} deadlineMs={pending!.deadline_ms} interactive={myDecision && picked === null} states={states}
            label={`for ${who(pending!.actor)}`}
            onPick={(i) => { setPicked(i); send({ t: 'ANSWER', d: { index: i } }) }}
            footer={
              <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
                <span role="status">{myDecision ? (picked === null ? 'Your turn: pick an answer (keys 1 to 4).' : 'Answer sent…') : `${actorName} is answering…`}</span>
                {myDecision && g.stage === 'turns' && <Button tone="ghost" onClick={() => send({ t: 'FORFEIT' })}>Skip my turn</Button>}
              </div>
            } />
        )}

        {!answering && g.reveal && lastQuestion && (
          <QuestionCard question={lastQuestion} deadlineMs={null} interactive={false} states={revealStates} label=""
            footer={<p role="status">{g.reveal.timed_out || g.reveal.forfeit
              ? `${who(g.reveal.player)} ${g.reveal.forfeit ? 'skipped' : 'ran out of time'}. The answer was ${lastQuestion.answers[g.reveal.correct_index]}.`
              : g.reveal.chosen === g.reveal.correct_index ? `${who(g.reveal.player)} got it right!` : `${who(g.reveal.player)} missed it. The answer was ${lastQuestion.answers[g.reveal.correct_index]}.`}</p>} />
        )}

        {pending?.kind === 'draw' && (
          <section className="card col center" aria-label="Draw a card">
            <h2>{pending.which === 'wango' ? 'Wicked Wango card' : 'Chance card'}</h2>
            {card ? (
              <FlipCard flipped={flipped} label="Card" front={<span aria-hidden="true">🂠</span>}
                back={<><span className="card-icon" aria-hidden="true">{CARD_ICON[card.name] ?? '🃏'}</span><span className="card-title">{card.name}</span></>} />
            ) : null}
            {myDecision
              ? <Button big onClick={() => send({ t: 'DRAW_CARD' })}>Draw the card</Button>
              : <p role="status">{actorName} is about to draw…</p>}
            <Countdown deadline={pending.deadline_ms} />
          </section>
        )}

        {(pending?.kind === 'spin' || (!pending && wheel.result)) && (
          <section className="card col center" aria-label="Wheel of Mayhem">
            <h2>Wheel of Mayhem</h2>
            <Wheel result={wheel.result} spinId={wheel.id} reduced={reduced} />
            {pending?.kind === 'spin' && (myDecision
              ? <Button big onClick={() => send({ t: 'SPIN' })}>Spin the wheel!</Button>
              : <p role="status">{actorName} is about to spin…</p>)}
            {wheel.result && <p role="status"><strong>{wheel.result}</strong></p>}
            {pending?.kind === 'spin' && <Countdown deadline={pending.deadline_ms} />}
          </section>
        )}

        {pending?.kind !== 'draw' && pending?.kind !== 'spin' && card && (
          <section className="card center" aria-label="Card drawn">
            <FlipCard flipped={flipped} label="Card" front={<span aria-hidden="true">🂠</span>}
              back={<><span className="card-icon" aria-hidden="true">{CARD_ICON[card.name] ?? '🃏'}</span><span className="card-title">{card.name}</span></>} />
          </section>
        )}

        {pending?.kind === 'pick_target' && (
          <section className="card col" aria-label="Choose a player">
            <h2>{pending.purpose === 'gift' ? 'Whom do you rob? (100 points)' : 'Swap scores with…'}</h2>
            {myDecision ? (
              <>
                <div className="picker">
                  {(pending.options ?? []).map((id) => (
                    <button key={id} type="button" onClick={() => send({ t: 'PICK_TARGET', d: { user_id: id } })}>
                      <Avatar member={byId.get(id) ?? { user_id: id, name: '?', avatar_url: '' }} size={48} />
                      <span>{name(id)}</span>
                      {!g.mist && <span className="muted">{g.players.find((p) => p.user_id === id)?.score?.toLocaleString()}</span>}
                    </button>
                  ))}
                </div>
                {pending.can_skip && <Button tone="ghost" onClick={() => send({ t: 'PICK_TARGET', d: { user_id: null } })}>No thanks, keep my score</Button>}
              </>
            ) : <p role="status">{actorName} is choosing…</p>}
            <Countdown deadline={pending.deadline_ms} />
          </section>
        )}

        {pending?.kind === 'pick_rule' && (
          <section className="card col" aria-label="Choose a law">
            <h2>Write the law of the land</h2>
            {myDecision ? (
              <div className="laws">
                {LAWS.map((l) => (
                  <button key={l.id} type="button" className="law" onClick={() => send({ t: 'PICK_RULE', d: { rule_id: l.id } })}>
                    <strong>{l.name}</strong><span className="muted">{l.description}</span>
                  </button>
                ))}
              </div>
            ) : <p role="status">{actorName} is choosing a law…</p>}
            <Countdown deadline={pending.deadline_ms} />
          </section>
        )}

        {pending?.kind === 'monkey' && (
          <section className="card col center" aria-label="The Golden Monkey">
            <h2>🐒 The Golden Monkey waits</h2>
            <p>One side is fortune, the other misfortune. The monkey has already decided.</p>
            {myDecision ? (
              <div className="monkey">
                <Button tone="secondary" onClick={() => send({ t: 'MONKEY', d: { choice: 'belly' } })}><span aria-hidden="true">🫃</span>Belly</Button>
                <Button tone="secondary" onClick={() => send({ t: 'MONKEY', d: { choice: 'tail' } })}><span aria-hidden="true">🐒</span>Tail</Button>
              </div>
            ) : <p role="status">{actorName} faces the monkey…</p>}
            <Countdown deadline={pending.deadline_ms} />
          </section>
        )}

        <EventFeed />
        {room.role === 'spectator' && <Banner tone="info" icon="👀">You are watching this game.</Banner>}
      </div>
    </main>
  )
}
