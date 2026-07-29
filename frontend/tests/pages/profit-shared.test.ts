import { describe, it, expect } from 'vitest'
import { computeHoldingsSummary, computePositionValuation, computeCumulativePnl, findBaseAssetForDate } from '../../src/pages/profit-math'
import type { Position, SectorStock, AccountSnapshot } from '../../src/types'

/**
 * computePositionValuation — 개별 보유종목 평가 계산 SSOT 함수 회귀 테스트.
 * sell-position.ts 개별 행(cur_price/pnl/rate)과 computeHoldingsSummary(요약행)가
 * 공유하는 단일 공식 (P10 SSOT, P23 일관성).
 * P21/P23: cur_price null → isNull=true, 나머지 0 (개별 행 '-' 표시와 동일 패턴).
 *
 * computeHoldingsSummary — 보유 종목 요약 계산 회귀 테스트.
 * computePositionValuation 결과를 합산 (P10 SSOT 재사용).
 * P21/P23: cur_price null인 보유종목 있으면 계산에서 제외 + hasNullPrice=true 반환
 * (개별 종목 행 pnl/rate 컬럼의 null → '-' 표시 패턴과 동일).
 */

function makePosition(code: string, qty: number, avgPrice: number): Position {
  return {
    stk_cd: code, stk_nm: `종목${code}`, qty, avg_price: avgPrice,
    cur_price: 0, buy_amt: avgPrice * qty, pnl_rate: 0, buy_date: '20260720',
  }
}

function makeSectorStock(code: string, curPrice: number | null): SectorStock {
  return {
    code, name: `종목${code}`, cur_price: curPrice, change: 0, change_rate: 0,
    trade_amount: 0, strength: 0, sector: '업종1',
  }
}

describe('computeHoldingsSummary — 정상 경로 (cur_price 존재)', () => {
  it('단일 종목 평가금액/평가손익/수익률 계산', () => {
    const positions = [makePosition('005930', 10, 70000)]
    const sectorStocks = { '005930': makeSectorStock('005930', 80000) }
    const result = computeHoldingsSummary(positions, sectorStocks)
    expect(result.evalTotal).toBe(800000)  // 80000 * 10
    expect(result.buyTotal).toBe(700000)  // 70000 * 10
    expect(result.evalPnl).toBe(100000)
    expect(result.evalRate).toBeCloseTo(14.29, 1)
    expect(result.hasNullPrice).toBe(false)
  })

  it('다중 종목 합산 계산', () => {
    const positions = [
      makePosition('005930', 10, 70000),
      makePosition('000660', 5, 120000),
    ]
    const sectorStocks = {
      '005930': makeSectorStock('005930', 80000),
      '000660': makeSectorStock('000660', 130000),
    }
    const result = computeHoldingsSummary(positions, sectorStocks)
    expect(result.evalTotal).toBe(1450000)  // 800000 + 650000
    expect(result.buyTotal).toBe(1300000)  // 700000 + 600000
    expect(result.evalPnl).toBe(150000)
    expect(result.hasNullPrice).toBe(false)
  })

  it('qty 0인 종목은 계산에서 제외', () => {
    const positions = [
      makePosition('005930', 10, 70000),
      makePosition('000660', 0, 120000),
    ]
    const sectorStocks = {
      '005930': makeSectorStock('005930', 80000),
      '000660': makeSectorStock('000660', 130000),
    }
    const result = computeHoldingsSummary(positions, sectorStocks)
    expect(result.evalTotal).toBe(800000)
    expect(result.buyTotal).toBe(700000)
    expect(result.hasNullPrice).toBe(false)
  })

  it('빈 positions', () => {
    const result = computeHoldingsSummary([], {})
    expect(result.evalTotal).toBe(0)
    expect(result.buyTotal).toBe(0)
    expect(result.evalPnl).toBe(0)
    expect(result.evalRate).toBe(0)
    expect(result.hasNullPrice).toBe(false)
  })
})

