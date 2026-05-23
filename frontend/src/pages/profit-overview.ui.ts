// frontend/src/pages/profit-overview.ui.ts
// 수익현황 페이지 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createProfitChart, type ProfitChartApi } from '../components/canvas-profit-chart'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createGlobalWsBadge } from '../settings'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, createStockNameColumn, createNumberCell, createPnlCell } from '../components/common/ui-styles'
import { ACCOUNT_LABELS_REAL, ACCOUNT_LABELS_TEST } from '../components/common/account-labels'
import type { SectorStock } from '../types'

// ── Props 타입 정의 ──

export interface ProfitOverviewProps {
  // 계좌 데이터
  account: {
    deposit?: number
    orderable?: number
    total_eval_amount?: number
    total_pnl?: number
    total_pnl_rate?: number
    positionCount?: number
    accumulated_investment?: number
    initial_deposit?: number
  }
  
  // 거래 내역
  buyHistory: Record<string, unknown>[]
  sellHistory: Record<string, unknown>[]
  
  // 일별 요약 (차트용)
  dailySummary: Record<string, unknown>[]
  
  // 거래 모드
  tradeMode: 'test' | 'real'
  
  // 당일 매수/매도 금액 (미리 계산된 값)
  todayBuyAmt?: number
  todaySellAmt?: number
  
  // 누적 실현 손익 (미리 계산된 값)
  cumulativePnl?: number
  cumulativePnlRate?: number
  
  // 당일/당월/누적 손익 (미리 계산된 값)
  todayPnl?: number
  todayRate?: number
  monthPnl?: number
  monthRate?: number
  totalPnl?: number
  totalRate?: number
  
  // WS 구독 상태
  wsSubscribed: boolean
  
  // 업종별 종목 데이터 (종목명 표시용)
  sectorStocks: Record<string, SectorStock>
  
  // 이벤트 핸들러 (UI 전용 상태 변경)
  onTabChange: (tab: 'buy' | 'sell') => void
  onDateFilter: (date: string | null) => void
  onDrilldownToggle: (active: boolean) => void
  onChartBarClick: (date: string) => void
  onChartDateRangeChange: (from: string, to: string) => void
}

const ROW_CSS = `display:flex;justify-content:space-between;padding:7px 4px;border-bottom:1px solid #f0f0f0;font-size:${FONT_SIZE.label};`

/* ── 매수 컬럼 (7개) ── */
const BUY_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', render: (_, i) => String(i + 1) },
  { key: 'date', label: '날짜', align: 'center', render: r => { const d = String(r.date ?? ''); return d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d } },
  { key: 'time', label: '시간', align: 'center', render: r => String(r.time ?? '').slice(0, 5) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      return {
        name: String(r.stk_nm ?? ''),
        market_type: undefined,
        nxt_enable: undefined
      }
    }
  ),
  { key: 'price', label: '매수가', align: 'right', render: r => createNumberCell(Number(r.price ?? 0)) },
  { key: 'qty', label: '수량', align: 'right', render: r => createNumberCell(Number(r.qty ?? 0)) },
  { key: 'total_amt', label: '매수금액', align: 'right', render: r => fmtWon(Number(r.total_amt ?? 0)) },
  { key: 'fee', label: '수수료', align: 'right', render: r => fmtWon(Number(r.fee ?? 0)) },
]

