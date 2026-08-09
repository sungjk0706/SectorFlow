import { describe, it, expect } from 'vitest'
import { computeHoldingsSummary, computePositionValuation, computeCumulativePnl, getPositionValuationPrice } from '../../src/pages/profit-math'
import type { MasterStock, Position } from '../../src/types'

/**
 * computePositionValuation — 개별 보유종목 평가 계산 SSOT 함수 회귀 테스트.
 * sell-position.ts 개별 행(cur_price/pnl/rate)과 computeHoldingsSummary(요약행)가
 * 공유하는 단일 공식 (P10 SSOT, P23 일관성).
 * P21/P23: cur_price null → isNull=true, 나머지 0 (개별 행 '-' 표시와 동일 패턴).
 *
 * 평가 가격 소스: masterStocks(백엔드 master_stocks_cache 프론트 사본)의 장중 실시간가 또는 장외 확정가.
 * positions.cur_price는 거래 계산용 원재료이며 화면 평가값의 소스로 사용하지 않는다.
 *
 * computeHoldingsSummary — 보유 종목 요약 계산 회귀 테스트.
 * computePositionValuation 결과를 합산 (P10 SSOT 재사용).
 * P21/P23: cur_price null인 보유종목 있으면 계산에서 제외 + hasNullPrice=true 반환
 * (개별 종목 행 pnl/rate 컬럼의 null → '-' 표시 패턴과 동일).
 */

function makePosition(code: string, qty: number, avgPrice: number, curPrice: number | null = null): Position {
  return {
    stk_cd: code, stk_nm: `종목${code}`, qty, avg_price: avgPrice,
    cur_price: curPrice, buy_amt: avgPrice * qty, pnl_amount: null, pnl_rate: 0, eval_amount: null, buy_date: '20260720',
  }
}

function makeValuationPrices(positions: Position[]): Record<string, MasterStock> {
  return Object.fromEntries(positions.map(p => [p.stk_cd, {
    code: p.stk_cd,
    name: p.stk_nm,
    cur_price: p.cur_price,
    change_rate: 0,
  }]))
}

describe('masterStocks 평가 가격 SSOT', () => {
  it('positions.cur_price가 없어도 masterStocks 확정가로 평가한다', () => {
    const position = makePosition('005930', 3, 58800, null)
    const masterStocks = {
      '005930': { code: '005930', name: '두산로보틱스', cur_price: 61600, change_rate: 0 },
    }

    expect(getPositionValuationPrice(position, masterStocks)).toBe(61600)
    const result = computeHoldingsSummary([position], masterStocks)
    expect(result.evalTotal).toBe(184800)
    expect(result.evalPnl).toBe(8400)
    expect(result.evalRate).toBeCloseTo(4.76, 1)
    expect(result.hasNullPrice).toBe(false)
  })

  it('masterStocks에 가격이 없으면 계산하지 않고 누락 상태를 유지한다', () => {
    const position = makePosition('005930', 3, 58800, null)
    const result = computeHoldingsSummary([position], {})
    expect(result.evalTotal).toBe(0)
    expect(result.evalPnl).toBe(0)
    expect(result.hasNullPrice).toBe(true)
  })
})

