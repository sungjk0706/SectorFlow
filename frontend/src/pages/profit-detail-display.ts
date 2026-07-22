// frontend/src/pages/profit-detail-display.ts
// 수익 상세 페이지 — 카드/탭/드릴다운/테이블 표시 (F-05 분할, P24 단순성)
// profit-detail.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { FONT_WEIGHT, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import {
  BUY_COLS,
  SELL_COLS,
  createDrilldownCols,
} from './profit-columns'
import {
  type DailyDrilldownRow,
  type SummaryCardEls,
  getLocalToday,
  buildMonthlyDrilldown,
  filterTradeRows,
} from './profit-shared'
import { saveProfitDetailView } from './profit-detail-view'
import type { ProfitDetailState } from './profit-detail'

/* ── 요약 카드 선택 스타일 ── */
function applyCardStyle(card: HTMLDivElement, active: boolean, borderActive: string, bgActive: string): void {
  Object.assign(card.style, {
    border: active ? '2px solid ' + borderActive : '1px solid ' + COLOR.borderLight,
    background: active ? bgActive : COLOR.surfaceLight,
  })
}

/* ── 하단 통계 카드 색상 연동 (상단 선택 기간과 동일 색) ── */
export function updateStatCardSelection(state: ProfitDetailState): void {
  const colorMap: Record<string, { border: string; bg: string }> = {
    today: { border: COLOR.down, bg: COLOR.downBg },
    prev: { border: COLOR.periodPrev, bg: COLOR.periodPrevBg },
    month: { border: COLOR.periodMonth, bg: COLOR.periodMonthBg },
    total: { border: COLOR.periodTotal, bg: COLOR.periodTotalBg },
  }
  const sel = state.selectedView ? colorMap[state.selectedView] : undefined
  for (const card of state.statCardEls) {
    Object.assign(card.style, {
      border: sel ? '2px solid ' + sel.border : '1px solid ' + COLOR.borderLight,
      background: sel ? sel.bg : COLOR.surfaceLight,
    })
  }
}

export function updateCardSelection(state: ProfitDetailState): void {
  if (!state.summaryCardEls) return
  applyCardStyle(state.summaryCardEls.todayCard, state.selectedView === 'today', COLOR.down, COLOR.downBg)
  applyCardStyle(state.summaryCardEls.prevCard, state.selectedView === 'prev', COLOR.periodPrev, COLOR.periodPrevBg)
  applyCardStyle(state.summaryCardEls.monthCard, state.selectedView === 'month', COLOR.periodMonth, COLOR.periodMonthBg)
  applyCardStyle(state.summaryCardEls.totalCard, state.selectedView === 'total', COLOR.periodTotal, COLOR.periodTotalBg)
  updateStatCardSelection(state)
}

export function updateDrilldownBtnStyle(state: ProfitDetailState, active: boolean): void {
  state.drilldownBtnHandle?.setActive(active)
}

/* ── 탭 헤더 텍스트 업데이트 ── */
function setTabLabel(btn: HTMLButtonElement, label: string, count: number): void {
  // 라벨 텍스트 + 동적 숫자(파란색 강조) 분리 렌더
  btn.replaceChildren()
  btn.appendChild(document.createTextNode(`${label} (`))
  const numSpan = document.createElement('span')
  Object.assign(numSpan.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.semibold })
  numSpan.textContent = String(count)
  btn.appendChild(numSpan)
  btn.appendChild(document.createTextNode('건)'))
}