/* ── 매도 컬럼 (12개) ── */
const SELL_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', render: (_, i) => String(i + 1) },
  { key: 'date', label: '날짜', align: 'center', render: r => { const d = String(r.date ?? ''); return d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d } },
  { key: 'time', label: '시간', align: 'center', render: r => String(r.time ?? '').slice(0, 5) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      return {
        name: String(r.stk_nm ?? ''),
        market_type: undefined,
        nxt_enable: undefined
      }
    }
  ),
  { key: 'avg_buy_price', label: '매수가', align: 'right', render: r => createNumberCell(Number(r.avg_buy_price ?? 0)) },
  { key: 'price', label: '매도가', align: 'right', render: r => {
    const sell = Number(r.price ?? 0)
    return createPnlCell(sell)
  }},
  { key: 'qty', label: '수량', align: 'right', render: r => createNumberCell(Number(r.qty ?? 0)) },
  { key: 'buy_total_amt', label: '매수금액', align: 'right', render: r => fmtWon(Number(r.buy_total_amt ?? 0)) },
  { key: 'total_amt', label: '매도금액', align: 'right', render: r => {
    const v = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = fmtWon(Number(r.total_amt ?? 0))
    return span
  }},
  { key: 'realized_pnl', label: '실현손익', align: 'right', render: r => {
    const v = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = `${v > 0 ? '+' : ''}${v.toLocaleString()}원`
    return span
  }},
  { key: 'pnl_rate', label: '수익률', align: 'right', render: r => {
    const v = Number(r.pnl_rate ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
    return span
  }},
  { key: 'fee', label: '수수료', align: 'right', render: r => fmtWon(Number(r.fee ?? 0)) },
  { key: 'tax', label: '세금', align: 'right', render: r => fmtWon(Number(r.tax ?? 0)) },
]

/* ── 더미 데이터 ── */
const DUMMY_BUY: Record<string, unknown>[] = [
  { date: '2026-04-14', time: '09:15:00', stk_nm: '삼성전자', price: 70000, qty: 100, total_amt: 7001050, fee: 1050 },
  { date: '2026-04-14', time: '09:22:00', stk_nm: 'SK하이닉스', price: 185000, qty: 50, total_amt: 9251388, fee: 1388 },
]

const DUMMY_SELL: Record<string, unknown>[] = [
  { date: '2026-04-14', time: '10:05:00', stk_nm: '삼성전자', avg_buy_price: 70000, price: 71500, qty: 100, buy_total_amt: 7001050, total_amt: 7134627, realized_pnl: 133577, pnl_rate: 1.91, fee: 1073, tax: 14300 },
  { date: '2026-04-14', time: '10:30:00', stk_nm: 'SK하이닉스', avg_buy_price: 185000, price: 183000, qty: 50, buy_total_amt: 9251388, total_amt: 9130327, realized_pnl: -121061, pnl_rate: -1.31, fee: 1373, tax: 18300 },
]

/* ── 드릴다운 타입 ── */
export interface DailyDrilldownRow {
  date: string
  sellCount: number
  buyCount: number
  pnl: number
  buyTotal: number
  rate: number
}

/* ── 드릴다운 컬럼 ── */
const DRILLDOWN_COLS: ColumnDef<DailyDrilldownRow>[] = [
  { key: 'date', label: '날짜', align: 'center', render: r => {
    const span = document.createElement('span')
    span.style.cursor = 'pointer'
    span.style.color = '#1976d2'
    span.style.textDecoration = 'underline'
    span.textContent = r.date.slice(5) // MM-DD
    span.addEventListener('click', () => props.onDateFilter(r.date))
    return span
  }},
  { key: 'sellCount', label: '매도건수', align: 'right', render: r => String(r.sellCount) },
  { key: 'buyCount', label: '매수건수', align: 'right', render: r => String(r.buyCount) },
  { key: 'pnl', label: '당일손익', align: 'right', render: r => {
    const span = document.createElement('span')
    span.style.color = pnlColor(r.pnl)
    span.textContent = fmtWon(r.pnl)
    return span
  }},
  { key: 'rate', label: '당일수익률', align: 'right', render: r => {
    const span = document.createElement('span')
    span.style.color = pnlColor(r.rate)
    span.textContent = `${r.rate > 0 ? '+' : ''}${r.rate.toFixed(2)}%`
    return span
  }},
]

/* ── 컴포넌트 생성 함수 ── */

let props: ProfitOverviewProps

