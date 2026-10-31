import type { ClientMessage, Envelope, GameEvent, RoomState, ServerError } from './protocol'
import { CLOSE } from './protocol'

export type ConnStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface FatalInfo {
  kind: 'auth' | 'forbidden' | 'unknown_instance' | 'replaced' | 'maintenance' | 'full' | 'other'
  code: string
  message: string
}

export interface ClientHooks {
  onStatus(status: ConnStatus): void
  onState(state: RoomState): void
  onEvent(event: GameEvent): void
  onError(error: ServerError): void
  onBye(reason: string): void
  onFatal(info: FatalInfo): void
}

export interface ClientOptions {
  url: string
  auth: () => Promise<{ access_token: string; instance_id: string }>
  hooks: ClientHooks
  WebSocketImpl?: typeof WebSocket
  now?: () => number
  random?: () => number
  setTimeoutImpl?: (fn: () => void, ms: number) => unknown
  clearTimeoutImpl?: (h: unknown) => void
}

const PING_MS = 30_000
const BACKOFF_BASE_MS = 500
const BACKOFF_CAP_MS = 8_000

/** Delay before reconnect attempt number `attempt` (1-based): exponential with full jitter. */
export function backoffDelay(attempt: number, random: () => number): number {
  const ceiling = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** (attempt - 1))
  return Math.round(ceiling / 2 + (random() * ceiling) / 2)
}

/**
 * The only thing that talks to the server. It authenticates with the first frame, keeps the socket alive with a ping
 * every 30 s, reconnects with backoff, asks for a full STATE when it sees a gap in `seq`, and keeps an estimate of the
 * server's clock. Screens never touch the socket.
 */
export class GameClient {
  private ws: WebSocket | null = null
  private status: ConnStatus = 'idle'
  private attempt = 0
  private lastSeq = 0
  private msgId = 0
  private pingTimer: unknown = null
  private retryTimer: unknown = null
  private stopped = false
  private fatalReported = false
  private offsets: number[] = []
  readonly opts: Required<Pick<ClientOptions, 'now' | 'random' | 'setTimeoutImpl' | 'clearTimeoutImpl'>> & ClientOptions

  constructor(opts: ClientOptions) {
    this.opts = {
      now: () => Date.now(),
      random: Math.random,
      setTimeoutImpl: (fn, ms) => setTimeout(fn, ms),
      clearTimeoutImpl: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
      ...opts,
    }
  }

  /** Estimated server time in ms. */
  serverNow(): number {
    return this.opts.now() + this.clockOffset()
  }

  clockOffset(): number {
    if (!this.offsets.length) return 0
    return [...this.offsets].sort((a, b) => a - b)[Math.floor(this.offsets.length / 2)]
  }

  connect(): void {
    this.stopped = false
    this.fatalReported = false
    void this.open()
  }

  /** The retry button on an error screen: start over from scratch. */
  retry(): void {
    this.clearTimers()
    this.ws?.close(1000)
    this.ws = null
    this.attempt = 0
    this.offsets = []
    this.connect()
  }

  close(): void {
    this.stopped = true
    this.clearTimers()
    this.ws?.close(1000)
    this.ws = null
    this.setStatus('closed')
  }

  send(message: ClientMessage): boolean {
    if (!this.ws || this.ws.readyState !== 1 || this.status !== 'open') return false
    const t = message.t
    const frame: Record<string, unknown> = { v: 1, t, d: 'd' in message && message.d ? message.d : {} }
    if (t !== 'PING' && t !== 'RESYNC') frame.id = `c${++this.msgId}`
    this.ws.send(JSON.stringify(frame))
    return true
  }

  // ───────────────────────────── internals ─────────────────────────────

  private setStatus(s: ConnStatus): void {
    if (this.status !== s) {
      this.status = s
      this.opts.hooks.onStatus(s)
    }
  }

  private clearTimers(): void {
    if (this.pingTimer) this.opts.clearTimeoutImpl(this.pingTimer)
    if (this.retryTimer) this.opts.clearTimeoutImpl(this.retryTimer)
    this.pingTimer = this.retryTimer = null
  }

