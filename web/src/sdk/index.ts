import type { ActivitySdk } from './types'

export type { ActivitySdk, Session } from './types'
export { SdkError } from './types'

/** Picks the adapter. The mock branch is a compile-time constant, so production builds drop it entirely. */
export async function loadSdk(): Promise<ActivitySdk> {
  if (import.meta.env.VITE_MOCK_DISCORD === '1') {
    const { createMockSdk } = await import('./mock')
    return createMockSdk()
  }
  const { createDiscordSdk } = await import('./discord')
  return createDiscordSdk(import.meta.env.VITE_DISCORD_CLIENT_ID ?? '')
}
