// frontend/src/pages/profit-shared.ts
// 수익현황 페이지 공통 모듈 — profit-overview.ts와 profit-detail.ts가 공유하는 로직

import type { ColumnDef } from '../components/common/data-table'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, fmtComma, createStockNameColumn, createCodeCell, createNumberCell, COLOR } from '../components/common/ui-styles'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import type { AccountSnapshot, Position, SectorStock } from '../types'
import type { SectorDonutRow } from '../components/canvas-sector-donut'
import { assignSectorColors } from '../components/canvas-sector-donut'

/* ── 타입 정의 ── */

export interface SectorStockPnl {
  stk_cd: string
  stk_nm: string
  realized_pnl: number
  pnl_rate: number
  qty: number
}

export interface SectorPnlGroup {
  sector: string
  color: string
  pnl: number
  rate: number
  stocks: SectorStockPnl[]
}

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

/* ── 요약 카드 공통 함수 ── */

export interface SummaryCardEls {
  todayPnlEl: HTMLSpanElement
  todayRateEl: HTMLSpanElement
  monthPnlEl: HTMLSpanElement
  monthRateEl: HTMLSpanElement
  totalPnlEl: HTMLSpanElement
  totalRateEl: HTMLSpanElement
  todayCard: HTMLDivElement
  monthCard: HTMLDivElement
  totalCard: HTMLDivElement
}

export interface SummaryCardCallbacks {
  onTodayClick?: () => void
  onMonthClick?: () => void
  onTotalClick?: () => void
}

