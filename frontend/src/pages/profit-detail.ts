// frontend/src/pages/profit-detail.ts
// 수익 상세 페이지 — Vanilla TS PageModule
// profit-overview에서 차트/요약/계좌를 재사용하되, 전체 거래내역(가상 스크롤 + 날짜 필터)에 집중

import { createProfitChart, type ProfitChartApi } from '../components/canvas-profit-chart'
import { createDataTable, type DataTableApi } from '../components/common/data-table'
import { globalSettingsManager } from '../settings'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { sectionTitle } from '../components/common/settings-common'
import { ACCOUNT_LABELS_REAL, ACCOUNT_LABELS_TEST } from '../components/common/account-labels'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import {
  BUY_COLS,
  SELL_COLS,
  DUMMY_BUY,
  DUMMY_SELL,
  getLocalToday,
  aggregatePnl,
  buildChartFromDailySummary,
  renderAccountVals as renderAccountValsShared,
  type AccountValsParams,
} from './profit-shared'

/* ── 헬퍼 ── */

const ROW_CSS = `display:flex;justify-content:space-between;padding:7px 4px;border-bottom:1px solid #f0f0f0;font-size:${FONT_SIZE.label};`

/* ── 모듈 변수 ── */
type LowerTab = 'buy' | 'sell'

let chart: ProfitChartApi | null = null
let accountValRefs: HTMLSpanElement[] = []
let testAccountValRefs: HTMLSpanElement[] = []
let holdingCountSpan: HTMLSpanElement | null = null
let holdingCountSpanTest: HTMLSpanElement | null = null
let realAccountContainer: HTMLDivElement | null = null
let testAccountContainer: HTMLDivElement | null = null
let buyHistory: Record<string, unknown>[] = []
let sellHistory: Record<string, unknown>[] = []
let activeTab: LowerTab = 'sell'
let sellTable: DataTableApi<Record<string, unknown>> | null = null
let buyTable: DataTableApi<Record<string, unknown>> | null = null
let sellTabBtn: HTMLButtonElement | null = null
let buyTabBtn: HTMLButtonElement | null = null
let tableContainer: HTMLDivElement | null = null
let dateFromInput: HTMLInputElement | null = null
let dateToInput: HTMLInputElement | null = null
let dummyMsg: HTMLDivElement | null = null
let unsubAccount: (() => void) | null = null

/* ── rAF 배칭 상태 ── */
let _rafId: number | null = null
let _mounted = false
let _dirtyAccount = false
let _dirtyHistory = false
let _dirtyChart = false
let _dirtySectorStocks = false

/* ── 요약 카드 DOM 참조 ── */
let todayPnlEl: HTMLSpanElement | null = null
let todayRateEl: HTMLSpanElement | null = null
let monthPnlEl: HTMLSpanElement | null = null
let monthRateEl: HTMLSpanElement | null = null
let totalPnlEl: HTMLSpanElement | null = null
let totalRateEl: HTMLSpanElement | null = null

/* ── 계좌 현황 렌더 (shared 순수 함수 래핑) ── */
function renderAccountVals(): void {
  const state = hotStore.getState()
  const settings = globalSettingsManager.getSettings()
  const params: AccountValsParams = {
    account: state.account,
    positionCount: state.positionCount ?? 0,
    isTestMode: settings?.trade_mode === 'test',
    buyHistory,
    sellHistory,
    realAccountContainer,
    testAccountContainer,
    accountValRefs,
    testAccountValRefs,
    holdingCountSpan,
    holdingCountSpanTest,
  }
  renderAccountValsShared(params)
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
  const filteredSells = filterRows(sellHistory, dateFrom, dateTo)
  const filteredBuys = filterRows(buyHistory, dateFrom, dateTo)
  if (sellTabBtn) {
    sellTabBtn.textContent = `매도 내역 (${filteredSells.length}건)`
  }
  if (buyTabBtn) {
    buyTabBtn.textContent = `매수 내역 (${filteredBuys.length}건)`
  }
}

/* ── 날짜 필터 ── */
function filterRows(rows: Record<string, unknown>[], dateFrom: string, dateTo: string): Record<string, unknown>[] {
  if (!dateFrom && !dateTo) return rows
  return rows.filter(r => {
    const d = String(r.date ?? '')
    if (dateFrom && d < dateFrom) return false
    if (dateTo && d > dateTo) return false
    return true
  })
}

