import { describe, it, expect } from 'vitest'
import {
  getRecent5TradingDays,
  buildSectorDonutRows,
  buildSectorStockPnl,
  filterTradeRows,
  aggregatePnl,
  buildMonthlyDrilldown,
  buildFivedayDrilldown,
  buildCumulativeDrilldown,
  buildChartFromDailySummary,
  buildTodayDrilldown,
  computeTodayAggregates,
} from '../../src/pages/profit-math'

/* ── getRecent5TradingDays ── */

describe('getRecent5TradingDays', () => {
  it('최근 5거래일 날짜를 내림차순 반환', () => {
    const dailySummary = [
      { date: '2026-07-25' }, { date: '2026-07-28' }, { date: '2026-07-29' },
      { date: '2026-07-30' }, { date: '2026-07-31' }, { date: '2026-08-01' },
    ]
    expect(getRecent5TradingDays(dailySummary)).toEqual([
      '2026-08-01', '2026-07-31', '2026-07-30', '2026-07-29', '2026-07-28',
    ])
  })

  it('5거래일 미만일 경우 전체 반환', () => {
    const dailySummary = [{ date: '2026-07-29' }, { date: '2026-07-30' }]
    expect(getRecent5TradingDays(dailySummary)).toEqual(['2026-07-30', '2026-07-29'])
  })

  it('빈 배열 → 빈 배열', () => {
    expect(getRecent5TradingDays([])).toEqual([])
  })

  it('빈 날짜 필터링', () => {
    const dailySummary = [{ date: '2026-07-29' }, { date: '' }, { date: '2026-07-30' }]
    expect(getRecent5TradingDays(dailySummary)).toEqual(['2026-07-30', '2026-07-29'])
  })
})

/* ── filterTradeRows ── */

describe('filterTradeRows', () => {
  const rows = [
    { date: '2026-07-28', stk_cd: '005930', stk_nm: '삼성전자' },
    { date: '2026-07-29', stk_cd: '000660', stk_nm: 'SK하이닉스' },
    { date: '2026-07-30', stk_cd: '005930', stk_nm: '삼성전자' },
  ]

  it('날짜 범위 필터', () => {
    const result = filterTradeRows(rows, '2026-07-29', '2026-07-30')
    expect(result).toHaveLength(2)
    expect(result[0].date).toBe('2026-07-29')
    expect(result[1].date).toBe('2026-07-30')
  })

  it('종목명 검색 필터', () => {
    const result = filterTradeRows(rows, '', '', '삼성')
    expect(result).toHaveLength(2)
    expect(result.every(r => r.stk_nm === '삼성전자')).toBe(true)
  })

  it('종목코드 검색 필터', () => {
    const result = filterTradeRows(rows, '', '', '000660')
    expect(result).toHaveLength(1)
    expect(result[0].stk_cd).toBe('000660')
  })

  it('빈 날짜 + 빈 검색 → 전체 반환', () => {
    expect(filterTradeRows(rows, '', '')).toHaveLength(3)
  })

  it('빈 배열', () => {
    expect(filterTradeRows([], '', '')).toEqual([])
  })
})

/* ── aggregatePnl — 실현 수익률 계산 정확성 (설계서 8.1) ── */
// 분모 규칙 (매수원금 기반 — 설계서 0절 최상위 원칙):
//   실현 수익률 = 해당 기간 매도 완료된 종목들의 실현손익 합 ÷ 총 매수원금 합 × 100
//   개별 종목 수익률의 평균이 아님 — 전체 실현손익 합계 ÷ 전체 매수금액 합계 (P22 데이터 정합성).
//   분모 0 시 computeWeightedRate 0 반환 (P20 폴백 금지 — 0은 유효한 값).

