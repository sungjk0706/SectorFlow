import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { computeOrderBlockStatus } from '../../src/utils/order-block-status'
import type { UIState } from '../../src/stores/uiStore'
import type { AppSettings } from '../../src/types'

/**
 * 세션 9 — 주문 차단 UI 판정 통일 회귀 테스트.
 * buy-target.ts / sell-position.ts 양쪽이 computeOrderBlockStatus() 단일 SSOT를 사용하므로
 * 우선순위 8단계 + side별 텍스트 매핑 + side 불일치 예외를 고정한다 (P10/P21/P22).
 */

/** 테스트용 기본 UIState — 모든 차단 플래그 OFF */
function makeCleanUiState(): UIState {
  return {
    settings: null,
    status: null,
    sectorStatus: null,
    selectedSector: null,
    initialized: true,
    engineReady: true,
    avgAmtProgress: null,
    marketPhase: { krx: '장중', nxt: '장중', krx_alert: null, is_nxt_only: false },
    buyLimitStatus: { daily_buy_spent: 0 },
    wsSubscribeStatus: { index_subscribed: true, quote_subscribed: true },
    sectorScoresDelta: null,
    sectorScoresWaiting: false,
    sectorSummary: null,
    engineReloadComplete: true,
    receiveRate: null,
    indexData: null,
    circuitBreakerOpen: null,
    orderTimeBlocked: null,
    riskBlockStatus: null,
    realtimeLatencyExceeded: false,
    dailyBuyStateFailed: false,
    testCashFailed: null,
    positionBuildFailed: false,
    degradedMode: false,
  }
}

/** 테스트용 기본 AppSettings — 자동매매 ON, 시간대 통과 (09:00~15:20) */
function makeCleanSettings(): AppSettings {
  return {
    // 리스크 매니저 기본 — 차단 없음
    risk_manager_on: false,
    daily_loss_limit_on: false,
    daily_loss_limit: -500000,
    daily_loss_rate_limit_on: false,
    daily_loss_rate_limit: -5.0,
    risk_block_buy_on: false,
    risk_block_sell_on: false,
    consecutive_loss_limit_on: false,
    consecutive_loss_limit: 3,
    // 토글 — 자동매매 ON, 매수/매도 ON
    auto_buy_on: true,
    auto_sell_on: true,
    time_scheduler_on: true,
    // 시간 — 통과 범위 (실제 시간 체크는 toLocaleTimeString 기반이라 테스트는 mock)
    buy_time_start: '09:00',
    buy_time_end: '15:20',
    sell_time_start: '09:00',
    sell_time_end: '15:20',
  } as unknown as AppSettings
}

