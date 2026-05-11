// frontend/src/pages/profit-overview.ts
// 수익현황 페이지 — Vanilla TS PageModule
// ProfitOverviewPage.tsx + AccountSummaryTable.tsx + DailyProfitChart.tsx + TradeHistoryTable.tsx 통합 전환

import { createProfitChart, type ProfitChartApi } from '../components/canvas-profit-chart'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createWsStatusBadge } from '../components/common/setting-row'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, createStockNameColumn, createNumberCell, createPnlCell } from '../components/common/ui-styles'
import { appStore } from '../stores/appStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'

/* ── 헬퍼 ── */

/** 일별 요약 → 차트 데이터 변환. 매도 없는 날(sell_count=0)은 pnl=null로 표시 → 막대 안 그림 */
function buildChartFromDailySummary(summary: Record<string, unknown>[]): { date: string; pnl: number | null; rate: number }[] {
  const rows = summary.map(r => {
    const raw = String(r.date ?? '')
    const sellCount = Number(r.sell_count ?? 0)
    if (sellCount === 0) return { date: raw, pnl: null, rate: 0 }
    const pnl = Number(r.realized_pnl ?? 0)
    const rate = Number(r.pnl_rate ?? 0)
    return { date: raw, pnl, rate }
  })
  // X축: 왼쪽=과거, 오른쪽=최신
  return rows
}

/* ── 계좌 현황 테이블 라벨 ── */
const ACCOUNT_LABELS_REAL = ['예수금', '주문가능 금액', '오늘 매수 금액', '오늘 매도 금액', '보유주식 평가 금액', '보유주식 평가 손익금', '보유주식 평가 수익률', '누적 총 실현 손익금', '누적 총 실현 수익률']
const ACCOUNT_LABELS_TEST = ['초기 투자금', '예수금', '주문가능 금액', '오늘 매수 금액', '오늘 매도 금액', '보유주식 평가 금액', '보유주식 평가 손익금', '보유주식 평가 수익률', '누적 총 실현 손익금', '누적 총 실현 수익률']
const ROW_CSS = `display:flex;justify-content:space-between;padding:7px 4px;border-bottom:1px solid #f0f0f0;font-size:${FONT_SIZE.label};`

