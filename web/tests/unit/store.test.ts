import { beforeEach, describe, expect, it } from 'vitest'
import { cueFor } from '../../src/app/connection'
import { describeEvent } from '../../src/app/events'
import type { RoomState } from '../../src/net/protocol'
import { applySettings, DEFAULT_SETTINGS, loadSettings, prefersReducedMotion, saveSettings } from '../../src/state/settings'
import { useStore } from '../../src/state/store'
import { FIXTURES } from '../../src/app/fixtures'
import { mockUserId, createMockSdk } from '../../src/sdk/mock'
import { SdkError } from '../../src/sdk/types'
import { createDiscordSdk } from '../../src/sdk/discord'
import { loadSdk } from '../../src/sdk'

const room = (over: Partial<RoomState> = {}): RoomState => ({
  phase: 'lobby', mode: 'bamboozled', you: 1, role: 'player', host: 1, server_now_ms: 0, deadline_ms: null,
  config: { rounds: null, difficulty: null, category: null }, min_players: 2, max_players: 10, can_start: false,
  members: [], game: null, board: null, results: null, ...over,
})
const Q = { text: 'Q?', answers: ['a', 'b', 'c', 'd'], category: '', difficulty: 'easy', qtype: 'multiple' }
const playing = (question: typeof Q | null): RoomState => room({
  phase: 'playing',
  game: { mode: 'fff', you: 1, over: false, q_index: 0, total_q: 5, players: [], waiting_question: false, deadline_ms: 1, question, your_answer: null, reveal: null },
})

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); useStore.getState().reset() })

describe('the store is fed only by server frames (replay)', () => {
  it('a recorded session produces the expected state at each step', () => {
    const s = () => useStore.getState()
    s().applyState(room())
    expect(s().conn).toBe('open')
    expect(s().room?.phase).toBe('lobby')
    s().applyState(playing(Q))
    expect(s().lastQuestion).toEqual(Q)                              // remembered so the reveal can show the answers
    s().applyState(playing(null))
    expect(s().lastQuestion).toEqual(Q)                              // still there while the result is on screen
    s().applyState(room({ phase: 'results' }))
    expect(s().lastQuestion).toBeNull()                              // gone with the game
  })

  it('keeps only the latest 40 events and gives each a new id', () => {
    for (let i = 0; i < 55; i++) useStore.getState().pushEvent({ kind: 'tick', payload: { i } })
    const ev = useStore.getState().events
    expect(ev).toHaveLength(40)
    expect(ev[0].payload.i).toBe(15)
    expect(new Set(ev.map((e) => e.id)).size).toBe(40)
  })

  it('BYE flags the right overlay, and the next STATE clears them', () => {
    const st = useStore.getState()
    st.bye('server_restart'); expect(useStore.getState().interrupted).toBe(true)
    st.bye('room_closed'); expect(useStore.getState().roomClosed).toBe(true)
    st.bye('kicked'); expect(useStore.getState().fatal).toBeNull()
    st.applyState(room())
    expect(useStore.getState().interrupted).toBe(false)
    expect(useStore.getState().roomClosed).toBe(false)
  })

  it('toasts: friendly text for known codes, silence for tap races, at most three on screen', () => {
    const st = useStore.getState()
    st.serverError({ code: 'not_host', message: 'raw' })
    expect(useStore.getState().toasts[0].text).toBe('Only the host can do that.')
    for (const code of ['not_your_turn', 'bad_phase', 'already_answered']) st.serverError({ code, message: 'x' })
    expect(useStore.getState().toasts).toHaveLength(1)
    st.serverError({ code: 'brand_new_code', message: 'The server said this.' })
    expect(useStore.getState().toasts[1].text).toBe('The server said this.')
    st.toast('a'); st.toast('b')
    expect(useStore.getState().toasts).toHaveLength(3)
    st.dismissToast(useStore.getState().toasts[0].id)
    expect(useStore.getState().toasts).toHaveLength(2)
  })

  it('every fixture in the gallery can be applied without throwing', () => {
    for (const f of FIXTURES) {
      const fn = async () => { (await import('../../src/app/fixtures')).applyFixture(f) }
      expect(fn).not.toThrow()
    }
  })
})

