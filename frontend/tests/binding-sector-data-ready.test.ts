import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { bindWSToStore } from '../src/binding'
import { uiStore } from '../src/stores/uiStore'
import type { SectorScoreRow } from '../src/types'

/**
 * 세션 4 — binding.ts sector-scores 이벤트 → sectorDataReady 전환 단위 테스트.
 * 백엔드 수신율 임계값 게이트 결과를 프론트에서 재계산 없이 그대로 전달하는지 검증 (P10 SSOT, P21 투명성).
 * - WS 구독 시작 시 sectorDataReady=false (초기값)
 * - sector-scores status.waiting===true → sectorDataReady=false (대기)
 * - sector-scores status.waiting!==true → sectorDataReady=true (준비 완료)
 */

/** 최소 WSClient mock — onEvent 핸들러를 캡처하여 테스트에서 직접 호출 */
function createMockWSClient() {
  const handlers = new Map<string, ((data: unknown) => void)[]>()
  return {
    setConnectionCallbacks: vi.fn(),
    onEvent: vi.fn((type: string, handler: (data: unknown) => void) => {
      const list = handlers.get(type) ?? []
      list.push(handler)
      handlers.set(type, list)
    }),
    send: vi.fn(),
    /** 테스트에서 이벤트 발생 — 등록된 핸들러 호출 */
    emit(type: string, data: unknown) {
      const list = handlers.get(type) ?? []
      for (const h of list) h(data)
    },
  }
}

describe('binding — sector-scores → sectorDataReady 전환', () => {
  let prices: ReturnType<typeof createMockWSClient>
  let settings: ReturnType<typeof createMockWSClient>
  let orders: ReturnType<typeof createMockWSClient>

  beforeEach(() => {
    // M-02: sector-scores 핸들러가 rAF로 갱신을 미루므로 테스트에서는 동기 실행하도록 mock.
    // 반환값으로 null을 주어 rAF ID 체크가 다음 emit을 차단하지 않도록 함
    // (동기 실행 시 반환값이 콜백 내부의 null 설정을 덮어쓰는 문제 방지).
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return null as unknown as number
    })
    vi.stubGlobal('cancelAnimationFrame', () => {})
    // uiStore 초기 상태로 리셋 (sectorDataReady=false)
    uiStore.setState({ sectorDataReady: false, sectorScoresWaiting: false, sectorScoresDelta: null })
    prices = createMockWSClient()
    settings = createMockWSClient()
    orders = createMockWSClient()
    bindWSToStore(prices as any, settings as any, orders as any)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('초기 sectorDataReady 는 false 이다 (sectorScoresWaiting=false 기본값만으로 준비 완료 판단 금지)', () => {
    expect(uiStore.getState().sectorDataReady).toBe(false)
  })

  it('sector-scores status.waiting===true 수신 시 sectorDataReady=false (수신 대기)', () => {
    prices.emit('sector-scores', {
      scores: [] as SectorScoreRow[],
      status: { waiting: true },
    })
    expect(uiStore.getState().sectorScoresWaiting).toBe(true)
    expect(uiStore.getState().sectorDataReady).toBe(false)
  })

  it('sector-scores status.waiting!==true 수신 시 sectorDataReady=true (임계값 통과·준비 완료)', () => {
    // 먼저 대기 상태로 전환
    prices.emit('sector-scores', { scores: [], status: { waiting: true } })
    expect(uiStore.getState().sectorDataReady).toBe(false)
    // 정상 데이터 이벤트 — waiting 없음
    prices.emit('sector-scores', {
      scores: [{ sector: '반도체', score: 85 } as unknown as SectorScoreRow],
      status: { waiting: false },
    })
    expect(uiStore.getState().sectorScoresWaiting).toBe(false)
    expect(uiStore.getState().sectorDataReady).toBe(true)
  })

  it('status 필드 자체가 없는 sector-scores 도 준비 완료로 전환한다 (waiting!==true)', () => {
    prices.emit('sector-scores', { scores: [] })
    expect(uiStore.getState().sectorDataReady).toBe(true)
    expect(uiStore.getState().sectorScoresWaiting).toBe(false)
  })

  it('대기 → 준비 → 다시 대기 전환 시 sectorDataReady 도 false 로 되돌아간다', () => {
    prices.emit('sector-scores', { scores: [], status: { waiting: true } })
    expect(uiStore.getState().sectorDataReady).toBe(false)
    prices.emit('sector-scores', { scores: [], status: { waiting: false } })
    expect(uiStore.getState().sectorDataReady).toBe(true)
    prices.emit('sector-scores', { scores: [], status: { waiting: true } })
    expect(uiStore.getState().sectorDataReady).toBe(false)
  })
})