describe('computeHoldingsSummary — 정상 경로 (평가 가격 존재)', () => {
  it('단일 종목 평가금액/평가손익/수익률 계산', () => {
    const positions = [makePosition('005930', 10, 70000, 80000)]
    const result = computeHoldingsSummary(positions, makeValuationPrices(positions))
    expect(result.evalTotal).toBe(800000)  // 80000 * 10
    expect(result.buyTotal).toBe(700000)  // 70000 * 10
    expect(result.evalPnl).toBe(100000)
    expect(result.evalRate).toBeCloseTo(14.29, 1)
    expect(result.hasNullPrice).toBe(false)
  })

  it('다중 종목 합산 계산', () => {
    const positions = [
      makePosition('005930', 10, 70000, 80000),
      makePosition('000660', 5, 120000, 130000),
    ]
    const result = computeHoldingsSummary(positions, makeValuationPrices(positions))
    expect(result.evalTotal).toBe(1450000)  // 800000 + 650000
    expect(result.buyTotal).toBe(1300000)  // 700000 + 600000
    expect(result.evalPnl).toBe(150000)
    expect(result.hasNullPrice).toBe(false)
  })

  it('qty 0인 종목은 계산에서 제외', () => {
    const positions = [
      makePosition('005930', 10, 70000, 80000),
      makePosition('000660', 0, 120000, 130000),
    ]
    const result = computeHoldingsSummary(positions, makeValuationPrices(positions))
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
    const positions = [makePosition('005930', 10, 70000, null)]
    const result = computeHoldingsSummary(positions, makeValuationPrices(positions))
    expect(result.evalTotal).toBe(0)
    expect(result.buyTotal).toBe(0)  // null 종목은 buyTotal에서도 제외
    expect(result.evalPnl).toBe(0)
    expect(result.hasNullPrice).toBe(true)
  })

  it('cur_price null (시세 미수신 — 새로고침 직후/장 전) → hasNullPrice=true', () => {
    const positions = [makePosition('005930', 10, 70000, null)]
    const result = computeHoldingsSummary(positions, makeValuationPrices(positions))
    expect(result.evalTotal).toBe(0)
    expect(result.buyTotal).toBe(0)
    expect(result.hasNullPrice).toBe(true)
  })

  it('일부 종목만 cur_price null → hasNullPrice=true, null 종목 제외하고 계산', () => {
    const positions = [
      makePosition('005930', 10, 70000, 80000),
      makePosition('000660', 5, 120000, null),
    ]
    const result = computeHoldingsSummary(positions, makeValuationPrices(positions))
    // 005930만 계산에 포함
    expect(result.evalTotal).toBe(800000)
    expect(result.buyTotal).toBe(700000)
    expect(result.evalPnl).toBe(100000)
    expect(result.hasNullPrice).toBe(true)  // 000660이 null이므로
  })
})

describe('computePositionValuation — 정상 경로 (cur_price 존재)', () => {
  it('단일 종목 diff/pnl/rate/evalAmt/buyAmt 계산', () => {
    const p = makePosition('005930', 10, 70000, 80000)
    const v = computePositionValuation(p, p.cur_price)
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

  it('buyPrice 0 → rate 0 (분모 0 가드)', () => {
    const p = makePosition('005930', 10, 0, 80000)
    const v = computePositionValuation(p, p.cur_price)
    expect(v.isNull).toBe(false)
    expect(v.rate).toBe(0)
    expect(v.pnl).toBe(800000)  // (80000 - 0) * 10
  })
})

describe('computePositionValuation — null 경로 (P21/P23 투명성)', () => {
  it('cur_price null → isNull=true, 모든 계산 0', () => {
    const p = makePosition('005930', 10, 70000, null)
    const v = computePositionValuation(p, p.cur_price)
    expect(v.isNull).toBe(true)
    expect(v.curPrice).toBe(0)
    expect(v.pnl).toBe(0)
    expect(v.rate).toBe(0)
    expect(v.evalAmt).toBe(0)
    expect(v.buyAmt).toBe(0)
  })

  it('cur_price null (시세 미수신 — 새로고침 직후/장 전) → isNull=true', () => {
    const p = makePosition('005930', 10, 70000, null)
    const v = computePositionValuation(p, p.cur_price)
    expect(v.isNull).toBe(true)
  })

  it('qty 0 → isNull=false, evalAmt/buyAmt=0 (합산에 0 기여, hasNullPrice 영향 X)', () => {
    const p = makePosition('005930', 0, 70000, 80000)
    const v = computePositionValuation(p, p.cur_price)
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
      makePosition('005930', 10, 70000, 80000),
      makePosition('000660', 5, 120000, 130000),
    ]
    const perRow = positions.map(p => computePositionValuation(p, p.cur_price))
    const sumPnl = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.pnl), 0)
    const sumEvalAmt = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.evalAmt), 0)
    const sumBuyAmt = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.buyAmt), 0)

    const summary = computeHoldingsSummary(positions, makeValuationPrices(positions))
    expect(summary.evalTotal).toBe(sumEvalAmt)
    expect(summary.buyTotal).toBe(sumBuyAmt)
    expect(summary.evalPnl).toBe(sumPnl)
    // evalPnl = evalTotal - buyTotal (수학적 동일)
    expect(summary.evalPnl).toBe(summary.evalTotal - summary.buyTotal)
  })

  it('일부 null → 요약 hasNullPrice=true, null 종목은 합산에서 제외', () => {
    const positions = [
      makePosition('005930', 10, 70000, 80000),
      makePosition('000660', 5, 120000, null),
    ]
    const perRow = positions.map(p => computePositionValuation(p, p.cur_price))
    const nullCount = perRow.filter(v => v.isNull).length
    const sumPnl = perRow.reduce((s, v) => s + (v.isNull ? 0 : v.pnl), 0)

    const summary = computeHoldingsSummary(positions, makeValuationPrices(positions))
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
 * 분모 규칙 (매수원금 기반 — 설계서 0절 최상위 원칙):
 *   - 실현 수익률 = 해당 기간 매도 완료된 종목들의 실현손익 합 ÷ 총 매수원금 합 × 100
 *   - 4카드(당일/5거래일/당월/누적) 동일 공식 (설계 원칙 5) — computeCumulativePnl이 aggregatePnl 기반으로 계산.
 *   - 실전매매: 증권사 서버가 SSOT — rate null → '-' 표시 (AGENTS.md 실전vs가상 테이블).
 * dateFrom/dateTo 적용 시 해당 범위 내 손익·매수원금만 집계.
 */
function makeSellRow(date: string, realizedPnl: number, buyTotalAmt: number): Record<string, unknown> {
  return { date, realized_pnl: realizedPnl, buy_total_amt: buyTotalAmt }
}

describe('computeCumulativePnl — 가상매매 (분모=매수원금)', () => {
  it('단일 매도 — 수익률 = realized_pnl / buy_total_amt × 100', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100 = -10 (매수원금 분모)
  })

  it('다중 매도 합산 — 분모는 매수원금 합(buy_total_amt 합계)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100 (매수원금 500000+500000)
  })

  it('account 불필요 — 매수원금 기반은 account 없이도 rate 계산 정상', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBe(-10)  // 매수원금 기반 — account 불필요
  })
})

