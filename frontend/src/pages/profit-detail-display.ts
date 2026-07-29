// frontend/src/pages/profit-detail-display.ts
// 수익 상세 페이지 — 카드/탭/드릴다운 모달/테이블 표시 (F-05 분할 + 다단계 4세션 F-4 모달 드릴다운).
// 인라인 드릴다운 토글 제거 → 공통 dialog.ts 모달로 전환 (다단계 1세션 결정 2, P16 살아있는 경로).

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { showCustomDialog } from '../components/common/dialog'
import { FONT_WEIGHT, FONT_SIZE, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import {
  BUY_COLS,
  SELL_COLS,
} from './profit-columns'
import { type SummaryCardEls } from './profit-shared'
import {
  type TodayDrilldownResult,
  type CumulativeDrilldownResult,
  type DailyDrilldownRow,
  buildTodayDrilldown,
  buildFivedayDrilldown,
  buildMonthlyDrilldown,
  buildCumulativeDrilldown,
  filterTradeRows,
  computeCumulativePnl,
  findBaseAssetForDate,
  extractEarliestBaseAsset,
} from './profit-math'
import { getTradingToday } from '../utils/date'
import { saveProfitDetailView } from './profit-detail-view'
import { hotStore } from '../stores/hotStore'
import { globalSettingsManager } from '../settings'
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
  const dateRange = state.dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = state.stockFilterInput?.getValue() || ''
  const filteredSells = filterTradeRows(state.sellHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  const filteredBuys = filterTradeRows(state.buyHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  if (state.sellTabBtn) setTabLabel(state.sellTabBtn, '매도 내역', filteredSells.length)
  if (state.buyTabBtn) setTabLabel(state.buyTabBtn, '매수 내역', filteredBuys.length)
}

/* ── 드릴다운 모달 콘텐츠 빌더 (공통 dialog.ts 재사용 — P23 일관성) ── */

const DRILLDOWN_TABLE_STYLE = `width:100%;border-collapse:collapse;font-size:${FONT_SIZE.label};`
const DRILLDOWN_TH_STYLE = `padding:6px 8px;text-align:right;border-bottom:1px solid ${COLOR.borderLight};color:${COLOR.tertiary};font-weight:${FONT_WEIGHT.normal};white-space:nowrap;`
const DRILLDOWN_TD_STYLE = `padding:6px 8px;text-align:right;border-bottom:1px solid ${COLOR.borderLight};white-space:nowrap;`
const DRILLDOWN_TD_LEFT_STYLE = `padding:6px 8px;text-align:left;border-bottom:1px solid ${COLOR.borderLight};white-space:nowrap;`

function createDrilldownTable(headers: string[], rows: Array<Array<{ text: string; color?: string }>>): HTMLTableElement {
  const table = document.createElement('table')
  table.style.cssText = DRILLDOWN_TABLE_STYLE
  const thead = document.createElement('thead')
  const tr = document.createElement('tr')
  for (const h of headers) {
    const th = document.createElement('th')
    th.style.cssText = DRILLDOWN_TH_STYLE
    th.textContent = h
    tr.appendChild(th)
  }
  thead.appendChild(tr)
  table.appendChild(thead)
  const tbody = document.createElement('tbody')
  for (const row of rows) {
    const r = document.createElement('tr')
    for (const cell of row) {
      const td = document.createElement('td')
      td.style.cssText = DRILLDOWN_TD_STYLE
      if (cell.color) td.style.color = cell.color
      td.textContent = cell.text
      r.appendChild(td)
    }
    tbody.appendChild(r)
  }
  table.appendChild(tbody)
  return table
}

function createDrilldownSectionTitle(text: string): HTMLDivElement {
  const el = document.createElement('div')
  Object.assign(el.style, { fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.semibold, color: COLOR.neutral, margin: '12px 0 6px 0' })
  el.textContent = text
  return el
}

function createDrilldownSummary(text: string, color: string): HTMLDivElement {
  const el = document.createElement('div')
  Object.assign(el.style, { fontSize: FONT_SIZE.label, color, margin: '4px 0' })
  el.textContent = text
  return el
}

/** 당일 드릴다운 모달 콘텐츠 — 실현/평가 영역 구분 (P22 정합성: 실현+평가=당일 카드 총액). */
function buildTodayDrilldownContent(result: TodayDrilldownResult): HTMLElement {
  const wrap = document.createElement('div')

  wrap.appendChild(createDrilldownSectionTitle('실현 손익 (오늘 매도)'))
  const realizedRows = result.realizedRows.map(r => [
    { text: r.stk_nm, color: undefined },
    { text: `${r.realized_pnl >= 0 ? '+' : ''}${fmtWon(r.realized_pnl)}`, color: pnlColor(r.realized_pnl) },
  ])
  // 첫 컬럼은 좌측 정렬
  const realizedTable = createDrilldownTable(['종목', '실현손익'], realizedRows)
  realizedTable.querySelectorAll('td').forEach((td, i) => {
    if (i % 2 === 0) td.style.cssText = DRILLDOWN_TD_LEFT_STYLE
  })
  if (result.realizedRows.length === 0) {
    wrap.appendChild(createDrilldownSummary('매도 내역이 없습니다.', COLOR.tertiary))
  } else {
    wrap.appendChild(realizedTable)
  }
  wrap.appendChild(createDrilldownSummary(`실현 합계: ${result.realizedTotal >= 0 ? '+' : ''}${fmtWon(result.realizedTotal)}`, pnlColor(result.realizedTotal)))

  wrap.appendChild(createDrilldownSectionTitle('평가 손익 (현재 보유)'))
  const evalRows = result.evalRows.map(r => [
    { text: r.stk_nm, color: undefined },
    { text: `${r.pnl >= 0 ? '+' : ''}${fmtWon(r.pnl)}`, color: pnlColor(r.pnl) },
    { text: `${r.rate >= 0 ? '+' : ''}${r.rate.toFixed(2)}%`, color: pnlColor(r.pnl) },
  ])
  const evalTable = createDrilldownTable(['종목', '평가손익', '수익률'], evalRows)
  evalTable.querySelectorAll('td').forEach((td, i) => {
    if (i % 3 === 0) td.style.cssText = DRILLDOWN_TD_LEFT_STYLE
  })
  if (result.evalRows.length === 0) {
    wrap.appendChild(createDrilldownSummary('보유 종목이 없습니다.', COLOR.tertiary))
  } else {
    wrap.appendChild(evalTable)
  }
  wrap.appendChild(createDrilldownSummary(`평가 합계: ${result.evalTotal >= 0 ? '+' : ''}${fmtWon(result.evalTotal)}`, pnlColor(result.evalTotal)))

  const total = result.realizedTotal + result.evalTotal
  wrap.appendChild(createDrilldownSummary(`당일 총 손익: ${total >= 0 ? '+' : ''}${fmtWon(total)}`, pnlColor(total)))

  return wrap
}

/** 5거래일/당월 드릴다운 모달 콘텐츠 — 일별 실현손익 (DailyDrilldownRow 공통). */
function buildDailyDrilldownContent(rows: DailyDrilldownRow[], emptyText: string): HTMLElement {
  const wrap = document.createElement('div')
  if (rows.length === 0) {
    wrap.appendChild(createDrilldownSummary(emptyText, COLOR.tertiary))
    return wrap
  }
  const tableRows = rows.map(r => [
    { text: r.date, color: undefined },
    { text: String(r.sellCount), color: undefined },
    { text: String(r.buyCount), color: undefined },
    { text: `${r.pnl >= 0 ? '+' : ''}${fmtWon(r.pnl)}`, color: pnlColor(r.pnl) },
    { text: `${r.rate >= 0 ? '+' : ''}${r.rate.toFixed(2)}%`, color: pnlColor(r.pnl) },
  ])
  const table = createDrilldownTable(['날짜', '매도', '매수', '실현손익', '수익률'], tableRows)
  table.querySelectorAll('td').forEach((td, i) => {
    if (i % 5 === 0) td.style.cssText = DRILLDOWN_TD_LEFT_STYLE
  })
  wrap.appendChild(table)
  return wrap
}

/** 누적 드릴다운 모달 콘텐츠 — 월별 누적 손익 + 입금 이력 (결정 4). */
function buildCumulativeDrilldownContent(result: CumulativeDrilldownResult): HTMLElement {
  const wrap = document.createElement('div')

  wrap.appendChild(createDrilldownSectionTitle('월별 누적 손익'))
  if (result.monthlyRows.length === 0) {
    wrap.appendChild(createDrilldownSummary('거래 내역이 없습니다.', COLOR.tertiary))
  } else {
    const tableRows = result.monthlyRows.map(r => [
      { text: r.yearMonth, color: undefined },
      { text: `${r.pnl >= 0 ? '+' : ''}${fmtWon(r.pnl)}`, color: pnlColor(r.pnl) },
    ])
    const table = createDrilldownTable(['월', '실현손익'], tableRows)
    table.querySelectorAll('td').forEach((td, i) => {
      if (i % 2 === 0) td.style.cssText = DRILLDOWN_TD_LEFT_STYLE
    })
    wrap.appendChild(table)
  }

  wrap.appendChild(createDrilldownSectionTitle('입금 이력'))
  if (result.depositHistory.length === 0) {
    wrap.appendChild(createDrilldownSummary('입금 이력이 없습니다.', COLOR.tertiary))
  } else {
    const tableRows = result.depositHistory.map(r => [
      { text: r.date, color: undefined },
      { text: fmtWon(r.daily_deposit), color: undefined },
    ])
    const table = createDrilldownTable(['날짜', '입금액'], tableRows)
    table.querySelectorAll('td').forEach((td, i) => {
      if (i % 2 === 0) td.style.cssText = DRILLDOWN_TD_LEFT_STYLE
    })
    wrap.appendChild(table)
  }

  return wrap
}

/* ── 드릴다운 모달 오픈 (카드 클릭 핸들러 — F-4/F-6) ── */

export function openTodayDrilldown(state: ProfitDetailState): void {
  const hotState = hotStore.getState()
  const today = getTradingToday()
  const result = buildTodayDrilldown(state.sellHistory, hotState.positions, hotState.sectorStocks, today)
  showCustomDialog({
    title: '당일 손익 상세',
    content: buildTodayDrilldownContent(result),
    actions: [{ label: '닫기', onClick: () => {}, variant: 'default' }],
  })
}

export function openFivedayDrilldown(): void {
  const rows = buildFivedayDrilldown(hotStore.getState().dailySummary)
  showCustomDialog({
    title: '5거래일 손익 상세',
    content: buildDailyDrilldownContent(rows, '5거래일 거래 내역이 없습니다.'),
    actions: [{ label: '닫기', onClick: () => {}, variant: 'default' }],
  })
}

export function openMonthDrilldown(): void {
  const yearMonth = getTradingToday().slice(0, 7)
  const rows = buildMonthlyDrilldown(hotStore.getState().dailySummary, yearMonth)
  showCustomDialog({
    title: '당월 손익 상세',
    content: buildDailyDrilldownContent(rows, '당월 거래 내역이 없습니다.'),
    actions: [{ label: '닫기', onClick: () => {}, variant: 'default' }],
  })
}

export async function openCumulativeDrilldown(state: ProfitDetailState): Promise<void> {
  let depositHistory: Array<{ date: string; daily_deposit: number }> = []
  try {
    const res = await fetch('/api/trade-history/deposit-history')
    if (res.ok) {
      const data = await res.json() as { deposit_history?: Array<{ date: string; daily_deposit: number }> }
      depositHistory = data.deposit_history ?? []
    }
  } catch (err) {
    console.error('[profit-detail] 입금 이력 조회 실패:', err)
  }
  const result = buildCumulativeDrilldown(state.sellHistory, depositHistory)
  showCustomDialog({
    title: '누적 손익 상세',
    content: buildCumulativeDrilldownContent(result),
    actions: [{ label: '닫기', onClick: () => {}, variant: 'default' }],
  })
}

/* ── 드릴다운 날짜 클릭 → 거래내역 필터 ── */
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
  // 수익률: computeCumulativePnl SSOT 사용 (분모 규칙 단일 소스 — P10/P22).
  //   기초자산 분모 방식 — dateFrom 있을 때 findBaseAssetForDate로 전일 장마감 스냅샷 추출.
  //   baseAsset 없으면 earliestBaseAsset (둘 다 없으면 rate null → '-' 표시, P20).
  const isTestMode = globalSettingsManager.getSettings()?.trade_mode === 'test'
  const hotState = hotStore.getState()
  const earliestBaseAsset = extractEarliestBaseAsset(hotState.dailySummary)
  const baseAsset = dateRange.from
    ? findBaseAssetForDate(hotState.dailySummary, dateRange.from)
    : undefined
  const { rate: avgRate } = computeCumulativePnl({
    sellHistory: filteredSells,
    account: hotState.account,
    isTestMode,
    dateFrom: dateRange.from || undefined,
    dateTo: dateRange.to || undefined,
    baseAsset,
    earliestBaseAsset,
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
  saveProfitDetailView({ selectedView: state.selectedView, from: dr.from, to: dr.to })
}

/* ── SummaryCardEls 타입 re-export (mount.ts에서 사용) ── */
export type { SummaryCardEls }
export type { DataTableApi }
