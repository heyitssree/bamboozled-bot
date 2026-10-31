import type { ReactNode } from 'react'
import { useState } from 'react'
import type { Member, ResultRow } from '../net/protocol'
import { WHEEL_SEGMENTS } from '../net/protocol'

// ───────────────────────────── Avatar, PlayerChip ─────────────────────────────

const HUES = [255, 20, 150, 330, 200, 45]

export function Avatar({ member, size = 40 }: { member: Pick<Member, 'user_id' | 'name' | 'avatar_url'>; size?: number }) {
  const [failed, setFailed] = useState(false)
  const hue = HUES[member.user_id % HUES.length]
  const style = { width: size, height: size, fontSize: size * 0.42 }
  // decorative: the name is always written next to it, so screen readers skip the picture
  if (failed || !member.avatar_url) {
    return <span className="avatar avatar-fallback" style={{ ...style, background: `hsl(${hue} 45% 28%)` }} aria-hidden="true">{member.name.slice(0, 1).toUpperCase()}</span>
  }
  return (
    <img className="avatar" src={member.avatar_url} alt="" width={size} height={size} loading="lazy"
      referrerPolicy="no-referrer" onError={() => setFailed(true)} style={style} />
  )
}

export interface ChipBadges { silenced?: boolean; goldenPass?: boolean; sombrero?: boolean; host?: boolean; locked?: boolean; disconnected?: boolean; ready?: boolean }

export function PlayerChip({ member, score, active, badges = {}, me, hideScore, compact }: {
  member: Member; score?: number | null; active?: boolean; badges?: ChipBadges; me?: boolean; hideScore?: boolean; compact?: boolean
}) {
  const parts: [string, string][] = []
  if (badges.host) parts.push(['👑', 'host'])
  if (badges.silenced) parts.push(['🤫', 'silenced'])
  if (badges.goldenPass) parts.push(['🎫', 'has a golden pass'])
  if (badges.sombrero) parts.push(['🪅', 'wearing the sombrero'])
  if (badges.locked) parts.push(['🔒', 'locked in'])
  if (badges.ready) parts.push(['✔️', 'ready'])
  if (badges.disconnected) parts.push(['📡', 'reconnecting'])
  return (
    <div className={`chip${active ? ' chip-active' : ''}${me ? ' chip-me' : ''}${compact ? ' chip-compact' : ''}${badges.locked ? ' chip-locked' : ''}`}
      aria-current={active ? 'true' : undefined}>
      <Avatar member={member} size={compact ? 32 : 40} />
      <div className="chip-body">
        <span className="chip-name">{member.name}</span>
        <span className="chip-meta">
          {me && <span className="chip-you">You</span>}
          {active && <span className="chip-turn">Turn</span>}
          {parts.map(([icon, label]) => <span key={label} title={label} aria-label={label} role="img">{icon}</span>)}
        </span>
      </div>
      {score !== undefined && (
        <span className="chip-score" aria-label={hideScore || score === null ? 'score hidden by the Mist' : `${score} points`}>
          {hideScore || score === null ? '??' : score.toLocaleString()}
        </span>
      )}
    </div>
  )
}

export function Scoreboard({ children, label = 'Scores' }: { children: ReactNode; label?: string }) {
  return <section className="scoreboard" aria-label={label}>{children}</section>
}

// ───────────────────────────── TimerRing ─────────────────────────────

export function TimerRing({ seconds, fraction, size = 72 }: { seconds: number; fraction: number; size?: number }) {
  const r = 30
  const c = 2 * Math.PI * r
  const urgent = seconds <= 5
  return (
    <div className={`timer${urgent ? ' timer-urgent' : ''}`} style={{ width: size, height: size }} role="timer" aria-label={`${seconds} seconds left`}>
      <svg viewBox="0 0 72 72" width={size} height={size} aria-hidden="true">
        <circle cx="36" cy="36" r={r} className="timer-track" />
        <circle cx="36" cy="36" r={r} className="timer-arc" strokeDasharray={c} strokeDashoffset={c * (1 - fraction)} transform="rotate(-90 36 36)" />
      </svg>
      <span className="timer-num" aria-hidden="true">{seconds}</span>
    </div>
  )
}

// ───────────────────────────── AnswerButton ─────────────────────────────

export type AnswerState = 'idle' | 'selected' | 'locked' | 'correct' | 'wrong' | 'dim'

const STATE_WORD: Partial<Record<AnswerState, [string, string]>> = {
  correct: ['✔', 'Correct'], wrong: ['✖', 'Wrong'], locked: ['🔒', 'Locked in'], selected: ['●', 'Your pick'],
}

