export type Theme = 'system' | 'dark' | 'light'
export type Motion = 'system' | 'reduce' | 'full'
export interface Settings { sound: boolean; motion: Motion; theme: Theme }

const KEY = 'bamboozled.settings'
const SOUND_KEY = 'bamboozled.sound'
export const DEFAULT_SETTINGS: Settings = { sound: true, motion: 'system', theme: 'system' }

/** Storage can be missing, blocked or full (private windows, embedded frames): never let that break the app. */
function read(store: () => Storage, key: string): string | null {
  try { return store().getItem(key) } catch { return null }
}
function write(store: () => Storage, key: string, value: string): void {
  try { store().setItem(key, value) } catch { /* not remembered; the app still works */ }
}

export function loadSettings(): Settings {
  let saved: Partial<Settings> = {}
  try { saved = JSON.parse(read(() => localStorage, KEY) ?? '{}') as Partial<Settings> } catch { /* ignore */ }
  const sound = read(() => sessionStorage, SOUND_KEY)          // the mute choice is remembered for the session only
  return {
    theme: saved.theme === 'dark' || saved.theme === 'light' ? saved.theme : 'system',
    motion: saved.motion === 'reduce' || saved.motion === 'full' ? saved.motion : 'system',
    sound: sound === null ? DEFAULT_SETTINGS.sound : sound === '1',
  }
}

export function saveSettings(s: Settings): void {
  write(() => localStorage, KEY, JSON.stringify({ theme: s.theme, motion: s.motion }))
  write(() => sessionStorage, SOUND_KEY, s.sound ? '1' : '0')
}

/** Reflect the settings on <html> so the CSS tokens and the reduced-motion rules apply. */
export function applySettings(s: Settings, root: HTMLElement = document.documentElement): void {
  if (s.theme === 'system') delete root.dataset.theme
  else root.dataset.theme = s.theme
  if (s.motion === 'system') delete root.dataset.motion
  else root.dataset.motion = s.motion
}

export function prefersReducedMotion(s: Settings): boolean {
  if (s.motion === 'reduce') return true
  if (s.motion === 'full') return false
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}
