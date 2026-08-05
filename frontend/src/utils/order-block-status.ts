/**
 * 주문 차단 상태 판정 — 매수/매도 공통 게이트 집계 (P21 사용자 투명성).
 *
 * buy-target.ts / sell-position.ts 상단 상태 배지의 판정 로직을 단일 함수로 추출 (P10 SSOT).
 * 우선순위: 서킷브레이커 > 실시간 지연(공통) > 리스크(side) > 시간대 차단 > 일일 매수 상태 오류(매수) > 자동매매 OFF > 자동매수/매도 OFF > 시간대 외
 * 데이터 소스: 기존 uiStore 상태 + globalSettingsManager (P10 SSOT — 신규 데이터 없음)
 *
 * DOM 렌더링은 호출부 updateBadge() 담당 → 본 함수는 판정 결과만 반환 (관심사 분리, P24 단순성).
 * P23(일관성) + P24(단순성) + P10(SSOT) 준수.
 */

import type { UIState } from '../stores/uiStore'
import type { AppSettings } from '../types'

type OrderSide = 'buy' | 'sell'

interface OrderBlockStatus {
  /** 배지에 표시할 텍스트 ('매수 가능' | '차단: ...' | 'NXT만 가능' | '거래 시간 외' | '휴장일 — 매수/매도 중지') */
  text: string
  /** 차단 여부 (true=위험/강제 차단, false=정상 또는 정보 상태) */
  blocked: boolean
  /** 매수 가능한 시장이 남아 있는 부분 차단 여부 */
  partial?: boolean
  /** 휴장일 여부 — 헤더 marketPhase.krx/nxt == '휴장일' 시 true.
   *  위험(서킷브레이커/리스크)이 아니라 정보 상태이므로 회색 표시를 위해 호출부에서 사용 (P21/P23). */
  holiday?: boolean
}

/** side별 텍스트 매핑 (P10 SSOT — 단일 테이블에서 관리) */
const SIDE_TEXT: Record<OrderSide, {
  ok: string
  autoOff: string
  holiday: string
  outOfTime: (start: string, end: string) => string
  autoFlag: keyof AppSettings
  timeStart: keyof AppSettings
  timeEnd: keyof AppSettings
}> = {
  buy: {
    ok: '매수 가능',
    autoOff: '차단: 자동매수 OFF',
    holiday: '휴장일 — 매수 중지',
    outOfTime: (start, end) => `차단: 자동매수 시간 외 (${start}~${end})`,
    autoFlag: 'auto_buy_on',
    timeStart: 'buy_time_start',
    timeEnd: 'buy_time_end',
  },
  sell: {
    ok: '매도 가능',
    autoOff: '차단: 자동매도 OFF',
    holiday: '휴장일 — 매도 중지',
    outOfTime: (start, end) => `차단: 자동매도 시간 외 (${start}~${end})`,
    autoFlag: 'auto_sell_on',
    timeStart: 'sell_time_start',
    timeEnd: 'sell_time_end',
  },
}

/**
 * 매수/매도 작동 시간 창 판정 (P10 SSOT — 백엔드 auto_trading_effective._in_time_range와 동일 로직).
 * 헤더 칩 활성화와 주문 차단 배지 양쪽에서 공유 (P23 일관성).
 * @returns 현재 KST 시각이 [start, end] 구간 내이면 true, 외면 false
 */
export function isInTradeTimeWindow(settings: AppSettings, side: OrderSide): boolean {
  const t = SIDE_TEXT[side]
  const nowKst = new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit' })
  const start = String(settings[t.timeStart] ?? '09:00').slice(0, 5)
  const end = String(settings[t.timeEnd] ?? '15:20').slice(0, 5)
  return nowKst >= start && nowKst <= end
}

/**
 * 주문 차단 상태 판정.
 * @param side 'buy' | 'sell'
 * @param uiState uiStore 현재 상태
 * @param settings globalSettingsManager 설정 (null 허용 — 자동매매 OFF로 간주)
 */
export function computeOrderBlockStatus(
  side: OrderSide,
  uiState: UIState,
  settings: AppSettings | null,
): OrderBlockStatus {
  const t = SIDE_TEXT[side]

  // 휴장일 최우선 — 장 자체가 열리지 않으므로 매수/매도 모두 의미 없음.
  // 헤더 칩이 판단에 사용하는 동일 SSOT(uiState.marketPhase) 참조 (P10).
  // 위험 상태가 아니라 정보 상태이므로 holiday 플래그로 호출부에서 회색 표시 (P21/P23).
  const phase = uiState.marketPhase
  if (phase && (phase.krx === '휴장일' || phase.nxt === '휴장일')) {
    return { text: t.holiday, blocked: true, holiday: true }
  }

  if (uiState.circuitBreakerOpen) {
    return { text: '차단: 서킷브레이커', blocked: true }
  }
  if (uiState.realtimeLatencyExceeded) {
    return { text: '차단: 실시간 지연', blocked: true }
  }
  if (uiState.riskBlockStatus && uiState.riskBlockStatus.side === side) {
    return {
      text: `차단: 리스크(${uiState.riskBlockStatus.reason})`,
      blocked: true,
      partial: side === 'buy' && uiState.riskBlockStatus.partial === true,
    }
  }
  if (uiState.orderTimeBlocked) {
    // 시간대 상태는 "거래 시간이 아님"이라는 사실 알림 — 위험/강제 차단 아님 (P21 투명성).
    // 우선순위는 유지하되 blocked=false (정보 표시) — 서킷브레이커/리스크가 먼저 표시되어야 함.
    return { text: uiState.orderTimeBlocked.reason, blocked: false }
  }
  if (side === 'buy' && uiState.dailyBuyStateFailed) {
    return { text: '차단: 일일 상태 오류', blocked: true }
  }
  if (!settings || !settings.time_scheduler_on) {
    return { text: '차단: 자동매매 OFF', blocked: true }
  }
  if (!settings[t.autoFlag]) {
    return { text: t.autoOff, blocked: true }
  }

  // 작동 시간 범위 체크 — isInTradeTimeWindow 공유 헬퍼 사용 (P10 SSOT, P23 일관성)
  const start = String(settings[t.timeStart] ?? '09:00').slice(0, 5)
  const end = String(settings[t.timeEnd] ?? '15:20').slice(0, 5)
  if (!isInTradeTimeWindow(settings, side)) {
    return { text: t.outOfTime(start, end), blocked: true }
  }

  return { text: t.ok, blocked: false }
}
