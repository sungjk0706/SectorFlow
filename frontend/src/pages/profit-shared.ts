// frontend/src/pages/profit-shared.ts
// 수익현황 페이지 공통 모듈 — profit-overview.ts와 profit-detail.ts가 공유하는 로직

import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR, RADIUS, SHADOW, computeWeightedRate } from '../components/common/ui-styles'
import { normalizeStockCode } from '../stores/hotStore'
import { getTradingToday, isPreOpenPhase } from '../utils/date'
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
  rate: number
}

/* ── 당일 드릴다운 행 (실현/평가 영역 구분 — P22 정합성: 실현+평가=당일 카드 총액) ── */

export interface TodayDrilldownRealizedRow {
  stk_cd: string
  stk_nm: string
  realized_pnl: number
}

export interface TodayDrilldownEvalRow {
  stk_cd: string
  stk_nm: string
  pnl: number
  rate: number
  evalAmt: number
}

export interface TodayDrilldownResult {
  realizedRows: TodayDrilldownRealizedRow[]
  evalRows: TodayDrilldownEvalRow[]
  realizedTotal: number
  evalTotal: number
}

/* ── 누적 드릴다운 (월별 누적 손익 + 입금 이력 — P10 SSOT) ── */

export interface CumulativeMonthlyRow {
  yearMonth: string
  pnl: number
}

export interface DepositHistoryRow {
  date: string
  daily_deposit: number
}

export interface CumulativeDrilldownResult {
  monthlyRows: CumulativeMonthlyRow[]
  depositHistory: DepositHistoryRow[]
}

/* ── 요약 카드 공통 함수 ── */

export interface SummaryCardEls {
  todayPnlEl: HTMLSpanElement
  todayRateEl: HTMLSpanElement
  todaySubTextEl: HTMLSpanElement
  fivedayPnlEl: HTMLSpanElement
  fivedayRateEl: HTMLSpanElement
  monthPnlEl: HTMLSpanElement
  monthRateEl: HTMLSpanElement
  totalPnlEl: HTMLSpanElement
  totalRateEl: HTMLSpanElement
  todayCard: HTMLDivElement
  fivedayCard: HTMLDivElement
  monthCard: HTMLDivElement
  totalCard: HTMLDivElement
}

export interface SummaryCardCallbacks {
  onTodayClick?: () => void
  onFivedayClick?: () => void
  onMonthClick?: () => void
  onTotalClick?: () => void
}

const SUMMARY_CARD_STYLE = `flex:1;background:${COLOR.surfaceLight};border:1px solid ${COLOR.borderLight};border-radius:${RADIUS.sm};box-shadow:${SHADOW.card};padding:6px 12px;display:flex;flex-direction:column;justify-content:center;cursor:pointer;`
const SUMMARY_CARD_TITLES = ['당일 손익', '5거래일 손익', '당월 손익', '누적 손익']

/** 요약 카드 1개 DOM 생성. 실패 시 null 반환 (P25 격리 + P22 인덱스 정합성 — 호출부에서 더미 push).
 *  당일 카드(isToday=true)에만 서브 텍스트 요소(개장 전 표시용) 추가 — F-3-c. */
function buildSummaryCard(
  container: HTMLElement,
  title: string,
  handler: (() => void) | undefined,
  isToday: boolean,
): { pnlEl: HTMLSpanElement; rateEl: HTMLSpanElement; cardEl: HTMLDivElement; subTextEl?: HTMLSpanElement } | null {
  try {
    const card = document.createElement('div')
    card.style.cssText = SUMMARY_CARD_STYLE
    if (handler) card.addEventListener('click', handler)

    const titleEl = document.createElement('div')
    Object.assign(titleEl.style, { fontSize: FONT_SIZE.section, color: COLOR.tertiary, whiteSpace: 'nowrap' })
    titleEl.textContent = title

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

    let subTextEl: HTMLSpanElement | undefined
    if (isToday) {
      subTextEl = document.createElement('span')
      Object.assign(subTextEl.style, { fontSize: FONT_SIZE.label, color: COLOR.tertiary, marginTop: '2px', minHeight: '1em' })
      subTextEl.textContent = ''
      card.appendChild(subTextEl)
    }

    container.appendChild(card)
    return { pnlEl, rateEl, cardEl: card, subTextEl }
  } catch (e) {
    console.error('[profit-shared] summary card build error', e)
    return null
  }
}

