// frontend/src/pages/profit-detail.ts
// 수익 상세 페이지 — Vanilla TS PageModule
// 차트(크게) + 드릴다운 + 날짜/종목 필터 + 전체 거래내역(가상 스크롤) + 통계 정보

import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { createSearchInput } from '../components/common/search-input'
import { createTabBar, createToggleSelectBtn } from '../components/common/button'
import { createDateRangeInput, type DateRangeInputApi } from '../components/common/date-range-input'
import { hotStore } from '../stores/hotStore'
import { api } from '../api/client'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
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
  createSummaryCards,
  updateSummaryCards,
  filterTradeRows,
} from './profit-shared'

/* ── 모듈 변수 ── */
type LowerTab = 'buy' | 'sell'

let summaryCardEls: SummaryCardEls | null = null
let buyHistory: Record<string, unknown>[] = []
let sellHistory: Record<string, unknown>[] = []
let activeTab: LowerTab = 'sell'
let sellTable: DataTableApi<Record<string, unknown>> | null = null
let buyTable: DataTableApi<Record<string, unknown>> | null = null
let sellTabBtn: HTMLButtonElement | null = null
let buyTabBtn: HTMLButtonElement | null = null
let tabBarHandle: ReturnType<typeof createTabBar> | null = null
let tableContainer: HTMLDivElement | null = null
let tableViewContainer: HTMLDivElement | null = null
let drilldownViewContainer: HTMLDivElement | null = null
let dateRangeInput: DateRangeInputApi | null = null
let stockFilterInput: ReturnType<typeof createSearchInput> | null = null
let unsubStore: (() => void) | null = null

/* ── 드릴다운 상태 ── */
let drilldownActive = true
let drilldownTable: DataTableApi<DailyDrilldownRow> | null = null
let tabRow: HTMLDivElement | null = null
let drilldownBtnHandle: ReturnType<typeof createToggleSelectBtn> | null = null

type SelectedView = 'today' | 'prev' | 'month' | 'total' | 'drilldown' | null
let selectedView: SelectedView = null

/* ── 뷰 상태 localStorage 영속화 ── */
const PROFIT_DETAIL_VIEW_KEY = 'sf_profit_detail_view'

interface ProfitDetailViewState {
  selectedView: SelectedView
  drilldownActive: boolean
  from: string
  to: string
}

