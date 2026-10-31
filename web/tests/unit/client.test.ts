import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ClientHooks, FatalInfo } from '../../src/net/client'
import { backoffDelay, GameClient } from '../../src/net/client'
import type { RoomState } from '../../src/net/protocol'

class FakeSocket {
  static all: FakeSocket[] = []
  readyState = 0
  sent: Record<string, unknown>[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) { FakeSocket.all.push(this) }
  send(raw: string) { this.sent.push(JSON.parse(raw)) }
  close(code = 1000) { this.readyState = 3; this.onclose?.({ code }) }
  // test helpers
  open() { this.readyState = 1; this.onopen?.() }
  frame(t: string, d: unknown, seq: number) { this.onmessage?.({ data: JSON.stringify({ v: 1, t, seq, d }) }) }
  drop(code: number) { this.readyState = 3; this.onclose?.({ code }) }
}

const STATE = (now = 1_000_000): RoomState => ({
  phase: 'lobby', mode: 'bamboozled', you: 1, role: 'player', host: 1, server_now_ms: now, deadline_ms: null,
  config: { rounds: null, difficulty: null, category: null }, min_players: 2, max_players: 10, can_start: false,
  members: [], game: null, board: null, results: null,
})

function setup(over: { now?: () => number; random?: () => number } = {}) {
  FakeSocket.all = []
  const log = { status: [] as string[], states: [] as RoomState[], events: [] as unknown[], errors: [] as unknown[], byes: [] as string[], fatals: [] as FatalInfo[] }
  const hooks: ClientHooks = {
    onStatus: (s) => log.status.push(s), onState: (s) => log.states.push(s), onEvent: (e) => log.events.push(e),
    onError: (e) => log.errors.push(e), onBye: (r) => log.byes.push(r), onFatal: (f) => log.fatals.push(f),
  }
  const client = new GameClient({
    url: 'ws://x/api/ws', auth: async () => ({ access_token: 'tok', instance_id: 'inst' }), hooks,
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket, now: over.now ?? (() => 1_000_000), random: over.random ?? (() => 0.5),
  })
  return { client, log, sock: () => FakeSocket.all[FakeSocket.all.length - 1] }
}
const tick = () => vi.advanceTimersByTimeAsync(0)

