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

export type OrderSide = 'buy' | 'sell'

export interface OrderBlockStatus {
  /** 배지에 표시할 텍스트 ('매수 가능' | '차단: ...' | 'NXT만 가능' | '거래 시간 외') */
  text: string
  /** 차단 여부 (true=위험/강제 차단, false=정상 또는 정보 상태) */
  blocked: boolean
}

/** side별 텍스트 매핑 (P10 SSOT — 단일 테이블에서 관리) */
const SIDE_TEXT: Record<OrderSide, {
  ok: string
  autoOff: string
  outOfTime: (start: string, end: string) => string
  autoFlag: keyof AppSettings
  timeStart: keyof AppSettings
  timeEnd: keyof AppSettings
}> = {
  buy: {
    ok: '매수 가능',
    autoOff: '차단: 자동매수 OFF',
    outOfTime: (start, end) => `차단: 자동매수 시간 외 (${start}~${end})`,
    autoFlag: 'auto_buy_on',
    timeStart: 'buy_time_start',
    timeEnd: 'buy_time_end',
  },
  sell: {
    ok: '매도 가능',
    autoOff: '차단: 자동매도 OFF',
    outOfTime: (start, end) => `차단: 자동매도 시간 외 (${start}~${end})`,
    autoFlag: 'auto_sell_on',
    timeStart: 'sell_time_start',
    timeEnd: 'sell_time_end',
  },
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

  if (uiState.circuitBreakerOpen) {
    return { text: '차단: 서킷브레이커', blocked: true }
  }
  if (uiState.realtimeLatencyExceeded) {
    return { text: '차단: 실시간 지연', blocked: true }
  }
  if (uiState.riskBlockStatus && uiState.riskBlockStatus.side === side) {
    return { text: `차단: 리스크(${uiState.riskBlockStatus.reason})`, blocked: true }
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

  // 작동 시간 범위 체크 (KST HH:MM 기준 — 백엔드 auto_buy/sell_effective와 동일 로직)
  const nowKst = new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit' })
  const start = String(settings[t.timeStart] ?? '09:00').slice(0, 5)
  const end = String(settings[t.timeEnd] ?? '15:20').slice(0, 5)
  if (nowKst < start || nowKst > end) {
    return { text: t.outOfTime(start, end), blocked: true }
  }

  return { text: t.ok, blocked: false }
}
