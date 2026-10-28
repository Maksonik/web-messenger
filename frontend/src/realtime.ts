import { getAccessToken, refreshSession } from './api'
import type { ClientEvent, ServerEvent } from './types'

export type ConnectionStatus = 'connecting' | 'online' | 'offline'

const CLOSE_UNAUTHORIZED = 4401
const PING_INTERVAL_MS = 25_000
const MAX_BACKOFF_MS = 15_000

/**
 * One WebSocket for all chats. Reconnects with exponential backoff; when the server
 * rejects an expired access token it refreshes the session first.
 */
export class RealtimeClient {
  private socket: WebSocket | null = null
  private authenticated = false
  private stopped = false
  private attempt = 0
  private reconnectTimer: number | undefined
  private pingTimer: number | undefined
  private readonly listeners = new Set<(event: ServerEvent) => void>()
  private readonly statusListeners = new Set<(status: ConnectionStatus) => void>()
  private readonly onUnauthorized: () => void

  constructor(onUnauthorized: () => void) {
    this.onUnauthorized = onUnauthorized
  }

  start(): void {
    this.stopped = false
    this.connect()
  }

  stop(): void {
    this.stopped = true
    window.clearTimeout(this.reconnectTimer)
    window.clearInterval(this.pingTimer)
    this.socket?.close()
    this.socket = null
  }

  subscribe(listener: (event: ServerEvent) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  onStatus(listener: (status: ConnectionStatus) => void): () => void {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  /** Returns false when offline; the caller keeps the event and resends after reconnect. */
  send(event: ClientEvent): boolean {
    if (!this.authenticated || this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify(event))
    return true
  }

  private connect(): void {
    this.setStatus('connecting')
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${protocol}://${location.host}/api/ws`)
    this.socket = socket

    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'auth', token: getAccessToken() ?? '' }))
    }

    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as ServerEvent
      if (event.type === 'auth.ok') {
        this.authenticated = true
        this.attempt = 0
        this.setStatus('online')
        this.pingTimer = window.setInterval(() => this.send({ type: 'ping' }), PING_INTERVAL_MS)
      }
      this.listeners.forEach((listener) => listener(event))
    }

    socket.onclose = (close) => {
      window.clearInterval(this.pingTimer)
      if (this.socket !== socket) return
      this.socket = null
      this.authenticated = false
      this.setStatus('offline')
      if (this.stopped) return
      this.attempt += 1
      if (close.code === CLOSE_UNAUTHORIZED) {
        void this.refreshAndReconnect()
      } else {
        this.scheduleReconnect()
      }
    }
  }

  private async refreshAndReconnect(): Promise<void> {
    try {
      if (!(await refreshSession())) {
        this.onUnauthorized()
        return
      }
    } catch {
      // Network error: just retry later.
    }
    this.scheduleReconnect()
  }

  private scheduleReconnect(): void {
    if (this.stopped) return
    const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** (this.attempt - 1))
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay)
  }

  private setStatus(status: ConnectionStatus): void {
    this.statusListeners.forEach((listener) => listener(status))
  }
}
