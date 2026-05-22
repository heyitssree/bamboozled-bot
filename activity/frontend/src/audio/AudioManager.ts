class AudioManager {
  private context: AudioContext | null = null
  private buffers = new Map<string, AudioBuffer>()
  private activeNodes = new Map<string, AudioBufferSourceNode>()
  private masterGain: GainNode | null = null
  private masterVolume = 0.7

  private getContext(): AudioContext {
    if (!this.context) {
      this.context = new AudioContext()
      this.masterGain = this.context.createGain()
      this.masterGain.gain.value = this.masterVolume
      this.masterGain.connect(this.context.destination)
    }
    return this.context
  }

  async preload(sounds: string[]): Promise<void> {
    await Promise.allSettled(sounds.map((s) => this._loadSound(s)))
  }

  private async _loadSound(name: string): Promise<void> {
    const ctx = this.getContext()
    try {
      const resp = await fetch(`/sounds/${name}.mp3`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const arrayBuf = await resp.arrayBuffer()
      const audioBuf = await ctx.decodeAudioData(arrayBuf)
      this.buffers.set(name, audioBuf)
    } catch {
      // Sound file missing — will fall back to generated tone
    }
  }

  async play(
    soundName: string,
    options: { volume?: number; loop?: boolean } = {},
  ): Promise<void> {
    const ctx = this.getContext()
    if (ctx.state === 'suspended') {
      await ctx.resume()
    }

    const buffer = this.buffers.get(soundName)
    if (!buffer) {
      this._playFallbackTone(soundName)
      return
    }

    this.stop(soundName)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.loop = options.loop ?? false

    const gainNode = ctx.createGain()
    gainNode.gain.value = options.volume ?? 1.0
    source.connect(gainNode)
    gainNode.connect(this.masterGain ?? ctx.destination)
    source.start()
    this.activeNodes.set(soundName, source)
    source.onended = () => this.activeNodes.delete(soundName)
  }

  stop(soundName: string): void {
    const node = this.activeNodes.get(soundName)
    if (node) {
      try {
        node.stop()
      } catch {
        // already stopped
      }
      this.activeNodes.delete(soundName)
    }
  }

  setMasterVolume(volume: number): void {
    this.masterVolume = Math.max(0, Math.min(1, volume))
    if (this.masterGain) {
      this.masterGain.gain.value = this.masterVolume
    }
  }

  generateTone(
    frequency: number,
    duration: number,
    type: OscillatorType = 'sine',
  ): void {
    const ctx = this.getContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = type
    osc.frequency.value = frequency
    gain.gain.setValueAtTime(0.3, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration)
    osc.connect(gain)
    gain.connect(this.masterGain ?? ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + duration)
  }

  private _playFallbackTone(soundName: string): void {
    const toneMap: Record<string, [number, number, OscillatorType]> = {
      correct: [523, 0.3, 'sine'],
      wrong: [200, 0.4, 'sawtooth'],
      wheel_spin: [440, 0.8, 'square'],
      golden_monkey: [660, 0.6, 'sine'],
      bamboozle: [150, 0.5, 'sawtooth'],
      mist: [330, 1.0, 'sine'],
      sombrero: [280, 0.5, 'triangle'],
      game_over: [784, 1.0, 'sine'],
      tick: [880, 0.1, 'square'],
    }
    const params = toneMap[soundName] ?? [440, 0.3, 'sine']
    this.generateTone(...params)
  }
}

export const audio = new AudioManager()