  private async open(): Promise<void> {
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting')
    let creds: { access_token: string; instance_id: string }
    try {
      creds = await this.opts.auth()
    } catch (err) {
      this.fatal({ kind: 'auth', code: 'sign_in_failed', message: err instanceof Error ? err.message : 'Sign-in failed.' })
      this.setStatus('closed')
      return
    }
    if (this.stopped) return
    const Impl = this.opts.WebSocketImpl ?? WebSocket
    const ws = new Impl(this.opts.url)
    this.ws = ws
    this.lastSeq = 0
    ws.onopen = () => ws.send(JSON.stringify({ v: 1, t: 'AUTH', d: creds }))
    ws.onmessage = (e: MessageEvent) => this.onMessage(typeof e.data === 'string' ? e.data : '')
    ws.onclose = (e: CloseEvent) => this.onClose(e.code)
    ws.onerror = () => undefined // onclose follows and carries the code
  }

  private onMessage(raw: string): void {
    let frame: Envelope
    try {
      frame = JSON.parse(raw) as Envelope
    } catch {
      return
    }
    if (frame.seq > 0) {
      if (this.lastSeq && frame.seq !== this.lastSeq + 1) {
        this.lastSeq = frame.seq
        this.send({ t: 'RESYNC' }) // a gap: ask for the whole picture
      }
      this.lastSeq = frame.seq
    }
    switch (frame.t) {
      case 'STATE': {
        const state = frame.d as RoomState
        this.noteClock(state.server_now_ms)
        if (this.status !== 'open') {
          this.attempt = 0
          this.setStatus('open')
          this.startPing()
        }
        this.opts.hooks.onState(state)
        break
      }
      case 'EVENT':
        this.opts.hooks.onEvent(frame.d as GameEvent)
        break
      case 'ERROR': {
        const err = frame.d as ServerError
        if (this.status !== 'open') this.fatalFromError(err)
        else this.opts.hooks.onError(err)
        break
      }
      case 'BYE':
        this.opts.hooks.onBye((frame.d as { reason: string }).reason)
        break
      default:
        break
    }
  }

  private fatal(info: FatalInfo): void {
    this.fatalReported = true
    this.opts.hooks.onFatal(info)
  }

  private fatalFromError(err: ServerError): void {
    const kind: FatalInfo['kind'] =
      err.code === 'maintenance' ? 'maintenance'
      : err.code === 'server_full' || err.code === 'room_full' ? 'full'
      : err.code === 'opted_out' || err.code === 'not_in_instance' || err.code === 'no_location' ? 'forbidden'
      : err.code === 'unknown_instance' ? 'unknown_instance'
      : err.code === 'bad_token' || err.code.startsWith('auth') ? 'auth'
      : 'other'
    this.fatal({ kind, code: err.code, message: err.message })
  }

  private noteClock(serverNow: number): void {
    this.offsets.push(serverNow - this.opts.now())
    if (this.offsets.length > 9) this.offsets.shift()
  }

  private startPing(): void {
    if (this.pingTimer) this.opts.clearTimeoutImpl(this.pingTimer)
    this.pingTimer = this.opts.setTimeoutImpl(() => {
      this.send({ t: 'PING' })
      this.startPing()
    }, PING_MS)
  }

  private onClose(code: number): void {
    this.clearTimers()
    this.ws = null
    if (this.stopped) return
    if (this.fatalReported) {                       // the server explained itself with an ERROR frame first
      this.setStatus('closed')
      return
    }
    const stay: Record<number, FatalInfo['kind']> = {
      [CLOSE.NOT_AUTHENTICATED]: 'auth', [CLOSE.FORBIDDEN]: 'forbidden',
      [CLOSE.UNKNOWN_INSTANCE]: 'unknown_instance', [CLOSE.REPLACED]: 'replaced',
    }
    if (code in stay && this.status !== 'open' && code !== CLOSE.REPLACED) {
      // the server already explained with an ERROR frame (handled above); this covers a bare close
      this.fatal({ kind: stay[code], code: String(code), message: 'The server closed the connection.' })
      this.setStatus('closed')
      return
    }
    if (code === CLOSE.REPLACED) {
      this.fatal({ kind: 'replaced', code: 'replaced', message: 'Bamboozled is open in another window.' })
      this.setStatus('closed')
      return
    }
    this.scheduleReconnect()
  }

  private scheduleReconnect(): void {
    this.attempt += 1
    this.setStatus('reconnecting')
    const delay = backoffDelay(this.attempt, this.opts.random)
    this.retryTimer = this.opts.setTimeoutImpl(() => void this.open(), delay)
  }
}
