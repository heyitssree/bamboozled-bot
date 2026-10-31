import { useEffect } from 'react'
import { useStore } from '../state/store'

export function ToastHost() {
  const toasts = useStore((s) => s.toasts)
  const dismiss = useStore((s) => s.dismissToast)
  useEffect(() => {
    const timers = toasts.map((t) => setTimeout(() => dismiss(t.id), 6000))
    return () => timers.forEach(clearTimeout)
  }, [toasts, dismiss])
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`}>
          <span aria-hidden="true">{t.tone === 'error' ? '⚠️' : 'ℹ️'}</span>
          <span className="grow">{t.text}</span>
          <button type="button" className="toast-x" aria-label="Dismiss message" onClick={() => dismiss(t.id)}>✕</button>
        </div>
      ))}
    </div>
  )
}

/** Screen-reader announcements: turn changes, results, the clock at sensible intervals. Visually hidden. */
export function Announcer() {
  const text = useStore((s) => s.announcement)
  return <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-testid="announcer">{text}</div>
}