describe('computeHoldingsSummary — null 경로 (P21/P23 투명성)', () => {
  it('모든 종목 cur_price null → hasNullPrice=true, evalTotal=0', () => {
    const positions = [makePosition('005930', 10, 70000)]
    const sectorStocks = { '005930': makeSectorStock('005930', null) }
    const result = computeHoldingsSummary(positions, sectorStocks)
    expect(result.evalTotal).toBe(0)
    expect(result.buyTotal).toBe(0)  // null 종목은 buyTotal에서도 제외
    expect(result.evalPnl).toBe(0)
    expect(result.hasNullPrice).toBe(true)
  })

  it('sectorStocks 비어있음 (새로고침 직후) → hasNullPrice=true', () => {
    const positions = [makePosition('005930', 10, 70000)]
    const result = computeHoldingsSummary(positions, {})
    expect(result.evalTotal).toBe(0)
    expect(result.buyTotal).toBe(0)
    expect(result.hasNullPrice).toBe(true)
  })

  it('일부 종목만 cur_price null → hasNullPrice=true, null 종목 제외하고 계산', () => {
    const positions = [
      makePosition('005930', 10, 70000),
      makePosition('000660', 5, 120000),
    ]
    const sectorStocks = {
      '005930': makeSectorStock('005930', 80000),
      '000660': makeSectorStock('000660', null),
    }
    const result = computeHoldingsSummary(positions, sectorStocks)
    // 005930만 계산에 포함
    expect(result.evalTotal).toBe(800000)
    expect(result.buyTotal).toBe(700000)
    expect(result.evalPnl).toBe(100000)
    expect(result.hasNullPrice).toBe(true)  // 000660이 null이므로
  })

  it('종목코드 정규화 — 앞자리 A 제거', () => {
    const positions = [makePosition('A005930', 10, 70000)]
    const sectorStocks = { '005930': makeSectorStock('005930', 80000) }
    const result = computeHoldingsSummary(positions, sectorStocks)
    expect(result.evalTotal).toBe(800000)
    expect(result.hasNullPrice).toBe(false)
  })
})

describe('computePositionValuation — 정상 경로 (cur_price 존재)', () => {
  it('단일 종목 diff/pnl/rate/evalAmt/buyAmt 계산', () => {
    const p = makePosition('005930', 10, 70000)
    const sectorStocks = { '005930': makeSectorStock('005930', 80000) }
    const v = computePositionValuation(p, sectorStocks)
    expect(v.isNull).toBe(false)
    expect(v.curPrice).toBe(80000)
    expect(v.buyPrice).toBe(70000)
    expect(v.qty).toBe(10)
    expect(v.diff).toBe(10000)          // 80000 - 70000
    expect(v.pnl).toBe(100000)          // 10000 * 10
    expect(v.rate).toBeCloseTo(14.29, 1) // 10000 / 70000 * 100
    expect(v.evalAmt).toBe(800000)      // 80000 * 10
    expect(v.buyAmt).toBe(700000)       // 70000 * 10
  })

  it('종목코드 정규화 — 앞자리 A 제거', () => {
    const p = makePosition('A005930', 10, 70000)
    const sectorStocks = { '005930': makeSectorStock('005930', 80000) }
    const v = computePositionValuation(p, sectorStocks)
    expect(v.isNull).toBe(false)
    expect(v.curPrice).toBe(80000)
  })

  it('buyPrice 0 → rate 0 (분모 0 가드)', () => {
    const p = makePosition('005930', 10, 0)
    const sectorStocks = { '005930': makeSectorStock('005930', 80000) }
    const v = computePositionValuation(p, sectorStocks)
    expect(v.isNull).toBe(false)
    expect(v.rate).toBe(0)
    expect(v.pnl).toBe(800000)  // (80000 - 0) * 10
  })
})

describe('computePositionValuation — null 경로 (P21/P23 투명성)', () => {
  it('cur_price null → isNull=true, 모든 계산 0', () => {
    const p = makePosition('005930', 10, 70000)
    const sectorStocks = { '005930': makeSectorStock('005930', null) }
    const v = computePositionValuation(p, sectorStocks)
    expect(v.isNull).toBe(true)
    expect(v.curPrice).toBe(0)
    expect(v.pnl).toBe(0)
    expect(v.rate).toBe(0)
    expect(v.evalAmt).toBe(0)
    expect(v.buyAmt).toBe(0)
  })

  it('sectorStocks 비어있음 (새로고침 직후) → isNull=true', () => {
    const p = makePosition('005930', 10, 70000)
    const v = computePositionValuation(p, {})
    expect(v.isNull).toBe(true)
  })

  it('qty 0 → isNull=false, evalAmt/buyAmt=0 (합산에 0 기여, hasNullPrice 영향 X)', () => {
    const p = makePosition('005930', 0, 70000)
    const sectorStocks = { '005930': makeSectorStock('005930', 80000) }
    const v = computePositionValuation(p, sectorStocks)
    expect(v.isNull).toBe(false)  // curPrice 존재하므로 null 아님
    expect(v.qty).toBe(0)
    expect(v.pnl).toBe(0)         // diff * 0
    expect(v.evalAmt).toBe(0)     // curPrice * 0
    expect(v.buyAmt).toBe(0)      // buyPrice * 0
  })
})

