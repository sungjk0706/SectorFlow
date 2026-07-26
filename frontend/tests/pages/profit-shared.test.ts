import { describe, it, expect } from 'vitest'
import { computeHoldingsSummary } from '../../src/pages/profit-shared'
import type { Position, SectorStock } from '../../src/types'

/**
 * computeHoldingsSummary — 보유 종목 요약 계산 순수 함수 회귀 테스트.
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
    trade_amount: 0, strength: 0, sector: '업종1', rank: 1, guard_pass: true, reason: '',
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
