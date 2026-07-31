// frontend/src/pages/profit-math.ts
// 수익 페이지 순수 계산 모듈 — DOM 의존 없는 수학·집계·변환 함수 (F-05 분할, P24 단순성)
// profit-shared.ts에서 분리. 동작 변경 없음.
//
// 본 모듈은 순수 함수만 포함 (P10 SSOT — 계산 공식 단일 소스).
// DOM 조작(createSummaryCards/updateSummaryCards/renderAccountVals)은 profit-shared.ts에 잔류.
//
// 의존성:
// - computeWeightedRate (ui-styles) — 순수 수학 헬퍼
// - getTradingToday (date) — 순수 날짜 유틸
// - Position (types) — 타입만
// - SectorDonutRow, assignSectorColors (canvas-sector-donut) — 순수 함수/타입

import { computeWeightedRate, COLOR } from '../components/common/ui-styles'
import type { Position } from '../types'
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

/* ── 순수 함수 ── */

/** dailySummary에서 최근 5거래일 날짜를 내림차순 추출.
 *  5거래일 카드 집계의 공통 소스 — P10 SSOT. */
export function getRecent5TradingDays(dailySummary: Record<string, unknown>[]): string[] {
  const dates = dailySummary
    .map(r => String(r.date ?? ''))
    .filter(d => d)
    .sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))
  return dates.slice(0, 5)
}

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
  isTestMode: boolean
  dateFrom?: string
  dateTo?: string
}

/** 누적/기간 실현 손익 + 수익률 단일 계산 소스 (P10 SSOT).
 *  분모 규칙 (매수원금 기반 — 설계서 0절 최상위 원칙):
 *    - 실현 수익률 = 해당 기간 매도 완료된 종목들의 실현손익 합 ÷ 총 매수원금 합 × 100
 *    - aggregatePnl이 이 계산을 수행 (pnl / buyTotal * 100) — 본 함수는 aggregatePnl 결과를 그대로 사용.
 *    - 실전모드: 증권사 서버가 SSOT (AGENTS.md 실전vs테스트 테이블) — rate null → '-' 표시.
 *  rate null 반환: 실전모드 시 (P20 — 분모 0 시 computeWeightedRate가 0 반환하므로 null 아님).
 *  dateFrom/dateTo 적용 시 해당 범위 내 손익만 집계.
 *  renderAccountVals(계좌 현황)·canvas-sector-donut(도넛 중앙)·updateSummaryCards(요약 카드)·
 *  updateStatistics(하단 통계)가 동일 분모·동일 데이터 범위를 사용하도록 추출 (P22 데이터 정합성). */
export function computeCumulativePnl(params: CumulativePnlParams): { pnl: number; rate: number | null } {
  const { sellHistory, isTestMode, dateFrom, dateTo } = params
  const { pnl, rate } = aggregatePnl(sellHistory, dateFrom, dateTo)
  // 실전모드: 증권사 서버가 SSOT — 앱에서 수익률 재계산 금지 (AGENTS.md 실전vs테스트 테이블)
  if (!isTestMode) {
    return { pnl, rate: null }
  }
  return { pnl, rate }
}

/** 거래일별 요약 → 차트 데이터 변환. 비거래일(sell_count=0 && buy_count=0)은 배열에서 제외. 매도 없는 날(sell_count=0, buy_count>0)은 pnl=null로 표시 → 막대 안 그림 */
export function buildChartFromDailySummary(summary: Record<string, unknown>[]): { date: string; pnl: number | null; rate: number; buyFee: number; sellFee: number; tax: number }[] {
  const rows = summary
    .filter(r => Number(r.sell_count ?? 0) > 0 || Number(r.buy_count ?? 0) > 0)
    .map(r => {
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
 * - 현재가: p.cur_price (보유종목 자체의 실시간 갱신 값, 필터 무관 — P10 SSOT 정정)
 *   틱 핸들러(applyRealData)가 sectorStocks와 동일한 실시간 가격으로 갱신하며,
 *   보유종목은 필터와 무관하게 항상 갱신되므로 주 소스로 삼는다.
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
): PositionValuation {
  const qty = p.qty ?? 0
  const buyPrice = p.avg_price
  const curPriceRaw = p.cur_price
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
): { evalTotal: number; evalPnl: number; evalRate: number; buyTotal: number; hasNullPrice: boolean } {
  let evalTotal = 0
  let buyTotal = 0
  let hasNullPrice = false
  for (const p of positions) {
    const v = computePositionValuation(p)
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

/* ── 당일 매수/매도금액 + 당일/누적 수수료·세금 집계 (buyHistory + sellHistory 기반) ── */
export function computeTodayAggregates(
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