/* ── 요약 카드 갱신 ── */
function updateSummaryCards(): void {
  const today = getLocalToday()
  const yearMonth = today.slice(0, 7)

  const dailySummary = hotStore.getState().dailySummary
  const todayEntry = dailySummary.find(r => String(r.date ?? '') === today)
  const dayPnl = todayEntry ? Number(todayEntry.realized_pnl ?? 0) : 0
  const dayRate = todayEntry ? Number(todayEntry.pnl_rate ?? 0) : 0

  const monS = aggregatePnl(sellHistory, yearMonth + '-01', yearMonth + '-31')
  const allS = aggregatePnl(sellHistory)

  if (todayPnlEl) { todayPnlEl.textContent = fmtWon(dayPnl); todayPnlEl.style.color = pnlColor(dayPnl) }
  if (todayRateEl) { todayRateEl.textContent = `${dayRate.toFixed(2)}%`; todayRateEl.style.color = pnlColor(dayPnl) }
  if (monthPnlEl) { monthPnlEl.textContent = fmtWon(monS.pnl); monthPnlEl.style.color = pnlColor(monS.pnl) }
  if (monthRateEl) { monthRateEl.textContent = `${monS.rate.toFixed(2)}%`; monthRateEl.style.color = pnlColor(monS.pnl) }
  if (totalPnlEl) { totalPnlEl.textContent = fmtWon(allS.pnl); totalPnlEl.style.color = pnlColor(allS.pnl) }
  if (totalRateEl) { totalRateEl.textContent = `${allS.rate.toFixed(2)}%`; totalRateEl.style.color = pnlColor(allS.pnl) }
}