describe('computeCumulativePnl — 실전매매 (증권사 서버 SSOT — 앱 재계산 금지, AGENTS.md 실전vs가상 테이블)', () => {
  it('단일 매도 — 실전매매는 rate=null (증권사 SSOT, 앱 재계산 금지)', () => {
    const sells = [makeSellRow('2026-07-29', -100000, 1000000)]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: false,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBeNull()  // 실전매매: 증권사 서버가 SSOT — 앱 재계산 금지
  })

  it('다중 매도 합산 — 실전매매는 rate=null (증권사 SSOT)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: false,
    })
    expect(result.pnl).toBe(-100000)
    expect(result.rate).toBeNull()  // 실전매매: 증권사 서버가 SSOT — 앱 재계산 금지
  })

  it('빈 sellHistory — 실전매매는 rate=null', () => {
    const result = computeCumulativePnl({
      sellHistory: [], isTestMode: false,
    })
    expect(result.pnl).toBe(0)
    expect(result.rate).toBeNull()  // 실전매매: 증권사 서버가 SSOT — 앱 재계산 금지
  })
})

describe('computeCumulativePnl — 날짜 필터 (P10 SSOT, 도넛 차트와 계좌현황 공통)', () => {
  it('dateFrom/dateTo 적용 시 범위 내 손익·매수원금만 집계 (매수원금 분모)', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -20000, 200000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    expect(result.pnl).toBe(-70000)  // -50000 + -20000
    // 분모 = 범위 내 매수원금 합 = 500000 + 200000 = 700000, rate = -70000 / 700000 * 100 = -10
    expect(result.rate).toBe(-10)
  })

  it('dateFrom만 적용 시 범위 내 손익·매수원금만 집계', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),
      makeSellRow('2026-07-28', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-28',
    })
    expect(result.pnl).toBe(-50000)
    // 분모 = 500000, rate = -50000 / 500000 * 100 = -10
    expect(result.rate).toBe(-10)
  })

  it('빈 sellHistory → pnl=0, rate=0 (매수원금 0 → computeWeightedRate 0 반환)', () => {
    const result = computeCumulativePnl({
      sellHistory: [], isTestMode: true,
    })
    expect(result.pnl).toBe(0)
    expect(result.rate).toBe(0)
  })
})

