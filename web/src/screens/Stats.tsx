import { useEffect, useState } from 'react'
import type { BoardEntry, MyStats } from '../app/api'
import { fetchBoard, fetchMyStats } from '../app/api'
import { Skeleton, Tabs } from '../components/ui'
import type { Mode } from '../net/protocol'
import { MODE_INFO } from '../net/protocol'
import { useStore } from '../state/store'

type Tab = 'mine' | Mode
type Load<T> = { state: 'loading' } | { state: 'error' } | { state: 'ready'; data: T }

function useLoad<T>(load: () => Promise<T>, deps: unknown[]): Load<T> {
  const [res, setRes] = useState<Load<T>>({ state: 'loading' })
  useEffect(() => {
    let live = true
    setRes({ state: 'loading' })
    load().then((data) => live && setRes({ state: 'ready', data })).catch(() => live && setRes({ state: 'error' }))
    return () => { live = false }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return res
}

function MyStats() {
  const modes: Mode[] = ['bamboozled', 'fff', 'survival']
  const res = useLoad(() => Promise.all(modes.map((m) => fetchMyStats(m))), [])
  if (res.state === 'loading') return <Skeleton label="Loading your stats" />
  if (res.state === 'error') return <p role="alert">We could not load your stats. Please try again in a moment.</p>
  if (res.data.every((s: MyStats) => s.games === 0)) return <p>You have not finished a game yet. Your stats will show up here.</p>
  return (
    <table className="table">
      <caption className="sr-only">Your stats by game</caption>
      <thead><tr><th scope="col">Game</th><th scope="col" className="num">Played</th><th scope="col" className="num">Won</th><th scope="col" className="num">Best</th></tr></thead>
      <tbody>
        {modes.map((m, i) => (
          <tr key={m}>
            <th scope="row">{MODE_INFO[m].title}</th>
            <td className="num">{res.data[i].games}</td><td className="num">{m === 'survival' ? '–' : res.data[i].wins}</td>
            <td className="num">{(m === 'survival' ? res.data[i].best_streak : res.data[i].best_score).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Board({ mode }: { mode: Mode }) {
  const [scope, setScope] = useState<'server' | 'global'>('server')
  const me = useStore((s) => s.me)
  const res = useLoad(() => fetchBoard(mode, scope), [mode, scope])
  const headers: Record<Mode, string[]> = { bamboozled: ['Wins', 'Games', 'Points'], fff: ['Correct', 'Avg ms', ''], survival: ['Streak', 'Level', ''] }
  const cells = (r: BoardEntry): (string | number)[] =>
    mode === 'bamboozled' ? [r.wins as number, r.games as number, (r.total_score as number).toLocaleString()]
      : mode === 'fff' ? [`${r.correct_answers}/${r.total_questions}`, r.avg_response_ms ? String(r.avg_response_ms) : '–', '']
        : [r.streak as number, String(r.difficulty ?? ''), '']
  return (
    <div className="col">
      <div className="row" role="group" aria-label="Where from">
        {(['server', 'global'] as const).map((s) => (
          <button key={s} type="button" className={`btn ${scope === s ? 'btn-primary' : 'btn-secondary'}`} aria-pressed={scope === s} onClick={() => setScope(s)}>
            {s === 'server' ? 'This server' : 'Everywhere'}
          </button>
        ))}
      </div>
      {res.state === 'loading' && <Skeleton label="Loading the leaderboard" />}
      {res.state === 'error' && <p role="alert">We could not load the leaderboard. Please try again in a moment.</p>}
      {res.state === 'ready' && res.data.length === 0 && <p>No games here yet. Be the first on the board!</p>}
      {res.state === 'ready' && res.data.length > 0 && (
        <table className="table">
          <caption className="sr-only">{MODE_INFO[mode].title} leaderboard, {scope === 'server' ? 'this server' : 'everywhere'}</caption>
          <thead><tr><th scope="col">#</th><th scope="col">Player</th>{headers[mode].filter(Boolean).map((h) => <th key={h} scope="col" className="num">{h}</th>)}</tr></thead>
          <tbody>
            {res.data.map((r, i) => (
              <tr key={`${r.user_id}-${i}`}>
                <td>{i + 1}</td><td>{r.name}{r.user_id === me?.id ? ' (you)' : ''}</td>
                {cells(r).filter((_c, j) => headers[mode][j]).map((c, j) => <td key={j} className="num">{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function Stats() {
  const [tab, setTab] = useState<Tab>('mine')
  const tabs = [{ id: 'mine', label: 'My stats' }, ...(Object.keys(MODE_INFO) as Mode[]).map((m) => ({ id: m, label: MODE_INFO[m].title }))]
  return <Tabs tabs={tabs} active={tab} onChange={(id) => setTab(id as Tab)} label="Stats and leaderboards">{tab === 'mine' ? <MyStats /> : <Board mode={tab} />}</Tabs>
}