describe('aggregatePnl — 실현 수익률 계산 정확성 (설계 8.1)', () => {
  it('매도 없음 — sellHistory=[] → pnl=0, buyTotal=0, rate=0 (분모 0 → computeWeightedRate 0 반환)', () => {
    const result = aggregatePnl([])
    expect(result.pnl).toBe(0)
    expect(result.buyTotal).toBe(0)
    expect(result.rate).toBe(0)
  })

  it('1건 매도 (수익) — 매수 100만원 → 매도 105만원 → pnl=+5만원, rate=+5.00%', () => {
    const sells = [{ date: '2026-07-29', realized_pnl: 50000, buy_total_amt: 1000000 }]
    const result = aggregatePnl(sells)
    expect(result.pnl).toBe(50000)
    expect(result.buyTotal).toBe(1000000)
    expect(result.rate).toBe(5)  // 50000 / 1000000 * 100
  })

  it('1건 매도 (손실) — 매수 100만원 → 매도 98만원 → pnl=-2만원, rate=-2.00%', () => {
    const sells = [{ date: '2026-07-29', realized_pnl: -20000, buy_total_amt: 1000000 }]
    const result = aggregatePnl(sells)
    expect(result.pnl).toBe(-20000)
    expect(result.buyTotal).toBe(1000000)
    expect(result.rate).toBe(-2)  // -20000 / 1000000 * 100
  })

  it('여러 건 매도 (모두 수익) — 3건(100→105, 200→210, 300→309) → pnl=+24만원, rate=+4.00% (24/600)', () => {
    const sells = [
      { date: '2026-07-28', realized_pnl: 50000, buy_total_amt: 1000000 },   // 100→105 (+5만)
      { date: '2026-07-29', realized_pnl: 100000, buy_total_amt: 2000000 },  // 200→210 (+10만)
      { date: '2026-07-30', realized_pnl: 90000, buy_total_amt: 3000000 },   // 300→309 (+9만)
    ]
    const result = aggregatePnl(sells)
    expect(result.pnl).toBe(240000)        // 5 + 10 + 9 = 24만
    expect(result.buyTotal).toBe(6000000)  // 100 + 200 + 300 = 600만
    expect(result.rate).toBe(4)            // 240000 / 6000000 * 100 = 4 (개별 평균 아님)
  })

  it('손익 혼합 (+/-) — 100→105(+5), 200→198(-2), 300→309(+9) → pnl=+12만원, rate=+2.00% (12/600)', () => {
    const sells = [
      { date: '2026-07-28', realized_pnl: 50000, buy_total_amt: 1000000 },    // +5만
      { date: '2026-07-29', realized_pnl: -20000, buy_total_amt: 2000000 },   // -2만
      { date: '2026-07-30', realized_pnl: 90000, buy_total_amt: 3000000 },    // +9만
    ]
    const result = aggregatePnl(sells)
    expect(result.pnl).toBe(120000)        // 5 - 2 + 9 = 12만 (손익 상쇄)
    expect(result.buyTotal).toBe(6000000)  // 100 + 200 + 300 = 600만
    expect(result.rate).toBe(2)            // 120000 / 6000000 * 100 = 2 (매수원금 합 분모)
  })
})

/* ── buildSectorDonutRows ── */

describe('buildSectorDonutRows', () => {
  it('업종별 손익 집계 + 절대값 내림차순 정렬', () => {
    const sells = [
      { sector: '반도체', realized_pnl: 100000 },
      { sector: '금융', realized_pnl: -200000 },
      { sector: '반도체', realized_pnl: 50000 },
    ]
    const rows = buildSectorDonutRows(sells)
    expect(rows).toHaveLength(2)
    // 절대값 내림차순: |−200000| > |150000|
    expect(rows[0].sector).toBe('금융')
    expect(rows[0].pnl).toBe(-200000)
    expect(rows[1].sector).toBe('반도체')
    expect(rows[1].pnl).toBe(150000)
  })

  it('sector 누락 → 미분류', () => {
    const sells = [{ realized_pnl: 10000 }]
    const rows = buildSectorDonutRows(sells)
    expect(rows[0].sector).toBe('미분류')
  })

  it('빈 배열', () => {
    expect(buildSectorDonutRows([])).toEqual([])
  })
})

/* ── buildSectorStockPnl ── */