/* ── 매수 컬럼 (7개) ── */
const BUY_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', render: (_, i) => String(i + 1) },
  { key: 'date', label: '날짜', align: 'center', render: r => { const d = String(r.date ?? ''); return d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d } },
  { key: 'time', label: '시간', align: 'center', render: r => String(r.time ?? '').slice(0, 5) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      const state = appStore.getState()
      const sectorStock = state.sectorStocks[String(r.stk_cd ?? '')]
      return {
        name: String(r.stk_nm ?? ''),
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
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
      const state = appStore.getState()
      const sectorStock = state.sectorStocks[String(r.stk_cd ?? '')]
      return {
        name: String(r.stk_nm ?? ''),
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
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

/* ── 요약 카드 집계 (순수 함수) ── */

export interface PnlSummary {
  pnl: number       // 실현손익 합계
  buyTotal: number   // 매수금액 합계
  rate: number       // pnl / buyTotal * 100 (buyTotal=0이면 0)
}

/** sellHistory에서 날짜 필터 기반 손익 집계 */
export function aggregatePnl(
  sells: Record<string, unknown>[],
  dateFrom?: string,
  dateTo?: string,
): PnlSummary {
  let pnl = 0
  let buyTotal = 0
  for (const r of sells) {
    const d = String(r.date ?? '')
    if (dateFrom && d < dateFrom) continue
    if (dateTo && d > dateTo) continue
    pnl += Number(r.realized_pnl ?? 0)
    buyTotal += Number(r.buy_total_amt ?? 0)
  }
  return { pnl, buyTotal, rate: buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0 }
}

/* ── 당월 드릴다운 집계 (순수 함수) ── */

export interface DailyDrilldownRow {
  date: string
  sellCount: number
  buyCount: number
  pnl: number
  buyTotal: number
  rate: number
}

/** sellHistory + buyHistory에서 당월 일별 요약 집계 */
export function buildMonthlyDrilldown(
  sells: Record<string, unknown>[],
  buys: Record<string, unknown>[],
  yearMonth: string,
): DailyDrilldownRow[] {
  const prefix = yearMonth + '-'
  const map = new Map<string, DailyDrilldownRow>()

  for (const r of sells) {
    const d = String(r.date ?? '')
    if (!d.startsWith(prefix)) continue
    let row = map.get(d)
    if (!row) { row = { date: d, sellCount: 0, buyCount: 0, pnl: 0, buyTotal: 0, rate: 0 }; map.set(d, row) }
    row.sellCount++
    row.pnl += Number(r.realized_pnl ?? 0)
    row.buyTotal += Number(r.buy_total_amt ?? 0)
  }

  for (const r of buys) {
    const d = String(r.date ?? '')
    if (!d.startsWith(prefix)) continue
    let row = map.get(d)
    if (!row) { row = { date: d, sellCount: 0, buyCount: 0, pnl: 0, buyTotal: 0, rate: 0 }; map.set(d, row) }
    row.buyCount++
  }

  const rows = [...map.values()]
  for (const row of rows) {
    row.rate = row.buyTotal > 0 ? Math.round(row.pnl / row.buyTotal * 10000) / 100 : 0
  }
  rows.sort((a, b) => b.date.localeCompare(a.date))
  return rows
}

/* ── 모듈 변수 ── */
type LowerTab = 'buy' | 'sell'

let chart: ProfitChartApi | null = null
let accountValRefs: HTMLSpanElement[] = []
let testAccountValRefs: HTMLSpanElement[] = []
let holdingCountLabel: HTMLSpanElement | null = null
let holdingCountLabelTest: HTMLSpanElement | null = null
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

/* ── rAF coalescing 상태 ── */
let _rafId: number | null = null
let _mounted = false
/** 다음 rAF에서 갱신할 필드 그룹 플래그 */
let _dirtyAccount = false
let _dirtyHistory = false
let _dirtyChart = false

/* ── 드릴다운 상태 ── */
let drilldownActive = false
let dateFilter: string | null = null
let drilldownTable: DataTableApi<DailyDrilldownRow> | null = null
let tabRow: HTMLDivElement | null = null
let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null

/* ── 요약 카드 DOM 참조 ── */
let todayPnlEl: HTMLSpanElement | null = null
let todayRateEl: HTMLSpanElement | null = null
let monthPnlEl: HTMLSpanElement | null = null
let monthRateEl: HTMLSpanElement | null = null
let totalPnlEl: HTMLSpanElement | null = null
let totalRateEl: HTMLSpanElement | null = null
/** 카드 참조 */
// eslint-disable-next-line prefer-const
let monthCard: HTMLDivElement | null = null
let todayCard: HTMLDivElement | null = null
let totalCard: HTMLDivElement | null = null
export { monthCard as _monthCard }

/* ── 계좌 현황 렌더 ── */
function renderAccountVals(): void {
  const state = appStore.getState()
  const a = state.account
  const isTestMode = state.settings?.trade_mode === 'test'

  // 당일 매수/매도금액은 체결 이력에서 직접 집계
  const today = new Date().toISOString().slice(0, 10)
  const todayBuyAmt = buyHistory
    .filter(r => String(r.date ?? '') === today)
    .reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const todaySellAmt = sellHistory
    .filter(r => String(r.date ?? '') === today)
    .reduce((s, r) => s + Number(r.total_amt ?? 0), 0)

  // 보유주식 평가금액/평가손익: positions에서 실시간 합산
  const positions = state.positions || []
  let evalTotal = 0
  let evalPnl = 0
  let buyAmtTotal = 0
  for (const pos of positions) {
    const curPrice = pos.cur_price ?? 0
    if (curPrice === 0) continue // WS 미수신 상태 제외
    const qty = pos.qty ?? 0
    const buyAmt = pos.buy_amt ?? 0
    const posEval = curPrice * qty
    evalTotal += posEval
    evalPnl += posEval - buyAmt
    buyAmtTotal += buyAmt
  }

  // 누적 실현 손익: sellHistory 전체 합산
  const cumPnl = aggregatePnl(sellHistory)

  // CSS display 토글로 모드별 컨테이너 전환
  if (realAccountContainer && testAccountContainer) {
    realAccountContainer.style.display = isTestMode ? 'none' : ''
    testAccountContainer.style.display = isTestMode ? '' : 'none'
  }

  if (isTestMode) {
    // 테스트모드: 10행 (초기투자금, 예수금, 주문가능금액, 오늘매수, 오늘매도, 보유평가금액, 보유평가손익, 보유평가수익률, 누적손익, 누적수익률)
    const tv = testAccountValRefs
    if (tv.length < 10) return
    const initialDeposit = a?.initial_deposit ?? 0
    const deposit = a?.deposit ?? 0
    const orderable = a?.orderable ?? 0
    const holdingCount = positions.filter(p => (p.qty ?? 0) > 0).length
    tv[0].textContent = `${initialDeposit.toLocaleString()}원`
    tv[1].textContent = `${deposit.toLocaleString()}원`
    tv[2].textContent = `${orderable.toLocaleString()}원`
    tv[3].textContent = `${todayBuyAmt.toLocaleString()}원`
    tv[4].textContent = `${todaySellAmt.toLocaleString()}원`
    tv[5].textContent = `${evalTotal.toLocaleString()}원`
    if (holdingCountLabelTest) holdingCountLabelTest.textContent = `보유주식 평가금액 (${holdingCount}종목)`
    const evalSign = evalPnl > 0 ? '+' : ''
    const evalColor = pnlColor(evalPnl)
    tv[6].textContent = `${evalSign}${evalPnl.toLocaleString()}원`
    tv[6].style.color = evalColor
    const evalRate = buyAmtTotal > 0 ? Math.round(evalPnl / buyAmtTotal * 10000) / 100 : 0
    const evalRateSign = evalRate > 0 ? '+' : ''
    tv[7].textContent = `${evalRateSign}${evalRate.toFixed(2)}%`
    tv[7].style.color = evalColor
    const cumSign = cumPnl.pnl > 0 ? '+' : ''
    const cumColor = pnlColor(cumPnl.pnl)
    tv[8].textContent = `${cumSign}${cumPnl.pnl.toLocaleString()}원`
    tv[8].style.color = cumColor
    tv[9].textContent = `${cumSign}${cumPnl.rate.toFixed(2)}%`
    tv[9].style.color = cumColor
  } else {
    // 실전모드: 9행 (예수금, 주문가능금액, 오늘매수, 오늘매도, 보유평가금액, 보유평가손익, 보유평가수익률, 누적손익, 누적수익률)
    const rv = accountValRefs
    if (rv.length < 9) return
    const deposit = a?.deposit ?? 0
    const orderable = a?.orderable ?? Math.max(0, deposit - todayBuyAmt)
    const holdingCount = positions.filter(p => (p.qty ?? 0) > 0).length
    rv[0].textContent = `${deposit.toLocaleString()}원`
    rv[1].textContent = `${orderable.toLocaleString()}원`
    rv[2].textContent = `${todayBuyAmt.toLocaleString()}원`
    rv[3].textContent = `${todaySellAmt.toLocaleString()}원`
    rv[4].textContent = `${evalTotal.toLocaleString()}원`
    if (holdingCountLabel) holdingCountLabel.textContent = `보유주식 평가금액 (${holdingCount}종목)`
    const evalSign = evalPnl > 0 ? '+' : ''
    const evalColor = pnlColor(evalPnl)
    rv[5].textContent = `${evalSign}${evalPnl.toLocaleString()}원`
    rv[5].style.color = evalColor
    const evalRate = buyAmtTotal > 0 ? Math.round(evalPnl / buyAmtTotal * 10000) / 100 : 0
    const evalRateSign = evalRate > 0 ? '+' : ''
    rv[6].textContent = `${evalRateSign}${evalRate.toFixed(2)}%`
    rv[6].style.color = evalColor
    const cumSign = cumPnl.pnl > 0 ? '+' : ''
    const cumColor = pnlColor(cumPnl.pnl)
    rv[7].textContent = `${cumSign}${cumPnl.pnl.toLocaleString()}원`
    rv[7].style.color = cumColor
    rv[8].textContent = `${cumSign}${cumPnl.rate.toFixed(2)}%`
    rv[8].style.color = cumColor
  }
}

/* ── 탭 버튼 스타일 ── */
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
  const today = new Date().toISOString().slice(0, 10)
  const yearMonth = today.slice(0, 7)

  const dayS = aggregatePnl(sellHistory, today, today)
  const monS = aggregatePnl(sellHistory, yearMonth + '-01', yearMonth + '-31')
  const allS = aggregatePnl(sellHistory)

  if (todayPnlEl) { todayPnlEl.textContent = fmtWon(dayS.pnl); todayPnlEl.style.color = pnlColor(dayS.pnl) }
  if (todayRateEl) { todayRateEl.textContent = `${dayS.rate.toFixed(2)}%`; todayRateEl.style.color = pnlColor(dayS.pnl) }
  if (monthPnlEl) { monthPnlEl.textContent = fmtWon(monS.pnl); monthPnlEl.style.color = pnlColor(monS.pnl) }
  if (monthRateEl) { monthRateEl.textContent = `${monS.rate.toFixed(2)}%`; monthRateEl.style.color = pnlColor(monS.pnl) }
  if (totalPnlEl) { totalPnlEl.textContent = fmtWon(allS.pnl); totalPnlEl.style.color = pnlColor(allS.pnl) }
  if (totalRateEl) { totalRateEl.textContent = `${allS.rate.toFixed(2)}%`; totalRateEl.style.color = pnlColor(allS.pnl) }
}

/* ── 드릴다운 컬럼 ── */
const DRILLDOWN_COLS: ColumnDef<DailyDrilldownRow>[] = [
  { key: 'date', label: '날짜', align: 'center', render: r => {
    const span = document.createElement('span')
    span.style.cursor = 'pointer'
    span.style.color = '#1976d2'
    span.style.textDecoration = 'underline'
    span.textContent = r.date.slice(5) // MM-DD
    span.addEventListener('click', () => filterByDate(r.date))
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
    drilldownTable = createDataTable<DailyDrilldownRow>({
      columns: DRILLDOWN_COLS,
      emptyText: '당월 거래 내역이 없습니다.',
      zebraStriping: true,
    })
    drilldownViewContainer.appendChild(drilldownTable.el)
  }

  const yearMonth = new Date().toISOString().slice(0, 7)
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
    Object.assign(dummyMsg.style, { textAlign: 'center', fontSize: FONT_SIZE.badge, color: '#999', marginTop: '-4px' })
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

  const state = appStore.getState()
  const isTestMode = state.settings?.trade_mode === 'test'

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
  const retentionLabel = document.createElement('span')
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

  // 테스트모드/실시간 상태 뱃지
  wsBadge = createWsStatusBadge({
    subscribed: !isTestMode,
    broker: isTestMode ? undefined : 'kiwoom',
    label: isTestMode ? '테스트모드' : undefined,
  })
  accountHeader.appendChild(wsBadge.el)
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
    if (i === 5) holdingCountLabelTest = label
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
      dateFilter = new Date().toISOString().slice(0, 10)
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
    data: buildChartFromDailySummary(appStore.getState().dailySummary),
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
        const state = appStore.getState()
        const tradeMode = state.settings?.trade_mode || 'test'
        const token = localStorage.getItem('token') || 'dev-bypass'
        const params = new URLSearchParams({ date_from: from, date_to: to, trade_mode: tradeMode })
        const resp = await fetch(`/api/trade-history/daily-summary?${params}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (resp.ok) {
          const data = await resp.json()
          chart?.updateData(buildChartFromDailySummary(data))
        }
      } catch (err) {
        console.warn('[profit-overview] daily-summary fetch failed:', err)
      }
    },
  })

  // 초기 데이터 반영 — subscribe 등록 전에 모듈 변수 할당 (Bug 5 fix)
  const initState = appStore.getState()
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  // 초기화면: 당일 내역 표시
  dateFilter = new Date().toISOString().slice(0, 10)
  updateTabLabels()
  updateSummaryCards()
  showTable()

  // appStore 구독 — rAF coalescing + selective update
  let prevSellRef = initState.sellHistory
  let prevBuyRef = initState.buyHistory
  let prevDailySummaryRef = initState.dailySummary
  let prevAccountRef = initState.account
  let prevTradeMode = initState.settings?.trade_mode
  let prevPositionsRef = initState.positions
  _mounted = true

  unsubAccount = appStore.subscribe((curr) => {
    // 필드 그룹별 참조 비교
    const accountChanged = curr.account !== prevAccountRef || curr.positions !== prevPositionsRef
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const chartChanged = curr.dailySummary !== prevDailySummaryRef || curr.settings?.trade_mode !== prevTradeMode

    // 아무것도 변경되지 않으면 skip
    if (!accountChanged && !historyChanged && !chartChanged) return

    // 참조 갱신
    if (accountChanged) {
      prevAccountRef = curr.account
      prevPositionsRef = curr.positions
      _dirtyAccount = true
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
      prevTradeMode = curr.settings?.trade_mode
      _dirtyChart = true
    }

    // rAF coalescing: 이미 예약된 rAF가 있으면 추가 예약하지 않음
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
        const latest = appStore.getState()
        const tradeModeChanged = latest.settings?.trade_mode !== prevTradeMode
        chart?.updateData(buildChartFromDailySummary(latest.dailySummary))
        if (tradeModeChanged) {
          prevTradeMode = latest.settings?.trade_mode
          const isTest = latest.settings?.trade_mode === 'test'
          wsBadge?.update(!isTest, isTest ? undefined : 'kiwoom', isTest ? '테스트모드' : undefined)
          retentionLabel.textContent = isTest ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
          // 계좌 현황 컨테이너 토글
          if (realAccountContainer && testAccountContainer) {
            realAccountContainer.style.display = isTest ? 'none' : ''
            testAccountContainer.style.display = isTest ? '' : 'none'
          }
          renderAccountVals()
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
  if (unsubAccount) { unsubAccount(); unsubAccount = null }
  if (chart) { chart.destroy(); chart = null }
  if (sellTable) { sellTable.destroy(); sellTable = null }
  if (buyTable) { buyTable.destroy(); buyTable = null }
  if (drilldownTable) { drilldownTable.destroy(); drilldownTable = null }
  drilldownActive = false
  dateFilter = null
  tabRow = null
  wsBadge = null
  accountValRefs = []
  testAccountValRefs = []
  holdingCountLabel = null
  holdingCountLabelTest = null
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
}

export default { mount, unmount }
