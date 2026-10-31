import { useState } from 'react'
import { postPrivacy } from '../app/api'
import { audio } from '../audio/manager'
import { Button, Modal, Toggle } from '../components/ui'
import { useStore } from '../state/store'

const VERSION = __APP_VERSION__

export function Settings() {
  const settings = useStore((s) => s.settings)
  const setSettings = useStore((s) => s.setSettings)
  const toast = useStore((s) => s.toast)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)

  const optOut = async () => {
    setBusy(true)
    const result = await postPrivacy('opt_out')
    setBusy(false)
    setConfirm(false)
    if (result === 'done') toast('Done. Your results were deleted and you are opted out. Use /privacy opt_in to come back.', 'info')
    else if (result === 'unavailable') toast('Privacy controls are not switched on yet. Use /privacy in Discord for now.')
    else toast('That did not work. Please try again in a moment.')
  }

  return (
    <div className="col">
      <section className="col" aria-labelledby="pref-h">
        <h3 id="pref-h">Preferences</h3>
        <Toggle label="Sound effects" checked={settings.sound} hint="Starts after your first tap."
          onChange={(sound) => { audio.enabled = sound; setSettings({ sound }); if (sound) { audio.unlock(); audio.play('card') } }} />
        <Toggle label="Reduce motion" checked={settings.motion === 'reduce'} hint="Results appear at once instead of animating."
          onChange={(on) => setSettings({ motion: on ? 'reduce' : 'full' })} />
        <div className="field">
          <label htmlFor="theme">Theme</label>
          <select id="theme" className="select" value={settings.theme} onChange={(e) => setSettings({ theme: e.target.value as 'system' | 'dark' | 'light' })}>
            <option value="system">Match my device</option><option value="dark">Dark</option><option value="light">Light</option>
          </select>
        </div>
      </section>
      <section className="col" aria-labelledby="priv-h">
        <h3 id="priv-h">Privacy</h3>
        <p>Bamboozled keeps only your Discord id and your results. It never saves your name or picture: they are fetched from Discord when shown.</p>
        <p className="muted">Opting out deletes your results and stats and stops you joining games. Backups age out within 72 hours and logs within 14 days.</p>
        <div><Button tone="danger" onClick={() => setConfirm(true)}>Opt out and delete my results…</Button></div>
      </section>
      <p className="muted">Bamboozled {VERSION}</p>
      {confirm && (
        <Modal title="Opt out of Bamboozled?" onClose={() => setConfirm(false)}
          actions={<><Button tone="ghost" onClick={() => setConfirm(false)}>Keep playing</Button><Button tone="danger" disabled={busy} onClick={optOut}>{busy ? 'Working…' : 'Yes, delete and opt out'}</Button></>}>
          <p>This deletes all your results and stats and you will not be able to join games until you opt back in. It cannot be undone.</p>
          <p className="muted">You can opt back in later with /privacy opt_in, after a short wait.</p>
        </Modal>
      )}
    </div>
  )
}