describe('buildSectorStockPnl', () => {
  it('업종별 종목 수익 그룹화', () => {
    const sells = [
      { sector: '반도체', stk_cd: '005930', stk_nm: '삼성전자', realized_pnl: 100000, buy_total_amt: 1000000, qty: 10 },
      { sector: '반도체', stk_cd: '000660', stk_nm: 'SK하이닉스', realized_pnl: -50000, buy_total_amt: 500000, qty: 5 },
      { sector: '금융', stk_cd: '005930', stk_nm: '삼성전자', realized_pnl: 20000, buy_total_amt: 200000, qty: 2 },
    ]
    const groups = buildSectorStockPnl(sells)
    expect(groups).toHaveLength(2)
    // 반도체 그룹: 2 종목
    const semi = groups.find(g => g.sector === '반도체')
    expect(semi).toBeDefined()
    expect(semi!.stocks).toHaveLength(2)
    expect(semi!.pnl).toBe(50000)  // 100000 + (-50000)
  })

  it('동일 stk_cd 여러 매도 기록 합산', () => {
    const sells = [
      { sector: '반도체', stk_cd: '005930', stk_nm: '삼성전자', realized_pnl: 50000, buy_total_amt: 500000, qty: 5 },
      { sector: '반도체', stk_cd: '005930', stk_nm: '삼성전자', realized_pnl: 30000, buy_total_amt: 300000, qty: 3 },
    ]
    const groups = buildSectorStockPnl(sells)
    expect(groups[0].stocks).toHaveLength(1)
    expect(groups[0].stocks[0].realized_pnl).toBe(80000)
    expect(groups[0].stocks[0].qty).toBe(8)
  })
})

/* ── buildMonthlyDrilldown ── */

describe('buildMonthlyDrilldown', () => {
  it('당월 거래일별 요약 집계', () => {
    const dailySummary = [
      { date: '2026-07-25', sell_count: 2, buy_count: 1, realized_pnl: 50000, pnl_rate: 5 },
      { date: '2026-07-28', sell_count: 1, buy_count: 0, realized_pnl: -20000, pnl_rate: -2 },
      { date: '2026-08-01', sell_count: 1, buy_count: 1, realized_pnl: 10000, pnl_rate: 1 },
    ]
    const rows = buildMonthlyDrilldown(dailySummary, '2026-07')
    expect(rows).toHaveLength(2)
    expect(rows[0].date).toBe('2026-07-28')  // 내림차순
    expect(rows[1].date).toBe('2026-07-25')
  })

  it('해당 월 데이터 없음', () => {
    const dailySummary = [{ date: '2026-08-01', sell_count: 1, buy_count: 0, realized_pnl: 10000, pnl_rate: 1 }]
    expect(buildMonthlyDrilldown(dailySummary, '2026-07')).toEqual([])
  })
})

/* ── buildFivedayDrilldown ── */

describe('buildFivedayDrilldown', () => {
  it('최근 5거래일 일별 실현손익', () => {
    const dailySummary = [
      { date: '2026-07-25', sell_count: 1, buy_count: 0, realized_pnl: 10000, pnl_rate: 1 },
      { date: '2026-07-28', sell_count: 2, buy_count: 1, realized_pnl: 30000, pnl_rate: 3 },
      { date: '2026-07-29', sell_count: 1, buy_count: 0, realized_pnl: -5000, pnl_rate: -0.5 },
    ]
    const rows = buildFivedayDrilldown(dailySummary)
    expect(rows).toHaveLength(3)
    expect(rows[0].date).toBe('2026-07-29')  // 내림차순
  })

  it('빈 dailySummary', () => {
    expect(buildFivedayDrilldown([])).toEqual([])
  })
})

/* ── buildCumulativeDrilldown ── */

describe('buildCumulativeDrilldown', () => {
  it('월별 누적 손익 집계', () => {
    const sells = [
      { date: '2026-07-28', realized_pnl: 50000 },
      { date: '2026-07-29', realized_pnl: -20000 },
      { date: '2026-08-01', realized_pnl: 30000 },
    ]
    const result = buildCumulativeDrilldown(sells, [])
    expect(result.monthlyRows).toHaveLength(2)
    expect(result.monthlyRows[0].yearMonth).toBe('2026-08')  // 내림차순
    expect(result.monthlyRows[0].pnl).toBe(30000)
    expect(result.monthlyRows[1].yearMonth).toBe('2026-07')
    expect(result.monthlyRows[1].pnl).toBe(30000)  // 50000 + (-20000)
  })

  it('빈 sellHistory', () => {
    const result = buildCumulativeDrilldown([], [])
    expect(result.monthlyRows).toEqual([])
  })
})

/* ── buildChartFromDailySummary ── */