describe('computeCumulativePnl — 4카드 동일 공식 (설계 원칙 5·검증 원칙)', () => {
  // 동일 sellHistory에 대해 기간(당일·5거래일·당월·누적)에 관계없이 계산 공식은 동일.
  // 집계 대상(기간 필터)만 달라짐 — 분모 규칙 분기 없음.

  it('누적 모드 + 가상매매 → 분모=매수원금 합 (전체 매도 범위)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
    })
    expect(result.rate).toBe(-10)  // -100000 / 1000000 * 100 (매수원금 분모)
  })

  it('기간 한정 모드 + 가상매매 → 분모=해당 기간 매수원금 합 (누적투자금 아님)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    // 분모 = 500000 + 500000 = 1000000, rate = -100000 / 1000000 * 100 = -10
    expect(result.rate).toBe(-10)
  })

  it('기간 한정 모드 + 실전매매 → rate=null (증권사 SSOT, 앱 재계산 금지)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', -50000, 500000),
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: false,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    expect(result.rate).toBeNull()  // 실전매매: 증권사 서버가 SSOT — 앱 재계산 금지
  })
})

/* ── computeCumulativePnl — 기간별 동일 공식 (설계 8.2) ── */
// 검증 명제 (설계 원칙 5 · 검증 원칙): 4기간 케이스 모두 동일 computeCumulativePnl(aggregatePnl) 호출,
//   분모 규칙 분기 없음 — 기간 필터(dateFrom/dateTo)만 입력 차이.
// P22 데이터 정합성: 각 기간 선택이 실제로 동일한 계산 공식에 정확하게 필터만 적용하는지 검증.
//   - 기간 밖 거래가 실제로 제외되는지 (단순 호출 테스트 아님)
//   - 경계값: dateFrom 당일 포함, dateTo 당일 포함, dateFrom 이전 제외, dateTo 이후 제외

describe('computeCumulativePnl — 기간별 동일 공식 (설계 8.2 — 기간 밖 거래 제외 검증)', () => {
  // 공통 패턴: [기간밖, 기간안, 기간밖] 섞어서 기간 안 거래만 집계되는지 검증

  it('당일 — dateFrom=dateTo=today, 기간 밖 거래 제외 + 경계값(dateFrom/dateTo 당일 포함)', () => {
    const sells = [
      makeSellRow('2026-07-28', -30000, 300000),  // 기간 밖 (당일 이전)
      makeSellRow('2026-07-29', -50000, 500000),  // 기간 안 (당일 = dateFrom = dateTo)
      makeSellRow('2026-07-30', -20000, 200000),  // 기간 밖 (당일 이후)
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-29', dateTo: '2026-07-29',
    })
    expect(result.pnl).toBe(-50000)        // 당일 매도만
    expect(result.rate).toBe(-10)          // -50000 / 500000 * 100 (매수원금 분모)
  })

  it('5거래일 — recent5[4]~recent5[0] 범위, 범위 밖 거래 제외', () => {
    // recent5 = ['2026-08-01', '2026-07-31', '2026-07-30', '2026-07-29', '2026-07-28']
    // recent5[4]='2026-07-28' (from), recent5[0]='2026-08-01' (to)
    const sells = [
      makeSellRow('2026-07-25', -10000, 100000),  // 기간 밖 (5거래일 이전)
      makeSellRow('2026-07-28', -50000, 500000),  // 기간 안 (from 경계 — 포함)
      makeSellRow('2026-07-30', -30000, 300000),  // 기간 안
      makeSellRow('2026-08-01', -20000, 200000),  // 기간 안 (to 경계 — 포함)
      makeSellRow('2026-08-04', -40000, 400000),  // 기간 밖 (5거래일 이후)
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-08-01',
    })
    expect(result.pnl).toBe(-100000)       // -50000 + -30000 + -20000 (기간 안 3건)
    // buyTotal은 computeCumulativePnl 반환값에 없음 (aggregatePnl만 반환) — 8.1에서 별도 검증
    expect(result.rate).toBe(-10)          // -100000 / 1000000 * 100
  })

  it('당월 — monthStart~monthEnd 범위, 전월/익월 거래 제외', () => {
    const sells = [
      makeSellRow('2026-06-30', -10000, 100000),  // 기간 밖 (전월)
      makeSellRow('2026-07-15', -50000, 500000),  // 기간 안 (당월)
      makeSellRow('2026-07-31', -30000, 300000),  // 기간 안 (당월 말일 경계)
      makeSellRow('2026-08-01', -20000, 200000),  // 기간 밖 (익월)
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-01', dateTo: '2026-07-31',
    })
    expect(result.pnl).toBe(-80000)        // -50000 + -30000 (당월 2건)
    expect(result.rate).toBe(-10)          // -80000 / 800000 * 100
  })

  it('누적 — dateFrom/dateTo 없음, 전체 매도 집계 (필터 미적용)', () => {
    const sells = [
      makeSellRow('2026-06-30', -10000, 100000),  // 과거
      makeSellRow('2026-07-15', -50000, 500000),  // 최근
      makeSellRow('2026-08-01', -20000, 200000),  // 미래 (필터 없으므로 포함)
    ]
    const result = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      // dateFrom/dateTo 생략 — 전체 범위
    })
    expect(result.pnl).toBe(-80000)        // 전체 3건 합
    expect(result.rate).toBe(-10)          // -80000 / 800000 * 100
  })
})

