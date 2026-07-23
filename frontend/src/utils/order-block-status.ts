/**
 * 주문 차단 상태 판정 — 매수/매도 공통 게이트 집계 (P21 사용자 투명성).
 *
 * buy-target.ts / sell-position.ts 상단 상태 배지의 판정 로직을 단일 함수로 추출 (P10 SSOT).
 * 우선순위: 서킷브레이커 > 리스크(side) > 시간대 차단 > 자동매매 OFF > 자동매수/매도 OFF > 시간대 외
 * 데이터 소스: 기존 uiStore 상태 + globalSettingsManager (P10 SSOT — 신규 데이터 없음)
 *
 * DOM 렌더링은 호출부 updateBadge() 담당 → 본 함수는 판정 결과만 반환 (관심사 분리, P24 단순성).
 * P23(일관성) + P24(단순성) + P10(SSOT) 준수.
 */

import type { UIState } from '../stores/uiStore'
import type { AppSettings } from '../types'

export type OrderSide = 'buy' | 'sell'

export interface OrderBlockStatus {
  /** 배지에 표시할 텍스트 ('매수 가능' | '차단: ...') */
  text: string
  /** 차단 여부 (true=차단, false=정상) */
  blocked: boolean
}

/** side별 텍스트 매핑 (P10 SSOT — 단일 테이블에서 관리) */
const SIDE_TEXT: Record<OrderSide, {
  ok: string
  autoOff: string
  outOfTime: string
  autoFlag: keyof AppSettings
  timeStart: keyof AppSettings
  timeEnd: keyof AppSettings
}> = {
  buy: {
    ok: '매수 가능',
    autoOff: '차단: 자동매수 OFF',
    outOfTime: '차단: 매수 시간대 외',
    autoFlag: 'auto_buy_on',
    timeStart: 'buy_time_start',
    timeEnd: 'buy_time_end',
  },
  sell: {
    ok: '매도 가능',
    autoOff: '차단: 자동매도 OFF',
    outOfTime: '차단: 매도 시간대 외',
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
  if (uiState.riskBlockStatus && uiState.riskBlockStatus.side === side) {
    return { text: `차단: 리스크(${uiState.riskBlockStatus.reason})`, blocked: true }
  }
  if (uiState.orderTimeBlocked) {
    return { text: `차단: ${uiState.orderTimeBlocked.reason}`, blocked: true }
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
    return { text: t.outOfTime, blocked: true }
  }

  return { text: t.ok, blocked: false }
}
