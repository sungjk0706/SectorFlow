// frontend/src/pages/profit-overview.ts
// 수익현황 페이지 — Vanilla TS PageModule
// ProfitOverviewPage.tsx + AccountSummaryTable.tsx + DailyProfitChart.tsx + TradeHistoryTable.tsx 통합 전환

import { createProfitChart, type ProfitChartApi } from '../components/canvas-profit-chart'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
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
  type DailyDrilldownRow,
  getLocalToday,
  aggregatePnl,
  buildMonthlyDrilldown,
  buildChartFromDailySummary,
  createDrilldownCols,
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
let tableViewContainer: HTMLDivElement | null = null
let drilldownViewContainer: HTMLDivElement | null = null
let dummyMsg: HTMLDivElement | null = null
let unsubAccount: (() => void) | null = null

/* ── rAF 배칭 상태 ── */
let _rafId: number | null = null
let _mounted = false
/** 다음 rAF에서 갱신할 필드 그룹 플래그 */
let _dirtyAccount = false
let _dirtyHistory = false
let _dirtyChart = false
let _dirtySectorStocks = false

/* ── 드릴다운 상태 ── */
let drilldownActive = false
let dateFilter: string | null = null
let drilldownTable: DataTableApi<DailyDrilldownRow> | null = null
let tabRow: HTMLDivElement | null = null
let drilldownCols: ColumnDef<DailyDrilldownRow>[] = []
/* ── 요약 카드 DOM 참조 ── */
let todayPnlEl: HTMLSpanElement | null = null
let todayRateEl: HTMLSpanElement | null = null
let monthPnlEl: HTMLSpanElement | null = null
let monthRateEl: HTMLSpanElement | null = null
let totalPnlEl: HTMLSpanElement | null = null
let totalRateEl: HTMLSpanElement | null = null
/** 카드 참조 */
let monthCard: HTMLDivElement | null = null
let todayCard: HTMLDivElement | null = null
let totalCard: HTMLDivElement | null = null

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
  // 계좌 현황에 총금액/손익 표시하므로 탭에서는 건수만 간결하게 표시
  if (sellTabBtn) {
    sellTabBtn.textContent = `매도 내역 (${sellHistory.length}건)`
  }
  if (buyTabBtn) {
    buyTabBtn.textContent = `매수 내역 (${buyHistory.length}건)`
  }
}

/* ── 요약 카드 갱신 ── */
function updateSummaryCards(): void {
  const today = getLocalToday()
  const yearMonth = today.slice(0, 7)

  // 당일 손익: dailySummary에서 오늘 날짜 entry 조회 (SSOT — 백엔드 집계값 사용)
  const dailySummary = hotStore.getState().dailySummary
  const todayEntry = dailySummary.find(r => String(r.date ?? '') === today)
  const dayPnl = todayEntry ? Number(todayEntry.realized_pnl ?? 0) : 0
  const dayRate = todayEntry ? Number(todayEntry.pnl_rate ?? 0) : 0

  // 당월/누적 손익: sellHistory 기반 집계
  const monS = aggregatePnl(sellHistory, yearMonth + '-01', yearMonth + '-31')
  const allS = aggregatePnl(sellHistory)

  if (todayPnlEl) { todayPnlEl.textContent = fmtWon(dayPnl); todayPnlEl.style.color = pnlColor(dayPnl) }
  if (todayRateEl) { todayRateEl.textContent = `${dayRate.toFixed(2)}%`; todayRateEl.style.color = pnlColor(dayPnl) }
  if (monthPnlEl) { monthPnlEl.textContent = fmtWon(monS.pnl); monthPnlEl.style.color = pnlColor(monS.pnl) }
  if (monthRateEl) { monthRateEl.textContent = `${monS.rate.toFixed(2)}%`; monthRateEl.style.color = pnlColor(monS.pnl) }
  if (totalPnlEl) { totalPnlEl.textContent = fmtWon(allS.pnl); totalPnlEl.style.color = pnlColor(allS.pnl) }
  if (totalRateEl) { totalRateEl.textContent = `${allS.rate.toFixed(2)}%`; totalRateEl.style.color = pnlColor(allS.pnl) }
}