export function createProfitOverviewCard(initialProps: ProfitOverviewProps): { el: HTMLElement; update: (newProps: ProfitOverviewProps) => void; destroy: () => void } {
  props = initialProps
  
  let root: HTMLElement | null = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  
  // UI 전용 상태
  let activeTab: 'buy' | 'sell' = 'sell'
  let drilldownActive = false
  let dateFilter: string | null = null
  
  // DOM 참조
  let chart: ProfitChartApi | null = null
  let accountValRefs: HTMLSpanElement[] = []
  let testAccountValRefs: HTMLSpanElement[] = []
  let holdingCountLabel: HTMLSpanElement | null = null
  let holdingCountLabelTest: HTMLSpanElement | null = null
  let realAccountContainer: HTMLDivElement | null = null
  let testAccountContainer: HTMLDivElement | null = null
  let sellTable: DataTableApi<Record<string, unknown>> | null = null
  let buyTable: DataTableApi<Record<string, unknown>> | null = null
  let sellTabBtn: HTMLButtonElement | null = null
  let buyTabBtn: HTMLButtonElement | null = null
  let tableContainer: HTMLDivElement | null = null
  let tableViewContainer: HTMLDivElement | null = null
  let drilldownViewContainer: HTMLDivElement | null = null
  let dummyMsg: HTMLDivElement | null = null
  let drilldownTable: DataTableApi<DailyDrilldownRow> | null = null
  let tabRow: HTMLDivElement | null = null
  let wsBadge: HTMLElement | null = null
  let todayPnlEl: HTMLSpanElement | null = null
  let todayRateEl: HTMLSpanElement | null = null
  let monthPnlEl: HTMLSpanElement | null = null
  let monthRateEl: HTMLSpanElement | null = null
  let totalPnlEl: HTMLSpanElement | null = null
  let totalRateEl: HTMLSpanElement | null = null
  let monthCard: HTMLDivElement | null = null
  let todayCard: HTMLDivElement | null = null
  let totalCard: HTMLDivElement | null = null
  let retentionLabel: HTMLSpanElement | null = null

  const isTestMode = props.tradeMode === 'test'

  /* ── 상단 (테스트모드: 55%, 실전모드: 48%) ── */
  const upper = document.createElement('div')
  Object.assign(upper.style, {
    flex: `0 0 ${isTestMode ? '55%' : '48%'}`,
    borderBottom: '1px solid #ddd',
    overflow: 'hidden',
    display: 'flex',
    gap: '8px',
  })

  // 우 50%: 일별 수익률 차트
  const chartPanel = document.createElement('div')
  Object.assign(chartPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px' })
  const chartTitle = document.createElement('div')
  Object.assign(chartTitle.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: FONT_SIZE.label, fontWeight: 'normal', color: '#1976d2', padding: '6px 0 8px', borderBottom: '1px solid #eee', marginBottom: '8px' })
  const chartTitleText = document.createElement('span')
  chartTitleText.textContent = '일별 수익률'
  retentionLabel = document.createElement('span')
  Object.assign(retentionLabel.style, { fontSize: '11px', color: '#999', fontWeight: 'normal' })
  retentionLabel.textContent = isTestMode ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
  chartTitle.appendChild(chartTitleText)
  chartTitle.appendChild(retentionLabel)
  chartPanel.appendChild(chartTitle)

  const chartContainer = document.createElement('div')
  chartPanel.appendChild(chartContainer)

  // 좌 50%: 계좌 현황 테이블
  const accountPanel = document.createElement('div')
  Object.assign(accountPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px' })

  // 계좌현황 헤더: 타이틀 + 상태 뱃지
  const accountHeader = document.createElement('div')
  Object.assign(accountHeader.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #eee', marginBottom: '8px', padding: '6px 0 8px' })

  const accountTitle = document.createElement('div')
  Object.assign(accountTitle.style, { fontSize: FONT_SIZE.label, fontWeight: 'normal', color: '#1976d2' })
  accountTitle.textContent = '계좌 현황'
  accountHeader.appendChild(accountTitle)

  wsBadge = createGlobalWsBadge()
  accountHeader.appendChild(wsBadge)
  accountPanel.appendChild(accountHeader)

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
    label.textContent = ACCOUNT_LABELS_REAL[i]
    if (i === 4) holdingCountLabel = label
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
    label.textContent = ACCOUNT_LABELS_TEST[i]
    if (i === 4) holdingCountLabelTest = label
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
    Object.assign(titleEl.style, { fontSize: FONT_SIZE.badge, color: '#888', whiteSpace: 'nowrap' })
    titleEl.textContent = CARD_TITLES[i]

    const valRow = document.createElement('div')
    Object.assign(valRow.style, { display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', gap: '6px' })

    const pnlEl = document.createElement('span')
    Object.assign(pnlEl.style, { fontSize: FONT_SIZE.section, fontWeight: 'normal' })
    pnlEl.textContent = fmtWon(0)

    const rateEl = document.createElement('span')
    Object.assign(rateEl.style, { fontSize: FONT_SIZE.label, color: '#333' })
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
    props.onTabChange('sell')
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
    props.onTabChange('buy')
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

  // 당일 카드 클릭 → 오늘 날짜 필터
  if (todayCard) {
    todayCard.addEventListener('click', () => {
      drilldownActive = false
      dateFilter = new Date().toISOString().slice(0, 10)
      if (tabRow) tabRow.style.display = 'flex'
      showTable()
      props.onDateFilter(dateFilter)
    })
  }

  // 당월 카드 클릭 → 드릴다운 토글
  if (monthCard) {
    monthCard.addEventListener('click', () => {
      drilldownActive = !drilldownActive
      dateFilter = null
      props.onDrilldownToggle(drilldownActive)
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
      props.onDateFilter(null)
    })
  }

  // 차트 생성
  const chartData = buildChartFromDailySummary(props.dailySummary)
  chart = createProfitChart({
    container: chartContainer,
    data: chartData,
    onBarClick: (date: string) => {
      dateFilter = date
      drilldownActive = false
      if (tabRow) tabRow.style.display = 'flex'
      showTable()
      props.onDateFilter(date)
    },
    onDateRangeChange: (from: string, to: string) => {
      props.onChartDateRangeChange(from, to)
    },
  })

  // 초기 데이터 반영
  renderAccountVals()
  updateSummaryCards()
  updateTabLabels()
  showTable()

  // ── 헬퍼 함수 ──

  function buildChartFromDailySummary(summary: Record<string, unknown>[]): { date: string; pnl: number | null; rate: number }[] {
    const rows = summary.map(r => {
      const raw = String(r.date ?? '')
      const sellCount = Number(r.sell_count ?? 0)
      if (sellCount === 0) return { date: raw, pnl: null, rate: 0 }
      const pnl = Number(r.realized_pnl ?? 0)
      const rate = Number(r.pnl_rate ?? 0)
      return { date: raw, pnl, rate }
    })
    return rows
  }

  function renderAccountVals(): void {
    const a = props.account
    const isTestMode = props.tradeMode === 'test'

    const todayBuyAmt = props.todayBuyAmt ?? 0
    const todaySellAmt = props.todaySellAmt ?? 0
    const positionCount = a?.positionCount ?? 0
    const evalTotal = a?.total_eval_amount ?? 0
    const evalPnl = a?.total_pnl ?? 0
    const evalRate = a?.total_pnl_rate ?? 0
    const cumPnl = props.cumulativePnl ?? 0
    const cumRate = props.cumulativePnlRate ?? 0

    if (realAccountContainer && testAccountContainer) {
      realAccountContainer.style.display = isTestMode ? 'none' : ''
      testAccountContainer.style.display = isTestMode ? '' : 'none'
    }

    if (isTestMode) {
      const tv = testAccountValRefs
      if (tv.length < 9) return
      const accumulatedInvestment = a?.accumulated_investment ?? a?.initial_deposit ?? 0
      const orderable = a?.orderable ?? 0
      tv[0].textContent = `${accumulatedInvestment.toLocaleString()}원`
      tv[1].textContent = `${orderable.toLocaleString()}원`
      tv[2].textContent = `${todayBuyAmt.toLocaleString()}원`
      tv[3].textContent = `${todaySellAmt.toLocaleString()}원`
      tv[4].textContent = `${evalTotal.toLocaleString()}원`
      if (holdingCountLabelTest) holdingCountLabelTest.textContent = `보유주식 평가금액 (${positionCount}종목)`
      const evalSign = evalPnl > 0 ? '+' : ''
      const evalColor = pnlColor(evalPnl)
      tv[5].textContent = `${evalSign}${evalPnl.toLocaleString()}원`
      tv[5].style.color = evalColor
      const evalRateSign = evalRate > 0 ? '+' : ''
      tv[6].textContent = `${evalRateSign}${evalRate.toFixed(2)}%`
      tv[6].style.color = evalColor
      const cumSign = cumPnl > 0 ? '+' : ''
      const cumColor = pnlColor(cumPnl)
      tv[7].textContent = `${cumSign}${cumPnl.toLocaleString()}원`
      tv[7].style.color = cumColor
      tv[8].textContent = `${cumSign}${cumRate.toFixed(2)}%`
      tv[8].style.color = cumColor
    } else {
      const rv = accountValRefs
      if (rv.length < 9) return
      const deposit = a?.deposit ?? 0
      const orderable = a?.orderable ?? Math.max(0, deposit - todayBuyAmt)
      rv[0].textContent = `${deposit.toLocaleString()}원`
      rv[1].textContent = `${orderable.toLocaleString()}원`
      rv[2].textContent = `${todayBuyAmt.toLocaleString()}원`
      rv[3].textContent = `${todaySellAmt.toLocaleString()}원`
      rv[4].textContent = `${evalTotal.toLocaleString()}원`
      if (holdingCountLabel) holdingCountLabel.textContent = `보유주식 평가금액 (${positionCount}종목)`
      const evalSign = evalPnl > 0 ? '+' : ''
      const evalColor = pnlColor(evalPnl)
      rv[5].textContent = `${evalSign}${evalPnl.toLocaleString()}원`
      rv[5].style.color = evalColor
      const evalRateSign = evalRate > 0 ? '+' : ''
      rv[6].textContent = `${evalRateSign}${evalRate.toFixed(2)}%`
      rv[6].style.color = evalColor
      const cumSign = cumPnl > 0 ? '+' : ''
      const cumColor = pnlColor(cumPnl)
      rv[7].textContent = `${cumSign}${cumPnl.toLocaleString()}원`
      rv[7].style.color = cumColor
      rv[8].textContent = `${cumSign}${cumRate.toFixed(2)}%`
      rv[8].style.color = cumColor
    }
  }

  function applyTabStyle(btn: HTMLButtonElement, active: boolean): void {
    Object.assign(btn.style, {
      flex: '1',
      padding: '8px 0',
      cursor: 'pointer',
      border: 'none',
      background: 'transparent',
      borderBottom: active ? '2px solid #1976d2' : '2px solid transparent',
      fontWeight: active ? FONT_WEIGHT.normal : FONT_WEIGHT.normal,
      color: active ? '#1976d2' : '#666',
      fontSize: FONT_SIZE.label,
      textAlign: 'center',
    })
  }

  function updateTabLabels(): void {
    if (sellTabBtn) {
      sellTabBtn.textContent = `매도 내역 (${props.sellHistory.length}건)`
    }
    if (buyTabBtn) {
      buyTabBtn.textContent = `매수 내역 (${props.buyHistory.length}건)`
    }
  }

  function updateSummaryCards(): void {
    const todayPnl = props.todayPnl ?? 0
    const todayRate = props.todayRate ?? 0
    const monthPnl = props.monthPnl ?? 0
    const monthRate = props.monthRate ?? 0
    const totalPnl = props.totalPnl ?? 0
    const totalRate = props.totalRate ?? 0

    if (todayPnlEl) { todayPnlEl.textContent = fmtWon(todayPnl); todayPnlEl.style.color = pnlColor(todayPnl) }
    if (todayRateEl) { todayRateEl.textContent = `${todayRate.toFixed(2)}%`; todayRateEl.style.color = pnlColor(todayPnl) }
    if (monthPnlEl) { monthPnlEl.textContent = fmtWon(monthPnl); monthPnlEl.style.color = pnlColor(monthPnl) }
    if (monthRateEl) { monthRateEl.textContent = `${monthRate.toFixed(2)}%`; monthRateEl.style.color = pnlColor(monthPnl) }
    if (totalPnlEl) { totalPnlEl.textContent = fmtWon(totalPnl); totalPnlEl.style.color = pnlColor(totalPnl) }
    if (totalRateEl) { totalRateEl.textContent = `${totalRate.toFixed(2)}%`; totalRateEl.style.color = pnlColor(totalPnl) }
  }

  function showDrilldown(): void {
    if (!tableViewContainer || !drilldownViewContainer) return

    tableViewContainer.style.display = 'none'
    drilldownViewContainer.style.display = ''

    if (tabRow) tabRow.style.display = 'none'

    if (!drilldownTable) {
      drilldownTable = createDataTable<DailyDrilldownRow>({
        columns: DRILLDOWN_COLS,
        emptyText: '당월 거래 내역이 없습니다.',
        zebraStriping: true,
      })
      drilldownViewContainer.appendChild(drilldownTable.el)
    }

    // 드릴다운 데이터는 Props로 받아야 함 (비즈니스 로직 제거)
    // 임시로 빈 배열 사용
    drilldownTable.updateRows([])
  }

  function showTable(): void {
    if (!tableViewContainer || !drilldownViewContainer) return

    tableViewContainer.style.display = ''
    drilldownViewContainer.style.display = 'none'

    const isSell = activeTab === 'sell'
    let rows = isSell ? props.sellHistory : props.buyHistory

    if (dateFilter) {
      rows = rows.filter(r => String(r.date ?? '') === dateFilter)
    }

    const isDummy = rows.length === 0 && !dateFilter
    const displayRows = isDummy ? (isSell ? DUMMY_SELL : DUMMY_BUY) : rows

    // 매수/매도 테이블 생성 (sectorStocks 전달)
    if (!sellTable) {
      sellTable = createDataTable<Record<string, unknown>>({
        columns: SELL_COLS.map(col => ({
          ...col,
          render: col.key === 'stk_nm' ? (r, i) => {
            const fn = (SELL_COLS[3] as any).render
            return fn(r, i, props.sectorStocks)
          } : col.render
        })),
        emptyText: '매도 내역이 없습니다.',
        zebraStriping: true,
      })
      tableViewContainer.appendChild(sellTable.el)
    }

    if (!buyTable) {
      buyTable = createDataTable<Record<string, unknown>>({
        columns: BUY_COLS.map(col => ({
          ...col,
          render: col.key === 'stk_nm' ? (r, i) => {
            const fn = (BUY_COLS[3] as any).render
            return fn(r, i, props.sectorStocks)
          } : col.render
        })),
        emptyText: '매수 내역이 없습니다.',
        zebraStriping: true,
      })
      tableViewContainer.appendChild(buyTable.el)
    }

    sellTable.el.style.display = isSell ? '' : 'none'
    buyTable.el.style.display = isSell ? 'none' : ''

    const activeTbl = isSell ? sellTable : buyTable
    activeTbl.updateRows(displayRows)

    if (dummyMsg) dummyMsg.remove()
    if (isDummy) {
      dummyMsg = document.createElement('div')
      Object.assign(dummyMsg.style, { textAlign: 'center', fontSize: FONT_SIZE.badge, color: '#999', marginTop: '-4px' })
      dummyMsg.textContent = '거래 체결 시 자동으로 표시됩니다'
      tableViewContainer.appendChild(dummyMsg)
    }

    if (sellTabBtn) applyTabStyle(sellTabBtn, activeTab === 'sell')
    if (buyTabBtn) applyTabStyle(buyTabBtn, activeTab === 'buy')
  }

  // Props 업데이트 함수
  function update(newProps: ProfitOverviewProps): void {
    Object.assign(props, newProps)
    
    // 계좌 현황 갱신
    renderAccountVals()
    
    // 요약 카드 갱신
    updateSummaryCards()
    
    // 탭 라벨 갱신
    updateTabLabels()
    
    // 차트 데이터 갱신
    const chartData = buildChartFromDailySummary(props.dailySummary)
    chart?.updateData(chartData)
    
    // 테이블 갱신
    if (drilldownActive) {
      showDrilldown()
    } else {
      showTable()
    }
  }

  // 파괴 함수
  function destroy(): void {
    if (chart) { chart.destroy(); chart = null }
    if (sellTable) { sellTable.destroy(); sellTable = null }
    if (buyTable) { buyTable.destroy(); buyTable = null }
    if (drilldownTable) { drilldownTable.destroy(); drilldownTable = null }
    if (root && root.parentNode) root.parentNode.removeChild(root)
    root = null
    accountValRefs = []
    testAccountValRefs = []
    holdingCountLabel = null
    holdingCountLabelTest = null
    realAccountContainer = null
    testAccountContainer = null
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
    tabRow = null
    wsBadge = null
    retentionLabel = null
  }

  return { el: root, update, destroy }
}
