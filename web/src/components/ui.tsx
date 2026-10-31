import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { useEffect, useId, useRef, useState } from 'react'

type Tone = 'primary' | 'secondary' | 'danger' | 'ghost'

export function Button({ tone = 'primary', big, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone; big?: boolean }) {
  return (
    <button type="button" {...rest} className={`btn btn-${tone}${big ? ' btn-big' : ''} ${rest.className ?? ''}`}>
      {children}
    </button>
  )
}

/** An icon-only button must have an accessible name. */
export function IconButton({ label, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button type="button" {...rest} aria-label={label} title={label} className={`icon-btn ${rest.className ?? ''}`}>
      <span aria-hidden="true">{children}</span>
    </button>
  )
}

export function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  const id = useId()
  return (
    <div className="toggle-row">
      <div className="grow">
        <span id={id} className="toggle-label">{label}</span>
        {hint && <span className="muted toggle-hint"> {hint}</span>}
      </div>
      <button type="button" role="switch" aria-checked={checked} aria-labelledby={id} className="toggle" onClick={() => onChange(!checked)}>
        <span className="toggle-knob" aria-hidden="true" />
        <span className="toggle-state" aria-hidden="true">{checked ? 'On' : 'Off'}</span>
      </button>
    </div>
  )
}

export function Skeleton({ label = 'Loading', lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div className="skeleton-wrap" role="status">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ width: `${100 - i * 15}%` }} aria-hidden="true" />)}
    </div>
  )
}

export function Banner({ tone = 'info', children, icon }: { tone?: 'info' | 'warn' | 'error' | 'success'; children: ReactNode; icon?: string }) {
  return (
    <div className={`banner banner-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <span aria-hidden="true">{icon ?? (tone === 'error' ? '⚠️' : tone === 'warn' ? '⏳' : tone === 'success' ? '✅' : 'ℹ️')}</span>
      <div className="grow">{children}</div>
    </div>
  )
}

export interface TabDef { id: string; label: string }

export function Tabs({ tabs, active, onChange, children, label }: { tabs: TabDef[]; active: string; onChange: (id: string) => void; children: ReactNode; label: string }) {
  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return
    e.preventDefault()
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
    onChange(tabs[next].id)
    ;(e.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus()
  }
  return (
    <div>
      <div role="tablist" aria-label={label} className="tabs">
        {tabs.map((t, i) => (
          <button key={t.id} id={`tab-${t.id}`} role="tab" type="button" aria-selected={active === t.id} aria-controls={`panel-${t.id}`}
            tabIndex={active === t.id ? 0 : -1} className="tab" onClick={() => onChange(t.id)} onKeyDown={(e) => onKey(e, i)}>
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`} className="tab-panel">{children}</div>
    </div>
  )
}

export function Modal({ title, onClose, children, actions }: { title: string; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const root = ref.current
    const focusables = () => Array.from(root?.querySelectorAll<HTMLElement>('button, [href], input, select, [tabindex]:not([tabindex="-1"])') ?? [])
    focusables()[0]?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus() }
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={ref} className="modal card" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId}>{title}</h2>
        <div className="col">{children}</div>
        {actions && <div className="row modal-actions">{actions}</div>}
      </div>
    </div>
  )
}

export function Skip() {
  return <a className="skip" href="#main">Skip to the game</a>
}

/** Hook-free helper used by screens that need a one-shot delay. */
export function useDelayedFlag(ms: number, active: boolean): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!active) { setOn(false); return }
    const t = setTimeout(() => setOn(true), ms)
    return () => clearTimeout(t)
  }, [ms, active])
  return on
}
