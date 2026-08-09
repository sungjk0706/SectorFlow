// frontend/src/pages/profit-shared.ts
// 수익현황 페이지 공통 모듈 — profit-overview.ts와 profit-detail.ts가 공유하는 로직
//
// 파일 분할 (F-05, P24 단순성):
// - profit-math.ts: 순수 계산 함수 (DOM 의존 없음 — 집계·변환·평가 계산)
// - profit-shared.ts (본 파일): DOM 렌더 함수 (요약 카드·계좌 현황)
//
// 본 파일은 DOM 조작이 포함된 함수만 직접 구현.

// profit-math.ts에서 계산 함수 import (DOM 렌더용 — 내부 사용)
import {
  computeCumulativePnl,
  computeTodayAggregates,
  getRecent5TradingDays,
} from './profit-math'

import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR, RADIUS, SHADOW } from '../components/common/ui-styles'
import { getTradingToday } from '../utils/date'
import type { AccountSnapshot } from '../types'

/* ── 요약 카드 공통 함수 ── */

export interface SummaryCardEls {
  todayPnlEl: HTMLSpanElement
  todayRateEl: HTMLSpanElement
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

interface SummaryCardCallbacks {
  onTodayClick?: () => void
  onFivedayClick?: () => void
  onMonthClick?: () => void
  onTotalClick?: () => void
}

const SUMMARY_CARD_STYLE = `flex:1;background:${COLOR.surfaceLight};border:1px solid ${COLOR.borderLight};border-radius:${RADIUS.sm};box-shadow:${SHADOW.card};padding:6px 12px;display:flex;flex-direction:column;justify-content:center;cursor:pointer;`
const SUMMARY_CARD_TITLES = ['당일 손익', '5거래일 손익', '당월 손익', '누적 손익']

/** 요약 카드 1개 DOM 생성. 실패 시 null 반환 (P25 격리 + P22 인덱스 정합성 — 호출부에서 더미 push).
 *  4카드 동일 구조 (P23 일관성) — 당일 카드 특수 분기 제거 (개장 전 폴백 제거, P10 SSOT 단일 해석). */
function buildSummaryCard(
  container: HTMLElement,
  title: string,
  handler: (() => void) | undefined,
): { pnlEl: HTMLSpanElement; rateEl: HTMLSpanElement; cardEl: HTMLDivElement } | null {
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

    container.appendChild(card)
    return { pnlEl, rateEl, cardEl: card }
  } catch (e) {
    console.error('[profit-shared] summary card build error', e)
    return null
  }
}

/** 요약 카드 4개(당일/5거래일/당월/누적 손익) DOM 생성, 클릭 콜백 주입, 요소 참조 반환.
 *  전일 카드 제거 (다단계 1세션 결정 1). 4카드 동일 구조 (P23 일관성).
 *  카드 클릭 시 테이블 필터링 + 선택 강조 표시 (팝업 없음 — P24 단순성). */