/* ── computeCumulativePnl — 모드별 (설계 8.3) ── */
// P18 가상매매 동등성: 동일 매도 완료 거래에 대해 pnl은 모드 무관 동일,
//   rate만 차이 (가상매매=계산값, 실전매매=null).
// 실전매매: 증권사 서버가 SSOT — 앱에서 수익률 재계산 금지 (AGENTS.md 실전vs가상 테이블).

describe('computeCumulativePnl — 모드별 (설계 8.3 — pnl 동일성 + rate만 차이)', () => {
  it('동일 sellHistory → 가상매매/실전매매 pnl 동일, rate만 차이 (P18 가상매매 동등성)', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', 30000, 300000),
    ]
    const testResult = computeCumulativePnl({ sellHistory: sells, isTestMode: true })
    const realResult = computeCumulativePnl({ sellHistory: sells, isTestMode: false })

    // pnl 동일성 — 모드가 바뀌어도 실현손익 계산 자체는 동일 (P18)
    expect(realResult.pnl).toBe(testResult.pnl)  // -20000
    expect(testResult.pnl).toBe(-20000)          // -50000 + 30000

    // rate만 차이 — 가상매매=계산값, 실전매매=null (증권사 SSOT)
    expect(testResult.rate).toBe(-2.5)           // -20000 / 800000 * 100 = -2.5
    expect(realResult.rate).toBeNull()           // 실전매매: 앱 재계산 금지
  })

  it('동일 sellHistory + 기간 필터 → 모드 무관 pnl 동일, rate만 차이', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', 30000, 300000),
    ]
    const testResult = computeCumulativePnl({
      sellHistory: sells, isTestMode: true,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })
    const realResult = computeCumulativePnl({
      sellHistory: sells, isTestMode: false,
      dateFrom: '2026-07-28', dateTo: '2026-07-29',
    })

    // pnl 동일성 (기간 필터 적용 후에도 모드 무관 동일)
    expect(realResult.pnl).toBe(testResult.pnl)  // -20000 (-50000 + 30000)
    // rate만 차이
    expect(testResult.rate).toBe(-2.5)           // -20000 / 800000 * 100
    expect(realResult.rate).toBeNull()
  })
})

