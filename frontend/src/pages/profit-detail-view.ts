// frontend/src/pages/profit-detail-view.ts
// 수익 상세 페이지 — 뷰 상태 localStorage 영속화 (F-05 분할, P24 단순성)
// profit-detail.ts에서 이관. 순수 이동, 동작 변경 없음.

import type { SelectedView } from './profit-detail'

/* ── 뷰 상태 localStorage 영속화 ── */
export const PROFIT_DETAIL_VIEW_KEY = 'sf_profit_detail_view'

export interface ProfitDetailViewState {
  selectedView: SelectedView
  drilldownActive: boolean
  from: string
  to: string
}

export function loadProfitDetailView(): ProfitDetailViewState | null {
  try {
    const raw = localStorage.getItem(PROFIT_DETAIL_VIEW_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { selectedView?: string; drilldownActive?: boolean; from?: string; to?: string }
    const validViews: string[] = ['today', 'prev', 'month', 'total', 'drilldown']
    const sv = parsed.selectedView ?? null
    if (sv !== null && !validViews.includes(sv)) return null
    // total/drilldown은 from/to가 빈 문자열일 수 있음
    const from = parsed.from ?? ''
    const to = parsed.to ?? ''
    // 수동 날짜 범위(sv === null) 또는 today/prev/month인 경우 from/to 유효성 검증
    if (sv === null || sv === 'today' || sv === 'prev' || sv === 'month') {
      if (from && !/^\d{4}-\d{2}-\d{2}$/.test(from)) return null
      if (to && !/^\d{4}-\d{2}-\d{2}$/.test(to)) return null
      if (from && to && from > to) return null
    }
    return {
      selectedView: sv as SelectedView,
      drilldownActive: parsed.drilldownActive ?? false,
      from,
      to,
    }
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
