// frontend/src/api/ws.ts — 시세 전용 WebSocket 클라이언트

import { inflate } from 'pako'
import { forceLogout } from './client'
import { setBackfilling } from '../stores/appStore'

// key expansion: 백엔드 key shortening 복원
const KEY_MAP: Record<string, string> = { t: 'type', i: 'item', v: 'values' }

/** 단축 키를 원래 키로 복원 */
function expandKeys(data: Record<string, unknown>): Record<string, unknown> {
  const expanded: Record<string, unknown> = {}
  for (const key of Object.keys(data)) {
    const fullKey = KEY_MAP[key] || key
    expanded[fullKey] = data[key]
  }
  return expanded
}

type EventHandler<T = any> = (data: T) => void

export class WSClient {
  private ws: WebSocket | null = null
  private handlers: Map<string, EventHandler[]> = new Map()
  private reconnectDelay = 1000
  private maxReconnectDelay = 30000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private consecutivePingFailures: number = 0
  private _onConnected: (() => void) | null = null
  private _onDisconnected: (() => void) | null = null
  private token: string | null = null
  private _hasConnectedOnce: boolean = false

  setConnectionCallbacks(onConnected: () => void, onDisconnected: () => void): void {
    this._onConnected = onConnected
    this._onDisconnected = onDisconnected
  }

  connect(token: string): void {
    this.token = token
    this.reconnectDelay = 1000
    this._connect()
  }

  private _connect(): void {
    if (!this.token) return
    this.disconnect()
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${location.host}/api/ws/prices?token=${encodeURIComponent(this.token)}`
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    this.ws = ws

    ws.onopen = () => {
      this.reconnectDelay = 1000
      this._startPing()
      if (this._hasConnectedOnce) {
        // 재연결 성공 → backfilling 플래그 설정, 서버 initial-snapshot 대기
        setBackfilling(true)
      }
      this._hasConnectedOnce = true
      if (this._onConnected) this._onConnected()
    }

    ws.onmessage = (e: MessageEvent) => {
      if (e.data instanceof ArrayBuffer) {
        // binary frame: zlib decompress → JSON parse → key expand
        this._handleBinaryFrame(e.data)
      } else {
        // text frame: JSON parse → key expand (real-data만)
        this._handleTextFrame(e.data as string)
      }
    }

    ws.onerror = () => {}

    ws.onclose = (e: CloseEvent) => {
      if (this.ws === ws) this.ws = null
      this._stopPing()
      if (this._onDisconnected) this._onDisconnected()
      // 1008 = 서버 인증 거부 → 로그아웃
      if (e.code === 1008) {
        forceLogout()
        return
      }
      // 나머지 (1006 포함) → 지수 백오프 재연결
      this._scheduleReconnect()
    }
  }

  private _scheduleReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = setTimeout(() => this._connect(), this.reconnectDelay)
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay)
  }

  private _startPing(): void {
    this._stopPing()
    this.consecutivePingFailures = 0
    this.pingTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      try {
        this.ws.send(JSON.stringify({ type: 'ping' }))
        this.consecutivePingFailures = 0
      } catch {
        this.consecutivePingFailures++
        if (this.consecutivePingFailures >= 2) {
          this._stopPing()
          if (this.ws) this.ws.close()
          this._scheduleReconnect()
        }
      }
    }, 25_000)
  }

  private _stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  private _handleBinaryFrame(buffer: ArrayBuffer): void {
    try {
      const decompressed = inflate(new Uint8Array(buffer), { to: 'string' })
      const msg = JSON.parse(decompressed)
      this._dispatchMessage(msg)
    } catch (err) {
      console.error('[WS] binary frame 디코딩 실패:', err)
    }
  }

  private _handleTextFrame(text: string): void {
    try {
      const msg = JSON.parse(text)
      this._dispatchMessage(msg)
    } catch (err) {
      console.error('[WS] 파싱 실패:', err)
    }
  }

  private _dispatchMessage(msg: { event: string; data: unknown }): void {
    const eventType = msg.event as string
    let data = msg.data
    // real-data 이벤트의 단축 키 복원
    if (eventType === 'real-data' && data && typeof data === 'object') {
      data = expandKeys(data as Record<string, unknown>)
    }
    const list = this.handlers.get(eventType)
    if (list) list.forEach(h => h(data))
  }

  onEvent<T = any>(type: string, handler: EventHandler<T>): void {
    const list = (this.handlers.get(type) || []) as EventHandler<any>[]
    list.push(handler)
    this.handlers.set(type, list)
  }

  offEvent(type: string, handler: EventHandler): void {
    const list = this.handlers.get(type)
    if (!list) return
    const idx = list.indexOf(handler)
    if (idx !== -1) list.splice(idx, 1)
  }

  send(data: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data)
    }
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  disconnect(): void {
    this._stopPing()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }
}

export const wsClient = new WSClient()

/** 현재 페이지 활성 알림 → 백엔드 per-client 필터링 */
export function notifyPageActive(page: string): void {
  wsClient.send(JSON.stringify({ type: 'page-active', page }))
}

/** 현재 페이지 비활성 알림 → 백엔드 per-client 필터링 해제 */
export function notifyPageInactive(page: string): void {
  wsClient.send(JSON.stringify({ type: 'page-inactive', page }))
}