/* ── 드릴다운 테이블 표시 ── */
function showDrilldown(): void {
  if (!tableViewContainer || !drilldownViewContainer) return

  // CSS display 토글로 뷰 전환
  tableViewContainer.style.display = 'none'
  drilldownViewContainer.style.display = ''

  // 탭 버튼 숨기기
  if (tabRow) tabRow.style.display = 'none'

  // 드릴다운 테이블이 없으면 1회 생성
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

/* ── 날짜 필터 → Trade Table ── */
function filterByDate(date: string): void {
  dateFilter = date
  drilldownActive = false

  // 탭 버튼 복원
  if (tabRow) tabRow.style.display = 'flex'

  showTable()
}

/* ── 테이블 전환 ── */
function showTable(): void {
  if (!tableViewContainer || !drilldownViewContainer) return

  // CSS display 토글로 뷰 전환
  tableViewContainer.style.display = ''
  drilldownViewContainer.style.display = 'none'

  const isSell = activeTab === 'sell'
  let rows = isSell ? sellHistory : buyHistory

  // 날짜 필터 적용
  if (dateFilter) {
    rows = rows.filter(r => String(r.date ?? '') === dateFilter)
  }

  const isDummy = rows.length === 0 && !dateFilter
  const displayRows = isDummy ? (isSell ? DUMMY_SELL : DUMMY_BUY) : rows

  // 매도 테이블 — 1회 생성 후 재사용
  if (!sellTable) {
    sellTable = createDataTable<Record<string, unknown>>({
      columns: SELL_COLS,
      emptyText: '매도 내역이 없습니다.',
      zebraStriping: true,
    })
    tableViewContainer.appendChild(sellTable.el)
  }

  // 매수 테이블 — 1회 생성 후 재사용
  if (!buyTable) {
    buyTable = createDataTable<Record<string, unknown>>({
      columns: BUY_COLS,
      emptyText: '매수 내역이 없습니다.',
      zebraStriping: true,
    })
    tableViewContainer.appendChild(buyTable.el)
  }

  // 활성 탭에 따라 테이블 표시/숨김 토글
  sellTable.el.style.display = isSell ? '' : 'none'
  buyTable.el.style.display = isSell ? 'none' : ''

  // rowStyle 적용을 위해 updateRows 호출
  const activeTbl = isSell ? sellTable : buyTable
  activeTbl.updateRows(displayRows)

  // 더미 메시지
  if (dummyMsg) dummyMsg.remove()
  if (isDummy) {
    dummyMsg = document.createElement('div')
    Object.assign(dummyMsg.style, { textAlign: 'center', fontSize: FONT_SIZE.badge, color: COLOR.disabled, marginTop: '-4px' })
    dummyMsg.textContent = '거래 체결 시 자동으로 표시됩니다'
    tableViewContainer.appendChild(dummyMsg)
  }

  // 탭 스타일 갱신
  if (sellTabBtn) applyTabStyle(sellTabBtn, activeTab === 'sell')
  if (buyTabBtn) applyTabStyle(buyTabBtn, activeTab === 'buy')
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-overview')
  buyHistory = []
  sellHistory = []
  activeTab = 'sell'
  accountValRefs = []

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  root.appendChild(createCardTitle('수익현황'))

  const settings = globalSettingsManager.getSettings()
  const isTestMode = settings?.trade_mode === 'test'

  /* ── 상단 (자연스러운 높이) ── */
  const upper = document.createElement('div')
  Object.assign(upper.style, {
    flex: 'none',
    borderBottom: '1px solid #ddd',
    overflow: 'hidden',
    display: 'flex',
    gap: '8px',
  })

  // 우 50%: 일별 수익률 차트
  const chartPanel = document.createElement('div')
  Object.assign(chartPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px' })
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

  // 좌 50%: 계좌 현황 테이블
  const accountPanel = document.createElement('div')
  Object.assign(accountPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px' })

  // 계좌현황 헤더
  const accountHeader = sectionTitle('계좌 현황')
  accountHeader.style.color = COLOR.down

  accountPanel.appendChild(accountHeader)

  // 계좌 현황 DOM 생성 (실전모드 + 테스트모드 각각, CSS display 토글)

  // 실전모드 컨테이너
  realAccountContainer = document.createElement('div')
  realAccountContainer.style.display = isTestMode ? 'none' : ''
  for (let i = 0; i < ACCOUNT_LABELS_REAL.length; i++) {
    const row = document.createElement('div')
    row.style.cssText = ROW_CSS
    if (i % 2 === 1) {
      row.style.backgroundColor = '#f9f9f9'
    }
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

  // 테스트모드 컨테이너
  testAccountContainer = document.createElement('div')
  testAccountContainer.style.display = isTestMode ? '' : 'none'
  for (let i = 0; i < ACCOUNT_LABELS_TEST.length; i++) {
    const row = document.createElement('div')
    row.style.cssText = ROW_CSS
    if (i % 2 === 1) {
      row.style.backgroundColor = '#f9f9f9'
    }
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

  upper.appendChild(chartPanel)
  upper.appendChild(accountPanel)
  root.appendChild(upper)

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
    card.style.cursor = 'pointer'
    if (i === 0) todayCard = card
    if (i === 1) monthCard = card
    if (i === 2) totalCard = card

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

  /* ── 하단 60% ── */
  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', overflow: 'auto' })

  // 탭 헤더
  tabRow = document.createElement('div')
  Object.assign(tabRow.style, { display: 'flex', borderBottom: '1px solid #eee', marginBottom: '8px', paddingTop: '4px' })

  sellTabBtn = document.createElement('button')
  applyTabStyle(sellTabBtn, true)
  sellTabBtn.addEventListener('click', (e) => {
    dateFilter = null
    drilldownActive = false
    activeTab = 'sell'
    if (tabRow) tabRow.style.display = 'flex'
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })

  buyTabBtn = document.createElement('button')
  applyTabStyle(buyTabBtn, false)
  buyTabBtn.addEventListener('click', (e) => {
    dateFilter = null
    drilldownActive = false
    activeTab = 'buy'
    if (tabRow) tabRow.style.display = 'flex'
    showTable()
    updateTabLabels()
    ;(e.target as HTMLElement).blur()
  })

  tabRow.appendChild(sellTabBtn)
  tabRow.appendChild(buyTabBtn)
  lower.appendChild(tabRow)

  // 테이블 컨테이너
  tableContainer = document.createElement('div')
  Object.assign(tableContainer.style, { padding: '0 4px' })

  // 테이블 뷰와 드릴다운 뷰 컨테이너를 미리 생성
  tableViewContainer = document.createElement('div')
  drilldownViewContainer = document.createElement('div')
  drilldownViewContainer.style.display = 'none'

  tableContainer.appendChild(tableViewContainer)
  tableContainer.appendChild(drilldownViewContainer)

  lower.appendChild(tableContainer)
  root.appendChild(lower)

  container.appendChild(root)

  // 당일 카드 클릭 → 오늘 날짜 필터
  if (todayCard) {
    todayCard.addEventListener('click', () => {
      drilldownActive = false
      dateFilter = getLocalToday()
      if (tabRow) tabRow.style.display = 'flex'
      showTable()
    })
  }

  // 당월 카드 클릭 → 드릴다운 토글
  if (monthCard) {
    monthCard.addEventListener('click', () => {
      drilldownActive = !drilldownActive
      dateFilter = null
      if (drilldownActive) {
        showDrilldown()
      } else {
        if (tabRow) tabRow.style.display = 'flex'
        showTable()
      }
    })
  }

  // 누적 카드 클릭 → 전체 내역
  if (totalCard) {
    totalCard.addEventListener('click', () => {
      drilldownActive = false
      dateFilter = null
      if (tabRow) tabRow.style.display = 'flex'
      showTable()
    })
  }

  // 차트 생성 — store의 dailySummary 초기 데이터로 시작
  chart = createProfitChart({
    container: chartContainer,
    data: buildChartFromDailySummary(hotStore.getState().dailySummary),
    onBarClick: (date: string) => {
      // 막대 클릭 → 해당 일자 체결 내역 필터
      dateFilter = date
      drilldownActive = false
      if (tabRow) tabRow.style.display = 'flex'
      showTable()
    },
    onDateRangeChange: async (from: string, to: string) => {
      // 날짜 변경 → API 호출 → 차트 갱신
      try {
        const settings = globalSettingsManager.getSettings()
        const tradeMode = settings?.trade_mode || 'test'
        const data = await api.getDailySummary(from, to, tradeMode)
        chart?.updateData(buildChartFromDailySummary(data))
      } catch (err) {
        console.warn('[profit-overview] daily-summary fetch failed:', err)
      }
    },
  })

  // 초기 데이터 반영 — subscribe 등록 전에 모듈 변수 할당 (Bug 5 fix)
  const initState = hotStore.getState()
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  // 초기화면: 당일 내역 표시
  dateFilter = getLocalToday()
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
    // 필드 그룹별 참조 비교
    const accountChanged = curr.account !== prevAccountRef || curr.positions !== prevPositionsRef || curr.sectorStocks !== prevSectorStocksRef
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const chartChanged = curr.dailySummary !== prevDailySummaryRef || globalSettingsManager.getSettings()?.trade_mode !== prevTradeMode

    // 아무것도 변경되지 않으면 skip
    if (!accountChanged && !historyChanged && !chartChanged) return

    // 참조 갱신
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

    // rAF 배칭: 이미 예약된 rAF가 있으면 추가 예약하지 않음
    if (_rafId !== null) return

    _rafId = requestAnimationFrame(() => {
      _rafId = null
      if (!_mounted) return

      // 변경된 필드 그룹에 해당하는 DOM 섹션만 갱신
      if (_dirtyAccount) {
        _dirtyAccount = false
        renderAccountVals()
      }

      if (_dirtyHistory) {
        _dirtyHistory = false
        if (drilldownActive) {
          showDrilldown()
        } else {
          showTable()
        }
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
          // WS 상태 배지는 전역 싱글톤이 자동 업데이트하므로 수동 업데이트 제거
          retentionLabel.textContent = isTest ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
          // 계좌 현황 컨테이너 토글
          if (realAccountContainer && testAccountContainer) {
            realAccountContainer.style.display = isTest ? 'none' : ''
            testAccountContainer.style.display = isTest ? '' : 'none'
          }
          renderAccountVals()
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

  // 초기 계좌 현황 표시
  renderAccountVals()
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  notifyPageInactive('profit-overview')
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  _dirtyAccount = false
  _dirtyHistory = false
  _dirtyChart = false
  _dirtySectorStocks = false
  if (unsubAccount) { unsubAccount(); unsubAccount = null }
  if (chart) { chart.destroy(); chart = null }
  if (sellTable) { sellTable.destroy(); sellTable = null }
  if (buyTable) { buyTable.destroy(); buyTable = null }
  if (drilldownTable) { drilldownTable.destroy(); drilldownTable = null }
  drilldownActive = false
  dateFilter = null
  tabRow = null
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
  tableViewContainer = null
  drilldownViewContainer = null
  dummyMsg = null
  todayPnlEl = null; todayRateEl = null
  monthPnlEl = null; monthRateEl = null
  totalPnlEl = null; totalRateEl = null
  monthCard = null
  drilldownCols = []
}

export default { mount, unmount }
