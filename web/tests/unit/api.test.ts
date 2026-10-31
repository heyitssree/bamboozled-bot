import { afterEach, describe, expect, it, vi } from 'vitest'
import { postPrivacy } from '../../src/app/api'

vi.mock('../../src/app/connection', () => ({ authHeaders: () => ({ Authorization: 'Bearer t' }) }))

const answer = (status: number) => vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status })))
afterEach(() => vi.unstubAllGlobals())

describe('postPrivacy', () => {
  it.each([
    [200, 'done'], [409, 'in_game'], [429, 'cooldown'], [404, 'unavailable'], [405, 'unavailable'], [503, 'unavailable'], [500, 'failed'],
  ])('turns HTTP %i into %s', async (status, outcome) => {
    answer(status)
    expect(await postPrivacy('opt_out')).toBe(outcome)
  })
  it('sends the sign-in with the request, to the right route', async () => {
    answer(200)
    await postPrivacy('opt_in')
    expect(fetch).toHaveBeenCalledWith('/api/privacy/opt_in', { method: 'POST', headers: { Authorization: 'Bearer t' } })
  })
  it('a network failure is a failure, not a crash', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    expect(await postPrivacy('opt_out')).toBe('failed')
  })
})