/** 요약 카드 4개(당일/5거래일/당월/누적 손익) DOM 생성, 클릭 콜백 주입, 요소 참조 반환.
 *  전일 카드 제거 (다단계 1세션 결정 1). 당일 카드에 서브 텍스트 요소 포함 (F-3-c). */
export function createSummaryCards(container: HTMLElement, callbacks: SummaryCardCallbacks = {}): SummaryCardEls {
  const clickHandlers = [callbacks.onTodayClick, callbacks.onFivedayClick, callbacks.onMonthClick, callbacks.onTotalClick]

  const pnlEls: HTMLSpanElement[] = []
  const rateEls: HTMLSpanElement[] = []
  const cardEls: HTMLDivElement[] = []
  let todaySubTextEl: HTMLSpanElement | undefined

  for (let i = 0; i < 4; i++) {
    // P25: 카드 단위 격리 — 한 카드 생성 throw 시 다음 카드 계속 렌더링.
    // 실패 시 더미 push로 인덱스 정합성 유지 (P22). buildStatRow 패턴과 일치 (P23).
    const built = buildSummaryCard(container, SUMMARY_CARD_TITLES[i], clickHandlers[i], i === 0)
    if (built) {
      pnlEls.push(built.pnlEl)
      rateEls.push(built.rateEl)
      cardEls.push(built.cardEl)
      if (i === 0 && built.subTextEl) todaySubTextEl = built.subTextEl
    } else {
      const dummyPnl = document.createElement('span')
      dummyPnl.textContent = '-'
      pnlEls.push(dummyPnl)
      const dummyRate = document.createElement('span')
      dummyRate.textContent = '-'
      rateEls.push(dummyRate)
      const dummyCard = document.createElement('div')
      cardEls.push(dummyCard)
    }
  }

  return {
    todayPnlEl: pnlEls[0], todayRateEl: rateEls[0],
    todaySubTextEl: todaySubTextEl ?? document.createElement('span'),
    fivedayPnlEl: pnlEls[1], fivedayRateEl: rateEls[1],
    monthPnlEl: pnlEls[2], monthRateEl: rateEls[2],
    totalPnlEl: pnlEls[3], totalRateEl: rateEls[3],
    todayCard: cardEls[0], fivedayCard: cardEls[1], monthCard: cardEls[2], totalCard: cardEls[3],
  }
}

/** dailySummary에서 최근 5거래일 날짜를 내림차순 추출.
 *  5거래일 카드 집계와 5거래일 카드 클릭 시 드릴다운 날짜 범위의 공통 소스 — P10 SSOT. */
export function getRecent5TradingDays(dailySummary: Record<string, unknown>[]): string[] {
  const dates = dailySummary
    .map(r => String(r.date ?? ''))
    .filter(d => d)
    .sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))
  return dates.slice(0, 5)
}

/** dailySummary에서 earliest_base_asset 추출 (모든 행 동일 값 — B-2).
 *  computeCumulativePnl·renderAccountVals·buildDonutCenter 공통 분모 소스 — P10 SSOT.
 *  undefined 반환 시 호출처에서 rate null → '-' 표시 (P20 폴백 금지). */