describe('computePositionValuation ↔ computeHoldingsSummary 일관성 (P10 SSOT)', () => {
  it('요약 evalPnl = sum(개별 pnl), evalTotal = sum(개별 evalAmt)', () => {
    const positions = [
      makePosition('005930', 10, 70000),
      makePosition('000660', 5, 120000),
    ]
    const sectorStocks = {
      '005930': makeSectorStock('005930', 80000),
      '000660': makeSectorStock('000660', 130000),
    }
    const perRow = positions.map(p => computePositionValuation(p, sectorStocks))
    const sumPnl = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.pnl), 0)
    const sumEvalAmt = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.evalAmt), 0)
    const sumBuyAmt = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.buyAmt), 0)

    const summary = computeHoldingsSummary(positions, sectorStocks)
    expect(summary.evalTotal).toBe(sumEvalAmt)
    expect(summary.buyTotal).toBe(sumBuyAmt)
    expect(summary.evalPnl).toBe(sumPnl)
    // evalPnl = evalTotal - buyTotal (수학적 동일)
    expect(summary.evalPnl).toBe(summary.evalTotal - summary.buyTotal)
  })

  it('일부 null → 요약 hasNullPrice=true, null 종목은 합산에서 제외', () => {
    const positions = [
      makePosition('005930', 10, 70000),
      makePosition('000660', 5, 120000),
    ]
    const sectorStocks = {
      '005930': makeSectorStock('005930', 80000),
      '000660': makeSectorStock('000660', null),
    }
    const perRow = positions.map(p => computePositionValuation(p, sectorStocks))
    const nullCount = perRow.filter(v => v.isNull).length
    const sumPnl = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.pnl), 0)

    const summary = computeHoldingsSummary(positions, sectorStocks)
    expect(nullCount).toBe(1)
    expect(summary.hasNullPrice).toBe(true)
    expect(summary.evalPnl).toBe(sumPnl)  // null 종목 제외 합과 일치
  })
})

/**
 * computeCumulativePnl — 누적 실현 손익 + 수익률 SSOT 함수 회귀 테스트.
 * renderAccountVals(계좌 현황)와 canvas-sector-donut(도넛 차트 중앙)가
 * 동일 분모·동일 데이터 범위를 사용하도록 추출 (P10 SSOT, P22 데이터 정합성).
 *
 * 분모 규칙 (기초자산 분모 방식):
 *   - 누적 모드 (dateFrom/dateTo 없음): 초기 투자원금 (테스트=accumulated_investment / 실전=buy_total_amt)
 *   - 기간 한정 모드 + baseAsset 전달: baseAsset (전일 장마감 총자산 + 당일 순입출금)
 *   - 기간 한정 모드 + baseAsset 미전달: 첫 거래일 기초자산 = 초기 투자원금 (결정 6, 폴밭 아닌 초기값 정의)
 * dateFrom/dateTo 적용 시 해당 범위 내 손익만 집계.
 */
function makeSellRow(date: string, realizedPnl: number, buyTotalAmt: number): Record<string, unknown> {
  return { date, realized_pnl: realizedPnl, buy_total_amt: buyTotalAmt }
}

function makeAccount(accumulatedInvestment: number): AccountSnapshot {
  return {
    total_buy_amount: 0, total_sell_amount: 0, total_eval_amount: 0,
    total_pnl: 0, total_pnl_rate: 0, deposit: 0,
    accumulated_investment: accumulatedInvestment,
    initial_deposit: accumulatedInvestment,
    trade_mode: 'test',
  }
}

describe('computeCumulativePnl — 테스트모드 (분모=누적투자금)', () => {
  it('단일 매도 — 수익률 = realized_pnl / accumulated_investment × 100', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(1000000), isTestMode: true,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100 = -10
  })

  it('다중 매도 합산 — 분모는 누적투자금(매수원가 합계 아님)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(1000000), isTestMode: true,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100 (매수원가 1000000 아님)
  })

  it('account 누락 시 rate=null (P20 폴백 금지 — initial_deposit 폴백 제거, 다단계 1세션 결정 5)', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: true,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBeNull()  // 분모 undefined → null (P20)
  })
})

