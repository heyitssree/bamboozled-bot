import { authHeaders } from './connection'
import type { Mode } from '../net/protocol'

export interface MyStats { games: number; wins: number; best_score: number; total_score: number; best_streak: number }
export interface BoardEntry { user_id: number; name: string; [key: string]: unknown }

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: authHeaders() })
  if (!res.ok) throw new Error(`${res.status}`)
  return (await res.json()) as T
}

export const fetchMyStats = (mode: Mode) => getJson<MyStats>(`/api/me/stats?mode=${mode}`)
export const fetchBoard = (mode: Mode, scope: 'server' | 'global') =>
  getJson<{ rows: BoardEntry[] }>(`/api/leaderboard?mode=${mode}&scope=${scope}`).then((r) => r.rows)

export type PrivacyOutcome = 'done' | 'in_game' | 'cooldown' | 'unavailable' | 'failed'

/** Opt out or in. The server refuses an opt-out during a running game (409) and an early opt-in (429). */
export async function postPrivacy(action: 'opt_out' | 'opt_in'): Promise<PrivacyOutcome> {
  try {
    const res = await fetch(`/api/privacy/${action}`, { method: 'POST', headers: authHeaders() })
    if (res.ok) return 'done'
    if (res.status === 409) return 'in_game'
    if (res.status === 429) return 'cooldown'
    return res.status === 404 || res.status === 405 || res.status === 501 || res.status === 503 ? 'unavailable' : 'failed'
  } catch {
    return 'failed'
  }
}
