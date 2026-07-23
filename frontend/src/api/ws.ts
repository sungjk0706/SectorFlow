// frontend/src/api/ws.ts — 다중 채널 WebSocket 클라이언트 (prices, settings, orders)

import { event } from '../types/event'

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

/** Protobuf 바이너리 스트림 디코딩 */
function decodeProtobufEvents(buffer: ArrayBuffer): { event: string; data: unknown }[] {
  const uint8Array = new Uint8Array(buffer)
  const events: { event: string; data: unknown }[] = []
  let offset = 0

  while (offset < uint8Array.length) {
    // 길이 접두사 (4 bytes)
    if (offset + 4 > uint8Array.length) break
    const length = new DataView(uint8Array.buffer, offset, 4).getUint32(0, false)
    offset += 4

    // 이벤트 데이터
    if (offset + length > uint8Array.length) break
    const eventBytes = uint8Array.slice(offset, offset + length)
    offset += length

    // Protobuf 디코딩
    try {
      const protoEvent = event.Event.deserializeBinary(eventBytes)
      const data: Record<string, unknown> = {}

      // data 필드 변환 (Map -> Object)
      if (protoEvent.data) {
        protoEvent.data.forEach((value, key) => {
          data[key] = value
        })
      }

      // 종목코드 추가
      if (data['code']) {
        events.push({ event: protoEvent.type, data })
      }
    } catch (err) {
      console.error('[WS] Protobuf 디코딩 실패:', err)
    }
  }

  return events
}

type EventHandler<T = unknown> = (data: T) => void

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
  private channel: 'prices' | 'settings' | 'orders'

  constructor(channel: 'prices' | 'settings' | 'orders' = 'prices') {
    this.channel = channel
  }

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
    const url = `${proto}//${location.host}/api/ws/${this.channel}?token=${encodeURIComponent(this.token)}`
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    this.ws = ws

    ws.onopen = () => {
      this.reconnectDelay = 1000
      this._startPing()
      if (this._onConnected) this._onConnected()
    }

    ws.onmessage = (e: MessageEvent) => {
      if (e.data instanceof ArrayBuffer) {
        // binary frame: Protobuf decode → key expand
        this._handleBinaryFrame(e.data)
      } else {
        // text frame: JSON parse → key expand (real-data만)
        this._handleTextFrame(e.data as string)
      }
    }

    ws.onerror = (e) => {
      console.error('[WS] 오류:', e)
    }

    ws.onclose = (e: CloseEvent) => {
      if (this.ws === ws) this.ws = null
      this._stopPing()
      if (this._onDisconnected) this._onDisconnected()
      // 1008 = 서버 인증 거부
      if (e.code === 1008) {
        console.error('[WS] 인증 거부 (code 1008) — 연결 종료')
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
      // Protobuf 디코딩 (바이너리 스트림)
      const events = decodeProtobufEvents(buffer)
      for (const evt of events) {
        try {
          this._dispatchMessage(evt)
        } catch (err) {
          console.error('[WS] binary frame event 디스패치 실패:', err)
        }
      }
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
    if (list) {
      for (const h of list) {
        try {
          h(data)
        } catch (err) {
          console.error(`[WS] 핸들러 실행 실패 (event=${eventType}):`, err)
        }
      }
    }
  }

  onEvent<T = unknown>(type: string, handler: EventHandler<T>): void {
    const list = this.handlers.get(type) || []
    list.push(handler as EventHandler)
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

export const wsClient = new WSClient('prices')
export const wsSettingsClient = new WSClient('settings')
export const wsOrdersClient = new WSClient('orders')

/** 현재 활성 페이지 추적 — WS (재)연결 시 재전송용 */
let _currentPage: string | null = null

/** 현재 페이지 활성 알림 → 백엔드 per-client 필터링 */
export function notifyPageActive(page: string): void {
  _currentPage = page
  wsClient.send(JSON.stringify({ type: 'page-active', page }))
  wsSettingsClient.send(JSON.stringify({ type: 'page-active', page }))
}

/** 현재 페이지 비활성 알림 → 백엔드 per-client 필터링 해제 */
export function notifyPageInactive(page: string): void {
  if (_currentPage === page) _currentPage = null
  wsClient.send(JSON.stringify({ type: 'page-inactive', page }))
  wsSettingsClient.send(JSON.stringify({ type: 'page-inactive', page }))
}

/** 현재 활성 페이지 반환 — WS (재)연결 시 page-active 재전송용 */
export function getCurrentPage(): string | null {
  return _currentPage
}

/** FID 구독 설정 → 백엔드 per-client FID 필터링 */
export function subscribeFids(fids: string[]): void {
  wsClient.send(JSON.stringify({ type: 'subscribe-fids', fids }))
}