describe('computeOrderBlockStatus — 우선순위 8단계 (세션 9)', () => {
  let dateSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    // KST 10:00 — 시간대 통과 상태 고정
    dateSpy = vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('10:00')
  })

  afterEach(() => {
    dateSpy.mockRestore()
  })

  describe('1순위 — 서킷브레이커 (최우선, 양쪽 공통)', () => {
    it('buy: circuitBreakerOpen 시 다른 차단과 무관하게 서킷브레이커 표시', () => {
      const ui = makeCleanUiState()
      ui.circuitBreakerOpen = { message: '서킷브레이커 발동' }
      ui.realtimeLatencyExceeded = true  // 2순위도 켜져 있지만 1순위가 우선
      ui.riskBlockStatus = { side: 'buy', reason: '손실한도' }  // 3순위도 켜져 있지만 1순위가 우선
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 서킷브레이커')
    })

    it('sell: 동일하게 서킷브레이커 우선', () => {
      const ui = makeCleanUiState()
      ui.circuitBreakerOpen = { message: '서킷브레이커 발동' }
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 서킷브레이커')
    })
  })

  describe('2순위 — 실시간 지연 (양쪽 공통)', () => {
    it('buy: realtimeLatencyExceeded 시 서킷브레이커 없으면 실시간 지연 표시', () => {
      const ui = makeCleanUiState()
      ui.realtimeLatencyExceeded = true
      ui.riskBlockStatus = { side: 'buy', reason: '손실한도' }  // 3순위도 켜져 있지만 2순위 우선
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 실시간 지연')
    })

    it('sell: 동일하게 실시간 지연 우선 (리스크보다 상위)', () => {
      const ui = makeCleanUiState()
      ui.realtimeLatencyExceeded = true
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 실시간 지연')
    })
  })

  describe('3순위 — 리스크 차단 (side 일치 시에만)', () => {
    it('buy: riskBlockStatus.side=buy 시 buy 화면에 리스크 사유 표시', () => {
      const ui = makeCleanUiState()
      ui.riskBlockStatus = { side: 'buy', reason: '일일 손실한도 도달' }
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 리스크(일일 손실한도 도달)')
    })

    it('sell: riskBlockStatus.side=sell 시 sell 화면에 리스크 사유 표시', () => {
      const ui = makeCleanUiState()
      ui.riskBlockStatus = { side: 'sell', reason: '연속손실' }
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 리스크(연속손실)')
    })

    it('buy: riskBlockStatus.side=sell 시 buy 화면은 리스크 차단 안 함 (side 불일치 예외)', () => {
      const ui = makeCleanUiState()
      ui.riskBlockStatus = { side: 'sell', reason: '매도 전용 리스크' }
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매수 가능')
    })

    it('sell: riskBlockStatus.side=buy 시 sell 화면은 리스크 차단 안 함 (side 불일치 예외)', () => {
      const ui = makeCleanUiState()
      ui.riskBlockStatus = { side: 'buy', reason: '매수 전용 리스크' }
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매도 가능')
    })
  })

  describe('4순위 — 시간대 차단 (orderTimeBlocked, 양쪽 공통)', () => {
    it('buy: orderTimeBlocked 시 동시호가/장외 사유 표시', () => {
      const ui = makeCleanUiState()
      ui.orderTimeBlocked = { reason: '동시호가 시간대' }
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 동시호가 시간대')
    })

    it('sell: 동일하게 시간대 차단 사유 표시', () => {
      const ui = makeCleanUiState()
      ui.orderTimeBlocked = { reason: '장외 시간대' }
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 장외 시간대')
    })
  })

  describe('5순위 — 일일 매수 상태 오류 (buy 전용)', () => {
    it('buy: dailyBuyStateFailed 시 일일 상태 오류 표시', () => {
      const ui = makeCleanUiState()
      ui.dailyBuyStateFailed = true
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 일일 상태 오류')
    })

    it('sell: dailyBuyStateFailed 시 sell 화면은 차단 안 함 (buy 전용 예외)', () => {
      const ui = makeCleanUiState()
      ui.dailyBuyStateFailed = true
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매도 가능')
    })
  })

  describe('6순위 — 자동매매 OFF (time_scheduler_on=false, 양쪽 공통)', () => {
    it('buy: time_scheduler_on=false 시 자동매매 OFF 표시', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.time_scheduler_on = false
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 자동매매 OFF')
    })

    it('sell: 동일하게 자동매매 OFF 표시', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.time_scheduler_on = false
      const r = computeOrderBlockStatus('sell', ui, s)
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 자동매매 OFF')
    })

    it('settings=null 시 자동매매 OFF로 간주 (P21 — 설정 미로드 투명성)', () => {
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('buy', ui, null)
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 자동매매 OFF')
    })
  })

  describe('7순위 — 자동매수/자동매도 OFF (side별 플래그)', () => {
    it('buy: auto_buy_on=false 시 자동매수 OFF 표시', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.auto_buy_on = false
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 자동매수 OFF')
    })

    it('sell: auto_sell_on=false 시 자동매도 OFF 표시', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.auto_sell_on = false
      const r = computeOrderBlockStatus('sell', ui, s)
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 자동매도 OFF')
    })

    it('buy: auto_sell_on=false는 buy 화면에 영향 없음 (side 분리)', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.auto_sell_on = false
      s.auto_buy_on = true
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매수 가능')
    })
  })

  describe('8순위 — 시간대 외 (작동 시간 범위 벗어남)', () => {
    it('buy: nowKst < buy_time_start 시 매수 시간대 외', () => {
      dateSpy.mockReturnValue('08:30')  // 개시 전
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 매수 시간대 외')
    })

    it('buy: nowKst > buy_time_end 시 매수 시간대 외', () => {
      dateSpy.mockReturnValue('15:30')  // 마감 후
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 매수 시간대 외')
    })

    it('sell: nowKst < sell_time_start 시 매도 시간대 외', () => {
      dateSpy.mockReturnValue('08:30')
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 매도 시간대 외')
    })

    it('sell: nowKst > sell_time_end 시 매도 시간대 외', () => {
      dateSpy.mockReturnValue('15:30')
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('sell', ui, makeCleanSettings())
      expect(r.blocked).toBe(true)
      expect(r.text).toBe('차단: 매도 시간대 외')
    })

    it('경계값: start와 동일 시간은 통과 (>=start)', () => {
      dateSpy.mockReturnValue('09:00')
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매수 가능')
    })

    it('경계값: end와 동일 시간은 통과 (<=end)', () => {
      dateSpy.mockReturnValue('15:20')
      const ui = makeCleanUiState()
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매수 가능')
    })
  })

  describe('정상 경로 — 모든 차단 조건 미충족', () => {
    it('buy: 매수 가능', () => {
      const r = computeOrderBlockStatus('buy', makeCleanUiState(), makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매수 가능')
    })

    it('sell: 매도 가능', () => {
      const r = computeOrderBlockStatus('sell', makeCleanUiState(), makeCleanSettings())
      expect(r.blocked).toBe(false)
      expect(r.text).toBe('매도 가능')
    })
  })

  describe('우선순위 교차 검증 — 상위 차단이 하위 무시', () => {
    it('1순위(서킷) > 6순위(자동매매 OFF): 자동매매 OFF여도 서킷브레이커 우선', () => {
      const ui = makeCleanUiState()
      ui.circuitBreakerOpen = { message: '발동' }
      const s = makeCleanSettings()
      s.time_scheduler_on = false
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.text).toBe('차단: 서킷브레이커')
    })

    it('4순위(시간대) > 5순위(일일상태오류): 시간대 차단이 일일 상태 오류보다 우선', () => {
      const ui = makeCleanUiState()
      ui.orderTimeBlocked = { reason: '동시호가' }
      ui.dailyBuyStateFailed = true
      const r = computeOrderBlockStatus('buy', ui, makeCleanSettings())
      expect(r.text).toBe('차단: 동시호가')
    })

    it('5순위(일일상태오류) > 6순위(자동매매 OFF): buy 전용 5순위가 자동매매 OFF보다 우선', () => {
      const ui = makeCleanUiState()
      ui.dailyBuyStateFailed = true
      const s = makeCleanSettings()
      s.time_scheduler_on = false
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.text).toBe('차단: 일일 상태 오류')
    })

    it('6순위(자동매매 OFF) > 7순위(자동매수 OFF): 스케줄러 OFF가 side 플래그보다 우선', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.time_scheduler_on = false
      s.auto_buy_on = false
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.text).toBe('차단: 자동매매 OFF')
    })

    it('7순위(자동매수 OFF) > 8순위(시간대 외): side 플래그가 시간대 체크보다 우선', () => {
      dateSpy.mockReturnValue('23:00')  // 시간대 외
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.auto_buy_on = false
      const r = computeOrderBlockStatus('buy', ui, s)
      expect(r.text).toBe('차단: 자동매수 OFF')
    })
  })

  describe('side별 텍스트 매핑 일관성 (P23)', () => {
    it('정상 텍스트: buy=매수 가능, sell=매도 가능', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      expect(computeOrderBlockStatus('buy', ui, s).text).toBe('매수 가능')
      expect(computeOrderBlockStatus('sell', ui, s).text).toBe('매도 가능')
    })

    it('자동 OFF 텍스트: buy=자동매수 OFF, sell=자동매도 OFF', () => {
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      s.auto_buy_on = false
      s.auto_sell_on = false
      expect(computeOrderBlockStatus('buy', ui, s).text).toBe('차단: 자동매수 OFF')
      expect(computeOrderBlockStatus('sell', ui, s).text).toBe('차단: 자동매도 OFF')
    })

    it('시간대 외 텍스트: buy=매수 시간대 외, sell=매도 시간대 외', () => {
      dateSpy.mockReturnValue('23:00')
      const ui = makeCleanUiState()
      const s = makeCleanSettings()
      expect(computeOrderBlockStatus('buy', ui, s).text).toBe('차단: 매수 시간대 외')
      expect(computeOrderBlockStatus('sell', ui, s).text).toBe('차단: 매도 시간대 외')
    })

    it('공통 차단 텍스트는 side 무관 동일: 서킷브레이커/실시간 지연/자동매매 OFF', () => {
      const ui1 = makeCleanUiState()
      ui1.circuitBreakerOpen = { message: '발동' }
      expect(computeOrderBlockStatus('buy', ui1, makeCleanSettings()).text)
        .toBe(computeOrderBlockStatus('sell', ui1, makeCleanSettings()).text)

      const ui2 = makeCleanUiState()
      ui2.realtimeLatencyExceeded = true
      expect(computeOrderBlockStatus('buy', ui2, makeCleanSettings()).text)
        .toBe(computeOrderBlockStatus('sell', ui2, makeCleanSettings()).text)

      const s = makeCleanSettings()
      s.time_scheduler_on = false
      expect(computeOrderBlockStatus('buy', makeCleanUiState(), s).text)
        .toBe(computeOrderBlockStatus('sell', makeCleanUiState(), s).text)
    })
  })
})
