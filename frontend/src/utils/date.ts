// frontend/src/utils/date.ts
// 로컬 시간 기준 날짜 유틸 — UTC 시차 문제 방지 (P23 공통 자산, P10 SSOT).
// profit-shared/sell-position/profit-overview-date/canvas-profit-chart 공유.

/** 로컬 시간 기준 오늘 날짜 (YYYY-MM-DD). */
export function getLocalToday(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/** 로컬 시간 기준 이번 달 시작일 (YYYY-MM-01). */
export function getLocalMonthStart(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
}
