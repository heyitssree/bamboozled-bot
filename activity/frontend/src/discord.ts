import { DiscordSDK } from '@discord/embedded-app-sdk'

export const discordSdk = new DiscordSDK(import.meta.env.VITE_DISCORD_CLIENT_ID as string)

export interface DiscordUser {
  id: string
  username: string
  avatar: string | null
  discriminator: string
}

export async function setupDiscord(): Promise<DiscordUser> {
  await discordSdk.ready()

  const { code } = await discordSdk.commands.authorize({
    client_id: import.meta.env.VITE_DISCORD_CLIENT_ID as string,
    response_type: 'code',
    state: '',
    prompt: 'none',
    scope: ['identify', 'guilds'],
  })

  const response = await fetch('/api/oauth/callback', {
    method: 'POST',
    body: JSON.stringify({ code }),
    headers: { 'Content-Type': 'application/json' },
  })

  if (!response.ok) {
    throw new Error('OAuth token exchange failed')
  }

  const { access_token } = (await response.json()) as { access_token: string }
  const auth = await discordSdk.commands.authenticate({ access_token })

  return auth.user as DiscordUser
}

export function getAvatarUrl(userId: string, avatarHash: string | null): string {
  if (!avatarHash) {
    const defaultIndex = parseInt(userId) % 5
    return `https://cdn.discordapp.com/embed/avatars/${defaultIndex}.png`
  }
  return `https://cdn.discordapp.com/avatars/${userId}/${avatarHash}.png?size=128`
}
