import { DiscordSDK } from '@discord/embedded-app-sdk'
import type { ActivitySdk, Session } from './types'
import { SdkError } from './types'

/** Real adapter around Discord's Embedded App SDK. Verify the calls against Discord's current Activity docs. */
export function createDiscordSdk(clientId: string): ActivitySdk {
  let sdk: DiscordSDK | null = null
  return {
    async init(): Promise<Session> {
      // Discord opens an Activity with a frame_id; without one we are in a plain browser tab.
      if (!new URLSearchParams(window.location.search).has('frame_id')) {
        throw new SdkError('not_in_discord', 'Bamboozled has to be opened from inside Discord.')
      }
      sdk = new DiscordSDK(clientId)
      await sdk.ready()
      const { code } = await sdk.commands.authorize({
        client_id: clientId, response_type: 'code', state: '', prompt: 'none', scope: ['identify'],
      })
      const res = await fetch('/api/oauth/token', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
      })
      if (!res.ok) throw new SdkError('sign_in_failed', 'Discord sign-in did not complete. Please try again.')
      const { access_token } = (await res.json()) as { access_token: string }
      const auth = await sdk.commands.authenticate({ access_token })
      if (!auth) throw new SdkError('sign_in_failed', 'Discord did not confirm the sign-in.')
      return {
        accessToken: access_token, instanceId: sdk.instanceId, userId: auth.user.id,
        name: auth.user.global_name ?? auth.user.username,
      }
    },
    onParticipants(cb) {
      const handler = (e: { participants: { id: string }[] }) => cb(e.participants.map((p) => p.id))
      void sdk?.subscribe('ACTIVITY_INSTANCE_PARTICIPANTS_UPDATE', handler)
      return () => void sdk?.unsubscribe('ACTIVITY_INSTANCE_PARTICIPANTS_UPDATE', handler)
    },
  }
}