describe('GameClient', () => {
  beforeEach(() => { vi.useFakeTimers() })

  it('authenticates with the very first frame, never in the URL', async () => {
    const { client, sock } = setup()
    client.connect(); await tick()
    expect(sock().url).toBe('ws://x/api/ws')
    sock().open()
    expect(sock().sent).toEqual([{ v: 1, t: 'AUTH', d: { access_token: 'tok', instance_id: 'inst' } }])
  })

  it('is open once the first STATE arrives and tells the app', async () => {
    const { client, log, sock } = setup()
    client.connect(); await tick(); sock().open()
    expect(log.status).toEqual(['connecting'])
    sock().frame('STATE', STATE(), 1)
    expect(log.status).toEqual(['connecting', 'open'])
    expect(log.states).toHaveLength(1)
  })

  it('sends intents with an id, and refuses to send while not open', async () => {
    const { client, sock } = setup()
    expect(client.send({ t: 'START' })).toBe(false)
    client.connect(); await tick(); sock().open()
    expect(client.send({ t: 'START' })).toBe(false)              // signed in but no STATE yet
    sock().frame('STATE', STATE(), 1)
    expect(client.send({ t: 'ANSWER', d: { index: 2 } })).toBe(true)
    expect(client.send({ t: 'PING' })).toBe(true)
    const [, answer, ping] = sock().sent
    expect(answer).toMatchObject({ v: 1, t: 'ANSWER', d: { index: 2 }, id: 'c1' })
    expect(ping).toEqual({ v: 1, t: 'PING', d: {} })              // keepalives carry no id
  })

  it('pings every 30 seconds to keep idle proxies open', async () => {
    const { client, sock } = setup()
    client.connect(); await tick(); sock().open(); sock().frame('STATE', STATE(), 1)
    await vi.advanceTimersByTimeAsync(30_000)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(sock().sent.filter((m) => m.t === 'PING')).toHaveLength(2)
  })

  it('asks for a full STATE when it notices a gap in seq', async () => {
    const { client, sock } = setup()
    client.connect(); await tick(); sock().open()
    sock().frame('STATE', STATE(), 1)
    sock().frame('EVENT', { kind: 'x', payload: {} }, 2)
    sock().frame('EVENT', { kind: 'y', payload: {} }, 5)          // 3 and 4 were lost
    expect(sock().sent.filter((m) => m.t === 'RESYNC')).toHaveLength(1)
    sock().frame('EVENT', { kind: 'z', payload: {} }, 6)          // back in step: no further request
    expect(sock().sent.filter((m) => m.t === 'RESYNC')).toHaveLength(1)
  })

  it('learns the server clock from STATE frames and uses the median', async () => {
    let local = 1_000_000
    const { client, sock } = setup({ now: () => local })
    client.connect(); await tick(); sock().open()
    sock().frame('STATE', STATE(1_005_000), 1)                    // server is 5 s ahead
    sock().frame('STATE', STATE(1_005_100), 2)
    sock().frame('STATE', STATE(1_009_000), 3)                    // one wild reading does not move the median
    expect(client.clockOffset()).toBe(5100)
    local += 1000
    expect(client.serverNow()).toBe(1_006_100)
  })

  it('reconnects with backoff after an unexpected close, and goes back to open', async () => {
    const { client, log, sock } = setup()
    client.connect(); await tick(); sock().open(); sock().frame('STATE', STATE(), 1)
    sock().drop(1006)
    expect(log.status.at(-1)).toBe('reconnecting')
    const before = FakeSocket.all.length
    await vi.advanceTimersByTimeAsync(backoffDelay(1, () => 0.5) + 5)
    expect(FakeSocket.all.length).toBe(before + 1)
    sock().open(); sock().frame('STATE', STATE(), 1)
    expect(log.status.at(-1)).toBe('open')
  })

  it('keeps backing off while the server stays away, then resets after a success', async () => {
    const { client, sock } = setup()
    client.connect(); await tick(); sock().open(); sock().frame('STATE', STATE(), 1)
    for (let i = 0; i < 3; i++) { sock().drop(1006); await vi.advanceTimersByTimeAsync(backoffDelay(i + 1, () => 0.5) + 5) }
    expect(FakeSocket.all.length).toBe(4)
    sock().open(); sock().frame('STATE', STATE(), 1)
    sock().drop(1006)
    const n = FakeSocket.all.length
    await vi.advanceTimersByTimeAsync(backoffDelay(1, () => 0.5) + 5)       // back to the shortest delay
    expect(FakeSocket.all.length).toBe(n + 1)
  })

  it('treats a refusal explained by an ERROR frame as fatal, once, and does not reconnect', async () => {
    const { client, log, sock } = setup()
    client.connect(); await tick(); sock().open()
    sock().frame('ERROR', { code: 'opted_out', message: 'You have opted out.' }, 0)
    sock().drop(4403)
    expect(log.fatals).toEqual([{ kind: 'forbidden', code: 'opted_out', message: 'You have opted out.' }])
    expect(log.status.at(-1)).toBe('closed')
    await vi.advanceTimersByTimeAsync(20_000)
    expect(FakeSocket.all).toHaveLength(1)
  })

  it.each([
    ['maintenance', 'maintenance'], ['server_full', 'full'], ['room_full', 'full'], ['bad_token', 'auth'],
    ['unknown_instance', 'unknown_instance'], ['not_in_instance', 'forbidden'], ['weird', 'other'],
  ])('maps the error code %s to the screen kind %s', async (code, kind) => {
    const { client, log, sock } = setup()
    client.connect(); await tick(); sock().open()
    sock().frame('ERROR', { code, message: 'm' }, 0)
    expect(log.fatals[0].kind).toBe(kind)
  })

  it('a bare 4401 close before sign-in is fatal; 4409 means another window took over', async () => {
    const a = setup(); a.client.connect(); await tick(); a.sock().open(); a.sock().drop(4401)
    expect(a.log.fatals[0].kind).toBe('auth')
    const b = setup(); b.client.connect(); await tick(); b.sock().open(); b.sock().frame('STATE', STATE(), 1); b.sock().drop(4409)
    expect(b.log.fatals[0].kind).toBe('replaced')
  })

  it('a failed sign-in with Discord is fatal and retry starts over', async () => {
    FakeSocket.all = []
    let fail = true
    const log: FatalInfo[] = []
    const client = new GameClient({
      url: 'ws://x', WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
      auth: async () => { if (fail) throw new Error('Discord said no'); return { access_token: 't', instance_id: 'i' } },
      hooks: { onStatus: () => undefined, onState: () => undefined, onEvent: () => undefined, onError: () => undefined, onBye: () => undefined, onFatal: (f) => log.push(f) },
    })
    client.connect(); await tick()
    expect(log).toEqual([{ kind: 'auth', code: 'sign_in_failed', message: 'Discord said no' }])
    fail = false
    client.retry(); await tick()
    expect(FakeSocket.all).toHaveLength(1)
  })

  it('passes events, errors and BYE through, and ignores junk frames', async () => {
    const { client, log, sock } = setup()
    client.connect(); await tick(); sock().open(); sock().frame('STATE', STATE(), 1)
    sock().frame('EVENT', { kind: 'wheel_result', payload: { segment: 'Tax Season' } }, 2)
    sock().frame('ERROR', { code: 'not_host', message: 'no' }, 3)
    sock().frame('BYE', { reason: 'server_restart' }, 4)
    sock().frame('MYSTERY', {}, 5)
    sock().onmessage?.({ data: 'not json' })
    expect(log.events).toHaveLength(1)
    expect(log.errors).toHaveLength(1)
    expect(log.byes).toEqual(['server_restart'])
  })

  it('close() stops everything and never reconnects', async () => {
    const { client, log, sock } = setup()
    client.connect(); await tick(); sock().open(); sock().frame('STATE', STATE(), 1)
    client.close()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(FakeSocket.all).toHaveLength(1)
    expect(log.status.at(-1)).toBe('closed')
  })
})

describe('backoffDelay', () => {
  it('grows exponentially, is jittered, and is capped at 8 seconds', () => {
    expect(backoffDelay(1, () => 0)).toBe(250)
    expect(backoffDelay(1, () => 1)).toBe(500)
    expect(backoffDelay(3, () => 1)).toBe(2000)
    for (const attempt of [6, 10, 50]) {
      expect(backoffDelay(attempt, () => 1)).toBe(8000)
      expect(backoffDelay(attempt, () => 0)).toBe(4000)
    }
  })
})