function loadProfitDetailView(): ProfitDetailViewState | null {
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

function saveProfitDetailView(state: ProfitDetailViewState): void {
  try {
    localStorage.setItem(PROFIT_DETAIL_VIEW_KEY, JSON.stringify(state))
  } catch (e) {
    console.warn('[profit-detail] 뷰 상태 localStorage 저장 실패:', e)
  }
}

function persistViewState(): void {
  const dr = dateRangeInput?.getValue() ?? { from: '', to: '' }
  saveProfitDetailView({ selectedView, drilldownActive, from: dr.from, to: dr.to })
}

/* ── 통계 정보 DOM 참조 ── */
let statCountEl: HTMLSpanElement | null = null
let statBuyAmtEl: HTMLSpanElement | null = null
let statSellAmtEl: HTMLSpanElement | null = null
let statPnlEl: HTMLSpanElement | null = null
let statWinRateEl: HTMLSpanElement | null = null
let statAvgRateEl: HTMLSpanElement | null = null

/* ── rAF 배칭 상태 ── */
let _rafId: number | null = null
let _mounted = false
let _dirtyHistory = false
let _dirtySummary = false
let _dirtySectorStocks = false

/* ── 요약 카드 선택 스타일 ── */
function applyCardStyle(card: HTMLDivElement, active: boolean, borderActive: string, bgActive: string): void {
  Object.assign(card.style, {
    border: active ? '2px solid ' + borderActive : '1px solid ' + COLOR.borderLight,
    background: active ? bgActive : COLOR.surfaceLight,
  })
}

/* ── 하단 통계 카드 색상 연동 (상단 선택 기간과 동일 색) ── */
let statCardEls: HTMLDivElement[] = []

function updateStatCardSelection(): void {
  const colorMap: Record<string, { border: string; bg: string }> = {
    today: { border: COLOR.down, bg: COLOR.downBg },
    prev: { border: COLOR.periodPrev, bg: COLOR.periodPrevBg },
    month: { border: COLOR.periodMonth, bg: COLOR.periodMonthBg },
    total: { border: COLOR.periodTotal, bg: COLOR.periodTotalBg },
  }
  const sel = selectedView ? colorMap[selectedView] : undefined
  for (const card of statCardEls) {
    Object.assign(card.style, {
      border: sel ? '2px solid ' + sel.border : '1px solid ' + COLOR.borderLight,
      background: sel ? sel.bg : COLOR.surfaceLight,
    })
  }
}

function updateCardSelection(): void {
  if (!summaryCardEls) return
  applyCardStyle(summaryCardEls.todayCard, selectedView === 'today', COLOR.down, COLOR.downBg)
  applyCardStyle(summaryCardEls.prevCard, selectedView === 'prev', COLOR.periodPrev, COLOR.periodPrevBg)
  applyCardStyle(summaryCardEls.monthCard, selectedView === 'month', COLOR.periodMonth, COLOR.periodMonthBg)
  applyCardStyle(summaryCardEls.totalCard, selectedView === 'total', COLOR.periodTotal, COLOR.periodTotalBg)
  updateStatCardSelection()
}

function updateDrilldownBtnStyle(active: boolean): void {
  drilldownBtnHandle?.setActive(active)
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

function updateTabLabels(): void {
  const dateRange = dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = stockFilterInput?.getValue() || ''
  const filteredSells = filterTradeRows(sellHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  const filteredBuys = filterTradeRows(buyHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  if (sellTabBtn) setTabLabel(sellTabBtn, '매도 내역', filteredSells.length)
  if (buyTabBtn) setTabLabel(buyTabBtn, '매수 내역', filteredBuys.length)
}

/* ── 드릴다운 테이블 표시 ── */
function showDrilldown(): void {
  if (!tableViewContainer || !drilldownViewContainer) return

  tableViewContainer.style.display = 'none'
  drilldownViewContainer.style.display = ''

  if (tabRow) tabRow.style.display = 'none'

  if (!drilldownTable) {
    const drilldownCols = createDrilldownCols((date: string) => {
      filterByDate(date)
      selectedView = null
      updateCardSelection()
      persistViewState()
    })
    drilldownTable = createDataTable<DailyDrilldownRow>({
      columns: drilldownCols,
      emptyText: '당월 거래 내역이 없습니다.',
      zebraStriping: true,
    })
    drilldownViewContainer.appendChild(drilldownTable.el)
  }

  const yearMonth = getLocalToday().slice(0, 7)
  const rows = buildMonthlyDrilldown(sellHistory, buyHistory, yearMonth)
  drilldownTable.updateRows(rows)
}

/* ── 드릴다운 날짜 클릭 → 거래내역 필터 ── */
function filterByDate(date: string): void {
  drilldownActive = false

  if (dateRangeInput) dateRangeInput.setValue(date, date)

  if (tabRow) tabRow.style.display = 'flex'

  showTable()
  updateTabLabels()
}

/* ── 날짜 범위 필터 ── */
function filterByDateRange(from: string, to: string): void {
  drilldownActive = false

  if (dateRangeInput) dateRangeInput.setValue(from, to)

  if (tabRow) tabRow.style.display = 'flex'

  showTable()
  updateTabLabels()
}

/* ── 통계 정보 갱신 ── */
function updateStatistics(): void {
  const dateRange = dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = stockFilterInput?.getValue() || ''
  const filteredSells = filterTradeRows(sellHistory, dateRange.from, dateRange.to, stockQuery || undefined)
  const filteredBuys = filterTradeRows(buyHistory, dateRange.from, dateRange.to, stockQuery || undefined)

  const sellCount = filteredSells.length
  const buyCount = filteredBuys.length
  const buyAmt = filteredBuys.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const sellAmt = filteredSells.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const pnl = filteredSells.reduce((s, r) => s + Number(r.realized_pnl ?? 0), 0)
  const winCount = filteredSells.filter(r => Number(r.realized_pnl ?? 0) > 0).length
  const winRate = sellCount > 0 ? Math.round(winCount / sellCount * 10000) / 100 : 0
  const avgRate = sellCount > 0 ? Math.round(filteredSells.reduce((s, r) => s + Number(r.pnl_rate ?? 0), 0) / sellCount * 100) / 100 : 0

  if (statCountEl) statCountEl.textContent = `매도 ${sellCount}건 / 매수 ${buyCount}건`
  if (statBuyAmtEl) { statBuyAmtEl.textContent = fmtWon(buyAmt); statBuyAmtEl.style.color = COLOR.tertiary }
  if (statSellAmtEl) { statSellAmtEl.textContent = fmtWon(sellAmt); statSellAmtEl.style.color = COLOR.tertiary }
  if (statPnlEl) { statPnlEl.textContent = fmtWon(pnl); statPnlEl.style.color = pnlColor(pnl) }
  if (statWinRateEl) { statWinRateEl.textContent = `${winRate.toFixed(2)}%`; statWinRateEl.style.color = COLOR.tertiary }
  if (statAvgRateEl) { statAvgRateEl.textContent = `${avgRate > 0 ? '+' : ''}${avgRate.toFixed(2)}%`; statAvgRateEl.style.color = pnlColor(avgRate) }
}

/* ── 테이블 표시 ── */
function showTable(): void {
  if (!tableViewContainer || !drilldownViewContainer) return

  tableViewContainer.style.display = ''
  drilldownViewContainer.style.display = 'none'

  if (tabRow) tabRow.style.display = 'flex'

  const dateRange = dateRangeInput?.getValue() ?? { from: '', to: '' }
  const stockQuery = stockFilterInput?.getValue() || ''
  const isSell = activeTab === 'sell'
  let rows = isSell ? sellHistory : buyHistory
  rows = filterTradeRows(rows, dateRange.from, dateRange.to, stockQuery || undefined)

  if (!sellTable) {
    sellTable = createDataTable<Record<string, unknown>>({
      columns: SELL_COLS,
      virtualScroll: true,
      keyFn: (r, i) => `${r.stk_cd ?? ''}-${r.date ?? ''}-${r.time ?? ''}-${i}`,
      emptyText: '매도 내역이 없습니다.',
      zebraStriping: true,
    })
    tableViewContainer.appendChild(sellTable.el)
  }

  if (!buyTable) {
    buyTable = createDataTable<Record<string, unknown>>({
      columns: BUY_COLS,
      virtualScroll: true,
      keyFn: (r, i) => `${r.stk_cd ?? ''}-${r.date ?? ''}-${r.time ?? ''}-${i}`,
      emptyText: '매수 내역이 없습니다.',
      zebraStriping: true,
    })
    tableViewContainer.appendChild(buyTable.el)
  }

  sellTable.el.style.display = isSell ? '' : 'none'
  buyTable.el.style.display = isSell ? 'none' : ''

  const activeTbl = isSell ? sellTable : buyTable
  activeTbl.updateRows(rows)

  if (tabBarHandle) tabBarHandle.setActive(activeTab)

  updateStatistics()
}

/* ── mount 헬퍼: 요약 카드 행 (당일/직전/당월/누적 손익) ── */
function buildSummaryRow(todayStr: string, monthStart: string, monthEnd: string): HTMLDivElement {
  const summaryRow = document.createElement('div')
  Object.assign(summaryRow.style, { display: 'flex', gap: '8px', padding: '8px 4px', flex: 'none', borderBottom: '1px solid ' + COLOR.borderDark })

  summaryCardEls = createSummaryCards(summaryRow, {
    onTodayClick: () => {
      selectedView = 'today'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      filterByDate(todayStr)
      persistViewState()
    },
    onPrevClick: async () => {
      selectedView = 'prev'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      try {
        const prev = await api.getPrevTradingDay()
        // await 중 다른 카드/필터 클릭 시 덮어쓰기 방지
        if (selectedView !== 'prev') return
        filterByDate(prev.date)
        persistViewState()
      } catch (err) {
        console.error('[profit-detail] prev-trading-day fetch failed:', err)
      }
    },
    onMonthClick: () => {
      selectedView = 'month'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      filterByDateRange(monthStart, monthEnd)
      persistViewState()
    },
    onTotalClick: () => {
      selectedView = 'total'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      if (dateRangeInput) dateRangeInput.setValue('', '')
      drilldownActive = false
      showTable()
      updateTabLabels()
      persistViewState()
    },
  })

  return summaryRow
}

/* ── mount 헬퍼: 드릴다운 토글 버튼 클릭 콜백 ── */
function onDrilldownToggle(): void {
  drilldownActive = !drilldownActive
  if (drilldownActive) {
    selectedView = 'drilldown'
    updateCardSelection()
    updateDrilldownBtnStyle(true)
    showDrilldown()
    persistViewState()
  } else {
    selectedView = null
    updateCardSelection()
    updateDrilldownBtnStyle(false)
    showTable()
    updateTabLabels()
    persistViewState()
  }
}

/* ── mount 헬퍼: 필터 행 (날짜 범위 + 드릴다운 토글 + 종목 검색) ── */
function buildFilterRow(monthStart: string, todayStr: string): HTMLDivElement {
  const filterRow = document.createElement('div')
  Object.assign(filterRow.style, { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 4px', borderBottom: '1px solid ' + COLOR.borderLight, flexWrap: 'wrap' })

  dateRangeInput = createDateRangeInput({
    from: monthStart,
    to: todayStr,
    label: '기간:',
    onChange: () => {
      selectedView = null
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      showTable()
      updateTabLabels()
      persistViewState()
    },
  })
  filterRow.appendChild(dateRangeInput.el)

  drilldownBtnHandle = createToggleSelectBtn({
    label: '당월 일별 요약',
    active: false,
    onClick: onDrilldownToggle,
  })
  filterRow.appendChild(drilldownBtnHandle.el)

  const stockSep = document.createElement('span')
  stockSep.textContent = '|'
  stockSep.style.color = COLOR.border
  filterRow.appendChild(stockSep)

  stockFilterInput = createSearchInput({
    label: '종목명/코드',
    labelColor: COLOR.down,
    placeholder: '종목명/코드 검색',
    borderColor: COLOR.down,
    onSearch: () => { showTable(); updateTabLabels() },
  })
  filterRow.appendChild(stockFilterInput.el)

  return filterRow
}

/* ── mount 헬퍼: 탭 헤더 (매도/매수 내역) ── */
function buildTabRow(): HTMLDivElement {
  tabRow = document.createElement('div')
  Object.assign(tabRow.style, { display: 'flex', marginTop: '4px', padding: '0 4px', marginBottom: '12px' })

  tabBarHandle = createTabBar({
    tabs: [
      { id: 'sell', label: '매도 내역' },
      { id: 'buy', label: '매수 내역' },
    ],
    activeId: activeTab,
    onChange: (id) => {
      activeTab = id as LowerTab
      drilldownActive = false
      showTable()
      updateTabLabels()
    },
    fontSize: FONT_SIZE.tab,
    padding: '8px 16px',
    equalWidth: true,
    boxed: true,
  })
  sellTabBtn = tabBarHandle.buttons.get('sell') ?? null
  buyTabBtn = tabBarHandle.buttons.get('buy') ?? null
  tabRow.appendChild(tabBarHandle.el)
  return tabRow
}

/* ── mount 헬퍼: 테이블 컨테이너 (테이블 뷰 + 드릴다운 뷰) ── */
function buildTableContainer(): HTMLDivElement {
  tableContainer = document.createElement('div')
  Object.assign(tableContainer.style, { flex: '1', padding: '0 4px', overflow: 'auto' })

  tableViewContainer = document.createElement('div')
  drilldownViewContainer = document.createElement('div')
  drilldownViewContainer.style.display = 'none'

  tableContainer.appendChild(tableViewContainer)
  tableContainer.appendChild(drilldownViewContainer)
  return tableContainer
}

/* ── mount 헬퍼: 통계 정보 행 (총 건수/매수금액/매도금액/실현손익/승률/평균 수익률) ── */
function buildStatRow(): HTMLDivElement {
  const statRow = document.createElement('div')
  Object.assign(statRow.style, { display: 'flex', gap: '8px', padding: '6px 4px', borderTop: '1px solid ' + COLOR.borderLight, flex: 'none' })

  const STAT_STYLE = `flex:1;background:${COLOR.surfaceLight};border:1px solid ${COLOR.borderLight};border-radius:4px;padding:4px 8px;display:flex;flex-direction:column;align-items:center;gap:2px;`
  const STAT_LABELS = ['총 건수', '매수금액', '매도금액', '실현손익', '승률', '평균 수익률']
  const statEls: HTMLSpanElement[] = []
  statCardEls = []

  for (let i = 0; i < 6; i++) {
    const stat = document.createElement('div')
    stat.style.cssText = STAT_STYLE

    const labelEl = document.createElement('span')
    Object.assign(labelEl.style, { fontSize: FONT_SIZE.section, color: COLOR.tertiary })
    labelEl.textContent = STAT_LABELS[i]

    const valEl = document.createElement('span')
    Object.assign(valEl.style, { fontSize: FONT_SIZE.section, fontWeight: 'normal' })
    valEl.textContent = '-'

    stat.appendChild(labelEl)
    stat.appendChild(valEl)
    statRow.appendChild(stat)

    statEls.push(valEl)
    statCardEls.push(stat)
  }

  statCountEl = statEls[0]
  statBuyAmtEl = statEls[1]
  statSellAmtEl = statEls[2]
  statPnlEl = statEls[3]
  statWinRateEl = statEls[4]
  statAvgRateEl = statEls[5]

  return statRow
}

/* ── mount 헬퍼: 초기 데이터 반영 + 저장된 뷰 상태 복원 ── */
function restoreInitialView(todayStr: string, initState: ReturnType<typeof hotStore.getState>): void {
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  updateTabLabels()

  // 저장된 뷰 상태 복원 — 없으면 기본값 'today'
  const savedView = loadProfitDetailView()
  if (savedView) {
    selectedView = savedView.selectedView
    drilldownActive = savedView.drilldownActive
    if (dateRangeInput) dateRangeInput.setValue(savedView.from, savedView.to)
    updateCardSelection()
    if (savedView.drilldownActive) {
      updateDrilldownBtnStyle(true)
      showDrilldown()
    } else {
      updateDrilldownBtnStyle(false)
      showTable()
      updateTabLabels()
    }
  } else {
    selectedView = 'today'
    updateCardSelection()
    filterByDate(todayStr)
  }
  if (summaryCardEls) {
    updateSummaryCards(sellHistory, initState.dailySummary, summaryCardEls)
  }
}

/* ── mount 헬퍼: rAF 배칭 렌더 (dirty 플래그 기반 selective update) ── */
function flushDirtyRender(): void {
  _rafId = null
  if (!_mounted) return

  if (_dirtyHistory) {
    _dirtyHistory = false
    if (drilldownActive) {
      showDrilldown()
    } else {
      showTable()
    }
    updateTabLabels()
    if (summaryCardEls) {
      updateSummaryCards(sellHistory, hotStore.getState().dailySummary, summaryCardEls)
    }
  }

  if (_dirtySummary) {
    _dirtySummary = false
    if (summaryCardEls) {
      updateSummaryCards(sellHistory, hotStore.getState().dailySummary, summaryCardEls)
    }
  }

  if (_dirtySectorStocks) {
    _dirtySectorStocks = false
    if (drilldownActive) {
      showDrilldown()
    } else {
      showTable()
    }
  }
}

/* ── mount 헬퍼: hotStore 구독 (rAF 배칭 + selective update) ── */
function subscribeProfitDetailStore(initState: ReturnType<typeof hotStore.getState>): void {
  let prevSellRef = initState.sellHistory
  let prevBuyRef = initState.buyHistory
  let prevDailySummaryRef = initState.dailySummary
  let prevSectorStocksRef = initState.sectorStocks
  _mounted = true

  unsubStore = hotStore.subscribe((curr) => {
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const summaryChanged = curr.dailySummary !== prevDailySummaryRef
    const sectorStocksChanged = curr.sectorStocks !== prevSectorStocksRef

    if (!historyChanged && !summaryChanged && !sectorStocksChanged) return

    if (historyChanged) {
      prevSellRef = curr.sellHistory
      prevBuyRef = curr.buyHistory
      sellHistory = curr.sellHistory
      buyHistory = curr.buyHistory
      _dirtyHistory = true
    }
    if (summaryChanged) {
      prevDailySummaryRef = curr.dailySummary
      _dirtySummary = true
    }
    if (sectorStocksChanged) {
      prevSectorStocksRef = curr.sectorStocks
      _dirtySectorStocks = true
    }

    if (_rafId !== null) return
    _rafId = requestAnimationFrame(flushDirtyRender)
  })
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-detail')
  buyHistory = []
  sellHistory = []
  activeTab = 'sell'
  drilldownActive = true

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  root.appendChild(createCardTitle('수익 상세'))

  const todayStr = getLocalToday()
  const monthStart = todayStr.slice(0, 8) + '01'
  const monthEnd = todayStr.slice(0, 8) + '31'

  root.appendChild(buildSummaryRow(todayStr, monthStart, monthEnd))

  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', overflow: 'auto', display: 'flex', flexDirection: 'column' })
  lower.appendChild(buildFilterRow(monthStart, todayStr))
  lower.appendChild(buildTabRow())
  lower.appendChild(buildTableContainer())
  lower.appendChild(buildStatRow())
  root.appendChild(lower)
  container.appendChild(root)

  const initState = hotStore.getState()
  restoreInitialView(todayStr, initState)
  subscribeProfitDetailStore(initState)
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  notifyPageInactive('profit-detail')
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  _dirtyHistory = false
  _dirtySummary = false
  _dirtySectorStocks = false
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (sellTable) { sellTable.destroy(); sellTable = null }
  if (buyTable) { buyTable.destroy(); buyTable = null }
  if (drilldownTable) { drilldownTable.destroy(); drilldownTable = null }
  drilldownActive = false
  drilldownBtnHandle = null
  selectedView = null
  tabRow = null
  tabBarHandle = null
  buyHistory = []
  sellHistory = []
  sellTabBtn = null
  buyTabBtn = null
  tableContainer = null
  tableViewContainer = null
  drilldownViewContainer = null
  dateRangeInput = null
  stockFilterInput = null
  statCountEl = null
  statBuyAmtEl = null
  statSellAmtEl = null
  statPnlEl = null
  statWinRateEl = null
  statAvgRateEl = null
  statCardEls = []
  summaryCardEls = null
}

export default { mount, unmount }
