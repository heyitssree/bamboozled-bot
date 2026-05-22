import { useEffect, useRef } from 'react'
import { audio } from '../audio/AudioManager'
import { useGameStore } from '../store/gameStore'
import type { ServerMessage } from '../types'

const MAX_RETRIES = 5
const RETRY_DELAYS = [1000, 2000, 4000, 8000, 16000]

export function useWebSocket(sessionId: string, playerId: string, username: string, avatarUrl: string) {
  const setWs = useGameStore((s) => s.setWs)
  const applyStateUpdate = useGameStore((s) => s.applyStateUpdate)
  const setGameOver = useGameStore((s) => s.setGameOver)
  const setConnected = useGameStore((s) => s.setConnected)
  const retryCountRef = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const unmountedRef = useRef(false)

  useEffect(() => {
    unmountedRef.current = false

    function connect() {
      if (unmountedRef.current) return

      const backendUrl = (import.meta.env.VITE_BACKEND_URL as string) || 'ws://localhost:8000'
      const wsUrl = `${backendUrl}/ws/${sessionId}/${playerId}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      setWs(ws)

      ws.onopen = () => {
        retryCountRef.current = 0
        setConnected(true)
        ws.send(
          JSON.stringify({
            type: 'PLAYER_JOIN',
            username,
            avatar_url: avatarUrl,
          }),
        )
      }

      ws.onmessage = (event: MessageEvent<string>) => {
        let msg: ServerMessage
        try {
          msg = JSON.parse(event.data) as ServerMessage
        } catch {
          return
        }

        if (msg.type === 'STATE_UPDATE') {
          applyStateUpdate(msg.state)
        } else if (msg.type === 'SOUND_CUE') {
          audio.play(msg.sound).catch(() => undefined)
        } else if (msg.type === 'GAME_OVER') {
          applyStateUpdate(msg.state)
          setGameOver(msg.results, msg.boli_awards, msg.state)
        }
      }

      ws.onclose = () => {
        setConnected(false)
        if (!unmountedRef.current && retryCountRef.current < MAX_RETRIES) {
          const delay = RETRY_DELAYS[retryCountRef.current]
          retryCountRef.current += 1
          setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      unmountedRef.current = true
      wsRef.current?.close()
    }
  }, [sessionId, playerId]) // eslint-disable-line react-hooks/exhaustive-deps
}
