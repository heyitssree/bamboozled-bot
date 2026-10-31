import { send } from '../app/connection'
import { PlayerChip } from '../components/game'
import { Banner, Button } from '../components/ui'
import type { Mode, RoomState } from '../net/protocol'
import { MODE_INFO } from '../net/protocol'
import { useStore } from '../state/store'

const DIFFICULTIES = [['', 'Mixed'], ['easy', 'Easy'], ['medium', 'Medium'], ['hard', 'Hard']] as const
const ROUNDS: Record<Mode, number[]> = { bamboozled: [3, 5, 7, 10], fff: [5, 10, 15, 20], survival: [] }

export function Lobby({ room }: { room: RoomState }) {
  const conn = useStore((s) => s.conn)
  const isHost = room.host === room.you
  const me = room.members.find((m) => m.user_id === room.you)
  const spectator = room.role === 'spectator'
  const players = room.members.filter((m) => !m.spectator)
  const watchers = room.members.filter((m) => m.spectator)
  const connected = players.filter((m) => m.connected).length
  const missing = Math.max(0, room.min_players - connected)

  return (
    <main id="main" className="page">
      <section aria-labelledby="who">
        <h2 id="who">Players <span className="muted">({players.length}/{room.max_players})</span></h2>
        <div className="members" role="list">
          {players.map((m) => (
            <div role="listitem" key={m.user_id}>
              <PlayerChip member={m} me={m.user_id === room.you}
                badges={{ host: m.host, ready: m.ready, disconnected: !m.connected }} />
            </div>
          ))}
        </div>
        {watchers.length > 0 && (
          <p className="muted" style={{ marginTop: 'var(--sp-2)' }}>
            Watching: {watchers.map((w) => w.name).join(', ')}
          </p>
        )}
      </section>

      {spectator && (
        <Banner tone="info" icon="👀">You joined after the game filled up or started, so you are watching. You will be dealt in next game.</Banner>
      )}
      {conn === 'reconnecting' && <Banner tone="warn">Reconnecting… your seat is kept for a little while.</Banner>}

      <section aria-labelledby="mode-h" className="col">
        <h2 id="mode-h">Pick a game</h2>
        <div className="modes">
          {(Object.keys(MODE_INFO) as Mode[]).map((m) => {
            const info = MODE_INFO[m]
            return (
              <button key={m} type="button" className="mode-card" aria-pressed={room.mode === m} disabled={!isHost}
                onClick={() => send({ t: 'SET_MODE', d: { mode: m } })} data-testid={`mode-${m}`}>
                <span className="mode-icon" aria-hidden="true">{info.icon}</span>
                <h3>{info.title}</h3>
                <span className="muted">{info.players}</span>
                <span>{info.blurb}</span>
                {room.mode === m && <strong>Selected</strong>}
              </button>
            )
          })}
        </div>
        {!isHost && <p className="muted">Only the host can change the game. <strong>{room.members.find((m) => m.host)?.name ?? 'The host'}</strong> is choosing.</p>}
      </section>

      <section aria-labelledby="cfg-h" className="col">
        <h2 id="cfg-h">Settings</h2>
        <div className="config">
          {ROUNDS[room.mode].length > 0 && (
            <div className="field">
              <label htmlFor="rounds">{room.mode === 'fff' ? 'Questions' : 'Rounds'}</label>
              <select id="rounds" className="select" disabled={!isHost} value={room.config.rounds ?? ''}
                onChange={(e) => send({ t: 'SET_CONFIG', d: { rounds: e.target.value ? Number(e.target.value) : null } })}>
                <option value="">Default</option>
                {ROUNDS[room.mode].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="difficulty">Difficulty</label>
            <select id="difficulty" className="select" disabled={!isHost} value={room.config.difficulty ?? ''}
              onChange={(e) => send({ t: 'SET_CONFIG', d: { difficulty: e.target.value || null } })}>
              {DIFFICULTIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="category">Category</label>
            <select id="category" className="select" disabled={!isHost} value={room.config.category ?? ''}
              onChange={(e) => send({ t: 'SET_CONFIG', d: { category: e.target.value || null } })}>
              {['', 'General Knowledge', 'Science', 'History', 'Geography', 'Arts & Literature'].map((c) => <option key={c} value={c}>{c || 'All categories'}</option>)}
            </select>
          </div>
        </div>
      </section>

      <section className="row" style={{ flexWrap: 'wrap' }}>
        {!spectator && me && (
          <Button tone={me.ready ? 'secondary' : 'primary'} onClick={() => send({ t: 'READY', d: { ready: !me.ready } })} aria-pressed={me.ready}>
            {me.ready ? '✔ Ready (tap to undo)' : 'Ready'}
          </Button>
        )}
        {isHost && (
          <Button big disabled={!room.can_start} onClick={() => send({ t: 'START' })}>Start the game</Button>
        )}
        {isHost && missing > 0 && <span className="muted" role="status">Waiting for {missing} more player{missing === 1 ? '' : 's'}.</span>}
        {!isHost && !spectator && <span className="muted" role="status">Waiting for the host to start.</span>}
      </section>
    </main>
  )
}