describe('buildChartFromDailySummary', () => {
  it('매도 있는 날 → pnl/rate/fee/tax 추출', () => {
    const summary = [
      { date: '2026-07-28', sell_count: 2, realized_pnl: 50000, pnl_rate: 5, buy_fee: 100, sell_fee: 200, tax: 50 },
    ]
    const rows = buildChartFromDailySummary(summary)
    expect(rows).toHaveLength(1)
    expect(rows[0].pnl).toBe(50000)
    expect(rows[0].rate).toBe(5)
  })

  it('빈 배열', () => {
    expect(buildChartFromDailySummary([])).toEqual([])
  })

  it('비거래일(sell_count=0 && buy_count=0) 제외', () => {
    const summary = [
      { date: '2026-07-28', sell_count: 2, buy_count: 0, realized_pnl: 50000, pnl_rate: 5, buy_fee: 100, sell_fee: 200, tax: 50 },
      { date: '2026-07-29', sell_count: 0, buy_count: 0, realized_pnl: 0, pnl_rate: 0, buy_fee: 0, sell_fee: 0, tax: 0 },
    ]
    const rows = buildChartFromDailySummary(summary)
    expect(rows).toHaveLength(1)
    expect(rows[0].date).toBe('2026-07-28')
  })

  it('매수만 있는 날(sell_count=0, buy_count>0) 유지 → pnl=null', () => {
    const summary = [
      { date: '2026-07-28', sell_count: 0, buy_count: 3, realized_pnl: 0, pnl_rate: 0, buy_fee: 100, sell_fee: 0, tax: 0 },
    ]
    const rows = buildChartFromDailySummary(summary)
    expect(rows).toHaveLength(1)
    expect(rows[0].pnl).toBeNull()
  })
})

/* ── buildTodayDrilldown ── */

describe('buildTodayDrilldown', () => {
  it('실현(오늘 매도) 영역만', () => {
    const sellHistory = [
      { date: '2026-07-29', stk_cd: '005930', stk_nm: '삼성전자', realized_pnl: 100000 },
      { date: '2026-07-28', stk_cd: '000660', stk_nm: 'SK하이닉스', realized_pnl: 50000 },
    ]
    const result = buildTodayDrilldown(sellHistory, '2026-07-29')
    // 실현: 오늘 매도 1건
    expect(result.realizedRows).toHaveLength(1)
    expect(result.realizedRows[0].stk_cd).toBe('005930')
    expect(result.realizedTotal).toBe(100000)
  })

  it('오늘 매도 없음', () => {
    const result = buildTodayDrilldown([], '2026-07-29')
    expect(result.realizedRows).toEqual([])
    expect(result.realizedTotal).toBe(0)
  })
})

/* ── computeTodayAggregates ── */

describe('computeTodayAggregates', () => {
  it('당일 매수/매도금액 + 수수료/세금 집계', () => {
    const buyHistory = [
      { date: '2026-07-29', total_amt: 500000, fee: 100 },
      { date: '2026-07-28', total_amt: 300000, fee: 60 },
    ]
    const sellHistory = [
      { date: '2026-07-29', total_amt: 600000, fee: 120, tax: 300 },
      { date: '2026-07-28', total_amt: 400000, fee: 80, tax: 200 },
    ]
    const result = computeTodayAggregates(buyHistory, sellHistory, '2026-07-29')
    expect(result.todayBuyAmt).toBe(500000)
    expect(result.todaySellAmt).toBe(600000)
    expect(result.todayFeeTax).toBe(520)  // 100 + 120 + 300
    expect(result.cumFeeTax).toBe(860)  // 100+60 + 120+300+80+200
  })

  it('당일 거래 없음', () => {
    const buyHistory = [{ date: '2026-07-28', total_amt: 300000, fee: 60 }]
    const sellHistory = [{ date: '2026-07-28', total_amt: 400000, fee: 80, tax: 200 }]
    const result = computeTodayAggregates(buyHistory, sellHistory, '2026-07-29')
    expect(result.todayBuyAmt).toBe(0)
    expect(result.todaySellAmt).toBe(0)
    expect(result.todayFeeTax).toBe(0)
    expect(result.cumFeeTax).toBe(340)  // 60 + 80 + 200
  })

  it('빈 이력', () => {
    const result = computeTodayAggregates([], [], '2026-07-29')
    expect(result.todayBuyAmt).toBe(0)
    expect(result.todaySellAmt).toBe(0)
    expect(result.todayFeeTax).toBe(0)
    expect(result.cumFeeTax).toBe(0)
  })
})