describe('computeCumulativePnl — 실전모드 (분모=earliestBaseAsset — buyTotal 폐지, 다단계 1세션 결정 5)', () => {
  it('단일 매도 + earliestBaseAsset 전달 — 수익률 = realized_pnl / earliestBaseAsset × 100', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: false,
      earliestBaseAsset: 1000000,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100
  })

  it('다중 매도 합산 + earliestBaseAsset — 분모=earliestBaseAsset (buy_total_amt 폐지)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: false,
      earliestBaseAsset: 1000000,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100
  })

  it('earliestBaseAsset 미전달 → rate=null (P20 폴백 금지 — buyTotal로 덮지 않음)', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: false,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBeNull()  // earliestBaseAsset 없으면 null (P20)
  })
})

describe('computeCumulativePnl — 날짜 필터 (P10 SSOT, 도넛 차트와 계좌현황 공통)', () => {
  it('dateFrom/dateTo 적용 시 범위 내 손익만 집계 + 테스트모드 분모=누적투자금 (earliestBaseAsset 미전달 시 rate=null)', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -20000, 200000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(1000000), isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    expect(result.pnl).toBe(-70000)  // -50000 + -20000
    // baseAsset/earliestBaseAsset 미전달 시 rate=null (P20 폴백 금지 — initialInvestment로 덮지 않음)
    expect(result.rate).toBeNull()
  })

  it('dateFrom/dateTo + earliestBaseAsset 전달 → 분모=earliestBaseAsset', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -20000, 200000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(1000000), isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
      earliestBaseAsset: 1000000,
    })
    expect(result.pnl).toBe(-70000)
    expect(result.rate).toBe(-7)     // -70000 / 1000000 * 100
  })

  it('빈 sellHistory → pnl=0, rate=0 (누적투자금 분모 정상)', () => {
    const result = computeCumulativePnl({
      sellHistory: [], account: makeAccount(1000000), isTestMode: true,
    })
    expect(result.pnl).toBe(0)
    expect(result.rate).toBe(0)
  })
})

describe('computeCumulativePnl — 분모 규칙 (earliestBaseAsset 폴백 — 다단계 1세션 결정 5, P20 폴백 금지)', () => {
  // 테스트모드 누적: 분모=accumulated_investment (initial_deposit 폴백 제거 — null 시 rate null)
  // 실전모드 누적: 분모=earliestBaseAsset (buyTotal 폐지)
  // 기간 한정: baseAsset ?? earliestBaseAsset (둘 다 없으면 rate null)

  it('누적 모드 + 테스트모드 → 분모=누적투자금 (전체 투자원금 대비)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
    })
    expect(result.rate).toBe(-5)  // -100000 / 2000000 * 100 (누적투자금 분모)
  })

  it('기간 한정 모드 + 테스트모드 + baseAsset/earliestBaseAsset 미전달 → rate=null (P20)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    expect(result.rate).toBeNull()  // initialInvestment 폴백 제거 — null (P20)
  })

  it('기간 한정 모드 + 테스트모드 + earliestBaseAsset 전달 → 분모=earliestBaseAsset', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
      earliestBaseAsset: 2000000,
    })
    expect(result.rate).toBe(-5)  // -100000 / 2000000 * 100 (earliestBaseAsset 분모)
  })

  it('기간 한정 모드 + 실전모드 + baseAsset/earliestBaseAsset 미전달 → rate=null (P20, buyTotal 폐지)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: false,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    expect(result.rate).toBeNull()  // buyTotal 폐지 — null (P20)
  })

  it('기간 한정 모드 + 실전모드 + earliestBaseAsset 전달 → 분모=earliestBaseAsset', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: false,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
      earliestBaseAsset: 1000000,
    })
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100 (earliestBaseAsset 분모)
  })

  it('dateFrom만 있어도 테스트모드 + earliestBaseAsset → 분모=earliestBaseAsset', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),
      makeSellRow('2026-07-28', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
      dateFrom: '2026-07-28',
      earliestBaseAsset: 2000000,
    })
    expect(result.pnl).toBe(-50000)
    expect(result.rate).toBe(-2.5)  // -50000 / 2000000 * 100 (earliestBaseAsset 분모)
  })
})

