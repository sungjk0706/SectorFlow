// frontend/src/pages/profit-shared.ts
// 수익현황 페이지 공통 모듈 — profit-overview.ts와 profit-detail.ts가 공유하는 로직

import type { ColumnDef } from '../components/common/data-table'
import { pnlColor, fmtWon, fmtComma, createStockNameColumn, createCodeCell, createNumberCell, COLOR } from '../components/common/ui-styles'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import type { AccountSnapshot } from '../types'

/* ── 타입 정의 ── */

export interface PnlSummary {
  pnl: number       // 실현손익 합계
  buyTotal: number   // 매수금액 합계
  rate: number       // pnl / buyTotal * 100 (buyTotal=0이면 0)
}

export interface DailyDrilldownRow {
  date: string
  sellCount: number
  buyCount: number
  pnl: number
  buyTotal: number
  rate: number
}

/* ── 순수 함수 ── */

/** 로컬 시간 기준 오늘 날짜 (YYYY-MM-DD). UTC 시차 문제 방지. */
export function getLocalToday(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
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

/** 일별 요약 → 차트 데이터 변환. 매도 없는 날(sell_count=0)은 pnl=null로 표시 → 막대 안 그림 */
export function buildChartFromDailySummary(summary: Record<string, unknown>[]): { date: string; pnl: number | null; rate: number }[] {
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

/* ── 매수 컬럼 (7개) ── */
export const BUY_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', minWidth: 36, maxWidth: 36, render: (_, i) => String(i + 1) },
  { key: 'datetime', label: '일시', align: 'center', minWidth: 80, render: r => { const d = String(r.date ?? ''); const t = String(r.time ?? ''); const dd = d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d; return dd + (t ? ' ' + t : '') } },
  { key: 'stk_cd', label: '종목코드', align: 'center', minWidth: 72, maxWidth: 72, render: r => createCodeCell(String(r.stk_cd ?? '')) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      const state = hotStore.getState()
      const sectorStock = state.sectorStocks[normalizeStockCode(String(r.stk_cd ?? ''))]
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
export const SELL_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', minWidth: 36, maxWidth: 36, render: (_, i) => String(i + 1) },
  { key: 'datetime', label: '일시', align: 'center', minWidth: 80, render: r => { const d = String(r.date ?? ''); const t = String(r.time ?? ''); const dd = d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d; return dd + (t ? ' ' + t : '') } },
  { key: 'stk_cd', label: '종목코드', align: 'center', minWidth: 72, maxWidth: 72, render: r => createCodeCell(String(r.stk_cd ?? '')) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      const state = hotStore.getState()
      const sectorStock = state.sectorStocks[normalizeStockCode(String(r.stk_cd ?? ''))]
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
    const pnl = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(pnl)
    span.textContent = fmtComma(sell)
    return span
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

/* ── 드릴다운 컬럼 (팩토리 — onDateClick 콜백 주입) ── */
export function createDrilldownCols(onDateClick: (date: string) => void): ColumnDef<DailyDrilldownRow>[] {
  return [
    { key: 'date', label: '날짜', align: 'center', render: r => {
      const span = document.createElement('span')
      span.style.cursor = 'pointer'
      span.style.color = COLOR.down
      span.style.textDecoration = 'underline'
      span.textContent = r.date.slice(5) // MM-DD
      span.addEventListener('click', () => onDateClick(r.date))
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
}

/* ── 더미 데이터 ── */
export const DUMMY_BUY: Record<string, unknown>[] = [
  { date: '2026-04-14', time: '09:15:00', stk_cd: '005930', stk_nm: '삼성전자', price: 70000, qty: 100, total_amt: 7001050, fee: 1050 },
  { date: '2026-04-14', time: '09:22:00', stk_cd: '000660', stk_nm: 'SK하이닉스', price: 185000, qty: 50, total_amt: 9251388, fee: 1388 },
]

export const DUMMY_SELL: Record<string, unknown>[] = [
  { date: '2026-04-14', time: '10:05:00', stk_cd: '005930', stk_nm: '삼성전자', avg_buy_price: 70000, price: 71500, qty: 100, buy_total_amt: 7001050, total_amt: 7134627, realized_pnl: 133577, pnl_rate: 1.91, fee: 1073, tax: 14300 },
  { date: '2026-04-14', time: '10:30:00', stk_cd: '000660', stk_nm: 'SK하이닉스', avg_buy_price: 185000, price: 183000, qty: 50, buy_total_amt: 9251388, total_amt: 9130327, realized_pnl: -121061, pnl_rate: -1.31, fee: 1373, tax: 18300 },
]

/* ── 계좌 현황 렌더 (순수 함수 — 매개변수 기반) ── */

export interface AccountValsParams {
  account: AccountSnapshot | null
  positionCount: number
  isTestMode: boolean
  buyHistory: Record<string, unknown>[]
  sellHistory: Record<string, unknown>[]
  realAccountContainer: HTMLDivElement | null
  testAccountContainer: HTMLDivElement | null
  accountValRefs: HTMLSpanElement[]
  testAccountValRefs: HTMLSpanElement[]
  holdingCountSpan: HTMLSpanElement | null
  holdingCountSpanTest: HTMLSpanElement | null
}

export function renderAccountVals(params: AccountValsParams): void {
  const { account: a, positionCount, isTestMode, buyHistory, sellHistory } = params

  // 당일 매수/매도금액은 체결 이력에서 직접 집계
  const today = getLocalToday()
  const todayBuyAmt = buyHistory
    .filter(r => String(r.date ?? '') === today)
    .reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const todaySellAmt = sellHistory
    .filter(r => String(r.date ?? '') === today)
    .reduce((s, r) => s + Number(r.total_amt ?? 0), 0)

  // 보유주식 평가금액/평가손익/수익률: 백엔드가 실시간 계산하여 전송한 account 값 직접 사용
  const evalTotal = a?.total_eval_amount ?? 0
  const evalPnl = a?.total_pnl ?? 0
  const evalRate = a?.total_pnl_rate ?? 0

  // 누적 실현 손익: sellHistory 전체 합산
  const cumPnl = aggregatePnl(sellHistory)

  // CSS display 토글로 모드별 컨테이너 전환
  if (params.realAccountContainer && params.testAccountContainer) {
    params.realAccountContainer.style.display = isTestMode ? 'none' : ''
    params.testAccountContainer.style.display = isTestMode ? '' : 'none'
  }

  if (isTestMode) {
    // 테스트모드: 9행 (누적투자금, 주문가능금액, 오늘매수, 오늘매도, 보유평가금액, 보유평가손익, 보유평가수익률, 누적손익, 누적수익률)
    const tv = params.testAccountValRefs
    if (tv.length < 9) return
    const accumulatedInvestment = a?.accumulated_investment ?? a?.initial_deposit ?? 0
    const orderable = a?.orderable ?? 0
    tv[0].textContent = `${accumulatedInvestment.toLocaleString()}원`
    tv[1].textContent = `${orderable.toLocaleString()}원`
    tv[2].textContent = `${todayBuyAmt.toLocaleString()}원`
    tv[3].textContent = `${todaySellAmt.toLocaleString()}원`
    tv[4].textContent = `${evalTotal.toLocaleString()}원`
    if (params.holdingCountSpanTest) params.holdingCountSpanTest.textContent = String(positionCount)
    const evalSign = evalPnl > 0 ? '+' : ''
    const evalColor = pnlColor(evalPnl)
    tv[5].textContent = `${evalSign}${evalPnl.toLocaleString()}원`
    tv[5].style.color = evalColor
    const evalRateSign = evalRate > 0 ? '+' : ''
    tv[6].textContent = `${evalRateSign}${evalRate.toFixed(2)}%`
    tv[6].style.color = evalColor
    const cumSign = cumPnl.pnl > 0 ? '+' : ''
    const cumColor = pnlColor(cumPnl.pnl)
    tv[7].textContent = `${cumSign}${cumPnl.pnl.toLocaleString()}원`
    tv[7].style.color = cumColor
    tv[8].textContent = `${cumSign}${cumPnl.rate.toFixed(2)}%`
    tv[8].style.color = cumColor
  } else {
    // 실전모드: 9행 (예수금, 주문가능금액, 오늘매수, 오늘매도, 보유평가금액, 보유평가손익, 보유평가수익률, 누적손익, 누적수익률)
    const rv = params.accountValRefs
    if (rv.length < 9) return
    const deposit = a?.deposit ?? 0
    const orderable = a?.orderable ?? Math.max(0, deposit - todayBuyAmt)
    rv[0].textContent = `${deposit.toLocaleString()}원`
    rv[1].textContent = `${orderable.toLocaleString()}원`
    rv[2].textContent = `${todayBuyAmt.toLocaleString()}원`
    rv[3].textContent = `${todaySellAmt.toLocaleString()}원`
    rv[4].textContent = `${evalTotal.toLocaleString()}원`
    if (params.holdingCountSpan) params.holdingCountSpan.textContent = String(positionCount)
    const evalSign = evalPnl > 0 ? '+' : ''
    const evalColor = pnlColor(evalPnl)
    rv[5].textContent = `${evalSign}${evalPnl.toLocaleString()}원`
    rv[5].style.color = evalColor
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
