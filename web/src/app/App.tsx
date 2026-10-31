import { lazy, Suspense, useEffect, useState } from 'react'
import { Announcer, ToastHost } from '../components/Toasts'
import { Banner, IconButton, Modal, Skeleton, Skip } from '../components/ui'
import { Lobby } from '../screens/Lobby'
import { Results } from '../screens/Results'
import { Settings } from '../screens/Settings'
import { Splash } from '../screens/Splash'
import { applySettings } from '../state/settings'
import { useStore } from '../state/store'
import { audio } from '../audio/manager'
import { startApp } from './connection'

// each mode is its own chunk: a player who only ever plays one never downloads the others
const Bamboozled = lazy(() => import('../screens/Bamboozled'))
const Fff = lazy(() => import('../screens/Fff'))
const Survival = lazy(() => import('../screens/Survival'))
const Stats = lazy(() => import('../screens/Stats').then((m) => ({ default: m.Stats })))

// The screen gallery exists only in mock builds (VITE_MOCK_DISCORD=1): production bundles contain no fixtures.
const galleryId = import.meta.env.VITE_MOCK_DISCORD === '1' ? new URLSearchParams(window.location.search).get('screen') : null

const TITLE = { bamboozled: 'Bamboozled', fff: 'Fastest Fingers First', survival: 'Survival' } as const

export function App() {
  const { boot, fatal, room, conn, interrupted, roomClosed, settings } = useStore()
  const [dialog, setDialog] = useState<'settings' | 'stats' | null>(null)

  useEffect(() => {
    if (import.meta.env.VITE_MOCK_DISCORD === '1' && galleryId) {
      void import('./fixtures').then((m) => {
        m.installFakeApi()
        const f = m.fixtureById(galleryId)
        if (f) { m.applyFixture(f); setDialog(f.dialog ?? null) }
      })
      return
    }
    void startApp()
  }, [])
  useEffect(() => { applySettings(settings); audio.enabled = settings.sound }, [settings])

  if (boot.phase !== 'ready' || fatal || !room) return <Splash boot={boot} fatal={fatal} joining={boot.phase === 'ready'} />

  if (roomClosed) {
    return (
      <main id="main" className="hero">
        <div className="hero-logo" aria-hidden="true">🚪</div>
        <h1>This room was closed</h1>
        <p className="muted">It was idle for too long. Launch Bamboozled again from Discord to start a new game.</p>
      </main>
    )
  }

  const playing = room.phase === 'playing'
  return (
    <>
      <Skip />
      <header className="topbar">
        <h1>{room.phase === 'lobby' ? 'Bamboozled' : TITLE[room.mode]}</h1>
        <IconButton label="Stats and leaderboards" onClick={() => setDialog('stats')}>🏆</IconButton>
        <IconButton label="Settings" onClick={() => setDialog('settings')}>⚙️</IconButton>
      </header>
      {conn === 'reconnecting' && (
        <div className="reconnect-bar"><Banner tone="warn">Reconnecting… your seat is kept for a little while.</Banner></div>
      )}
      <Suspense fallback={<main id="main" className="page"><Skeleton label="Loading the game" /></main>}>
        {room.phase === 'lobby' && <Lobby room={room} />}
        {room.phase === 'results' && <Results room={room} />}
        {playing && room.mode === 'bamboozled' && <Bamboozled room={room} />}
        {playing && room.mode === 'fff' && <Fff room={room} />}
        {playing && room.mode === 'survival' && <Survival room={room} />}
      </Suspense>
      {interrupted && (
        <div className="overlay" role="alertdialog" aria-modal="true" aria-labelledby="int-h">
          <div className="card col center" style={{ maxWidth: 420 }}>
            <h2 id="int-h">Game interrupted</h2>
            <p>The game server restarted, so this game ended. Hang on: you will be back in the lobby in a moment.</p>
            <Skeleton label="Reconnecting" lines={1} />
          </div>
        </div>
      )}
      {dialog && (
        <Modal title={dialog === 'settings' ? 'Settings' : 'Stats and leaderboards'} onClose={() => setDialog(null)}>
          <Suspense fallback={<Skeleton label="Loading" />}>
            {dialog === 'settings' ? <Settings /> : <Stats />}
          </Suspense>
        </Modal>
      )}
      <ToastHost />
      <Announcer />
    </>
  )
}