/* ── 테이블 표시 ── */
function showTable(): void {
  if (!tableContainer) return

  const dateFrom = dateFromInput?.value || ''
  const dateTo = dateToInput?.value || ''
  const isSell = activeTab === 'sell'
  let rows = isSell ? sellHistory : buyHistory
  rows = filterRows(rows, dateFrom, dateTo)

  const isDummy = rows.length === 0 && !dateFrom && !dateTo
  const displayRows = isDummy ? (isSell ? DUMMY_SELL : DUMMY_BUY) : rows

  if (!sellTable) {
    sellTable = createDataTable<Record<string, unknown>>({
      columns: SELL_COLS,
      virtualScroll: true,
      keyFn: (r, i) => `${r.stk_cd ?? ''}-${r.date ?? ''}-${r.time ?? ''}-${i}`,
      emptyText: '매도 내역이 없습니다.',
      zebraStriping: true,
    })
    tableContainer.appendChild(sellTable.el)
  }

  if (!buyTable) {
    buyTable = createDataTable<Record<string, unknown>>({
      columns: BUY_COLS,
      virtualScroll: true,
      keyFn: (r, i) => `${r.stk_cd ?? ''}-${r.date ?? ''}-${r.time ?? ''}-${i}`,
      emptyText: '매수 내역이 없습니다.',
      zebraStriping: true,
    })
    tableContainer.appendChild(buyTable.el)
  }

  sellTable.el.style.display = isSell ? '' : 'none'
  buyTable.el.style.display = isSell ? 'none' : ''

  const activeTbl = isSell ? sellTable : buyTable
  activeTbl.updateRows(displayRows)

  if (dummyMsg) dummyMsg.remove()
  if (isDummy) {
    dummyMsg = document.createElement('div')
    Object.assign(dummyMsg.style, { textAlign: 'center', fontSize: FONT_SIZE.badge, color: COLOR.disabled, marginTop: '-4px' })
    dummyMsg.textContent = '거래 체결 시 자동으로 표시됩니다'
    tableContainer.appendChild(dummyMsg)
  }

  if (sellTabBtn) applyTabStyle(sellTabBtn, activeTab === 'sell')
  if (buyTabBtn) applyTabStyle(buyTabBtn, activeTab === 'buy')
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-detail')
  buyHistory = []
  sellHistory = []
  activeTab = 'sell'
  accountValRefs = []

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  root.appendChild(createCardTitle('수익 상세'))

  const settings = globalSettingsManager.getSettings()
  const isTestMode = settings?.trade_mode === 'test'

  /* ── 상단: 전체 너비 차트 (300px) ── */
  const chartPanel = document.createElement('div')
  Object.assign(chartPanel.style, { flex: 'none', borderBottom: '1px solid #ddd', overflow: 'hidden', padding: '0 4px' })

  const chartTitle = document.createElement('div')
  Object.assign(chartTitle.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.normal, color: COLOR.down, padding: '10px 0 6px', borderBottom: '2px solid #eee', marginBottom: '8px' })
  const chartTitleText = document.createElement('span')
  chartTitleText.textContent = '일별 수익률'
  const retentionLabel = document.createElement('span')
  Object.assign(retentionLabel.style, { fontSize: '11px', color: COLOR.disabled, fontWeight: 'normal' })
  retentionLabel.textContent = isTestMode ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
  chartTitle.appendChild(chartTitleText)
  chartTitle.appendChild(retentionLabel)
  chartPanel.appendChild(chartTitle)

  const chartContainer = document.createElement('div')
  chartPanel.appendChild(chartContainer)

  root.appendChild(chartPanel)

  /* ── 요약 카드 3개 ── */
  const summaryRow = document.createElement('div')
  Object.assign(summaryRow.style, { display: 'flex', gap: '8px', padding: '8px 4px' })

  const CARD_STYLE = `flex:1;background:#fafafa;border:1px solid #eee;border-radius:6px;padding:6px 12px;display:flex;justify-content:space-between;align-items:center;`
  const CARD_TITLES = ['당일 손익', '당월 손익', '누적 손익']

  const pnlEls: HTMLSpanElement[] = []
  const rateEls: HTMLSpanElement[] = []

  for (let i = 0; i < 3; i++) {
    const card = document.createElement('div')
    card.style.cssText = CARD_STYLE

    const titleEl = document.createElement('div')
    Object.assign(titleEl.style, { fontSize: FONT_SIZE.badge, color: COLOR.secondary, whiteSpace: 'nowrap' })
    titleEl.textContent = CARD_TITLES[i]

    const valRow = document.createElement('div')
    Object.assign(valRow.style, { display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', gap: '6px' })

    const pnlEl = document.createElement('span')
    Object.assign(pnlEl.style, { fontSize: FONT_SIZE.section, fontWeight: 'normal' })
    pnlEl.textContent = fmtWon(0)

    const rateEl = document.createElement('span')
    Object.assign(rateEl.style, { fontSize: FONT_SIZE.label, color: COLOR.neutral })
    rateEl.textContent = '0.00%'

    valRow.appendChild(pnlEl)
    valRow.appendChild(rateEl)
    card.appendChild(titleEl)
    card.appendChild(valRow)
    summaryRow.appendChild(card)

    pnlEls.push(pnlEl)
    rateEls.push(rateEl)
  }

  todayPnlEl = pnlEls[0]; todayRateEl = rateEls[0]
  monthPnlEl = pnlEls[1]; monthRateEl = rateEls[1]
  totalPnlEl = pnlEls[2]; totalRateEl = rateEls[2]

  root.appendChild(summaryRow)

  /* ── 계좌 현황 ── */
  const accountPanel = document.createElement('div')
  Object.assign(accountPanel.style, { flex: 'none', borderBottom: '1px solid #ddd', padding: '0 4px' })

  const accountHeader = sectionTitle('계좌 현황')
  accountHeader.style.color = COLOR.down
  accountPanel.appendChild(accountHeader)

  realAccountContainer = document.createElement('div')
  realAccountContainer.style.display = isTestMode ? 'none' : ''
  for (let i = 0; i < ACCOUNT_LABELS_REAL.length; i++) {
    const row = document.createElement('div')
    row.style.cssText = ROW_CSS
    if (i % 2 === 1) row.style.backgroundColor = '#f9f9f9'
    const label = document.createElement('span')
    if (i === 4) {
      label.appendChild(document.createTextNode('보유주식 평가금액 ('))
      const cntSpan = document.createElement('span')
      cntSpan.style.color = COLOR.down
      cntSpan.style.fontWeight = 'bold'
      label.appendChild(cntSpan)
      label.appendChild(document.createTextNode('종목)'))
      holdingCountSpan = cntSpan
    } else {
      label.textContent = ACCOUNT_LABELS_REAL[i]
    }
    const val = document.createElement('span')
    Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })
    row.appendChild(label)
    row.appendChild(val)
    realAccountContainer.appendChild(row)
    accountValRefs.push(val)
  }
  accountPanel.appendChild(realAccountContainer)

  testAccountContainer = document.createElement('div')
  testAccountContainer.style.display = isTestMode ? '' : 'none'
  for (let i = 0; i < ACCOUNT_LABELS_TEST.length; i++) {
    const row = document.createElement('div')
    row.style.cssText = ROW_CSS
    if (i % 2 === 1) row.style.backgroundColor = '#f9f9f9'
    const label = document.createElement('span')
    if (i === 4) {
      label.appendChild(document.createTextNode('보유주식 평가금액 ('))
      const cntSpan = document.createElement('span')
      cntSpan.style.color = COLOR.down
      cntSpan.style.fontWeight = 'bold'
      label.appendChild(cntSpan)
      label.appendChild(document.createTextNode('종목)'))
      holdingCountSpanTest = cntSpan
    } else {
      label.textContent = ACCOUNT_LABELS_TEST[i]
    }
    const val = document.createElement('span')
    Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })
    row.appendChild(label)
    row.appendChild(val)
    testAccountContainer.appendChild(row)
    testAccountValRefs.push(val)
  }
  accountPanel.appendChild(testAccountContainer)

  root.appendChild(accountPanel)

  /* ── 하단: 날짜 필터 + 거래내역 (가상 스크롤) ── */
  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', overflow: 'auto', display: 'flex', flexDirection: 'column' })

  // 날짜 필터 행
  const filterRow = document.createElement('div')
  Object.assign(filterRow.style, { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 4px', borderBottom: '1px solid #eee' })

  const filterLabel = document.createElement('span')
  Object.assign(filterLabel.style, { fontSize: FONT_SIZE.label, color: COLOR.secondary, whiteSpace: 'nowrap' })
  filterLabel.textContent = '기간:'
  filterRow.appendChild(filterLabel)

  dateFromInput = document.createElement('input')
  dateFromInput.type = 'date'
  const todayStr = getLocalToday()
  const monthStart = todayStr.slice(0, 8) + '01'
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
    if (dateFromInput) dateFromInput.value = ''
    if (dateToInput) dateToInput.value = ''
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })
  filterRow.appendChild(clearBtn)

  lower.appendChild(filterRow)

  // 탭 헤더
  const tabRow = document.createElement('div')
  Object.assign(tabRow.style, { display: 'flex', borderBottom: '1px solid #eee', marginBottom: '8px' })

  sellTabBtn = document.createElement('button')
  applyTabStyle(sellTabBtn, true)
  sellTabBtn.addEventListener('click', (e) => {
    activeTab = 'sell'
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })

  buyTabBtn = document.createElement('button')
  applyTabStyle(buyTabBtn, false)
  buyTabBtn.addEventListener('click', (e) => {
    activeTab = 'buy'
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })

  tabRow.appendChild(sellTabBtn)
  tabRow.appendChild(buyTabBtn)
  lower.appendChild(tabRow)

  // 테이블 컨테이너
  tableContainer = document.createElement('div')
  Object.assign(tableContainer.style, { flex: '1', padding: '0 4px', overflow: 'auto' })
  lower.appendChild(tableContainer)

  root.appendChild(lower)
  container.appendChild(root)

  // 날짜 필터 변경 이벤트
  dateFromInput.addEventListener('change', () => { showTable(); updateTabLabels() })
  dateToInput.addEventListener('change', () => { showTable(); updateTabLabels() })

  // 차트 생성
  chart = createProfitChart({
    container: chartContainer,
    height: 300,
    data: buildChartFromDailySummary(hotStore.getState().dailySummary),
    onBarClick: (date: string) => {
      if (dateFromInput) dateFromInput.value = date
      if (dateToInput) dateToInput.value = date
      showTable()
      updateTabLabels()
    },
    onDateRangeChange: async (from: string, to: string) => {
      try {
        const settings = globalSettingsManager.getSettings()
        const tradeMode = settings?.trade_mode || 'test'
        const data = await api.getDailySummary(from, to, tradeMode)
        chart?.updateData(buildChartFromDailySummary(data))
      } catch (err) {
        console.warn('[profit-detail] daily-summary fetch failed:', err)
      }
    },
  })

  // 초기 데이터 반영
  const initState = hotStore.getState()
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  updateTabLabels()
  updateSummaryCards()
  showTable()

  // hotStore 구독 — rAF 배칭 + selective update
  let prevSellRef = initState.sellHistory
  let prevBuyRef = initState.buyHistory
  let prevDailySummaryRef = initState.dailySummary
  let prevAccountRef = initState.account
  let prevTradeMode = globalSettingsManager.getSettings()?.trade_mode
  let prevPositionsRef = initState.positions
  let prevSectorStocksRef = initState.sectorStocks
  _mounted = true

  unsubAccount = hotStore.subscribe((curr) => {
    const accountChanged = curr.account !== prevAccountRef || curr.positions !== prevPositionsRef || curr.sectorStocks !== prevSectorStocksRef
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const chartChanged = curr.dailySummary !== prevDailySummaryRef || globalSettingsManager.getSettings()?.trade_mode !== prevTradeMode

    if (!accountChanged && !historyChanged && !chartChanged) return

    if (accountChanged) {
      prevAccountRef = curr.account
      prevPositionsRef = curr.positions
      prevSectorStocksRef = curr.sectorStocks
      _dirtyAccount = true
      _dirtySectorStocks = true
    }
    if (historyChanged) {
      prevSellRef = curr.sellHistory
      prevBuyRef = curr.buyHistory
      sellHistory = curr.sellHistory
      buyHistory = curr.buyHistory
      _dirtyHistory = true
    }
    if (chartChanged) {
      prevDailySummaryRef = curr.dailySummary
      prevTradeMode = globalSettingsManager.getSettings()?.trade_mode
      _dirtyChart = true
    }

    if (_rafId !== null) return

    _rafId = requestAnimationFrame(() => {
      _rafId = null
      if (!_mounted) return

      if (_dirtyAccount) {
        _dirtyAccount = false
        renderAccountVals()
      }

      if (_dirtyHistory) {
        _dirtyHistory = false
        showTable()
        updateSummaryCards()
        updateTabLabels()
        renderAccountVals()
      }

      if (_dirtyChart) {
        _dirtyChart = false
        updateSummaryCards()
        const latest = hotStore.getState()
        const settings = globalSettingsManager.getSettings()
        const tradeModeChanged = settings?.trade_mode !== prevTradeMode
        chart?.updateData(buildChartFromDailySummary(latest.dailySummary))
        if (tradeModeChanged) {
          prevTradeMode = settings?.trade_mode
          const isTest = settings?.trade_mode === 'test'
          retentionLabel.textContent = isTest ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
          if (realAccountContainer && testAccountContainer) {
            realAccountContainer.style.display = isTest ? 'none' : ''
            testAccountContainer.style.display = isTest ? '' : 'none'
          }
          renderAccountVals()
        }
      }

      if (_dirtySectorStocks) {
        _dirtySectorStocks = false
        showTable()
      }
    })
  })

  renderAccountVals()
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  notifyPageInactive('profit-detail')
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  _dirtyAccount = false
  _dirtyHistory = false
  _dirtyChart = false
  _dirtySectorStocks = false
  if (unsubAccount) { unsubAccount(); unsubAccount = null }
  if (chart) { chart.destroy(); chart = null }
  if (sellTable) { sellTable.destroy(); sellTable = null }
  if (buyTable) { buyTable.destroy(); buyTable = null }
  accountValRefs = []
  testAccountValRefs = []
  holdingCountSpan = null
  holdingCountSpanTest = null
  realAccountContainer = null
  testAccountContainer = null
  buyHistory = []
  sellHistory = []
  sellTabBtn = null
  buyTabBtn = null
  tableContainer = null
  dateFromInput = null
  dateToInput = null
  dummyMsg = null
  todayPnlEl = null; todayRateEl = null
  monthPnlEl = null; monthRateEl = null
  totalPnlEl = null; totalRateEl = null
}

export default { mount, unmount }
