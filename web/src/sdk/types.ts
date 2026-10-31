/** What the app needs from Discord. Only sdk/discord.ts and sdk/mock.ts implement it; nothing else imports the SDK. */
export interface Session {
  accessToken: string
  instanceId: string
  userId: string
  name: string
}

export interface ActivitySdk {
  /** Resolve once signed in. Rejects with SdkError('not_in_discord') when opened outside Discord. */
  init(): Promise<Session>
  /** Participants of the activity instance as Discord sees them (decoration only; the server's list is authoritative). */
  onParticipants(cb: (ids: string[]) => void): () => void
}

export class SdkError extends Error {
  constructor(readonly code: 'not_in_discord' | 'sign_in_failed', message: string) {
    super(message)
  }
}