describe('computeCumulativePnl — 기초자산 분모 (baseAsset 전달 시 — 사용자 결정 1·2)', () => {
  // 기간 한정 카드 + baseAsset 전달 시: 테스트/실전 모두 baseAsset 분모 (회전율 희석 방지 + 복리 자산 변화 반영)

  it('기간 한정 모드 + 테스트모드 + baseAsset 전달 → 분모=baseAsset (누적투자금 아님)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
      baseAsset: 1500000,  // 전일 장마감 총자산 150만원
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBeCloseTo(-6.67, 2)  // -100000 / 1500000 * 100 (baseAsset 분모)
  })

  it('기간 한정 모드 + 실전모드 + baseAsset 전달 → 분모=baseAsset (buy_total_amt 아님)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, account: null, isTestMode: false,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
      baseAsset: 1500000,  // 전일 장마감 총자산 150만원
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBeCloseTo(-6.67, 2)  // -100000 / 1500000 * 100 (baseAsset 분모, buy_total_amt 1000000 아님)
  })

  it('누적 모드 + baseAsset 전달 → 분모=초기 투자원금 (baseAsset 무시, 사용자 결정 3)', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
      baseAsset: 1500000,  // 누적 모드에서는 baseAsset 무시
    })
    expect(result.rate).toBe(-5)  // -100000 / 2000000 * 100 (누적 모드 = 초기 투자원금 분모)
  })

  it('baseAsset=0 전달 → 분모=0 → rate=null (0은 falsy → null 반환, P20 0 분모 금지)', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, account: makeAccount(2000000), isTestMode: true,
      dateFrom: '2026-07-29', dateTo: '2026-07-29',
      baseAsset: 0,  // 0은 falsy → null 반환 (0 분모 division 금지)
    })
    expect(result.rate).toBeNull()  // 0 분모 → null (P20)
  })
})

describe('findBaseAssetForDate — dailySummary에서 기초자산 추출 (P10 SSOT)', () => {
  function makeDailyRow(date: string, baseAsset: number): Record<string, unknown> {
    return { date, base_asset: baseAsset, sell_count: 0, buy_count: 0, realized_pnl: 0, pnl_rate: 0 }
  }

  it('date 이전 날짜 중 가장 최근 행의 base_asset 반환', () => {
    const dailySummary = [
      makeDailyRow('2026-07-25', 1000000),
      makeDailyRow('2026-07-28', 1500000),
      makeDailyRow('2026-07-29', 1800000),
    ]
    // 2026-07-30 기준: 2026-07-29가 가장 최근 이전 날짜
    expect(findBaseAssetForDate(dailySummary, '2026-07-30')).toBe(1800000)
  })

  it('date와 동일한 날짜는 제외 (전일 스냅샷이므로 미포함)', () => {
    const dailySummary = [
      makeDailyRow('2026-07-28', 1500000),
      makeDailyRow('2026-07-29', 1800000),
    ]
    // 2026-07-29 기준: 2026-07-29 동일 날짜 제외 → 2026-07-28 반환
    expect(findBaseAssetForDate(dailySummary, '2026-07-29')).toBe(1500000)
  })

  it('이전 날짜 없으면 undefined 반환 (첫 거래일 — 결정 6으로 초기 투자원금 처리)', () => {
    const dailySummary = [
      makeDailyRow('2026-07-29', 1800000),
      makeDailyRow('2026-07-30', 2000000),
    ]
    // 2026-07-28 기준: 이전 날짜 없음
    expect(findBaseAssetForDate(dailySummary, '2026-07-28')).toBeUndefined()
  })

  it('base_asset=0인 행은 건너뜀 (유효 기초자산 아님)', () => {
    const dailySummary = [
      makeDailyRow('2026-07-25', 0),
      makeDailyRow('2026-07-28', 1500000),
    ]
    // 2026-07-29 기준: 2026-07-28(1500000) 반환, 2026-07-25(0)은 건너뜀
    expect(findBaseAssetForDate(dailySummary, '2026-07-29')).toBe(1500000)
  })

  it('빈 dailySummary → undefined', () => {
    expect(findBaseAssetForDate([], '2026-07-30')).toBeUndefined()
  })

  it('base_asset 필드 누락 행은 건너뜀', () => {
    const dailySummary = [
      { date: '2026-07-25' },  // base_asset 필드 없음
      makeDailyRow('2026-07-28', 1500000),
    ]
    expect(findBaseAssetForDate(dailySummary, '2026-07-29')).toBe(1500000)
  })
})
