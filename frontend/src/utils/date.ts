// frontend/src/utils/date.ts
// 로컬 시간 기준 날짜 유틸 — UTC 시차 문제 방지 (P23 공통 자산, P10 SSOT).
// profit-shared/sell-position/profit-overview-date/canvas-profit-chart 공유.
// getTradingToday/getTradingMonthStart: 거래일 기준 날짜 (phase 기반, 개장 전→전일).

import { uiStore } from '../stores/uiStore'

/** 로컬 시간 기준 오늘 날짜 (YYYY-MM-DD). */
export function getLocalToday(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/** 개장 전(08:00 NXT 프리마켓 전) phase 집합 — 당일 거래일 미활성.
 *  P23 일관성 — sector-settings.ts REGULAR_PHASES 패턴 재사용.
 *  P10 SSOT — phase 판정은 백엔드 calc_timebased_market_phase()가 단일 소스. */
const PRE_OPEN_PHASES = new Set(['장개시전', '휴장일'])

/** 직전 평일(월~금) 날짜 반환 — 주말 건너뛰기.
 *  사용자 모델: "20:00~익일 08:00 = 당일(N일) 유지" → 월요일 07:00은 금요일 반환.
 *  공휴일은 백엔드 휴장일 캘린더가 별도 처리하므로 여기서는 요일 기준만 적용 (P24 단순성). */
function _prevWeekday(yyyyMmDd: string): string {
  const d = new Date(yyyyMmDd + 'T00:00:00')
  do {
    d.setDate(d.getDate() - 1)
  } while (d.getDay() === 0 || d.getDay() === 6) // 0=일, 6=토
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 당일 카드 개장 전(08:00 이전 또는 휴일) 여부 — 당일 카드 0원 강제 판정.
 *  PRE_OPEN_PHASES (기존 상수) 재사용 — getTradingToday 판정과 동일 집합 (P23 일관성).
 *  P10 SSOT — phase 판정은 uiStore.marketPhase 단일 소스. */
export function isPreOpenPhase(): boolean {
  const phase = uiStore.getState().marketPhase
  return PRE_OPEN_PHASES.has(phase.krx) && PRE_OPEN_PHASES.has(phase.nxt)
}

/** 거래일 기준 오늘 날짜 (YYYY-MM-DD).
 *  - 개장 전(장개시전/휴장일, 08:00 이전 또는 휴일): 직전 평일 반환
 *    (사용자 모델: 20:00~익일 08:00 = 당일 유지 → 개장 전에는 전일 성과 표시)
 *  - 장중·장마감 후(08:00~24:00): 오늘 반환 (장마감 후에도 당일 성과 유지)
 *  P10 SSOT — uiStore.marketPhase 기반 판정, 프론트 독립 시간 계산 금지. */
export function getTradingToday(): string {
  const calendarToday = getLocalToday()
  if (isPreOpenPhase()) {
    return _prevWeekday(calendarToday)
  }
  return calendarToday
}

/** 거래일 기준 이번 달 시작일 (YYYY-MM-01).
 *  getTradingToday() 기준 월의 1일 — 월 경계일 00:00~08:00에 전월 1일 반환. */
export function getTradingMonthStart(): string {
  return getTradingToday().slice(0, 7) + '-01'
}
