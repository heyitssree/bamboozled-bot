import { send } from '../app/connection'
import { Podium } from '../components/game'
import { Banner, Button } from '../components/ui'
import { useMembers } from '../hooks'
import type { RoomState } from '../net/protocol'

export function Results({ room }: { room: RoomState }) {
  const { name } = useMembers()
  const rows = room.results ?? []
  const isHost = room.host === room.you
  const me = rows.find((r) => r.user_id === room.you)
  const tied = rows.length > 1 && rows[0].score === rows[1].score
  const unit = room.mode === 'survival' ? 'streak' : 'points'
  return (
    <main id="main" className="page">
      <h1 className="center">{rows.length === 0 ? 'Game over' : room.mode === 'survival' ? 'Runs finished' : `${name(rows[0].user_id)} wins!`}</h1>
      {rows.length === 0 && <Banner tone="warn">Everyone left before the end, so there is no result to show.</Banner>}
      {rows.length > 0 && <Podium rows={rows} name={name} />}
      {tied && room.mode !== 'survival' && <Banner tone="info" icon="⚖️">Tied on {unit}. The tiebreak decided the order.</Banner>}
      {me && <p className="center" role="status">You finished <strong>#{me.rank}</strong> with {me.score.toLocaleString()} {unit}.</p>}
      {rows.length > 0 && (
        <table className="table">
          <caption className="sr-only">Final standings</caption>
          <thead><tr><th scope="col">#</th><th scope="col">Player</th><th scope="col" className="num">{room.mode === 'survival' ? 'Streak' : 'Score'}</th><th scope="col" className="num">Correct</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.user_id}>
                <td>{r.rank}</td>
                <td>{name(r.user_id)}{r.user_id === room.you ? ' (you)' : ''}{r.details.left ? ` (${String(r.details.left) === 'afk' ? 'went AFK' : 'left early'})` : ''}{r.details.reason === 'quit' ? ' (gave up)' : ''}</td>
                <td className="num">{r.score.toLocaleString()}</td>
                <td className="num">{r.correct}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted center" role="status">Your result is saved to the leaderboards.</p>
      <div className="row" style={{ justifyContent: 'center', flexWrap: 'wrap' }}>
        {isHost
          ? <Button big onClick={() => send({ t: 'REMATCH' })}>Play again</Button>
          : <p className="muted" role="status">Waiting for the host to start another game.</p>}
      </div>
    </main>
  )
}
