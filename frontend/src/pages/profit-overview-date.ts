// frontend/src/pages/profit-overview-date.ts
// 수익현황 페이지 — 날짜 범위 localStorage 영속화 (F-05 분할, P24 단순성)
// profit-overview.ts에서 이관. 순수 이동, 동작 변경 없음.

import { hotStore } from '../stores/hotStore'

/* ── 날짜 범위 localStorage 영속화 ── */
export const PROFIT_DATE_KEY = 'sf_profit_date_range'

export interface ProfitDateRange {
  from: string
  to: string
  quickLabel?: string
}

export function loadProfitDateRange(): ProfitDateRange | null {
  try {
    const raw = localStorage.getItem(PROFIT_DATE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { from?: string; to?: string; quickLabel?: string }
    // quickLabel이 있는 경우(5일/전체 등) from/to가 빈 문자열일 수 있음
    if (parsed.quickLabel) {
      return { from: parsed.from ?? '', to: parsed.to ?? '', quickLabel: parsed.quickLabel }
    }
    // 수동 날짜 범위 — from/to 유효성 검증
    if (parsed.from && parsed.to && /^\d{4}-\d{2}-\d{2}$/.test(parsed.from) && /^\d{4}-\d{2}-\d{2}$/.test(parsed.to) && parsed.from <= parsed.to) {
      return { from: parsed.from, to: parsed.to }
    }
    return null
  } catch (e) {
    console.warn('[profit-overview] 저장된 날짜 범위 로드 실패 (손상된 데이터):', e)
    return null
  }
}

export function saveProfitDateRange(from: string, to: string, quickLabel?: string): void {
  try {
    localStorage.setItem(PROFIT_DATE_KEY, JSON.stringify({ from, to, quickLabel }))
  } catch (e) {
    console.warn('[profit-overview] 날짜 범위 localStorage 저장 실패:', e)
  }
}

export function defaultDateRange(): { from: string; to: string } {
  const now = new Date()
  const from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
  const to = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return { from, to }
}

/* ── mount 헬퍼: 날짜 범위 초기화 (localStorage 로드 후 hotStore에 보장) ── */
export function initDateRange(): ProfitDateRange | null {
  const saved = loadProfitDateRange()
  if (saved) {
    hotStore.setState({ profitDateFrom: saved.from, profitDateTo: saved.to })
  } else if (!hotStore.getState().profitDateFrom || !hotStore.getState().profitDateTo) {
    const { from, to } = defaultDateRange()
    hotStore.setState({ profitDateFrom: from, profitDateTo: to })
    saveProfitDateRange(from, to)
  }
  return saved
}