/** 요약 카드 3개(당일/당월/누적 손익) DOM 생성, 클릭 콜백 주입, 요소 참조 반환 */
export function createSummaryCards(container: HTMLElement, callbacks: SummaryCardCallbacks = {}): SummaryCardEls {
  const CARD_STYLE = `flex:1;background:${COLOR.surfaceLight};border:1px solid ${COLOR.borderLight};border-radius:6px;padding:6px 12px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;`
  const CARD_TITLES = ['당일 손익', '당월 손익', '누적 손익']
  const clickHandlers = [callbacks.onTodayClick, callbacks.onMonthClick, callbacks.onTotalClick]

  const pnlEls: HTMLSpanElement[] = []
  const rateEls: HTMLSpanElement[] = []
  const cardEls: HTMLDivElement[] = []

  for (let i = 0; i < 3; i++) {
    const card = document.createElement('div')
    card.style.cssText = CARD_STYLE
    const handler = clickHandlers[i]
    if (handler) card.addEventListener('click', handler)
    cardEls.push(card)

    const titleEl = document.createElement('div')
    Object.assign(titleEl.style, { fontSize: FONT_SIZE.section, color: COLOR.tertiary, whiteSpace: 'nowrap' })
    titleEl.textContent = CARD_TITLES[i]

    const valRow = document.createElement('div')
    Object.assign(valRow.style, { display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', gap: '6px' })

    const pnlEl = document.createElement('span')
    Object.assign(pnlEl.style, { fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.normal })
    pnlEl.textContent = fmtWon(0)

    const rateEl = document.createElement('span')
    Object.assign(rateEl.style, { fontSize: FONT_SIZE.label, color: COLOR.neutral })
    rateEl.textContent = '0.00%'

    valRow.appendChild(pnlEl)
    valRow.appendChild(rateEl)
    card.appendChild(titleEl)
    card.appendChild(valRow)
    container.appendChild(card)

    pnlEls.push(pnlEl)
    rateEls.push(rateEl)
  }

  return {
    todayPnlEl: pnlEls[0], todayRateEl: rateEls[0],
    monthPnlEl: pnlEls[1], monthRateEl: rateEls[1],
    totalPnlEl: pnlEls[2], totalRateEl: rateEls[2],
    todayCard: cardEls[0], monthCard: cardEls[1], totalCard: cardEls[2],
  }
}

/** 당일/당월/누적 손익 계산 및 요약 카드 DOM 갱신 */
export function updateSummaryCards(
  sellHistory: Record<string, unknown>[],
  dailySummary: Record<string, unknown>[],
  els: SummaryCardEls,
): void {
  const today = getLocalToday()
  const yearMonth = today.slice(0, 7)

  const todayEntry = dailySummary.find(r => String(r.date ?? '') === today)
  const dayPnl = todayEntry ? Number(todayEntry.realized_pnl ?? 0) : 0
  const dayRate = todayEntry ? Number(todayEntry.pnl_rate ?? 0) : 0

  const monS = aggregatePnl(sellHistory, yearMonth + '-01', yearMonth + '-31')
  const allS = aggregatePnl(sellHistory)

  els.todayPnlEl.textContent = fmtWon(dayPnl)
  els.todayPnlEl.style.color = pnlColor(dayPnl)
  els.todayRateEl.textContent = `${dayRate.toFixed(2)}%`
  els.todayRateEl.style.color = pnlColor(dayPnl)
  els.monthPnlEl.textContent = fmtWon(monS.pnl)
  els.monthPnlEl.style.color = pnlColor(monS.pnl)
  els.monthRateEl.textContent = `${monS.rate.toFixed(2)}%`
  els.monthRateEl.style.color = pnlColor(monS.pnl)
  els.totalPnlEl.textContent = fmtWon(allS.pnl)
  els.totalPnlEl.style.color = pnlColor(allS.pnl)
  els.totalRateEl.textContent = `${allS.rate.toFixed(2)}%`
  els.totalRateEl.style.color = pnlColor(allS.pnl)
}

/** sellHistory → 업종별 종목 수익 집계 (도넛 차트 색상 동기화)
 *  1. sellHistory를 업종별로 그룹화
 *  2. 동일 종목(stk_cd)의 여러 매도 기록을 합산
 *  3. 도넛 차트와 동일한 절대값 내림차순 정렬 + 색상 할당
 */
export function buildSectorStockPnl(
  sells: Record<string, unknown>[],
): SectorPnlGroup[] {
  // 1. 업종별 손익 및 매수금액 집계 (도넛 차트와 동일 로직)
  const sectorPnlMap = new Map<string, number>()
  const sectorBuyTotalMap = new Map<string, number>()
  for (const r of sells) {
    const sector = String(r.sector ?? '미분류')
    const pnl = Number(r.realized_pnl ?? 0)
    const buyTotal = Number(r.buy_total_amt ?? 0)
    sectorPnlMap.set(sector, (sectorPnlMap.get(sector) ?? 0) + pnl)
    sectorBuyTotalMap.set(sector, (sectorBuyTotalMap.get(sector) ?? 0) + buyTotal)
  }

  // 2. 절대값 내림차순 정렬 (도넛 차트 processData와 동일)
  const donutRows: SectorDonutRow[] = Array.from(sectorPnlMap.entries())
    .map(([sector, pnl]) => ({ sector, pnl }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))

  // 3. 색상 할당 (공유 함수 사용 — SSOT)
  const colorMap = assignSectorColors(donutRows)

  // 4. 종목별 집계: 동일 stk_cd의 매도 기록 합산
  const stockMap = new Map<string, { stk_nm: string; realized_pnl: number; pnl_rate: number; qty: number; buy_total: number }>()
  for (const r of sells) {
    const sector = String(r.sector ?? '미분류')
    const stkCd = String(r.stk_cd ?? '')
    const key = sector + '\0' + stkCd
    const pnl = Number(r.realized_pnl ?? 0)
    const qty = Number(r.qty ?? 0)
    const buyTotal = Number(r.buy_total_amt ?? 0)
    const existing = stockMap.get(key)
    if (existing) {
      existing.realized_pnl += pnl
      existing.qty += qty
      existing.buy_total += buyTotal
    } else {
      stockMap.set(key, {
        stk_nm: String(r.stk_nm ?? ''),
        realized_pnl: pnl,
        pnl_rate: 0,
        qty,
        buy_total: buyTotal,
      })
    }
  }

  // 5. pnl_rate 계산 (합산된 기준)
  for (const v of stockMap.values()) {
    v.pnl_rate = v.buy_total > 0 ? Math.round(v.realized_pnl / v.buy_total * 10000) / 100 : 0
  }

  // 6. 업종별 그룹 조립
  return donutRows.map(({ sector, pnl }) => {
    const stocks: SectorStockPnl[] = []
    for (const [key, v] of stockMap) {
      const [sec] = key.split('\0')
      if (sec === sector) {
        stocks.push({
          stk_cd: key.split('\0')[1] ?? '',
          stk_nm: v.stk_nm,
          realized_pnl: v.realized_pnl,
          pnl_rate: v.pnl_rate,
          qty: v.qty,
        })
      }
    }
    stocks.sort((a, b) => Math.abs(b.realized_pnl) - Math.abs(a.realized_pnl))
    const sectorBuyTotal = sectorBuyTotalMap.get(sector) ?? 0
    const sectorRate = sectorBuyTotal > 0 ? Math.round(pnl / sectorBuyTotal * 10000) / 100 : 0
    return {
      sector,
      color: colorMap.get(sector) ?? COLOR.disabled,
      pnl,
      rate: sectorRate,
      stocks,
    }
  })
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
export function buildChartFromDailySummary(summary: Record<string, unknown>[]): { date: string; pnl: number | null; rate: number; buyFee: number; sellFee: number; tax: number }[] {
  const rows = summary.map(r => {
    const raw = String(r.date ?? '')
    const sellCount = Number(r.sell_count ?? 0)
    if (sellCount === 0) return { date: raw, pnl: null, rate: 0, buyFee: 0, sellFee: 0, tax: 0 }
    const pnl = Number(r.realized_pnl ?? 0)
    const rate = Number(r.pnl_rate ?? 0)
    const buyFee = Number(r.buy_fee ?? 0)
    const sellFee = Number(r.sell_fee ?? 0)
    const tax = Number(r.tax ?? 0)
    return { date: raw, pnl, rate, buyFee, sellFee, tax }
  })
  // X축: 왼쪽=과거, 오른쪽=최신
  return rows
}

/* ── 매수 컬럼 (7개) ── */
export const BUY_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', minWidth: 36, maxWidth: 36, render: (_, i) => String(i + 1) },
  { key: 'datetime', label: '일시', align: 'center', minWidth: 80, maxWidth: 95, render: r => { const d = String(r.date ?? ''); const t = String(r.time ?? ''); const dd = d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d; return dd + (t ? ' ' + t : '') } },
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
  { key: 'price', label: '매수가', align: 'right', minWidth: 60, maxWidth: 72, render: r => createNumberCell(Number(r.price ?? 0)) },
  { key: 'qty', label: '수량', align: 'right', minWidth: 48, maxWidth: 56, render: r => createNumberCell(Number(r.qty ?? 0)) },
  { key: 'total_amt', label: '매수금액', align: 'right', minWidth: 72, maxWidth: 85, render: r => fmtWon(Number(r.total_amt ?? 0)) },
  { key: 'fee', label: '수수료', align: 'right', minWidth: 60, maxWidth: 72, render: r => fmtWon(Number(r.fee ?? 0)) },
]

/* ── 매도 컬럼 (12개) ── */
export const SELL_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', minWidth: 36, maxWidth: 36, render: (_, i) => String(i + 1) },
  { key: 'datetime', label: '일시', align: 'center', minWidth: 80, maxWidth: 95, render: r => { const d = String(r.date ?? ''); const t = String(r.time ?? ''); const dd = d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d; return dd + (t ? ' ' + t : '') } },
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
  { key: 'avg_buy_price', label: '매수가', align: 'right', minWidth: 60, maxWidth: 72, render: r => createNumberCell(Number(r.avg_buy_price ?? 0)) },
  { key: 'price', label: '매도가', align: 'right', minWidth: 60, maxWidth: 72, render: r => {
    const sell = Number(r.price ?? 0)
    const pnl = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(pnl)
    span.textContent = fmtComma(sell)
    return span
  }},
  { key: 'qty', label: '수량', align: 'right', minWidth: 48, maxWidth: 56, render: r => createNumberCell(Number(r.qty ?? 0)) },
  { key: 'buy_total_amt', label: '매수금액', align: 'right', minWidth: 72, maxWidth: 85, render: r => fmtWon(Number(r.buy_total_amt ?? 0)) },
  { key: 'total_amt', label: '매도금액', align: 'right', minWidth: 72, maxWidth: 85, render: r => {
    const v = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = fmtWon(Number(r.total_amt ?? 0))
    return span
  }},
  { key: 'realized_pnl', label: '실현손익', align: 'right', minWidth: 72, maxWidth: 85, render: r => {
    const v = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = `${v > 0 ? '+' : ''}${v.toLocaleString()}원`
    return span
  }},
  { key: 'pnl_rate', label: '수익률', align: 'right', minWidth: 60, maxWidth: 72, render: r => {
    const v = Number(r.pnl_rate ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
    return span
  }},
  { key: 'fee', label: '수수료', align: 'right', minWidth: 60, maxWidth: 72, render: r => fmtWon(Number(r.fee ?? 0)) },
  { key: 'tax', label: '세금', align: 'right', minWidth: 60, maxWidth: 72, render: r => fmtWon(Number(r.tax ?? 0)) },
]

/* ── 드릴다운 컬럼 (팩토리 — onDateClick 콜백 주입) ── */
export function createDrilldownCols(onDateClick: (date: string) => void): ColumnDef<DailyDrilldownRow>[] {
  return [
    { key: 'date', label: '날짜', align: 'center', minWidth: 60, maxWidth: 72, render: r => {
      const span = document.createElement('span')
      span.style.cursor = 'pointer'
      span.style.color = COLOR.down
      span.style.textDecoration = 'underline'
      span.textContent = r.date.slice(5) // MM-DD
      span.addEventListener('click', () => onDateClick(r.date))
      return span
    }},
    { key: 'sellCount', label: '매도건수', align: 'right', minWidth: 52, maxWidth: 60, render: r => String(r.sellCount) },
    { key: 'buyCount', label: '매수건수', align: 'right', minWidth: 52, maxWidth: 60, render: r => String(r.buyCount) },
    { key: 'pnl', label: '당일손익', align: 'right', minWidth: 72, maxWidth: 85, render: r => {
      const span = document.createElement('span')
      span.style.color = pnlColor(r.pnl)
      span.textContent = fmtWon(r.pnl)
      return span
    }},
    { key: 'rate', label: '당일수익률', align: 'right', minWidth: 60, maxWidth: 72, render: r => {
      const span = document.createElement('span')
      span.style.color = pnlColor(r.rate)
      span.textContent = `${r.rate > 0 ? '+' : ''}${r.rate.toFixed(2)}%`
      return span
    }},
  ]
}

/* ── 보유 종목 요약 계산 (순수 함수 — P22 데이터 정합성) ── */

/**
 * 보유 종목 positions + 실시간 시세 sectorStocks로부터 평가금액/평가손익/수익률 계산.
 * 개별 종목 행(sell-position.ts COLUMNS pnl/rate 컬럼)과 동일한 데이터 소스·공식 사용.
 *
 * - 현재가: sectorStocks[code].cur_price ?? p.cur_price (실시간 틱 우선)
 * - 매입가: p.buy_price ?? p.avg_price
 * - 평가금액 = sum(현재가 × 수량)
 * - 매입금액 = sum(매입가 × 수량)
 * - 평가손익 = 평가금액 - 매입금액
 * - 수익률 = 평가손익 / 매입금액 × 100 (가중 평균, 매입금액 0이면 0)
 */
export function computeHoldingsSummary(
  positions: Position[],
  sectorStocks: Record<string, SectorStock>,
): { evalTotal: number; evalPnl: number; evalRate: number; buyTotal: number } {
  let evalTotal = 0
  let buyTotal = 0
  for (const p of positions) {
    const qty = p.qty ?? 0
    if (qty <= 0) continue
    const code = normalizeStockCode(p.stk_cd)
    const curPrice = sectorStocks[code]?.cur_price ?? p.cur_price ?? 0
    const buyPrice = p.buy_price ?? p.avg_price ?? 0
    evalTotal += Number(curPrice) * qty
    buyTotal += buyPrice * qty
  }
  const evalPnl = evalTotal - buyTotal
  const evalRate = buyTotal > 0 ? Math.round((evalPnl / buyTotal) * 10000) / 100 : 0
  return { evalTotal, evalPnl, evalRate, buyTotal }
}

/* ── 계좌 현황 렌더 (순수 함수 — 매개변수 기반) ── */

export interface AccountValsParams {
  account: AccountSnapshot | null
  positions: Position[]
  sectorStocks: Record<string, SectorStock>
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

  // 당일/누적 수수료·세금 집계 (buyHistory.fee + sellHistory.fee + sellHistory.tax)
  const todayFeeTax =
    buyHistory.filter(r => String(r.date ?? '') === today).reduce((s, r) => s + Number(r.fee ?? 0), 0) +
    sellHistory.filter(r => String(r.date ?? '') === today).reduce((s, r) => s + Number(r.fee ?? 0) + Number(r.tax ?? 0), 0)
  const cumFeeTax =
    buyHistory.reduce((s, r) => s + Number(r.fee ?? 0), 0) +
    sellHistory.reduce((s, r) => s + Number(r.fee ?? 0) + Number(r.tax ?? 0), 0)

  // 보유주식 평가금액/평가손익/수익률: positions + sectorStocks에서 직접 계산 (개별 종목 행과 동일 소스·공식)
  const { evalTotal, evalPnl, evalRate } = computeHoldingsSummary(params.positions, params.sectorStocks)

  // 누적 실현 손익: sellHistory 전체 합산
  const cumPnl = aggregatePnl(sellHistory)

  // CSS display 토글로 모드별 컨테이너 전환
  if (params.realAccountContainer && params.testAccountContainer) {
    params.realAccountContainer.style.display = isTestMode ? 'none' : ''
    params.testAccountContainer.style.display = isTestMode ? '' : 'none'
  }

  if (isTestMode) {
    // 테스트모드: 11행 (누적투자금, 주문가능금액, 오늘매수, 오늘매도, 보유평가금액, 보유평가손익, 보유평가수익률, 오늘수수료/세금, 누적수수료/세금, 누적손익, 누적수익률)
    const tv = params.testAccountValRefs
    if (tv.length < 11) return
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
    tv[7].textContent = `${todayFeeTax.toLocaleString()}원`
    tv[8].textContent = `${cumFeeTax.toLocaleString()}원`
    const cumSign = cumPnl.pnl > 0 ? '+' : ''
    const cumColor = pnlColor(cumPnl.pnl)
    tv[9].textContent = `${cumSign}${cumPnl.pnl.toLocaleString()}원`
    tv[9].style.color = cumColor
    tv[10].textContent = `${cumSign}${cumPnl.rate.toFixed(2)}%`
    tv[10].style.color = cumColor
  } else {
    // 실전모드: 11행 (예수금, 주문가능금액, 오늘매수, 오늘매도, 보유평가금액, 보유평가손익, 보유평가수익률, 오늘수수료/세금, 누적수수료/세금, 누적손익, 누적수익률)
    const rv = params.accountValRefs
    if (rv.length < 11) return
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
    rv[7].textContent = `${todayFeeTax.toLocaleString()}원`
    rv[8].textContent = `${cumFeeTax.toLocaleString()}원`
    const cumSign = cumPnl.pnl > 0 ? '+' : ''
    const cumColor = pnlColor(cumPnl.pnl)
    rv[9].textContent = `${cumSign}${cumPnl.pnl.toLocaleString()}원`
    rv[9].style.color = cumColor
    rv[10].textContent = `${cumSign}${cumPnl.rate.toFixed(2)}%`
    rv[10].style.color = cumColor
  }
}