export function extractEarliestBaseAsset(dailySummary: Record<string, unknown>[]): number | undefined {
  if (dailySummary.length === 0) return undefined
  const v = dailySummary[0].earliest_base_asset
  if (v == null) return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

/** 당일/5거래일/당월/누적 손익 계산 및 요약 카드 DOM 갱신 (전일 카드 제거 — 다단계 1세션 결정 1).
 *  모든 카드를 computeCumulativePnl SSOT로 계산 (P10 SSOT — 분모 규칙 단일 소스).
 *  분모 규칙 (기초자산 분모 방식 + earliestBaseAsset):
 *    - 기간 한정 카드(당일/5거래일/당월): baseAsset = findBaseAssetForDate(dailySummary, 기간시작일)
 *      · baseAsset 없으면 earliestBaseAsset (둘 다 없으면 rate null → '-' 표시, P20 폴백 금지)
 *      · 당일 카드: 전일 baseAsset + account.daily_deposit (당일 순입출금 보정, 결정 2)
 *    - 누적 카드: 테스트=accumulated_investment, 실전=earliestBaseAsset (buyTotal 폐지 — 다단계 1세션 결정 5)
 *  당일 카드 (F-3-c): PRE_OPEN(개장 전) → 0원 + "개장 전" 서브 텍스트.
 *    08:00+ → 오늘 실현(sellHistory 오늘 매도 realized_pnl 합) + 보유 평가(computeHoldingsSummary.evalPnl).
 *  dailySummary는 5거래일 날짜·base_asset·earliest_base_asset 추출에 사용 (날짜·기초자산 결정 SSOT). */
export function updateSummaryCards(
  dailySummary: Record<string, unknown>[],
  els: SummaryCardEls,
  sellHistory: Record<string, unknown>[],
  account: AccountSnapshot | null,
  isTestMode: boolean,
  positions: Position[],
  sectorStocks: Record<string, SectorStock>,
  earliestBaseAsset?: number,
): void {
  const today = getTradingToday()
  const yearMonth = today.slice(0, 7)
  const monthStart = yearMonth + '-01'
  const monthEnd = yearMonth + '-31'

  // 5거래일 날짜 범위 (내림차순 → [0]=최근, [4]=5번째)
  const recent5 = getRecent5TradingDays(dailySummary)
  const fivedayFrom = recent5.length > 0 ? recent5[recent5.length - 1] : ''
  const fivedayTo = recent5.length > 0 ? recent5[0] : ''

  // 기초자산 추출 (dailySummary에서 기간 시작일의 전일 장마감 스냅샷)
  const dayBaseAssetRaw = findBaseAssetForDate(dailySummary, today)
  // 당일 카드 분모 = 전일 baseAsset + 당일 입금액 (결정 2). 단, baseAsset 없으면 earliestBaseAsset 적용 — daily_deposit 보정 제외
  const dayBaseAsset = dayBaseAssetRaw != null
    ? dayBaseAssetRaw + (account?.daily_deposit ?? 0)
    : earliestBaseAsset
  const fiveBaseAsset = (fivedayFrom && fivedayTo) ? findBaseAssetForDate(dailySummary, fivedayFrom) : undefined
  const monthBaseAsset = findBaseAssetForDate(dailySummary, monthStart)

  // 당일 카드: 개장 전 여부 분기 (F-3-c)
  const preOpen = isPreOpenPhase()
  let dayPnl: number
  let dayRate: number | null
  if (preOpen) {
    // 개장 전: 0원 + 0.00% (강제 — 당일 성과 미확정)
    dayPnl = 0
    dayRate = 0
    els.todaySubTextEl.textContent = '개장 전'
  } else {
    // 08:00+: 오늘 실현(sellHistory 오늘 매도 realized_pnl 합) + 보유 평가(computeHoldingsSummary.evalPnl)
    const realizedToday = sellHistory
      .filter(r => String(r.date ?? '') === today)
      .reduce((s, r) => s + Number(r.realized_pnl ?? 0), 0)
    const { evalPnl } = computeHoldingsSummary(positions, sectorStocks)
    dayPnl = realizedToday + evalPnl
    dayRate = dayBaseAsset != null ? computeWeightedRate(dayPnl, dayBaseAsset) : null
    els.todaySubTextEl.textContent = ''
  }

  // 5거래일/당월/누적 카드: computeCumulativePnl SSOT 호출 (분모 규칙은 함수 내부에서 통일)
  const fiveS = (fivedayFrom && fivedayTo)
    ? computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: fivedayFrom, dateTo: fivedayTo, baseAsset: fiveBaseAsset, earliestBaseAsset })
    : { pnl: 0, rate: 0 as number | null }
  const monS = computeCumulativePnl({ sellHistory, account, isTestMode, dateFrom: monthStart, dateTo: monthEnd, baseAsset: monthBaseAsset, earliestBaseAsset })
  const allS = computeCumulativePnl({ sellHistory, account, isTestMode, earliestBaseAsset })  // 누적: earliestBaseAsset 분모 (buyTotal 폐지)

  els.todayPnlEl.textContent = fmtWon(dayPnl)
  els.todayPnlEl.style.color = pnlColor(dayPnl)
  els.todayRateEl.textContent = dayRate == null ? '-' : `${dayRate.toFixed(2)}%`
  els.todayRateEl.style.color = pnlColor(dayPnl)
  els.fivedayPnlEl.textContent = fmtWon(fiveS.pnl)
  els.fivedayPnlEl.style.color = pnlColor(fiveS.pnl)
  els.fivedayRateEl.textContent = fiveS.rate == null ? '-' : `${fiveS.rate.toFixed(2)}%`
  els.fivedayRateEl.style.color = pnlColor(fiveS.pnl)
  els.monthPnlEl.textContent = fmtWon(monS.pnl)
  els.monthPnlEl.style.color = pnlColor(monS.pnl)
  els.monthRateEl.textContent = monS.rate == null ? '-' : `${monS.rate.toFixed(2)}%`
  els.monthRateEl.style.color = pnlColor(monS.pnl)
  els.totalPnlEl.textContent = fmtWon(allS.pnl)
  els.totalPnlEl.style.color = pnlColor(allS.pnl)
  els.totalRateEl.textContent = allS.rate == null ? '-' : `${allS.rate.toFixed(2)}%`
  els.totalRateEl.style.color = pnlColor(allS.pnl)
}