export function createSummaryCards(container: HTMLElement, callbacks: SummaryCardCallbacks = {}): SummaryCardEls {
  const clickHandlers = [callbacks.onTodayClick, callbacks.onFivedayClick, callbacks.onMonthClick, callbacks.onTotalClick]

  const pnlEls: HTMLSpanElement[] = []
  const rateEls: HTMLSpanElement[] = []
  const cardEls: HTMLDivElement[] = []

  for (let i = 0; i < 4; i++) {
    // P25: 카드 단위 격리 — 한 카드 생성 throw 시 다음 카드 계속 렌더링.
    // 실패 시 더미 push로 인덱스 정합성 유지 (P22). buildStatRow 패턴과 일치 (P23).
    const built = buildSummaryCard(container, SUMMARY_CARD_TITLES[i], clickHandlers[i])
    if (built) {
      pnlEls.push(built.pnlEl)
      rateEls.push(built.rateEl)
      cardEls.push(built.cardEl)
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
    fivedayPnlEl: pnlEls[1], fivedayRateEl: rateEls[1],
    monthPnlEl: pnlEls[2], monthRateEl: rateEls[2],
    totalPnlEl: pnlEls[3], totalRateEl: rateEls[3],
    todayCard: cardEls[0], fivedayCard: cardEls[1], monthCard: cardEls[2], totalCard: cardEls[3],
  }
}

/** 당일/5거래일/당월/누적 손익 계산 및 요약 카드 DOM 갱신 (전일 카드 제거 — 다단계 1세션 결정 1).
 *  모든 카드를 computeCumulativePnl SSOT로 계산 (P10 SSOT — 분모 규칙 단일 소스).
 *  분모 규칙 (매수원금 기반 — 설계서 0절 최상위 원칙):
 *    - 실현 수익률 = 해당 기간 매도 완료된 종목들의 실현손익 합 ÷ 총 매수원금 합 × 100
 *    - 4카드(당일/5거래일/당월/누적) 동일 공식 (설계 원칙 5) — computeCumulativePnl이 aggregatePnl 기반으로 계산.
 *    - 실전매매: 증권사 서버가 SSOT — rate null → '-' 표시 (AGENTS.md 실전vs가상 테이블).
 *  당일 카드: getTradingToday() SSOT 기준 당일 실현손익 (개장 전 폴백 제거 — P10 단일 해석, P20 폴백 금지).
 *  dailySummary는 5거래일 날짜 추출에만 사용 (날짜 결정 SSOT). */
export function updateSummaryCards(
  dailySummary: Record<string, unknown>[],
  els: SummaryCardEls,
  sellHistory: Record<string, unknown>[],
  isTestMode: boolean,
): void {
  const today = getTradingToday()
  const yearMonth = today.slice(0, 7)
  const monthStart = yearMonth + '-01'
  const monthEnd = yearMonth + '-31'

  // 5거래일 날짜 범위 (내림차순 → [0]=최근, [4]=5번째)
  const recent5 = getRecent5TradingDays(dailySummary)
  const fivedayFrom = recent5.length > 0 ? recent5[recent5.length - 1] : ''
  const fivedayTo = recent5.length > 0 ? recent5[0] : ''

  // 4카드 동일 경로: computeCumulativePnl SSOT (P10 — 분모 규칙 단일 소스, P23 — 4카드 일관성)
  const dayS = computeCumulativePnl({ sellHistory, isTestMode, dateFrom: today, dateTo: today })
  const fiveS = (fivedayFrom && fivedayTo)
    ? computeCumulativePnl({ sellHistory, isTestMode, dateFrom: fivedayFrom, dateTo: fivedayTo })
    : { pnl: 0, rate: 0 as number | null }
  const monS = computeCumulativePnl({ sellHistory, isTestMode, dateFrom: monthStart, dateTo: monthEnd })
  const allS = computeCumulativePnl({ sellHistory, isTestMode })  // 누적: 전체 매도 범위

  els.todayPnlEl.textContent = fmtWon(dayS.pnl)
  els.todayPnlEl.style.color = pnlColor(dayS.pnl)
  els.todayRateEl.textContent = dayS.rate == null ? '-' : `${dayS.rate.toFixed(2)}%`
  els.todayRateEl.style.color = pnlColor(dayS.pnl)
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
  positionCount: number
  isTestMode: boolean
  buyHistory: Record<string, unknown>[]
  sellHistory: Record<string, unknown>[]
  liveAccountContainer: HTMLDivElement | null
  virtualAccountContainer: HTMLDivElement | null
  accountValRefs: HTMLSpanElement[]
  testAccountValRefs: HTMLSpanElement[]
  holdingCountSpan: HTMLSpanElement | null
  holdingCountSpanTest: HTMLSpanElement | null
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

  // 보유 종목 평가금액/평가손익/수익률: 백엔드 account-update snapshot 값을 그대로 표시 (P10 SSOT).
  //   가상매매: 백엔드가 종목 현재가 캐시 기반으로 계산한 값.
  //   실전매매: 증권사 서버에서 받은 값을 백엔드가 그대로 전달한 값.
  // 화면 단 자체 합산 계산 제거 — 미수신 종목은 백엔드 계산 단계에서 합산 제외됨 (P20 폴백 금지).
  const evalTotal = a?.total_eval_amount ?? 0
  const evalPnl = a?.total_pnl ?? 0
  const evalRate = a?.total_pnl_rate ?? 0

  // 누적 실현 손익 + 수익률: SSOT 함수 사용 (도넛 차트 중앙과 동일 소스 — P10/P22)
  // 분모: 매수원금 기반 (aggregatePnl — 설계서 0절 최상위 원칙).
  //       실전매매: 증권사 서버가 SSOT — rate null (AGENTS.md 실전vs가상 테이블).
  const { pnl: cumPnlAmt, rate: cumRate } = computeCumulativePnl({
    sellHistory, isTestMode,
  })
  const cumPnl = { pnl: cumPnlAmt, rate: cumRate }

  // CSS display 토글로 모드별 컨테이너 전환
  if (params.liveAccountContainer && params.virtualAccountContainer) {
    params.liveAccountContainer.style.display = isTestMode ? 'none' : ''
    params.virtualAccountContainer.style.display = isTestMode ? '' : 'none'
  }

  // 11행 공통 값 조립 (행 0만 모드별 상이: 가상매매=누적투자금, 실전=예수금)
  const row0 = isTestMode ? (a?.initial_deposit ?? 0) : (a?.deposit ?? 0)
  const orderable = a?.orderable ?? 0
  const evalText = `${evalTotal.toLocaleString()}원`
  const evalPnlText = `${evalPnl > 0 ? '+' : ''}${evalPnl.toLocaleString()}원`
  const evalRateText = `${evalRate > 0 ? '+' : ''}${evalRate.toFixed(2)}%`
  const evalColor = pnlColor(evalPnl)
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