/* ── 실현 수익률 SSOT 일관성 — 동일 입력 동일 결과 (4곳 호출 경로 — 설계 3.5) ── */
// 검증 명제 (P10 SSOT 회귀 방지): 동일 sellHistory + 동일 기간 필터 입력 시
//   4곳 호출 경로(updateSummaryCards·buildDonutCenter·updateStatistics·renderAccountVals)가
//   모두 동일 computeCumulativePnl 결과를 산출해야 함.
//   한 곳이라도 다르면 SSOT 위반 (별도 계산 경로 존재 의미).
//
// 4곳 호출 경로 매핑 (실제 호출 7회 — 사전조사 확인):
//   #1 updateSummaryCards 당일:    computeCumulativePnl({sellHistory, isTestMode, dateFrom: today, dateTo: today})
//   #2 updateSummaryCards 5거래일: computeCumulativePnl({sellHistory, isTestMode, dateFrom: fivedayFrom, dateTo: fivedayTo})
//   #3 updateSummaryCards 당월:    computeCumulativePnl({sellHistory, isTestMode, dateFrom: monthStart, dateTo: monthEnd})
//   #4 updateSummaryCards 누적:    computeCumulativePnl({sellHistory, isTestMode})  // 필터 없음
//   #5 renderAccountVals 누적:     computeCumulativePnl({sellHistory, isTestMode})  // 필터 없음 — #4와 동일 의도
//   #6 buildDonutCenter 사용자선택: computeCumulativePnl({sellHistory, isTestMode, dateFrom: localDateFrom, dateTo: localDateTo})
//   #7 updateStatistics 사용자선택: computeCumulativePnl({sellHistory, isTestMode, dateFrom: dateRange.from, dateTo: dateRange.to})
//
// 일관성 검증 대상 (동일 의도 호출 경로):
//   - 누적 일관성: #4 == #5 (둘 다 필터 없음 = 누적 의도)
//   - 기간 한정 일관성: #6 == #7 (둘 다 사용자 선택 기간, 동일 dateFrom/dateTo 전달 시)
//   - #1~#3은 각 카드별 다른 기간이 의도적 (일관성 위반 아님 — 4카드는 서로 다른 기간 표시)
//
// 본 테스트는 computeCumulativePnl 계약 수준에서 검증 (DOM 직접 테스트 회피 — P24 단순성).
//   4곳이 computeCumulativePnl을 사용한다는 사실은 grep 정적 검증으로 별도 확인.

describe('실현 수익률 SSOT 일관성 — 동일 입력 동일 결과 (4곳 호출 경로 — 설계 3.5)', () => {
  it('누적 일관성 — #4(updateSummaryCards 누적) == #5(renderAccountVals 누적), 필터 없음', () => {
    const sells = [
      makeSellRow('2026-07-28', -50000, 500000),
      makeSellRow('2026-07-29', 30000, 300000),
      makeSellRow('2026-07-30', -20000, 200000),
    ]
    // #4 경로 시뮬레이션: updateSummaryCards 누적 카드 — 필터 없음
    const path4 = computeCumulativePnl({ sellHistory: sells, isTestMode: true })
    // #5 경로 시뮬레이션: renderAccountVals 누적 — 필터 없음
    const path5 = computeCumulativePnl({ sellHistory: sells, isTestMode: true })

    // 동일 입력 → 동일 pnl·rate (SSOT — 한 곳이라도 다르면 우회 계산 경로 존재)
    expect(path5.pnl).toBe(path4.pnl)        // -40000
    expect(path5.rate).toBe(path4.rate)      // -4
    // pinned 값 (회귀 감지 — aggregatePnl 공식 변경 시 깨짐)
    expect(path4.pnl).toBe(-40000)           // -50000 + 30000 + -20000
    expect(path4.rate).toBe(-4)              // -40000 / 1000000 * 100
  })

  it('기간 한정 일관성 — #6(buildDonutCenter) == #7(updateStatistics), 동일 dateFrom/dateTo', () => {
    const sells = [
      makeSellRow('2026-07-27', -30000, 300000),  // 기간 밖
      makeSellRow('2026-07-28', -50000, 500000),  // 기간 안
      makeSellRow('2026-07-29', 30000, 300000),   // 기간 안
      makeSellRow('2026-07-30', -20000, 200000),  // 기간 밖
    ]
    const dateFrom = '2026-07-28'
    const dateTo = '2026-07-29'
    // #6 경로 시뮬레이션: buildDonutCenter — 사용자 선택 기간
    const path6 = computeCumulativePnl({ sellHistory: sells, isTestMode: true, dateFrom, dateTo })
    // #7 경로 시뮬레이션: updateStatistics — 사용자 선택 기간
    const path7 = computeCumulativePnl({ sellHistory: sells, isTestMode: true, dateFrom, dateTo })

    // 동일 입력 → 동일 pnl·rate (SSOT)
    expect(path7.pnl).toBe(path6.pnl)        // -20000
    expect(path7.rate).toBe(path6.rate)      // -2.5
    // pinned 값 (회귀 감지)
    expect(path6.pnl).toBe(-20000)           // -50000 + 30000 (기간 안 2건)
    expect(path6.rate).toBe(-2.5)            // -20000 / 800000 * 100
  })
})
