import type { ActivitySdk, Session } from './types'

/** Stand-in for Discord in development and tests (VITE_MOCK_DISCORD=1). Never part of a production bundle.
 *  http://localhost:5173/?user=alice&instance=test1 signs in as alice; the server must run with BAMBOOZLED_DEV_AUTH=1. */
const KNOWN: Record<string, number> = { alice: 1, bob: 2, carol: 3, dave: 4, erin: 5, frank: 6 }

export function mockUserId(name: string): number {
  if (name in KNOWN) return KNOWN[name]
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 100000
  return 1000 + h
}

export function createMockSdk(search = window.location.search): ActivitySdk {
  const params = new URLSearchParams(search)
  const name = (params.get('user') ?? 'alice').slice(0, 24)
  const instanceId = params.get('instance') ?? 'test1'
  const id = mockUserId(name)
  return {
    async init(): Promise<Session> {
      return { accessToken: `dev:${id}:${name}`, instanceId, userId: String(id), name }
    },
    onParticipants(cb) {
      const timer = setTimeout(() => cb([String(id)]), 0) // the same event shape the real SDK emits
      return () => clearTimeout(timer)
    },
  }
}
