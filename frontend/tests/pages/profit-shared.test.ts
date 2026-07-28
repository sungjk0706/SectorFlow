import { describe, it, expect } from 'vitest'
import { computeHoldingsSummary, computePositionValuation } from '../../src/pages/profit-shared'
import type { Position, SectorStock } from '../../src/types'

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
