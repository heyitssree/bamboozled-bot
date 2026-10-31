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

/** Privacy controls (Phase 5 adds the routes; until then the server answers 404 and we say so honestly). */
export async function postPrivacy(action: 'opt_out' | 'opt_in'): Promise<'done' | 'unavailable' | 'failed'> {
  try {
    const res = await fetch(`/api/privacy/${action}`, { method: 'POST', headers: authHeaders() })
    if (res.ok) return 'done'
    return res.status === 404 || res.status === 405 || res.status === 501 ? 'unavailable' : 'failed'
  } catch {
    return 'failed'
  }
}