export function AnswerButton({ index, text, state = 'idle', disabled, onClick }: { index: number; text: string; state?: AnswerState; disabled?: boolean; onClick?: () => void }) {
  const word = STATE_WORD[state]
  return (
    <button type="button" className={`answer answer-${state}`} disabled={disabled} onClick={onClick}
      aria-pressed={state === 'selected' || state === 'locked' ? true : undefined} data-testid={`answer-${index}`}>
      <span className="answer-key" aria-hidden="true">{index + 1}</span>
      <span className="answer-text">{text}</span>
      {word && (
        <span className="answer-flag">
          <span aria-hidden="true">{word[0]}</span> {word[1]}
        </span>
      )}
    </button>
  )
}

// ───────────────────────────── flip Card ─────────────────────────────

export function FlipCard({ flipped, front, back, label }: { flipped: boolean; front: ReactNode; back: ReactNode; label: string }) {
  return (
    <div className={`flip${flipped ? ' flip-on' : ''}`} role="group" aria-label={label}>
      <div className="flip-inner">
        <div className="flip-face flip-front" aria-hidden={flipped}>{front}</div>
        <div className="flip-face flip-back" aria-hidden={!flipped}>{back}</div>
      </div>
    </div>
  )
}

// ───────────────────────────── Wheel of Mayhem ─────────────────────────────

const SLICE = 360 / WHEEL_SEGMENTS.length
const SHORT: Record<string, string> = {
  'Ladder of Chance': 'Ladder', 'Tax Season': 'Tax', 'Gift of the Bamboozle': 'Gift', 'Full Reversal': 'Reversal',
  'Mystic Mist': 'Mist', 'Bonus Round': 'Bonus', 'Wango Again': 'Wango', "Monkey's Choice": 'Monkey',
}

/** The wheel lands where the server said it did. `spinId` changes for every spin; `result` is the segment name. */
export function Wheel({ result, spinId, reduced }: { result: string | null; spinId: number; reduced: boolean }) {
  const index = result ? Math.max(0, (WHEEL_SEGMENTS as readonly string[]).indexOf(result)) : 0
  // whole turns per spin so a repeat result still visibly spins; reduced motion shows the result at once
  const turns = result ? (reduced ? 0 : 4 + (spinId % 3)) : 0
  const angle = result ? turns * 360 - (index + 0.5) * SLICE : 0
  const slices = WHEEL_SEGMENTS.map((name, i) => {
    const a0 = ((i * SLICE - 90) * Math.PI) / 180
    const a1 = (((i + 1) * SLICE - 90) * Math.PI) / 180
    const [x0, y0, x1, y1] = [100 + 92 * Math.cos(a0), 100 + 92 * Math.sin(a0), 100 + 92 * Math.cos(a1), 100 + 92 * Math.sin(a1)]
    const mid = i * SLICE + SLICE / 2
    return (
      <g key={name}>
        <path d={`M100 100 L${x0} ${y0} A92 92 0 0 1 ${x1} ${y1} Z`} className={`wheel-slice wheel-slice-${i % 2}`} />
        <text x="100" y="26" className="wheel-label" transform={`rotate(${mid} 100 100)`} textAnchor="middle">{SHORT[name]}</text>
      </g>
    )
  })
  return (
    <div className="wheel" role="img" aria-label={result ? `Wheel of Mayhem, landed on ${result}` : 'Wheel of Mayhem'}>
      <div className="wheel-pointer" aria-hidden="true">▼</div>
      <svg viewBox="0 0 200 200" className="wheel-disc" aria-hidden="true" style={{ transform: `rotate(${angle}deg)` }} data-angle={angle}>
        {slices}
        <circle cx="100" cy="100" r="14" className="wheel-hub" />
      </svg>
    </div>
  )
}

// ───────────────────────────── Podium ─────────────────────────────

export function Podium({ rows, name }: { rows: ResultRow[]; name: (id: number) => string }) {
  const top = rows.slice(0, 3)
  const order = top.length === 3 ? [top[1], top[0], top[2]] : top           // 2nd, 1st, 3rd
  const medal = ['🥇', '🥈', '🥉']
  return (
    <ol className="podium" aria-label="Podium">
      {order.map((r) => (
        <li key={r.user_id} className={`podium-step podium-${r.rank}`}>
          <span className="podium-medal" aria-hidden="true">{medal[r.rank - 1]}</span>
          <span className="podium-name">{name(r.user_id)}</span>
          <span className="podium-score">{r.score.toLocaleString()}</span>
          <span className="podium-block"><span className="sr-only">Place </span>{r.rank}</span>
        </li>
      ))}
    </ol>
  )
}
