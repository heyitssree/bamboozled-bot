import { audio } from '../audio/manager'
import { GameClient } from '../net/client'
import type { ClientMessage } from '../net/protocol'
import { loadSdk, SdkError } from '../sdk'
import { useStore } from '../state/store'

let client: GameClient | null = null
let started = false
let session: { accessToken: string; instanceId: string } | null = null

/** Headers for the REST calls (stats, leaderboards, privacy). */
export function authHeaders(): Record<string, string> {
  return session ? { Authorization: `Bearer ${session.accessToken}`, 'X-Instance-Id': session.instanceId } : {}
}

export function wsUrl(loc: Pick<Location, 'protocol' | 'host'> = window.location): string {
  return `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/api/ws`
}

/** Sound for the cues that matter. Events carry what happened; state is always rebuilt from STATE frames. */
export function cueFor(kind: string, payload: Record<string, unknown>): Parameters<typeof audio.play>[0] | null {
  switch (kind) {
    case 'wheel_result': return 'spin'
    case 'card_drawn': return 'card'
    case 'reveal':
      if (Array.isArray(payload.winners)) return payload.winners.length ? 'correct' : 'wrong'      // Fastest Fingers
      return payload.chosen != null && payload.chosen === payload.correct_index ? 'correct' : 'wrong'
    case 'streak_up': return 'correct'
    case 'game_over': return payload.reason === 'wrong' || payload.reason === 'timeout' || payload.reason === 'error' ? 'wrong' : 'win'
    default: return null
  }
}

/** Sign in through the SDK, then open the socket. Safe to call twice (React StrictMode does). */
export async function startApp(): Promise<void> {
  if (started) return
  started = true
  const store = useStore.getState()
  store.setBoot({ phase: 'loading' })
  let signedIn
  try {
    signedIn = await (await loadSdk()).init()
  } catch (err) {
    started = false
    if (err instanceof SdkError) store.setBoot({ phase: 'error', kind: err.code, message: err.message })
    else store.setBoot({ phase: 'error', kind: 'sign_in_failed', message: 'Could not sign in to Discord. Please try again.' })
    return
  }
  session = { accessToken: signedIn.accessToken, instanceId: signedIn.instanceId }
  store.setMe({ id: Number(signedIn.userId), name: signedIn.name })
  client = new GameClient({
    url: wsUrl(),
    auth: async () => ({ access_token: signedIn.accessToken, instance_id: signedIn.instanceId }),
    hooks: {
      onStatus: (s) => useStore.getState().setConn(s),
      onState: (room) => {
        const st = useStore.getState()
        st.applyState(room)
        st.setClockOffset(client?.clockOffset() ?? 0)
      },
      onEvent: (event) => {
        useStore.getState().pushEvent(event)
        const cue = cueFor(event.kind, event.payload)
        if (cue) audio.play(cue)
      },
      onError: (e) => useStore.getState().serverError(e),
      onBye: (reason) => useStore.getState().bye(reason),
      onFatal: (info) => useStore.getState().setFatal(info),
    },
  })
  store.setBoot({ phase: 'ready' })
  client.connect()
}

export function send(message: ClientMessage): boolean {
  audio.unlock()                                  // the first tap is the gesture browsers need before sound can play
  return client?.send(message) ?? false
}

export function retry(): void {
  const st = useStore.getState()
  st.setFatal(null)
  if (st.boot.phase === 'error') {
    started = false
    void startApp()
    return
  }
  client?.retry()
}

export function stopApp(): void {
  client?.close()
  client = null
  started = false
}
