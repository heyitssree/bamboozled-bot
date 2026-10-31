import type { FatalInfo } from '../net/client'
import { retry } from '../app/connection'
import { Button, Skeleton } from '../components/ui'
import type { Boot } from '../state/store'

type View = { icon: string; title: string; body: string; retry?: string }

function describe(boot: Boot, fatal: FatalInfo | null, joining: boolean): View {
  if (boot.phase === 'error') {
    return boot.kind === 'not_in_discord'
      ? { icon: '🎮', title: 'Open Bamboozled from Discord', body: 'This is a Discord Activity. Join a voice channel, open the App Launcher (the rocket icon) and pick Bamboozled.' }
      : { icon: '🔑', title: 'Could not sign in', body: boot.message, retry: 'Try again' }
  }
  if (fatal) {
    switch (fatal.kind) {
      case 'forbidden':
        return fatal.code === 'opted_out'
          ? { icon: '🙈', title: 'You have opted out', body: 'You chose not to be part of Bamboozled. Type /privacy opt_in in Discord to play again.' }
          : { icon: '🚪', title: 'You can’t join this game', body: fatal.message || 'You are not part of this Activity session. Launch Bamboozled again from Discord.' }
      case 'unknown_instance':
        return { icon: '⌛', title: 'This session has ended', body: 'Launch Bamboozled again from Discord to start a new one.' }
      case 'full':
        return { icon: '🧳', title: 'Bamboozled is full right now', body: 'Too many games are running. Please try again in a few minutes.', retry: 'Try again' }
      case 'maintenance':
        return { icon: '🛠️', title: 'Back in a moment', body: 'Bamboozled is closed for maintenance. Try again shortly.', retry: 'Try again' }
      case 'replaced':
        return { icon: '🪟', title: 'Open in another window', body: 'Bamboozled is running in a different window for your account. Use this window instead?', retry: 'Use this window' }
      case 'auth':
        return { icon: '🔑', title: 'Could not sign in', body: fatal.message || 'Discord did not accept your sign-in. Reopen the Activity and try again.', retry: 'Try again' }
      default:
        return { icon: '⚠️', title: 'Something went wrong', body: fatal.message || 'We could not connect. Please try again.', retry: 'Try again' }
    }
  }
  return { icon: '🎡', title: joining ? 'Joining the game…' : 'Signing in…', body: '' }
}

export function Splash({ boot, fatal, joining }: { boot: Boot; fatal: FatalInfo | null; joining?: boolean }) {
  const v = describe(boot, fatal, !!joining)
  const loading = !v.body
  return (
    <main id="main" className="hero" aria-live="polite">
      <div className="hero-logo" aria-hidden="true">{v.icon}</div>
      <h1>{v.title}</h1>
      {loading ? <Skeleton label={v.title} lines={2} /> : <p className="muted">{v.body}</p>}
      {v.retry && <Button big onClick={retry}>{v.retry}</Button>}
    </main>
  )
}
