// frontend/src/pages/profit-detail-view.ts
// 수익 상세 페이지 — 뷰 상태 localStorage 영속화 (F-05 분할, P24 단순성)
// profit-detail.ts에서 이관. 순수 이동, 동작 변경 없음.
// 카드 클릭 팝업 제거 — selectedView 영속화 제거, 날짜 범위(from/to)만 영속화.

/* ── 뷰 상태 localStorage 영속화 ── */
export const PROFIT_DETAIL_VIEW_KEY = 'sf_profit_detail_view'

export interface ProfitDetailViewState {
  from: string
  to: string
}

export function loadProfitDetailView(): ProfitDetailViewState | null {
  try {
    const raw = localStorage.getItem(PROFIT_DETAIL_VIEW_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { from?: string; to?: string }
    const from = parsed.from ?? ''
    const to = parsed.to ?? ''
    if (from && !/^\d{4}-\d{2}-\d{2}$/.test(from)) return null
    if (to && !/^\d{4}-\d{2}-\d{2}$/.test(to)) return null
    if (from && to && from > to) return null
    return { from, to }
  } catch (e) {
    console.warn('[profit-detail] 저장된 뷰 상태 로드 실패 (손상된 데이터):', e)
    return null
  }
}

export function saveProfitDetailView(state: ProfitDetailViewState): void {
  try {
    localStorage.setItem(PROFIT_DETAIL_VIEW_KEY, JSON.stringify(state))
  } catch (e) {
    console.warn('[profit-detail] 뷰 상태 localStorage 저장 실패:', e)
  }
}