describe('describeEvent and cueFor', () => {
  const name = (id: number) => ['', 'Alice', 'Bob'][id] ?? '?'
  it('words the events plainly', () => {
    expect(describeEvent('wheel_result', { player: 1, segment: 'Tax Season' }, name)).toBe('The wheel lands on Tax Season for Alice.')
    expect(describeEvent('monkey_result', { player: 2, choice: 'tail', delta: -200 }, name)).toBe('Bob picks the tail and loses 200.')
    expect(describeEvent('monkey_result', { player: 2, choice: 'tail' }, name)).toBe('Bob picks the tail.')   // numbers stripped by the Mist
    expect(describeEvent('scores_swapped', { a: 1, b: 2 }, name)).toBe('Alice and Bob swap scores.')
    expect(describeEvent('nothing_we_know', {}, name)).toBeNull()
  })
  it('chooses a sound for the cues that matter', () => {
    expect(cueFor('wheel_result', {})).toBe('spin')
    expect(cueFor('card_drawn', {})).toBe('card')
    expect(cueFor('reveal', { chosen: 2, correct_index: 2 })).toBe('correct')
    expect(cueFor('reveal', { chosen: 1, correct_index: 2 })).toBe('wrong')
    expect(cueFor('reveal', { winners: [3] })).toBe('correct')
    expect(cueFor('reveal', { winners: [] })).toBe('wrong')
    expect(cueFor('game_over', { reason: 'wrong' })).toBe('wrong')
    expect(cueFor('game_over', {})).toBe('win')
    expect(cueFor('mist_on', {})).toBeNull()
  })
})

describe('settings', () => {
  it('round-trips, and the mute is remembered for the session only', () => {
    saveSettings({ sound: false, motion: 'reduce', theme: 'light' })
    expect(loadSettings()).toEqual({ sound: false, motion: 'reduce', theme: 'light' })
    expect(JSON.parse(localStorage.getItem('bamboozled.settings')!)).toEqual({ theme: 'light', motion: 'reduce' })   // no sound key here
    sessionStorage.clear()
    expect(loadSettings().sound).toBe(true)
  })
  it('survives garbage and blocked storage', () => {
    localStorage.setItem('bamboozled.settings', '{{{')
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS)
    localStorage.setItem('bamboozled.settings', JSON.stringify({ theme: 'neon', motion: 'wild' }))
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS)
    const real = Storage.prototype.getItem
    Storage.prototype.getItem = () => { throw new Error('blocked') }
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS)
    Storage.prototype.getItem = real
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = () => { throw new Error('full') }
    expect(() => saveSettings(DEFAULT_SETTINGS)).not.toThrow()
    Storage.prototype.setItem = setItem
  })
  it('applies theme and motion to the page, and system means "no override"', () => {
    const root = document.createElement('html')
    applySettings({ sound: true, motion: 'reduce', theme: 'dark' }, root)
    expect(root.dataset.theme).toBe('dark')
    expect(root.dataset.motion).toBe('reduce')
    applySettings(DEFAULT_SETTINGS, root)
    expect(root.dataset.theme).toBeUndefined()
    expect(root.dataset.motion).toBeUndefined()
    expect(prefersReducedMotion({ ...DEFAULT_SETTINGS, motion: 'reduce' })).toBe(true)
    expect(prefersReducedMotion({ ...DEFAULT_SETTINGS, motion: 'full' })).toBe(false)
  })
  it('setSettings updates the store, the page and storage together', () => {
    useStore.getState().setSettings({ theme: 'light' })
    expect(useStore.getState().settings.theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(loadSettings().theme).toBe('light')
    document.documentElement.removeAttribute('data-theme')
  })
})

describe('the SDK adapters', () => {
  it('the mock signs in from the URL and uses the same dev token format the server accepts', async () => {
    const sdk = createMockSdk('?user=bob&instance=abc')
    expect(await sdk.init()).toEqual({ accessToken: 'dev:2:bob', instanceId: 'abc', userId: '2', name: 'bob' })
    expect(mockUserId('alice')).toBe(1)
    expect(mockUserId('zed')).toBe(mockUserId('zed'))
    expect((await createMockSdk('').init()).name).toBe('alice')
  })
  it('the mock emits a participants update like the real SDK', async () => {
    const got: string[][] = []
    const stop = createMockSdk('?user=carol').onParticipants((ids) => got.push(ids))
    await new Promise((r) => setTimeout(r, 10))
    expect(got).toEqual([['3']])
    stop()
  })
  it('the real adapter refuses to run outside Discord (no frame_id) with a clear error', async () => {
    const err = await createDiscordSdk('123').init().catch((e) => e)
    expect(err).toBeInstanceOf(SdkError)
    expect(err.code).toBe('not_in_discord')
  })
  it('loadSdk uses the mock only when the build says so', async () => {
    const sdk = await loadSdk()                                     // vitest runs with VITE_MOCK_DISCORD unset
    await expect(sdk.init()).rejects.toBeInstanceOf(SdkError)
  })
})
