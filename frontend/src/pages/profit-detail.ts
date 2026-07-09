// frontend/src/pages/profit-detail.ts
// 수익 상세 페이지 — Vanilla TS PageModule
// 차트(크게) + 드릴다운 + 날짜/종목 필터 + 전체 거래내역(가상 스크롤) + 통계 정보

import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import {
  BUY_COLS,
  SELL_COLS,
  type DailyDrilldownRow,
  type SummaryCardEls,
  getLocalToday,
  buildMonthlyDrilldown,
  createDrilldownCols,
  createSummaryCards,
  updateSummaryCards,
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
let tableContainer: HTMLDivElement | null = null
let tableViewContainer: HTMLDivElement | null = null
let drilldownViewContainer: HTMLDivElement | null = null
let dateFromInput: HTMLInputElement | null = null
let dateToInput: HTMLInputElement | null = null
let stockFilterInput: HTMLInputElement | null = null
let unsubStore: (() => void) | null = null

/* ── 드릴다운 상태 ── */
let drilldownActive = true
let drilldownTable: DataTableApi<DailyDrilldownRow> | null = null
let drilldownCols: ColumnDef<DailyDrilldownRow>[] = []
let tabRow: HTMLDivElement | null = null
let drilldownBtnEl: HTMLButtonElement | null = null

type SelectedView = 'today' | 'month' | 'total' | 'drilldown' | null
let selectedView: SelectedView = null

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
function applyCardStyle(card: HTMLDivElement, active: boolean): void {
  Object.assign(card.style, {
    border: active ? '2px solid ' + COLOR.down : '1px solid #eee',
    background: active ? COLOR.downBg : '#fafafa',
  })
}

function updateCardSelection(): void {
  if (!summaryCardEls) return
  applyCardStyle(summaryCardEls.todayCard, selectedView === 'today')
  applyCardStyle(summaryCardEls.monthCard, selectedView === 'month')
  applyCardStyle(summaryCardEls.totalCard, selectedView === 'total')
}

function updateDrilldownBtnStyle(active: boolean): void {
  if (!drilldownBtnEl) return
  Object.assign(drilldownBtnEl.style, {
    border: active ? '2px solid ' + COLOR.down : '1px solid #eee',
    background: active ? COLOR.downBg : '#fff',
    color: active ? COLOR.down : COLOR.secondary,
  })
}

/* ── 탭 버튼 스타일 ── */
function applyTabStyle(btn: HTMLButtonElement, active: boolean): void {
  Object.assign(btn.style, {
    flex: '1',
    padding: '8px 0',
    cursor: 'pointer',
    border: 'none',
    background: 'transparent',
    borderBottom: active ? '2px solid ' + COLOR.down : '2px solid transparent',
    fontWeight: active ? FONT_WEIGHT.normal : FONT_WEIGHT.normal,
    color: active ? COLOR.down : COLOR.tertiary,
    fontSize: FONT_SIZE.label,
    textAlign: 'center',
  })
}

/* ── 탭 헤더 텍스트 업데이트 ── */
function updateTabLabels(): void {
  const dateFrom = dateFromInput?.value || ''
  const dateTo = dateToInput?.value || ''
  const stockQuery = stockFilterInput?.value.trim() || ''
  const filteredSells = filterRows(sellHistory, dateFrom, dateTo, stockQuery || undefined)
  const filteredBuys = filterRows(buyHistory, dateFrom, dateTo, stockQuery || undefined)
  if (sellTabBtn) {
    sellTabBtn.textContent = `매도 내역 (${filteredSells.length}건)`
  }
  if (buyTabBtn) {
    buyTabBtn.textContent = `매수 내역 (${filteredBuys.length}건)`
  }
}

/* ── 날짜 + 종목 필터 ── */
function filterRows(rows: Record<string, unknown>[], dateFrom: string, dateTo: string, stockQuery?: string): Record<string, unknown>[] {
  return rows.filter(r => {
    const d = String(r.date ?? '')
    if (dateFrom && d < dateFrom) return false
    if (dateTo && d > dateTo) return false
    if (stockQuery) {
      const code = String(r.stk_cd ?? '')
      const name = String(r.stk_nm ?? '')
      if (!code.includes(stockQuery) && !name.includes(stockQuery)) return false
    }
    return true
  })
}

/* ── 드릴다운 테이블 표시 ── */
function showDrilldown(): void {
  if (!tableViewContainer || !drilldownViewContainer) return

  tableViewContainer.style.display = 'none'
  drilldownViewContainer.style.display = ''

  if (tabRow) tabRow.style.display = 'none'

  if (!drilldownTable) {
    drilldownCols = createDrilldownCols(filterByDate)
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

  if (dateFromInput) dateFromInput.value = date
  if (dateToInput) dateToInput.value = date

  if (tabRow) tabRow.style.display = 'flex'

  showTable()
  updateTabLabels()
}

/* ── 날짜 범위 필터 ── */
function filterByDateRange(from: string, to: string): void {
  drilldownActive = false

  if (dateFromInput) dateFromInput.value = from
  if (dateToInput) dateToInput.value = to

  if (tabRow) tabRow.style.display = 'flex'

  showTable()
  updateTabLabels()
}

/* ── 통계 정보 갱신 ── */
function updateStatistics(): void {
  const dateFrom = dateFromInput?.value || ''
  const dateTo = dateToInput?.value || ''
  const stockQuery = stockFilterInput?.value.trim() || ''
  const filteredSells = filterRows(sellHistory, dateFrom, dateTo, stockQuery || undefined)
  const filteredBuys = filterRows(buyHistory, dateFrom, dateTo, stockQuery || undefined)

  const sellCount = filteredSells.length
  const buyCount = filteredBuys.length
  const buyAmt = filteredBuys.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const sellAmt = filteredSells.reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const pnl = filteredSells.reduce((s, r) => s + Number(r.realized_pnl ?? 0), 0)
  const winCount = filteredSells.filter(r => Number(r.realized_pnl ?? 0) > 0).length
  const winRate = sellCount > 0 ? Math.round(winCount / sellCount * 10000) / 100 : 0
  const avgRate = sellCount > 0 ? Math.round(filteredSells.reduce((s, r) => s + Number(r.pnl_rate ?? 0), 0) / sellCount * 100) / 100 : 0

  if (statCountEl) statCountEl.textContent = `매도 ${sellCount}건 / 매수 ${buyCount}건`
  if (statBuyAmtEl) { statBuyAmtEl.textContent = fmtWon(buyAmt); statBuyAmtEl.style.color = COLOR.secondary }
  if (statSellAmtEl) { statSellAmtEl.textContent = fmtWon(sellAmt); statSellAmtEl.style.color = COLOR.secondary }
  if (statPnlEl) { statPnlEl.textContent = fmtWon(pnl); statPnlEl.style.color = pnlColor(pnl) }
  if (statWinRateEl) { statWinRateEl.textContent = `${winRate.toFixed(2)}%`; statWinRateEl.style.color = COLOR.secondary }
  if (statAvgRateEl) { statAvgRateEl.textContent = `${avgRate > 0 ? '+' : ''}${avgRate.toFixed(2)}%`; statAvgRateEl.style.color = pnlColor(avgRate) }
}

/* ── 테이블 표시 ── */
function showTable(): void {
  if (!tableViewContainer || !drilldownViewContainer) return

  tableViewContainer.style.display = ''
  drilldownViewContainer.style.display = 'none'

  if (tabRow) tabRow.style.display = 'flex'

  const dateFrom = dateFromInput?.value || ''
  const dateTo = dateToInput?.value || ''
  const stockQuery = stockFilterInput?.value.trim() || ''
  const isSell = activeTab === 'sell'
  let rows = isSell ? sellHistory : buyHistory
  rows = filterRows(rows, dateFrom, dateTo, stockQuery || undefined)

  const displayRows = rows

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
  activeTbl.updateRows(displayRows)

  if (sellTabBtn) applyTabStyle(sellTabBtn, activeTab === 'sell')
  if (buyTabBtn) applyTabStyle(buyTabBtn, activeTab === 'buy')

  updateStatistics()
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

  /* ── 상단: 요약 카드 3개 ── */
  const todayStr = getLocalToday()
  const monthStart = todayStr.slice(0, 8) + '01'
  const monthEnd = todayStr.slice(0, 8) + '31'

  const summaryRow = document.createElement('div')
  Object.assign(summaryRow.style, { display: 'flex', gap: '8px', padding: '8px 4px', flex: 'none', borderBottom: '1px solid #ddd' })

  summaryCardEls = createSummaryCards(summaryRow, {
    onTodayClick: () => {
      selectedView = 'today'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      filterByDate(todayStr)
    },
    onMonthClick: () => {
      selectedView = 'month'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      filterByDateRange(monthStart, monthEnd)
    },
    onTotalClick: () => {
      selectedView = 'total'
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      if (dateFromInput) dateFromInput.value = ''
      if (dateToInput) dateToInput.value = ''
      drilldownActive = false
      showTable()
      updateTabLabels()
    },
  })

  root.appendChild(summaryRow)

  /* ── 하단: 필터 + 드릴다운/거래내역 + 통계 ── */
  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', overflow: 'auto', display: 'flex', flexDirection: 'column' })

  // 필터 행 (날짜 + 종목 + 드릴다운 토글)
  const filterRow = document.createElement('div')
  Object.assign(filterRow.style, { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 4px', borderBottom: '1px solid #eee', flexWrap: 'wrap' })

  const filterLabel = document.createElement('span')
  Object.assign(filterLabel.style, { fontSize: FONT_SIZE.label, color: COLOR.secondary, whiteSpace: 'nowrap' })
  filterLabel.textContent = '기간:'
  filterRow.appendChild(filterLabel)

  dateFromInput = document.createElement('input')
  dateFromInput.type = 'date'
  dateFromInput.value = monthStart
  Object.assign(dateFromInput.style, { padding: '2px 4px', fontSize: FONT_SIZE.label, border: '1px solid #eee', borderRadius: '4px', color: COLOR.code })
  filterRow.appendChild(dateFromInput)

  const dateSep = document.createElement('span')
  dateSep.textContent = '~'
  dateSep.style.color = '#ccc'
  filterRow.appendChild(dateSep)

  dateToInput = document.createElement('input')
  dateToInput.type = 'date'
  dateToInput.value = todayStr
  Object.assign(dateToInput.style, { padding: '2px 4px', fontSize: FONT_SIZE.label, border: '1px solid #eee', borderRadius: '4px', color: COLOR.code })
  filterRow.appendChild(dateToInput)

  const clearBtn = document.createElement('button')
  Object.assign(clearBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.label, border: '1px solid #eee', borderRadius: '4px', background: '#fff', cursor: 'pointer', color: COLOR.secondary })
  clearBtn.textContent = '전체'
  clearBtn.addEventListener('click', (e) => {
    selectedView = 'total'
    updateCardSelection()
    updateDrilldownBtnStyle(false)
    if (dateFromInput) dateFromInput.value = ''
    if (dateToInput) dateToInput.value = ''
    drilldownActive = false
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })
  filterRow.appendChild(clearBtn)

  // 종목 필터
  const stockSep = document.createElement('span')
  stockSep.textContent = '|'
  stockSep.style.color = '#ccc'
  filterRow.appendChild(stockSep)

  const stockLabel = document.createElement('span')
  Object.assign(stockLabel.style, { fontSize: FONT_SIZE.label, color: COLOR.secondary, whiteSpace: 'nowrap' })
  stockLabel.textContent = '종목:'
  filterRow.appendChild(stockLabel)

  stockFilterInput = document.createElement('input')
  stockFilterInput.type = 'text'
  stockFilterInput.placeholder = '종목명/코드'
  Object.assign(stockFilterInput.style, { padding: '2px 4px', fontSize: FONT_SIZE.label, border: '1px solid #eee', borderRadius: '4px', color: COLOR.code, width: '100px' })
  stockFilterInput.addEventListener('input', () => { showTable(); updateTabLabels() })
  filterRow.appendChild(stockFilterInput)

  // 드릴다운 토글 버튼
  drilldownBtnEl = document.createElement('button')
  Object.assign(drilldownBtnEl.style, { padding: '2px 8px', fontSize: FONT_SIZE.label, border: '1px solid #eee', borderRadius: '4px', background: '#fff', cursor: 'pointer', color: COLOR.secondary, marginLeft: 'auto' })
  drilldownBtnEl.textContent = '당월 일별 요약'
  drilldownBtnEl.addEventListener('click', (e) => {
    drilldownActive = !drilldownActive
    if (drilldownActive) {
      selectedView = 'drilldown'
      updateCardSelection()
      updateDrilldownBtnStyle(true)
      showDrilldown()
    } else {
      selectedView = null
      updateCardSelection()
      updateDrilldownBtnStyle(false)
      showTable()
      updateTabLabels()
    }
    ;(e.target as HTMLElement).blur()
  })
  filterRow.appendChild(drilldownBtnEl)

  lower.appendChild(filterRow)

  // 탭 헤더
  tabRow = document.createElement('div')
  Object.assign(tabRow.style, { display: 'flex', borderBottom: '1px solid #eee', marginBottom: '8px' })

  sellTabBtn = document.createElement('button')
  applyTabStyle(sellTabBtn, true)
  sellTabBtn.addEventListener('click', (e) => {
    activeTab = 'sell'
    drilldownActive = false
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })

  buyTabBtn = document.createElement('button')
  applyTabStyle(buyTabBtn, false)
  buyTabBtn.addEventListener('click', (e) => {
    activeTab = 'buy'
    drilldownActive = false
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })

  tabRow.appendChild(sellTabBtn)
  tabRow.appendChild(buyTabBtn)
  lower.appendChild(tabRow)

  // 테이블 컨테이너 (테이블 뷰 + 드릴다운 뷰)
  tableContainer = document.createElement('div')
  Object.assign(tableContainer.style, { flex: '1', padding: '0 4px', overflow: 'auto' })

  tableViewContainer = document.createElement('div')
  drilldownViewContainer = document.createElement('div')
  drilldownViewContainer.style.display = 'none'

  tableContainer.appendChild(tableViewContainer)
  tableContainer.appendChild(drilldownViewContainer)

  lower.appendChild(tableContainer)

  // 통계 정보 행
  const statRow = document.createElement('div')
  Object.assign(statRow.style, { display: 'flex', gap: '8px', padding: '6px 4px', borderTop: '1px solid #eee', flex: 'none' })

  const STAT_STYLE = `flex:1;background:#fafafa;border:1px solid #eee;border-radius:4px;padding:4px 8px;display:flex;flex-direction:column;align-items:center;gap:2px;`
  const STAT_LABELS = ['총 건수', '매수금액', '매도금액', '실현손익', '승률', '평균 수익률']
  const statEls: HTMLSpanElement[] = []

  for (let i = 0; i < 6; i++) {
    const stat = document.createElement('div')
    stat.style.cssText = STAT_STYLE

    const labelEl = document.createElement('span')
    Object.assign(labelEl.style, { fontSize: FONT_SIZE.label, color: COLOR.secondary })
    labelEl.textContent = STAT_LABELS[i]

    const valEl = document.createElement('span')
    Object.assign(valEl.style, { fontSize: FONT_SIZE.label, fontWeight: 'normal' })
    valEl.textContent = '-'

    stat.appendChild(labelEl)
    stat.appendChild(valEl)
    statRow.appendChild(stat)

    statEls.push(valEl)
  }

  statCountEl = statEls[0]
  statBuyAmtEl = statEls[1]
  statSellAmtEl = statEls[2]
  statPnlEl = statEls[3]
  statWinRateEl = statEls[4]
  statAvgRateEl = statEls[5]

  lower.appendChild(statRow)

  root.appendChild(lower)
  container.appendChild(root)

  // 날짜 필터 변경 이벤트
  dateFromInput.addEventListener('change', () => {
    selectedView = null
    updateCardSelection()
    updateDrilldownBtnStyle(false)
    showTable()
    updateTabLabels()
  })
  dateToInput.addEventListener('change', () => {
    selectedView = null
    updateCardSelection()
    updateDrilldownBtnStyle(false)
    showTable()
    updateTabLabels()
  })

  // 초기 데이터 반영
  const initState = hotStore.getState()
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  updateTabLabels()
  selectedView = 'today'
  updateCardSelection()
  filterByDate(todayStr)
  if (summaryCardEls) {
    updateSummaryCards(sellHistory, initState.dailySummary, summaryCardEls)
  }

  // hotStore 구독 — rAF 배칭 + selective update
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

    _rafId = requestAnimationFrame(() => {
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
    })
  })
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
  drilldownCols = []
  drilldownBtnEl = null
  selectedView = null
  tabRow = null
  buyHistory = []
  sellHistory = []
  sellTabBtn = null
  buyTabBtn = null
  tableContainer = null
  tableViewContainer = null
  drilldownViewContainer = null
  dateFromInput = null
  dateToInput = null
  stockFilterInput = null
  statCountEl = null
  statBuyAmtEl = null
  statSellAmtEl = null
  statPnlEl = null
  statWinRateEl = null
  statAvgRateEl = null
  summaryCardEls = null
}

export default { mount, unmount }
