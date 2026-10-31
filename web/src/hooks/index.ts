import { useEffect, useMemo, useRef, useState } from 'react'
import type { Member } from '../net/protocol'
import { prefersReducedMotion } from '../state/settings'
import type { UiEvent } from '../state/store'
import { serverNow, useStore } from '../state/store'

/** Server time, refreshed a few times a second. */
export function useServerNow(intervalMs = 250): number {
  const [now, setNow] = useState(serverNow())
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

export interface Countdown { remainingMs: number; fraction: number; seconds: number }

/** Time left until a server deadline. `totalMs` is the length of the whole window, for the ring. */
export function useCountdown(deadlineMs: number | null | undefined, totalMs: number): Countdown | null {
  const now = useServerNow(200)
  if (!deadlineMs) return null
  const remainingMs = Math.max(0, deadlineMs - now)
  return { remainingMs, fraction: Math.min(1, remainingMs / totalMs), seconds: Math.ceil(remainingMs / 1000) }
}

export function useReducedMotion(): boolean {
  const settings = useStore((s) => s.settings)
  return prefersReducedMotion(settings)
}

/** The most recent event of one of these kinds that arrived after this component mounted (null until one does). */
export function useLatestEvent(kinds: string[]): UiEvent | null {
  const events = useStore((s) => s.events)
  const baseline = useRef<number | null>(null)
  if (baseline.current === null) baseline.current = events.length ? events[events.length - 1].id : 0
  return useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e.id <= (baseline.current ?? 0)) break
      if (kinds.includes(e.kind)) return e
    }
    return null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events])
}

/** Keys 1-4 (and A-D) pick an answer on desktop. */
export function useAnswerKeys(enabled: boolean, count: number, onPick: (index: number) => void): void {
  useEffect(() => {
    if (!enabled) return
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return
      const k = e.key.toLowerCase()
      const index = '1234'.includes(k) && k.length === 1 ? Number(k) - 1 : 'abcd'.indexOf(k)
      if (k.length === 1 && index >= 0 && index < count) {
        e.preventDefault()
        onPick(index)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [enabled, count, onPick])
}

export function useMembers(): { byId: Map<number, Member>; name: (id: number) => string } {
  const members = useStore((s) => s.room?.members)
  return useMemo(() => {
    const byId = new Map((members ?? []).map((m) => [m.user_id, m]))
    return { byId, name: (id: number) => byId.get(id)?.name ?? 'A player' }
  }, [members])
}

/** Polite screen-reader announcements for turn changes, results and the clock. */
export function useAnnounce(): (text: string) => void {
  const announce = useStore((s) => s.announce)
  return announce
}

/** Countdown whose ring is sized by the first remaining time we saw for this deadline. */
export function useWindowCountdown(deadlineMs: number | null | undefined): Countdown | null {
  const now = useServerNow(200)
  const seen = useRef<{ deadline: number; total: number } | null>(null)
  if (!deadlineMs) { seen.current = null; return null }
  if (!seen.current || seen.current.deadline !== deadlineMs) seen.current = { deadline: deadlineMs, total: Math.max(1000, deadlineMs - now) }
  const remainingMs = Math.max(0, deadlineMs - now)
  return { remainingMs, fraction: Math.min(1, remainingMs / seen.current.total), seconds: Math.ceil(remainingMs / 1000) }
}

/** Announce the clock at 20, 10 and 5 seconds, and tick softly in the last five. */
export function useClockAnnouncements(seconds: number | undefined, active: boolean, label: string, tick: () => void): void {
  const announce = useStore((s) => s.announce)
  const last = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!active || seconds === undefined || last.current === seconds) return
    last.current = seconds
    if (seconds === 20 || seconds === 10 || seconds === 5) announce(`${seconds} seconds left ${label}`)
    if (seconds > 0 && seconds <= 5) tick()
  }, [seconds, active, label, tick, announce])
}