/** sellHistory → 업종별 종목 수익 집계 (도넛 차트 색상 동기화)
 *  1. sellHistory를 업종별로 그룹화
 *  2. 동일 종목(stk_cd)의 여러 매도 기록을 합산
 *  3. 도넛 차트와 동일한 절대값 내림차순 정렬 + 색상 할당
 */
/** sellHistory → 업종별 손익 집계 + 도넛 차트 행 (절대값 내림차순 정렬).
 *  buildSectorStockPnl과 canvas-sector-donut의 공통 집계 소스 — P10 SSOT.
 *  도넛 rate 제거 (다단계 2세션 결정 9) — 금액(손익 원금)만 표시, buyTotal 분모 제거. */
export function buildSectorDonutRows(sells: Record<string, unknown>[]): SectorDonutRow[] {
  const pnlMap = new Map<string, number>()
  for (const r of sells) {
    const sector = String(r.sector ?? '미분류')
    const pnl = Number(r.realized_pnl ?? 0)
    pnlMap.set(sector, (pnlMap.get(sector) ?? 0) + pnl)
  }
  return Array.from(pnlMap.entries())
    .map(([sector, pnl]) => ({ sector, pnl }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
}

export function buildSectorStockPnl(
  sells: Record<string, unknown>[],
): SectorPnlGroup[] {
  // 1. 업종별 손익 집계 — 공통 함수 재사용 (P10 SSOT)
  const donutRows = buildSectorDonutRows(sells)

  // 2. 색상 할당 (공유 함수 사용 — SSOT)
  const colorMap = assignSectorColors(donutRows)

  // 3. 업종별 매수금액 집계 (도넛 rate 제거로 donutRows에서 제거됨 — SectorPnlGroup.rate용 별도 집계)
  const sectorBuyTotalMap = new Map<string, number>()
  for (const r of sells) {
    const sector = String(r.sector ?? '미분류')
    sectorBuyTotalMap.set(sector, (sectorBuyTotalMap.get(sector) ?? 0) + Number(r.buy_total_amt ?? 0))
  }

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

  // 5. pnl_rate 계산 (합산된 기준) — 공통 함수 사용 (P23 일관성)
  for (const v of stockMap.values()) {
    v.pnl_rate = computeWeightedRate(v.realized_pnl, v.buy_total)
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
    const sectorRate = computeWeightedRate(pnl, sectorBuyTotalMap.get(sector) ?? 0)
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

/** 거래내역 날짜 + 종목 필터 (profit-overview/profit-detail 공통 — P23 SSOT) */
export function filterTradeRows(
  rows: Record<string, unknown>[],
  dateFrom: string,
  dateTo: string,
  stockQuery?: string,
): Record<string, unknown>[] {
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
  return { pnl, buyTotal, rate: computeWeightedRate(pnl, buyTotal) }
}

export interface CumulativePnlParams {
  sellHistory: Record<string, unknown>[]
  account: AccountSnapshot | null
  isTestMode: boolean
  dateFrom?: string
  dateTo?: string
  baseAsset?: number  // 기간 시작 시점 기초자산 (전일 장마감 총자산 + 당일 순입출금)
  earliestBaseAsset?: number  // 가장 오래된 total_asset 스냅샷 (누적 카드 실전 분모 — buyTotal 폐지, 다단계 1세션 결정 5)
}

/** 누적/기간 실현 손익 + 수익률 단일 계산 소스 (P10 SSOT).
 *  분모 규칙 (기초자산 분모 방식 + earliestBaseAsset — buyTotal 폐지, 다단계 1세션 결정 5):
 *    - 누적 카드 (dateFrom/dateTo 없음):
 *      · 테스트모드: accumulated_investment (initial_deposit 폴백)
 *      · 실전모드:   earliestBaseAsset (가장 오래된 total_asset 스냅샷 — buyTotal 폐지)
 *    - 기간 한정 카드 (dateFrom/dateTo 있음): 기초자산 (전일 장마감 총자산 + 당일 순입출금)
 *      · baseAsset 전달 시: baseAsset 분모 (사용자 결정 1·2)
 *      · baseAsset 미전달 시: earliestBaseAsset (둘 다 없으면 rate null → '-' 표시, P20 폴백 금지)
 *  rate null 반환: 분모 0/undefined 시 (P20 — buyTotal/0으로 덮지 않음).
 *  dateFrom/dateTo 적용 시 해당 범위 내 손익만 집계.
 *  renderAccountVals(계좌 현황)·canvas-sector-donut(도넛 중앙)·updateSummaryCards(요약 카드)·
 *  updateStatistics(하단 통계)가 동일 분모·동일 데이터 범위를 사용하도록 추출 (P22 데이터 정합성). */
export function computeCumulativePnl(params: CumulativePnlParams): { pnl: number; rate: number | null } {
  const { sellHistory, account, isTestMode, dateFrom, dateTo, baseAsset, earliestBaseAsset } = params
  const { pnl } = aggregatePnl(sellHistory, dateFrom, dateTo)
  const isCumulative = !dateFrom && !dateTo
  let denominator: number | null
  if (isCumulative) {
    // 누적 카드: 테스트=accumulated_investment, 실전=earliestBaseAsset (buyTotal 폐지)
    denominator = isTestMode
      ? (account?.accumulated_investment ?? account?.initial_deposit ?? null)
      : (earliestBaseAsset ?? null)
  } else {
    // 기간 한정 카드: baseAsset ?? earliestBaseAsset (둘 다 없으면 null → rate null, P20)
    denominator = baseAsset ?? earliestBaseAsset ?? null
  }
  return { pnl, rate: denominator ? computeWeightedRate(pnl, denominator) : null }
}

/** dailySummary에서 특정 날짜의 기초자산(전일 장마감 스냅샷) 추출.
 *  date 이전 날짜 중 가장 최근 행의 base_asset 필드 반환.
 *  없으면 undefined (computeCumulativePnl에서 초기 투자원금으로 처리 — 결정 6). */
export function findBaseAssetForDate(
  dailySummary: Record<string, unknown>[],
  date: string,
): number | undefined {
  let prevBaseAsset: number | undefined
  let prevDate = ''
  for (const r of dailySummary) {
    const d = String(r.date ?? '')
    const baseAsset = Number(r.base_asset ?? 0)
    if (d < date && d > prevDate && baseAsset > 0) {
      prevDate = d
      prevBaseAsset = baseAsset
    }
  }
  return prevBaseAsset
}

/** 백엔드 dailySummary에서 당월 거래일별 요약 집계 — P10 SSOT (per-day rate 재계산 금지, 백엔드 값 직접 사용).
 *  buildChartFromDailySummary와 동일한 dailySummary 직접 사용 패턴 (P23 일관성). */
export function buildMonthlyDrilldown(
  dailySummary: Record<string, unknown>[],
  yearMonth: string,
): DailyDrilldownRow[] {
  const prefix = yearMonth + '-'
  const rows = dailySummary
    .filter(r => String(r.date ?? '').startsWith(prefix))
    .map(r => ({
      date: String(r.date ?? ''),
      sellCount: Number(r.sell_count ?? 0),
      buyCount: Number(r.buy_count ?? 0),
      pnl: Number(r.realized_pnl ?? 0),
      rate: Number(r.pnl_rate ?? 0),
    }))
  rows.sort((a, b) => b.date.localeCompare(a.date))
  return rows
}

/** 당일 드릴다운 빌더 — 실현(오늘 매도) + 평가(현재 보유) 영역 구분 (F-3-d, 결정 3·11).
 *  realizedRows: 오늘 매도 종목별 realized_pnl 리스트 (sellHistory에서 오늘 날짜 필터).
 *  evalRows: 현재 보유 종목별 평가손익 (computePositionValuation 재사용 — P23 일관성).
 *  P22 정합성: realizedTotal + evalTotal = 당일 카드 총액 (updateSummaryCards 당일 계산식과 동일 소스). */
export function buildTodayDrilldown(
  sellHistory: Record<string, unknown>[],
  positions: Position[],
  sectorStocks: Record<string, SectorStock>,
  today: string,
): TodayDrilldownResult {
  const realizedRows: TodayDrilldownRealizedRow[] = []
  let realizedTotal = 0
  for (const r of sellHistory) {
    if (String(r.date ?? '') !== today) continue
    const pnl = Number(r.realized_pnl ?? 0)
    realizedRows.push({
      stk_cd: String(r.stk_cd ?? ''),
      stk_nm: String(r.stk_nm ?? ''),
      realized_pnl: pnl,
    })
    realizedTotal += pnl
  }
  realizedRows.sort((a, b) => Math.abs(b.realized_pnl) - Math.abs(a.realized_pnl))

  const evalRows: TodayDrilldownEvalRow[] = []
  let evalTotal = 0
  for (const p of positions) {
    const v = computePositionValuation(p, sectorStocks)
    if (v.isNull) continue  // cur_price null인 종목은 제외 (P21 — 호출처에서 '-' 표시와 별개)
    evalRows.push({
      stk_cd: p.stk_cd,
      stk_nm: p.stk_nm,
      pnl: v.pnl,
      rate: v.rate,
      evalAmt: v.evalAmt,
    })
    evalTotal += v.pnl
  }
  evalRows.sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))

  return { realizedRows, evalRows, realizedTotal, evalTotal }
}

/** 5거래일 드릴다운 빌더 — 최근 5거래일 일별 실현손익 (F-3-d).
 *  getRecent5TradingDays(공통 소스) + dailySummary 일별 realized_pnl (백엔드 값 직접 사용 — P10 SSOT). */
export function buildFivedayDrilldown(dailySummary: Record<string, unknown>[]): DailyDrilldownRow[] {
  const recent5 = getRecent5TradingDays(dailySummary)
  const recentSet = new Set(recent5)
  const rows = dailySummary
    .filter(r => recentSet.has(String(r.date ?? '')))
    .map(r => ({
      date: String(r.date ?? ''),
      sellCount: Number(r.sell_count ?? 0),
      buyCount: Number(r.buy_count ?? 0),
      pnl: Number(r.realized_pnl ?? 0),
      rate: Number(r.pnl_rate ?? 0),
    }))
  rows.sort((a, b) => b.date.localeCompare(a.date))
  return rows
}

/** 누적 드릴다운 빌더 — 월별 누적 손익 + 입금 이력 (F-3-d, 결정 4).
 *  monthlyRows: sellHistory 전체를 월별 그룹화한 realized_pnl 합 (내림차순).
 *  depositHistory: 백엔드 /api/trade-history/deposit-history 결과 (date, daily_deposit 리스트). */
export function buildCumulativeDrilldown(
  sellHistory: Record<string, unknown>[],
  depositHistory: DepositHistoryRow[],
): CumulativeDrilldownResult {
  const monthMap = new Map<string, number>()
  for (const r of sellHistory) {
    const d = String(r.date ?? '')
    if (d.length < 7) continue
    const ym = d.slice(0, 7)
    monthMap.set(ym, (monthMap.get(ym) ?? 0) + Number(r.realized_pnl ?? 0))
  }
  const monthlyRows = Array.from(monthMap.entries())
    .map(([yearMonth, pnl]) => ({ yearMonth, pnl }))
    .sort((a, b) => b.yearMonth.localeCompare(a.yearMonth))
  return { monthlyRows, depositHistory }
}

/** 거래일별 요약 → 차트 데이터 변환. 매도 없는 날(sell_count=0)은 pnl=null로 표시 → 막대 안 그림 */
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

/* ── 보유 종목 평가 계산 (순수 함수 — P10 SSOT, P22 데이터 정합성, P23 일관성) ── */

/**
 * 개별 보유종목 1건의 평가 계산 — 단일 진실 소스(SSOT).
 * sell-position.ts 개별 행(cur_price/pnl/rate 컬럼)과 computeHoldingsSummary(요약행)가
 * 동일한 공식·null 패턴을 공유하도록 추출 (P10/P23 — 공식 중복 제거).
 *
 * - 현재가: sectorStocks[code].cur_price (실시간 틱, 없으면 null)
 * - 매입가: p.avg_price
 * - curPrice null → isNull=true, 나머지 필드 0 (P21 투명성 — 호출처에서 '-' 표시)
 *   isNull은 오직 curPrice null(시세 미수신)만 의미. qty<=0은 isNull=false이며
 *   evalAmt/buyAmt=0으로 합산에 0 기여 (요약 hasNullPrice 영향 X — 기존 동작 보존).
 * - diff = curPrice - buyPrice
 * - pnl = diff × qty
 * - rate = buyPrice > 0 ? diff / buyPrice × 100 : 0 (단일 종목 수익률)
 * - evalAmt = curPrice × qty (평가금액)
 * - buyAmt = buyPrice × qty (매입금액)
 */
export interface PositionValuation {
  curPrice: number
  buyPrice: number
  qty: number
  diff: number
  pnl: number
  rate: number
  evalAmt: number
  buyAmt: number
  isNull: boolean
}

export function computePositionValuation(
  p: Position,
  sectorStocks: Record<string, SectorStock>,
): PositionValuation {
  const qty = p.qty ?? 0
  const buyPrice = p.avg_price
  const code = normalizeStockCode(p.stk_cd)
  const curPriceRaw = sectorStocks[code]?.cur_price ?? null
  if (curPriceRaw == null) {
    return { curPrice: 0, buyPrice, qty, diff: 0, pnl: 0, rate: 0, evalAmt: 0, buyAmt: 0, isNull: true }
  }
  const curPrice = Number(curPriceRaw)
  const diff = curPrice - buyPrice
  const pnl = diff * qty
  const rate = buyPrice > 0 ? (diff / buyPrice) * 100 : 0
  const evalAmt = curPrice * qty
  const buyAmt = buyPrice * qty
  return { curPrice, buyPrice, qty, diff, pnl, rate, evalAmt, buyAmt, isNull: false }
}

/**
 * 보유 종목 positions 전체 요약 — computePositionValuation 결과를 합산 (P10 SSOT 재사용).
 * 개별 종목 행과 동일한 데이터 소스·공식 사용.
 *
 * - 평가금액 = sum(evalAmt) — cur_price null인 종목은 계산에서 제외 (P21 투명성)
 * - 매입금액 = sum(buyAmt)
 * - 평가손익 = sum(pnl) (= 평가금액 - 매입금액, 수학적 동일)
 * - 수익률 = 평가손익 / 매입금액 × 100 (가중 평균, 매입금액 0이면 0)
 * - hasNullPrice: cur_price null인 보유종목이 하나라도 있으면 true → 호출처에서 '-' 표시 (P21, P23 — 개별 행과 동일 null 패턴)
 */
export function computeHoldingsSummary(
  positions: Position[],
  sectorStocks: Record<string, SectorStock>,
): { evalTotal: number; evalPnl: number; evalRate: number; buyTotal: number; hasNullPrice: boolean } {
  let evalTotal = 0
  let buyTotal = 0
  let hasNullPrice = false
  for (const p of positions) {
    const v = computePositionValuation(p, sectorStocks)
    if (v.isNull) {
      hasNullPrice = true
      continue
    }
    evalTotal += v.evalAmt
    buyTotal += v.buyAmt
  }
  const evalPnl = evalTotal - buyTotal
  const evalRate = computeWeightedRate(evalPnl, buyTotal)
  return { evalTotal, evalPnl, evalRate, buyTotal, hasNullPrice }
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
  earliestBaseAsset?: number  // 가장 오래된 total_asset 스냅샷 (누적 실전 분모 — buyTotal 폐지)
}

/** 당일 매수/매도금액 + 당일/누적 수수료·세금 집계 (buyHistory + sellHistory 기반). */
function computeTodayAggregates(
  buyHistory: Record<string, unknown>[],
  sellHistory: Record<string, unknown>[],
  today: string,
): { todayBuyAmt: number; todaySellAmt: number; todayFeeTax: number; cumFeeTax: number } {
  const todayBuyAmt = buyHistory
    .filter(r => String(r.date ?? '') === today)
    .reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const todaySellAmt = sellHistory
    .filter(r => String(r.date ?? '') === today)
    .reduce((s, r) => s + Number(r.total_amt ?? 0), 0)
  const todayFeeTax =
    buyHistory.filter(r => String(r.date ?? '') === today).reduce((s, r) => s + Number(r.fee ?? 0), 0) +
    sellHistory.filter(r => String(r.date ?? '') === today).reduce((s, r) => s + Number(r.fee ?? 0) + Number(r.tax ?? 0), 0)
  const cumFeeTax =
    buyHistory.reduce((s, r) => s + Number(r.fee ?? 0), 0) +
    sellHistory.reduce((s, r) => s + Number(r.fee ?? 0) + Number(r.tax ?? 0), 0)
  return { todayBuyAmt, todaySellAmt, todayFeeTax, cumFeeTax }
}

/** 계좌 현황 11행 렌더링 (test/real 공통 — P24 중복 제거).
 *  refs: 11개 span 참조, values: 11개 행 텍스트(원 단위·% 포함), colors: 색상 적용 인덱스↔색상 맵. */
function renderAccountRowSet(
  refs: HTMLSpanElement[],
  values: string[],
  colorMap: Map<number, string>,
): void {
  if (refs.length < 11) return
  for (let i = 0; i < 11; i++) {
    refs[i].textContent = values[i]
    const color = colorMap.get(i)
    if (color) refs[i].style.color = color
  }
}

export function renderAccountVals(params: AccountValsParams): void {
  const { account: a, positionCount, isTestMode, buyHistory, sellHistory } = params

  const today = getTradingToday()
  const { todayBuyAmt, todaySellAmt, todayFeeTax, cumFeeTax } = computeTodayAggregates(buyHistory, sellHistory, today)

  // 보유 종목 평가금액/평가손익/수익률: positions + sectorStocks에서 직접 계산 (개별 종목 행과 동일 소스·공식)
  const { evalTotal, evalPnl, evalRate, hasNullPrice } = computeHoldingsSummary(params.positions, params.sectorStocks)

  // 누적 실현 손익 + 수익률: SSOT 함수 사용 (도넛 차트 중앙과 동일 소스 — P10/P22)
  // 분모: 테스트모드=누적투자금(투자원금 대비 — 사용자 상식 기준, P21),
  //       실전모드=earliestBaseAsset (가장 오래된 total_asset 스냅샷 — buyTotal 폐지, 다단계 1세션 결정 5)
  const { pnl: cumPnlAmt, rate: cumRate } = computeCumulativePnl({
    sellHistory, account: a, isTestMode, earliestBaseAsset: params.earliestBaseAsset,
  })
  const cumPnl = { pnl: cumPnlAmt, rate: cumRate }

  // CSS display 토글로 모드별 컨테이너 전환
  if (params.realAccountContainer && params.testAccountContainer) {
    params.realAccountContainer.style.display = isTestMode ? 'none' : ''
    params.testAccountContainer.style.display = isTestMode ? '' : 'none'
  }

  // 11행 공통 값 조립 (행 0만 모드별 상이: 테스트=누적투자금, 실전=예수금)
  const row0 = isTestMode ? (a?.initial_deposit ?? 0) : (a?.deposit ?? 0)
  const orderable = a?.orderable ?? 0
  // P21/P23: cur_price null인 보유종목 있으면 평가금액/평가손익/수익률 3행 '-' 표시 (개별 행과 동일 null 패턴)
  const evalText = hasNullPrice ? '-' : `${evalTotal.toLocaleString()}원`
  const evalPnlText = hasNullPrice ? '-' : `${evalPnl > 0 ? '+' : ''}${evalPnl.toLocaleString()}원`
  const evalRateText = hasNullPrice ? '-' : `${evalRate > 0 ? '+' : ''}${evalRate.toFixed(2)}%`
  const evalColor = hasNullPrice ? '' : pnlColor(evalPnl)
  const cumSign = cumPnl.pnl > 0 ? '+' : ''
  const cumColor = pnlColor(cumPnl.pnl)

  const values = [
    `${row0.toLocaleString()}원`,
    `${orderable.toLocaleString()}원`,
    `${todayBuyAmt.toLocaleString()}원`,
    `${todaySellAmt.toLocaleString()}원`,
    evalText,
    evalPnlText,
    evalRateText,
    `${todayFeeTax.toLocaleString()}원`,
    `${cumFeeTax.toLocaleString()}원`,
    `${cumSign}${cumPnl.pnl.toLocaleString()}원`,
    cumRate == null ? '-' : `${cumSign}${cumRate.toFixed(2)}%`,
  ]
  const colorMap = new Map<number, string>([[5, evalColor], [6, evalColor], [9, cumColor], [10, cumColor]])

  if (isTestMode) {
    if (params.holdingCountSpanTest) params.holdingCountSpanTest.textContent = String(positionCount)
    renderAccountRowSet(params.testAccountValRefs, values, colorMap)
  } else {
    if (params.holdingCountSpan) params.holdingCountSpan.textContent = String(positionCount)
    renderAccountRowSet(params.accountValRefs, values, colorMap)
  }
}
