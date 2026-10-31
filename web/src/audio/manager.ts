/** Sound cues, synthesised here with the Web Audio API: nothing to download, nothing to license. Audio only starts
 *  after the first user gesture (browsers require it), and the mute toggle is respected everywhere. */
export type Cue = 'tick' | 'correct' | 'wrong' | 'spin' | 'card' | 'win'

const NOTES: Record<Cue, { f: number[]; d: number; type: OscillatorType; gain: number }> = {
  tick: { f: [880], d: 0.05, type: 'square', gain: 0.04 },
  correct: { f: [523, 659, 784], d: 0.12, type: 'triangle', gain: 0.09 },
  wrong: { f: [196, 147], d: 0.2, type: 'sawtooth', gain: 0.07 },
  spin: { f: [300, 420, 560, 700, 840], d: 0.09, type: 'sine', gain: 0.07 },
  card: { f: [660, 990], d: 0.07, type: 'triangle', gain: 0.07 },
  win: { f: [523, 659, 784, 1047], d: 0.16, type: 'triangle', gain: 0.1 },
}

export class AudioManager {
  private ctx: AudioContext | null = null
  private unlocked = false
  enabled = true

  /** Call from a click/tap/key handler. Safe to call repeatedly. */
  unlock(): void {
    if (this.unlocked || typeof window === 'undefined') return
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return
    try {
      this.ctx = new Ctor()
      void this.ctx.resume()
      this.unlocked = true
    } catch { /* no audio on this device */ }
  }

  play(cue: Cue): void {
    if (!this.enabled || !this.ctx) return
    const { f, d, type, gain } = NOTES[cue]
    const t0 = this.ctx.currentTime
    f.forEach((freq, i) => {
      const osc = this.ctx!.createOscillator()
      const amp = this.ctx!.createGain()
      osc.type = type
      osc.frequency.value = freq
      amp.gain.setValueAtTime(gain, t0 + i * d)
      amp.gain.exponentialRampToValueAtTime(0.0001, t0 + (i + 1) * d)
      osc.connect(amp).connect(this.ctx!.destination)
      osc.start(t0 + i * d)
      osc.stop(t0 + (i + 1) * d + 0.02)
    })
  }
}

export const audio = new AudioManager()
