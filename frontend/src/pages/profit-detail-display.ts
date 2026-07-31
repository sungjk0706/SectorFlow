// frontend/src/pages/profit-detail-display.ts
// 수익 상세 페이지 — 카드/탭/테이블 표시 (F-05 분할).
// 카드 클릭 시 테이블 필터링 + 선택 강조 표시 (팝업/드릴다운 모달 없음 — P24 단순성).

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { FONT_WEIGHT, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import {
  BUY_COLS,
  SELL_COLS,
} from './profit-columns'
import { type SummaryCardEls } from './profit-shared'
import {
  filterTradeRows,
  computeCumulativePnl,
} from './profit-math'
import { saveProfitDetailView } from './profit-detail-view'
import { globalSettingsManager } from '../settings'
import type { ProfitDetailState } from './profit-detail'

/* ── 1프레임 내 필터 결과 재사용 (P24 단순성 — filterTradeRows 중복 연산 방지) ──
 * showTable/updateTabLabels/updateStatistics가 같은 프레임에 같은 입력으로 호출될 때
 * filterTradeRows를 1회만 실행하고 결과를 재사용.
 * 캐시 유효성: sellHistory/buyHistory 참조 + dateFrom/dateTo/stockQuery 동일 시 재사용.
 * 수명 = 현재 입력이 유지되는 동안 (입력 변경 시 자동 무효화 — P22 정합성 위험 없음). */
function getFilteredRows(state: ProfitDetailState): { sells: Record<string, unknown>[]; buys: Record<string, unknown>[] } {
  const dateRange = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = state.stockFilterInput?.getValue() || ''

  // 캐시 유효성 검증 — 참조 동등성 + 입력값 동등성
  const cache = state.filterCache
  if (cache
    && cache.sellRef === state.sellHistory
    && cache.buyRef === state.buyHistory
    && cache.from === dateRange.from
    && cache.to === dateRange.to
    && cache.query === stockQuery
  ) {
    return { sells: cache.sells, buys: cache.buys }
  }

  // 캐시 미스 또는 무효 — 재계산
  const sells = filterTradeRows(state.sellHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  const buys = filterTradeRows(state.buyHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  state.filterCache = {
    sellRef: state.sellHistory,
    buyRef: state.buyHistory,
    from: dateRange.from,
    to: dateRange.to,
    query: stockQuery,
    sells,
    buys,
  }
  return { sells, buys }
}

/* ── 요약 카드 선택 스타일 ── */
function applyCardStyle(card: HTMLDivElement, active: boolean, borderActive: string, bgActive: string): void {
  Object.assign(card.style, {
    border: active ? '2px solid ' + borderActive : '1px solid ' + COLOR.borderLight,
    background: active ? bgActive : COLOR.surfaceLight,
  })
}

/* ── 하단 통계 카드 색상 연동 (상단 선택 기간과 동일 색) ── */
function updateStatCardSelection(state: ProfitDetailState): void {
  const colorMap: Record<string, { border: string; bg: string }> = {
    today: { border: COLOR.down, bg: COLOR.downBg },
    fiveday: { border: COLOR.period5day, bg: COLOR.period5dayBg },
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
  applyCardStyle(state.summaryCardEls.fivedayCard, state.selectedView === 'fiveday', COLOR.period5day, COLOR.period5dayBg)
  applyCardStyle(state.summaryCardEls.monthCard, state.selectedView === 'month', COLOR.periodMonth, COLOR.periodMonthBg)
  applyCardStyle(state.summaryCardEls.totalCard, state.selectedView === 'total', COLOR.periodTotal, COLOR.periodTotalBg)
  updateStatCardSelection(state)
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
  const { sells: filteredSells, buys: filteredBuys } = getFilteredRows(state)
  if (state.sellTabBtn) setTabLabel(state.sellTabBtn, '매도 내역', filteredSells.length)
  if (state.buyTabBtn) setTabLabel(state.buyTabBtn, '매수 내역', filteredBuys.length)
}

/* ── 날짜 필터 → 거래내역 갱신 ── */
export function filterByDate(state: ProfitDetailState, date: string): void {
  if (state.dateRangeInput) state.dateRangeInput.setValue(date, date)
  if (state.tabRow) state.tabRow.style.display = 'flex'
  showTable(state)
  updateTabLabels(state)
}

/* ── 날짜 범위 필터 ── */
export function filterByDateRange(state: ProfitDetailState, from: string, to: string): void {
  if (state.dateRangeInput) state.dateRangeInput.setValue(from, to)
  if (state.tabRow) state.tabRow.style.display = 'flex'
  showTable(state)
  updateTabLabels(state)
}

/* ── 통계 정보 갱신 ── */
function updateStatistics(state: ProfitDetailState): void {
  const dateRange = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  const { sells: filteredSells, buys: filteredBuys } = getFilteredRows(state)

  const sellCount = filteredSells.length
  const buyCount = filteredBuys.length
  const buyAmt = filteredBuys.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const sellAmt = filteredSells.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const pnl = filteredSells.reduce((s, r) => s + Number(r.realized_pnl ?? 0), 0)
  const winCount = filteredSells.filter(r => Number(r.realized_pnl ?? 0) > 0).length
  const winRate = sellCount > 0 ? Math.round(winCount / sellCount * 10000) / 100 : 0
  // 수익률: computeCumulativePnl SSOT 사용 (분모 규칙 단일 소스 — P10/P22).
  //   매수원금 기반 (aggregatePnl — 설계서 0절 최상위 원칙).
  //   실전모드: 증권사 서버가 SSOT — rate null → '-' 표시 (AGENTS.md 실전vs테스트 테이블).
  const isTestMode = globalSettingsManager.getSettings()?.trade_mode === 'test'
  const { rate: avgRate } = computeCumulativePnl({
    sellHistory: filteredSells,
    isTestMode,
    dateFrom: dateRange.from || undefined,
    dateTo: dateRange.to || undefined,
  })

  if (state.statCountEl) state.statCountEl.textContent = `매도 ${sellCount}건 / 매수 ${buyCount}건`
  if (state.statBuyAmtEl) { state.statBuyAmtEl.textContent = fmtWon(buyAmt); state.statBuyAmtEl.style.color = COLOR.tertiary }
  if (state.statSellAmtEl) { state.statSellAmtEl.textContent = fmtWon(sellAmt); state.statSellAmtEl.style.color = COLOR.tertiary }
  if (state.statPnlEl) { state.statPnlEl.textContent = fmtWon(pnl); state.statPnlEl.style.color = pnlColor(pnl) }
  if (state.statWinRateEl) { state.statWinRateEl.textContent = `${winRate.toFixed(2)}%`; state.statWinRateEl.style.color = COLOR.tertiary }
  if (state.statAvgRateEl) {
    state.statAvgRateEl.textContent = avgRate == null ? '-' : `${avgRate > 0 ? '+' : ''}${avgRate.toFixed(2)}%`
    state.statAvgRateEl.style.color = avgRate == null ? COLOR.tertiary : pnlColor(avgRate)
  }
}

/* ── 테이블 표시 ── */
export function showTable(state: ProfitDetailState): void {
  if (!state.tableViewContainer) return

  state.tableViewContainer.style.display = ''

  if (state.tabRow) state.tabRow.style.display = 'flex'

  const { sells, buys } = getFilteredRows(state)
  const isSell = state.activeTab === 'sell'
  const rows = isSell ? sells : buys

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
  saveProfitDetailView({ selectedView: state.selectedView, from: dr.from, to: dr.to })
}

/* ── SummaryCardEls 타입 re-export (mount.ts에서 사용) ── */
export type { SummaryCardEls }
export type { DataTableApi }
