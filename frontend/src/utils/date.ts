// frontend/src/utils/date.ts
// 로컬 시간 기준 날짜 유틸 — UTC 시차 문제 방지 (P23 공통 자산, P10 SSOT).
// profit-shared/sell-position/profit-overview-date/canvas-profit-chart 공유.
// getTradingToday/getTradingMonthStart: 거래일 기준 날짜 (백엔드 chart_reference_trading_day 기반).

import { uiStore } from '../stores/uiStore'

/** 로컬 시간 기준 오늘 날짜 (YYYY-MM-DD). */
export function getLocalToday(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/** 거래일 기준 오늘 날짜 (YYYY-MM-DD) — 백엔드 chart_reference_trading_day 직접 반환.
 *  - 개장 전(08:00 이전 또는 휴일): 백엔드가 직전 거래일 반환 (휴장일 캘린더 기반)
 *  - 장중·장마감 후(08:00~24:00): 백엔드가 오늘 반환
 *  - WS 미연결: 빈 문자열 반환 → 호출부에서 명시 처리 (P20 폴백 금지)
 *  P10 SSOT — uiStore.marketPhase.chart_reference_trading_day 단일 소스. */
export function getTradingToday(): string {
  return uiStore.getState().marketPhase.chart_reference_trading_day ?? ''
}

/** 거래일 기준 이번 달 시작일 (YYYY-MM-01).
 *  getTradingToday() 기준 월의 1일 — 월 경계일 00:00~08:00에 전월 1일 반환. */
export function getTradingMonthStart(): string {
  return getTradingToday().slice(0, 7) + '-01'
}
