// frontend/src/pages/profit-shared.ts
// 수익현황 페이지 공통 모듈 — profit-overview.ts와 profit-detail.ts가 공유하는 로직
//
// 파일 분할 (F-05, P24 단순성):
// - profit-math.ts: 순수 계산 함수 (DOM 의존 없음 — 집계·변환·평가 계산)
// - profit-shared.ts (본 파일): DOM 렌더 함수 (요약 카드·계좌 현황) + profit-math re-export
//
// 본 파일은 DOM 조작이 포함된 함수만 직접 구현.
// 순수 계산 함수는 profit-math.ts에서 re-export (기존 import 경로 호환 — P23 일관성).

// ── profit-math.ts re-export (기존 import 경로 호환 — P23 일관성) ──
export {
  // 타입
  type SectorStockPnl,
  type SectorPnlGroup,
  type PnlSummary,
  type DailyDrilldownRow,
  type TodayDrilldownRealizedRow,
  type TodayDrilldownEvalRow,
  type TodayDrilldownResult,
  type CumulativeMonthlyRow,
  type DepositHistoryRow,
  type CumulativeDrilldownResult,
  type CumulativePnlParams,
  type PositionValuation,
  // 함수
  getRecent5TradingDays,
  extractEarliestBaseAsset,
  buildSectorDonutRows,
  buildSectorStockPnl,
  filterTradeRows,
  aggregatePnl,
  computeCumulativePnl,
  findBaseAssetForDate,
  buildMonthlyDrilldown,
  buildTodayDrilldown,
  buildFivedayDrilldown,
  buildCumulativeDrilldown,
  buildChartFromDailySummary,
  computePositionValuation,
  computeHoldingsSummary,
  computeTodayAggregates,
} from './profit-math'

// profit-math.ts에서 계산 함수 import (DOM 렌더용 — 내부 사용)
import {
  computeCumulativePnl,
  computeHoldingsSummary,
  computeTodayAggregates,
  findBaseAssetForDate,
  getRecent5TradingDays,
} from './profit-math'

import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR, RADIUS, SHADOW, computeWeightedRate } from '../components/common/ui-styles'
import { getTradingToday, isPreOpenPhase } from '../utils/date'
import type { AccountSnapshot, Position, SectorStock } from '../types'

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

/** 당일/5거래일/당월/누적 손익 계산 및 요약 카드 DOM 갱신 (전일 카드 제거 — 다단계 1세션 결정 1).
 *  모든 카드를 computeCumulativePnl SSOT로 계산 (P10 SSOT — 분모 규칙 단일 소스).
 *  분모 규칙 (기초자산 분모 방식 + earliestBaseAsset):
 *    - 기간 한정 카드(당일/5거래일/당월): baseAsset = findBaseAssetForDate(dailySummary, 기간시작일)
 *      · baseAsset 없으면 earliestBaseAsset (둘 다 없으면 rate null → '-' 표시, P20 폴백 금지)
 *      · 당일 카드: 전일 baseAsset + account.daily_deposit (당일 순입출금 보정, 결정 2)
 *    - 누적 카드: 테스트=accumulated_investment, 실전=earliestBaseAsset (buyTotal 폐지 — 다단계 1세션 결정 5)
 *  당일 카드 (F-3-c): PRE OPEN(개장 전) → 0원 + "개장 전" 서브 텍스트.
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
  openSubText?: string,  // 개장 중 서브 텍스트 (P21 투명성 — profit-detail: '최근 체결 기준', profit-overview: 생략='')
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
    els.todaySubTextEl.textContent = openSubText ?? ''
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
