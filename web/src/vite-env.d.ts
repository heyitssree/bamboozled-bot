/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_DISCORD_CLIENT_ID?: string
  readonly VITE_MOCK_DISCORD?: string
}

declare const __APP_VERSION__: string