export function updateTabLabels(state: ProfitDetailState): void {
  const dateRange = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = state.stockFilterInput?.getValue() || ''
  const filteredSells = filterTradeRows(state.sellHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  const filteredBuys = filterTradeRows(state.buyHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  if (state.sellTabBtn) setTabLabel(state.sellTabBtn, '매도 내역', filteredSells.length)
  if (state.buyTabBtn) setTabLabel(state.buyTabBtn, '매수 내역', filteredBuys.length)
}

/* ── 드릴다운 테이블 표시 ── */
export function showDrilldown(state: ProfitDetailState): void {
  if (!state.tableViewContainer || !state.drilldownViewContainer) return

  state.tableViewContainer.style.display = 'none'
  state.drilldownViewContainer.style.display = ''

  if (state.tabRow) state.tabRow.style.display = 'none'

  if (!state.drilldownTable) {
    const drilldownCols = createDrilldownCols((date: string) => {
      filterByDate(state, date)
      state.selectedView = null
      updateCardSelection(state)
      persistViewState(state)
    })
    state.drilldownTable = createDataTable<DailyDrilldownRow>({
      columns: drilldownCols,
      emptyText: '당월 거래 내역이 없습니다.',
      zebraStriping: true,
    })
    state.drilldownViewContainer.appendChild(state.drilldownTable.el)
  }

  const yearMonth = getLocalToday().slice(0, 7)
  const rows = buildMonthlyDrilldown(state.sellHistory, state.buyHistory, yearMonth)
  state.drilldownTable.updateRows(rows)
}

/* ── 드릴다운 날짜 클릭 → 거래내역 필터 ── */
export function filterByDate(state: ProfitDetailState, date: string): void {
  state.drilldownActive = false

  if (state.dateRangeInput) state.dateRangeInput.setValue(date, date)

  if (state.tabRow) state.tabRow.style.display = 'flex'

  showTable(state)
  updateTabLabels(state)
}

/* ── 날짜 범위 필터 ── */
export function filterByDateRange(state: ProfitDetailState, from: string, to: string): void {
  state.drilldownActive = false

  if (state.dateRangeInput) state.dateRangeInput.setValue(from, to)

  if (state.tabRow) state.tabRow.style.display = 'flex'

  showTable(state)
  updateTabLabels(state)
}

/* ── 통계 정보 갱신 ── */
function updateStatistics(state: ProfitDetailState): void {
  const dateRange = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = state.stockFilterInput?.getValue() || ''
  const filteredSells = filterTradeRows(state.sellHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  const filteredBuys = filterTradeRows(state.buyHistory, dateRange.from, dateRange.to, stockQuery || undefined)

  const sellCount = filteredSells.length
  const buyCount = filteredBuys.length
  const buyAmt = filteredBuys.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const sellAmt = filteredSells.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const pnl = filteredSells.reduce((s, r) => s + Number(r.realized_pnl ?? 0), 0)
  const winCount = filteredSells.filter(r => Number(r.realized_pnl ?? 0) > 0).length
  const winRate = sellCount > 0 ? Math.round(winCount / sellCount * 10000) / 100 : 0
  // 가중 평균 수익률 = 실현손익 합 / 매입금액 합 × 100 (좌측상단 당일 손익 카드와 동일 공식, P22 데이터 정합성)
  const buyTotal = filteredSells.reduce((s, r) => s + Number(r.avg_buy_price ?? 0) * Number(r.qty ?? 0), 0)
  const avgRate = buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0

  if (state.statCountEl) state.statCountEl.textContent = `매도 ${sellCount}건 / 매수 ${buyCount}건`
  if (state.statBuyAmtEl) { state.statBuyAmtEl.textContent = fmtWon(buyAmt); state.statBuyAmtEl.style.color = COLOR.tertiary }
  if (state.statSellAmtEl) { state.statSellAmtEl.textContent = fmtWon(sellAmt); state.statSellAmtEl.style.color = COLOR.tertiary }
  if (state.statPnlEl) { state.statPnlEl.textContent = fmtWon(pnl); state.statPnlEl.style.color = pnlColor(pnl) }
  if (state.statWinRateEl) { state.statWinRateEl.textContent = `${winRate.toFixed(2)}%`; state.statWinRateEl.style.color = COLOR.tertiary }
  if (state.statAvgRateEl) { state.statAvgRateEl.textContent = `${avgRate > 0 ? '+' : ''}${avgRate.toFixed(2)}%`; state.statAvgRateEl.style.color = pnlColor(avgRate) }
}

/* ── 테이블 표시 ── */
export function showTable(state: ProfitDetailState): void {
  if (!state.tableViewContainer || !state.drilldownViewContainer) return

  state.tableViewContainer.style.display = ''
  state.drilldownViewContainer.style.display = 'none'

  if (state.tabRow) state.tabRow.style.display = 'flex'

  const dateRange = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = state.stockFilterInput?.getValue() || ''
  const isSell = state.activeTab === 'sell'
  let rows = isSell ? state.sellHistory : state.buyHistory
  rows = filterTradeRows(rows, dateRange.from, dateRange.to, stockQuery || undefined)

  if (!state.sellTable) {
    state.sellTable = createDataTable<Record<string, unknown>>({
      columns: SELL_COLS,
      virtualScroll: true,
      keyFn: (r, i) => `${r.stk_cd ?? ''}-${r.date ?? ''}-${r.time ?? ''}-${i}`,
      emptyText: '매도 내역이 없습니다.',
      zebraStriping: true,
    })
    state.tableViewContainer.appendChild(state.sellTable.el)
  }

  if (!state.buyTable) {
    state.buyTable = createDataTable<Record<string, unknown>>({
      columns: BUY_COLS,
      virtualScroll: true,
      keyFn: (r, i) => `${r.stk_cd ?? ''}-${r.date ?? ''}-${r.time ?? ''}-${i}`,
      emptyText: '매수 내역이 없습니다.',
      zebraStriping: true,
    })
    state.tableViewContainer.appendChild(state.buyTable.el)
  }

  state.sellTable.el.style.display = isSell ? '' : 'none'
  state.buyTable.el.style.display = isSell ? 'none' : ''

  const activeTbl = isSell ? state.sellTable : state.buyTable
  activeTbl.updateRows(rows)

  if (state.tabBarHandle) state.tabBarHandle.setActive(state.activeTab)

  updateStatistics(state)
}

/* ── 뷰 상태 영속화 (view.ts 위임) ── */

export function persistViewState(state: ProfitDetailState): void {
  const dr = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  saveProfitDetailView({ selectedView: state.selectedView, drilldownActive: state.drilldownActive, from: dr.from, to: dr.to })
}

/* ── SummaryCardEls 타입 re-export (mount.ts에서 사용) ── */
export type { SummaryCardEls }
export type { DataTableApi }
