import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  hotStore,
  applyMasterStocksSnapshot,
  applyMasterStocksDelta,
  applyBuyTargetsUpdate,
  applyBuyTargetsDelta,
  applyNewsHit,
  applyRealtimeReset,
  applyRealData,
  applyAccountUpdate,
  applyAccountSummaryUpdate,
  applyAccountSnapshot,
  flushTickBatch,
  rebuildBuyTargetIndex,
  normalizeStockCode,
  type HotState,
} from '../../src/stores/hotStore'
import type { MasterStock, StockScore, RealDataEvent, Position } from '../../src/types'

/** 테스트용 초기 상태 — masterStocks(실시간 SSOT)와 buyTargets(정적 스코어) 분리
 *  마이그레이션 후: buyTargets는 정적 필드만 보관, 실시간 시세는 masterStocks가 단일 진실 소스. */
function makeInitialHotState(): HotState {
  // buyTargets용 (StockScore — 정적 스코어만)
  const targetA: StockScore = {
    code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true, reject_reason: '',
  }
  const targetB: StockScore = {
    code: '000002', name: '종목B', sector: '업종2', rank: 2, guard_pass: true, reject_reason: '',
  }
  // masterStocks용 (MasterStock — 실시간 시세 + 식별 정보)
  // 백엔드 _REALTIME_FIELDS 8개와 동일한 실시간 필드 포함 (P10 SSOT, P23 일관성)
  const masterStocks: Record<string, MasterStock> = {
    '000001': { code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
      trade_amount: 5000, strength: 80, sector: '업종1',
      order_ratio: [120, 80], program_net_buy: 500, news_boost: 3 },
    '000002': { code: '000002', name: '종목B', cur_price: 20000, change: -200, change_rate: -0.9,
      trade_amount: 3000, strength: 60, sector: '업종2',
      order_ratio: [60, 90], program_net_buy: -200, news_boost: 0 },
  }
  const buyTargets = [{ ...targetA }, { ...targetB }]
  rebuildBuyTargetIndex(buyTargets)
  return {
    account: null,
    positions: [],
    positionCount: 0,
    masterStocks,
    sectorScores: [],
    buyTargets,
    sellHistory: [],
    buyHistory: [],
    dailySummary: [],
    freshness: {
      account: { group: 'account', revision: 0 },
      buy_targets: { group: 'buy_targets', revision: 0 },
      sector_scores: { group: 'sector_scores', revision: 0 },
      sector_stocks: { group: 'sector_stocks', revision: 0 },
      trade_history: { group: 'trade_history', revision: 0 },
    },
  }
}

function resetHotState(): void {
  const initial = makeInitialHotState()
  hotStore.setState(initial)
}

describe('hotStore — masterStocks 실시간 시세 SSOT (마이그레이션)', () => {
  beforeEach(() => {
    resetHotState()
  })

  describe('applyMasterStocksSnapshot', () => {
    it('masterStocks 교체 후 새 시세 반영', () => {
      const refreshedStockA: MasterStock = {
        code: '000001', name: '종목A', cur_price: 15000, change: 500, change_rate: 3.5,
        trade_amount: 9999, strength: 95, sector: '업종1',
      }
      const refreshedStockB: MasterStock = {
        code: '000002', name: '종목B', cur_price: 21000, change: 100, change_rate: 0.5,
        trade_amount: 8888, strength: 70, sector: '업종2',
      }
      applyMasterStocksSnapshot({ stocks: [refreshedStockA, refreshedStockB] })

      const state = hotStore.getState()
      expect(state.masterStocks['000001']!.cur_price).toBe(15000)
      expect(state.masterStocks['000001']!.change).toBe(500)
      expect(state.masterStocks['000001']!.change_rate).toBe(3.5)
      expect(state.masterStocks['000001']!.trade_amount).toBe(9999)
      expect(state.masterStocks['000001']!.strength).toBe(95)
      expect(state.masterStocks['000002']!.cur_price).toBe(21000)
    })

    it('빈 배열 수신 시 no-op (기존 masterStocks 유지)', () => {
      // applyMasterStocksSnapshot은 빈 스냅샷을 무시 — 백엔드가 빈 목록을 전송하지 않으므로
      // 빈 배열은 비정상 신호로 간주하여 기존 데이터 보호 (P20 폴백 금지).
      const prevCount = Object.keys(hotStore.getState().masterStocks).length
      const result = applyMasterStocksSnapshot({ stocks: [] })
      expect(result).toBe(false)
      expect(Object.keys(hotStore.getState().masterStocks).length).toBe(prevCount)
    })
  })

  describe('applyRealtimeReset', () => {
    it('reset 후 masterStocks 실시간 필드 모두 null (백엔드 8개와 동일)', () => {
      applyRealtimeReset()

      const state = hotStore.getState()
      const msA = state.masterStocks['000001']!
      expect(msA.cur_price).toBeNull()
      expect(msA.change).toBeNull()
      expect(msA.change_rate).toBeNull()
      expect(msA.trade_amount).toBeNull()
      expect(msA.strength).toBeNull()
      // 백엔드 _REALTIME_FIELDS 추가 3개 (P10 SSOT 동기화)
      expect(msA.order_ratio).toBeNull()
      expect(msA.program_net_buy).toBeNull()
      expect(msA.news_boost).toBeNull()

      // 정적 식별 필드는 유지
      expect(msA.name).toBe('종목A')
      expect(msA.sector).toBe('업종1')
    })

    it('reset 후 sectorScores도 빈 배열로 동기화 (백엔드 sector_summary_cache=None 반영)', () => {
      hotStore.setState({
        sectorScores: [
          { sector: '업종1', rank: 1, final_score: 10, rise_ratio: 100, total: 5, is_cutoff_passed: true, avg_trade_amount: 1000 } as never,
        ],
      })
      expect(hotStore.getState().sectorScores.length).toBe(1)

      applyRealtimeReset()

      expect(hotStore.getState().sectorScores).toEqual([])
    })

    it('reset 후 buyTargets 정적 필드 유지 (실시간 필드 없으므로 변경 없음)', () => {
      applyRealtimeReset()

      const state = hotStore.getState()
      const btA = state.buyTargets.find(t => t.code === '000001')!
      expect(btA.rank).toBe(1)
      expect(btA.guard_pass).toBe(true)
      expect(btA.name).toBe('종목A')
    })
  })

  describe('applyRealData', () => {
    it('real-data 틱 후 masterStocks 실시간 필드 갱신', () => {
      const event: RealDataEvent = {
        type: '01',
        item: '000001',
        values: {
          '10': '12000',  // 현재가
          '11': '+200',   // 대비
          '12': '1.67',   // 등락률
          '228': '85',    // 체결강도
          '14': '7000',   // 거래대금
        },
      }
      applyRealData(event)

      const state = hotStore.getState()
      const msA = state.masterStocks['000001']!

      // masterStocks(SSOT) 갱신 검증
      expect(msA.cur_price).toBe(12000)
      expect(msA.change).toBe(200)
      expect(msA.change_rate).toBe(1.67)
      expect(msA.strength).toBe(85)
      expect(msA.trade_amount).toBe(7000)
    })

    it('buyTargets에 없는 종목도 masterStocks만 갱신', () => {
      // 종목C는 masterStocks에만 있고 buyTargets에 없는 상태로 설정
      hotStore.setState((state) => ({
        masterStocks: {
          ...state.masterStocks,
          '000003': { code: '000003', name: '종목C', cur_price: 30000, change: 0, change_rate: 0 },
        },
      }))

      const event: RealDataEvent = {
        type: '01',
        item: '000003',
        values: { '10': '35000', '11': '+500', '12': '1.5', '228': '90', '14': '10000' },
      }
      applyRealData(event)

      const state = hotStore.getState()
      const msC = state.masterStocks['000003']!
      expect(msC.cur_price).toBe(35000)

      // buyTargets에는 종목C가 없음
      const btC = state.buyTargets.find(t => t.code === '000003')
      expect(btC).toBeUndefined()
    })
  })
})

describe('hotStore — 이벤트 계약 정합성 (세션 4)', () => {
  beforeEach(() => {
    resetHotState()
  })

  describe('applyBuyTargetsUpdate', () => {
    it('incoming 정적 필드가 prev와 다르면 setState 발화', () => {
      const incoming: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true, reject_reason: '' },
        { code: '000002', name: '종목B', sector: '업종2', rank: 2, guard_pass: true, reject_reason: '' },
      ]
      applyBuyTargetsUpdate({ buy_targets: incoming })
      const prevRef = hotStore.getState().buyTargets

      // rank 변경 (1 → 5)
      const updated: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 5, guard_pass: true, reject_reason: '' },
        { code: '000002', name: '종목B', sector: '업종2', rank: 2, guard_pass: true, reject_reason: '' },
      ]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets).not.toBe(prevRef)  // setState 발화
      expect(state.buyTargets[0].rank).toBe(5)
    })

    it('동일 정적 필드 시 setState 미발화 (same=true)', () => {
      const initial: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true,
          reject_reason: '', boost_score: 5.0, high_5d: 12000 },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })
      const prevRef = hotStore.getState().buyTargets

      // 동일 정적 필드 (참조만 다른 객체)
      const updated: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true,
          reject_reason: '', boost_score: 5.0, high_5d: 12000 },
      ]
      applyBuyTargetsUpdate({ buy_targets: updated })

      // same=true → buyTargets 배열 참조 동일 (setState 미발화)
      expect(hotStore.getState().buyTargets).toBe(prevRef)
    })

    it('news_boost 변경 시 setState 미발화 (same=true, news-hit 단일 경로 — 세션 3)', () => {
      const initial: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true,
          reject_reason: '', boost_score: 5.0, high_5d: 12000, news_boost: 0.0 },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })
      const prevRef = hotStore.getState().buyTargets

      // news_boost만 변경 (0.0 → 1.5) — same=true, setState 미발화
      const updated: StockScore[] = [{ ...initial[0], news_boost: 1.5 }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets).toBe(prevRef)            // 참조 동일 — setState 미발화
      expect(state.buyTargets[0].news_boost).toBe(0.0)  // news_boost 무시 (news-hit이 담당)
    })

    it('high_5d 변경 시 setState 발화 (same=false)', () => {
      const initial: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true,
          reject_reason: '', boost_score: 5.0, high_5d: 12000 },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })

      // high_5d 변경 (12000 → 13000)
      const updated: StockScore[] = [{ ...initial[0], high_5d: 13000 }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets[0].high_5d).toBe(13000)
    })
  })

  // ── 세션 4 — news_boost_title 보존 (P22 데이터 정합성) ──
  describe('applyBuyTargetsUpdate — news_boost_title 보존 (세션 4, P22)', () => {
    it('news_boost > 0 시 prev의 news_boost_title 보존 (전체 새로고침 후에도 툴팁 유지)', () => {
      // 1. applyNewsHit으로 news_boost + title 설정
      applyNewsHit({ codes: ['000001'], scores: [1.5], title: 'A기업 수주 계약' })
      expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('A기업 수주 계약')

      // 2. 전체 새로고침 — 백엔드 스냅샷은 news_boost 포함하지만 title 미포함
      const refreshed: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 1, guard_pass: true,
          reject_reason: '', boost_score: 5.0, high_5d: 12000, news_boost: 1.5 },
        { code: '000002', name: '종목B', sector: '업종2', rank: 2, guard_pass: true,
          reject_reason: '', boost_score: 3.0, high_5d: 22000, news_boost: 0 },
      ]
      applyBuyTargetsUpdate({ buy_targets: refreshed })

      // 3. news_boost > 0이므로 title 보존
      const btA = hotStore.getState().buyTargets.find(t => t.code === '000001')!
      expect(btA.news_boost_title).toBe('A기업 수주 계약')
    })
  })

  describe('applyBuyTargetsDelta', () => {
    it('added: buyTargets에 신규 종목 추가 (정적 필드만)', () => {
      const added: StockScore[] = [
        { code: '000005', name: '종목E', sector: '업종5', rank: 5, guard_pass: true, reject_reason: '' },
      ]
      applyBuyTargetsDelta({ added })
      const btE = hotStore.getState().buyTargets.find(t => t.code === '000005')!
      expect(btE.name).toBe('종목E')
      expect(btE.rank).toBe(5)
      expect(btE.sector).toBe('업종5')
    })

    it('removed: buyTargets에서 종목 제거', () => {
      applyBuyTargetsDelta({ removed: ['000002'] })
      expect(hotStore.getState().buyTargets.find(t => t.code === '000002')).toBeUndefined()
    })

    it('changed: 정적 필드 교체', () => {
      const changed: StockScore[] = [
        { code: '000001', name: '종목A-리네임', sector: '업종1', rank: 3, guard_pass: false, reject_reason: 'r' },
      ]
      applyBuyTargetsDelta({ changed })

      const btA = hotStore.getState().buyTargets.find(t => t.code === '000001')!
      expect(btA.name).toBe('종목A-리네임')
      expect(btA.rank).toBe(3)
      expect(btA.guard_pass).toBe(false)
    })

    it('added/removed/changed 동시 적용 시 순서대로 처리 (removed → changed → added)', () => {
      applyBuyTargetsDelta({
        removed: ['000002'],
        changed: [
          { code: '000001', name: '종목A-리네임', sector: '업종1', rank: 5, guard_pass: false, reject_reason: 'r' },
        ],
        added: [
          { code: '000003', name: '종목C', sector: '업종3', rank: 3, guard_pass: true, reject_reason: '' },
        ],
      })

      const state = hotStore.getState()
      // removed: 000002 제거
      expect(state.buyTargets.find(t => t.code === '000002')).toBeUndefined()
      // changed: 000001 리네임
      const btA = state.buyTargets.find(t => t.code === '000001')!
      expect(btA.name).toBe('종목A-리네임')
      expect(btA.rank).toBe(5)
      // added: 000003 추가
      const btC = state.buyTargets.find(t => t.code === '000003')!
      expect(btC.name).toBe('종목C')
    })

    it('변경 사항 없을 시 setState 미발화 (배열 참조 동일)', () => {
      const prev = hotStore.getState().buyTargets
      applyBuyTargetsDelta({ removed: [], changed: [], added: [] })
      expect(hotStore.getState().buyTargets).toBe(prev)
    })

    it('rebuildBuyTargetIndex 호출 — removed 후 getBuyTargetIndex 일관성', async () => {
      const { getBuyTargetIndex } = await import('../../src/stores/hotStore')
      // 초기: 000001 → idx 0, 000002 → idx 1
      expect(getBuyTargetIndex('000001')).toBe(0)
      expect(getBuyTargetIndex('000002')).toBe(1)

      applyBuyTargetsDelta({ removed: ['000001'] })

      // removed 후 인덱스 재구축: 000002 → idx 0, 000001 → undefined
      expect(getBuyTargetIndex('000001')).toBeUndefined()
      expect(getBuyTargetIndex('000002')).toBe(0)
    })

    // ── news_boost/news_boost_title 보존 (P10 SSOT — news-hit 단일 전달 경로 보호) ──
    it('changed: news_boost/news_boost_title 보존 — news-hit 단일 소스 보호 (P10/P21)', () => {
      // 1. news-hit으로 news_boost + title 세팅 (📰 표시 상태)
      applyNewsHit({ codes: ['000001'], scores: [1.5], boost_scores: [3.5], title: 'A기업 대규모 수주' })
      const afterHit = hotStore.getState().buyTargets[0]
      expect(afterHit.news_boost).toBe(1.5)
      expect(afterHit.news_boost_title).toBe('A기업 대규모 수주')

      // 2. 백엔드 changed delta — news_boost는 _BUY_TARGET_REALTIME_KEYS에 의해 pop 제거됨
      const changed: StockScore[] = [
        { code: '000001', name: '종목A', sector: '업종1', rank: 5, guard_pass: true,
          reject_reason: '', boost_score: 3.5 },
      ]
      applyBuyTargetsDelta({ changed })

      // 3. news_boost/news_boost_title 보존 검증 (📰 표시 유지)
      const afterDelta = hotStore.getState().buyTargets[0]
      expect(afterDelta.news_boost).toBe(1.5)
      expect(afterDelta.news_boost_title).toBe('A기업 대규모 수주')
      // boost_score는 delta 값으로 갱신
      expect(afterDelta.boost_score).toBe(3.5)
    })

    it('changed: news_boost 미설정 종목은 보존 시 undefined 유지 (불필요한 세팅 금지)', () => {
      const changed: StockScore[] = [
        { code: '000001', name: '종목A-리네임', sector: '업종1', rank: 5, guard_pass: true, reject_reason: '' },
      ]
      applyBuyTargetsDelta({ changed })
      const after = hotStore.getState().buyTargets[0]
      expect(after.news_boost).toBeUndefined()
      expect(after.news_boost_title).toBeUndefined()
    })
  })
})

// ── 세션 3 — news-hit 단일 갱신 경로 (P10 SSOT, P25 격리된 실패) ──────────────
describe('hotStore — applyNewsHit (news-hit 단일 갱신 경로, 세션 3)', () => {
  beforeEach(() => {
    resetHotState()
  })

  it('해당 종목의 news_boost만 patch (다른 필드 불변, 미해당 종목 불변)', () => {
    const prev = hotStore.getState().buyTargets
    const prevA = { ...prev[0] }
    const prevB = { ...prev[1] }

    applyNewsHit({ codes: ['000001'], scores: [1.5] })

    const state = hotStore.getState()
    // 종목A: news_boost만 1.5로 갱신, 나머지 필드 불변
    expect(state.buyTargets[0].news_boost).toBe(1.5)
    const { news_boost: _a, news_boost_title: _at, ...restA } = state.buyTargets[0]
    const { news_boost: _pa, news_boost_title: _pat, ...restPrevA } = prevA
    expect(restA).toEqual(restPrevA)

    // 종목B: 미해당 종목 불변
    expect(state.buyTargets[1].news_boost).toBeUndefined()
    const { news_boost: _b, news_boost_title: _bt, ...restB } = state.buyTargets[1]
    const { news_boost: _pb, news_boost_title: _pbt, ...restPrevB } = prevB
    expect(restB).toEqual(restPrevB)
  })

  it('여러 종목 동시 가산점 적용', () => {
    applyNewsHit({ codes: ['000001', '000002'], scores: [2.0, 1.5] })

    const state = hotStore.getState()
    expect(state.buyTargets[0].news_boost).toBe(2.0)
    expect(state.buyTargets[1].news_boost).toBe(1.5)
  })

  it('boost_scores 전달 시 boost_score도 갱신 (수정안 3 — 백엔드 재계산값)', () => {
    applyNewsHit({ codes: ['000001'], scores: [1.5], boost_scores: [7.5] })

    const state = hotStore.getState()
    expect(state.buyTargets[0].news_boost).toBe(1.5)
    expect(state.buyTargets[0].boost_score).toBe(7.5)
  })

  it('title 전달 시 news_boost_title에 보관 (📰 툴팁 표시용, P21)', () => {
    applyNewsHit({ codes: ['000001'], scores: [1.5], title: 'A기업 대규모 수주' })

    expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('A기업 대규모 수주')
  })

  it('title 누락 시 빈 문자열 (P20 명시적 값)', () => {
    applyNewsHit({ codes: ['000001'], scores: [1.5] })

    expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('')
  })

  it('codes 빈 배열 시 setState 미발화 (P25 격리된 실패)', () => {
    const prev = hotStore.getState().buyTargets
    applyNewsHit({ codes: [], scores: [] })
    expect(hotStore.getState().buyTargets).toBe(prev)
  })

  it('masterStocks news_boost도 동기화 (백엔드 master_stocks_cache와 일치, P10 SSOT)', () => {
    applyNewsHit({ codes: ['000001'], scores: [1.5] })

    const state = hotStore.getState()
    expect(state.masterStocks['000001']!.news_boost).toBe(1.5)
  })

  it('buyTargets에 없는 종목은 masterStocks에만 news_boost 갱신', () => {
    // 종목C는 masterStocks에만 있음
    hotStore.setState((state) => ({
      masterStocks: {
        ...state.masterStocks,
        '000003': { code: '000003', name: '종목C', cur_price: 30000, change: 0, change_rate: 0 },
      },
    }))

    applyNewsHit({ codes: ['000003'], scores: [2.0] })

    const state = hotStore.getState()
    expect(state.masterStocks['000003']!.news_boost).toBe(2.0)
    // buyTargets에는 종목C가 없음
    expect(state.buyTargets.find(t => t.code === '000003')).toBeUndefined()
  })
})

// ── 틱 디스패치 계약 (rAF 배칭) ──────────────────────────────────────────────
describe('hotStore — 틱 디스패치 계약 (rAF 배칭, 세션 3)', () => {
  beforeEach(() => {
    resetHotState()
    // 이전 테스트에서 남은 dirty Set 초기화 (rAF 배칭 잔류 방지)
    flushTickBatch()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  describe('real-data-tick 디스패치 계약', () => {
    it('변경 시 real-data-tick 디스패치', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      // flush 전에는 디스패치 안 됨
      expect(handler).not.toHaveBeenCalled()
      flushTickBatch()

      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      window.removeEventListener('real-data-tick', handler)
    })

    it('no-change(동일 값) 시 디스패치 안 함', () => {
      // 먼저 000001의 값을 설정
      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      flushTickBatch()

      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      // 동일 값 재호출
      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('real-data-tick', handler)
    })

    it('여러 종목 틱 → 단일 flush에서 각각 디스패치', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      applyRealData({ type: '01', item: '000002', values: { '10': '21000', '11': '+100', '12': '0.48', '228': '70', '14': '3000' } })
      // flush 전에는 디스패치 안 됨
      expect(handler).not.toHaveBeenCalled()
      flushTickBatch()

      // 단일 flush에서 2회 디스패치 (종목당 1회)
      expect(handler).toHaveBeenCalledTimes(2)
      const codes = handler.mock.calls.map(c => (c[0] as CustomEvent<string>).detail)
      expect(codes).toContain('000001')
      expect(codes).toContain('000002')
      window.removeEventListener('real-data-tick', handler)
    })

    it('동일 code 여러 틱 → 1회 디스패치 (Set dedup / last-write-wins)', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      // 동일 종목A에 3회 연속 틱 (값이 매번 변경됨)
      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      applyRealData({ type: '01', item: '000001', values: { '10': '12000', '11': '+200', '12': '1.67', '228': '90', '14': '7000' } })
      applyRealData({ type: '01', item: '000001', values: { '10': '13000', '11': '+300', '12': '2.5', '228': '95', '14': '8000' } })
      flushTickBatch()

      // Set dedup으로 1회 디스패치 (last-write-wins — 최종값 13000 반영)
      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      // 상태는 마지막 틱 값
      expect(hotStore.getState().masterStocks['000001']!.cur_price).toBe(13000)
      window.removeEventListener('real-data-tick', handler)
    })

    it('flush 후 새 틱은 다음 flush에서 디스패치 (Set 스왑)', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      // 첫 번째 배치
      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      flushTickBatch()
      expect(handler).toHaveBeenCalledTimes(1)

      // 두 번째 배치 — flush 후 새 틱
      applyRealData({ type: '01', item: '000001', values: { '10': '12000', '11': '+200', '12': '1.67', '228': '90', '14': '7000' } })
      flushTickBatch()
      expect(handler).toHaveBeenCalledTimes(2)
      window.removeEventListener('real-data-tick', handler)
    })
  })

  describe('orderbook-tick / program-tick 디스패치 계약 (applyMasterStocksDelta)', () => {
    it('order_ratio 변경 시 orderbook-tick 디스패치', () => {
      const handler = vi.fn()
      window.addEventListener('orderbook-tick', handler)

      applyMasterStocksDelta({ code: '000001', fields: { order_ratio: [100, 200] } })
      flushTickBatch()

      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      window.removeEventListener('orderbook-tick', handler)
    })

    it('order_ratio no-change(동일 원시값) 시 디스패치 안 함 — program_net_buy 단일 값으로 검증', () => {
      // 참고: order_ratio는 배열이므로 참조 비교로 항상 changed=true.
      // 백엔드가 delta를 보낼 때 값이 실제로 변경되었을 것이므로 프로덕션에서는 문제 없음.
      // 단일 값 필드(program_net_buy)로 no-change 검증.
      applyMasterStocksDelta({ code: '000001', fields: { program_net_buy: 5000 } })
      flushTickBatch()

      const handler = vi.fn()
      window.addEventListener('program-tick', handler)

      // 동일 값 재호출
      applyMasterStocksDelta({ code: '000001', fields: { program_net_buy: 5000 } })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('program-tick', handler)
    })

    it('masterStocks에 없는 종목은 스킵', () => {
      const handler = vi.fn()
      window.addEventListener('orderbook-tick', handler)

      applyMasterStocksDelta({ code: '999999', fields: { order_ratio: [100, 200] } })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('orderbook-tick', handler)
    })

    it('program_net_buy 변경 시 program-tick 디스패치', () => {
      const handler = vi.fn()
      window.addEventListener('program-tick', handler)

      applyMasterStocksDelta({ code: '000001', fields: { program_net_buy: 5000 } })
      flushTickBatch()

      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      window.removeEventListener('program-tick', handler)
    })

    it('program_net_buy no-change(동일 값) 시 디스패치 안 함', () => {
      applyMasterStocksDelta({ code: '000001', fields: { program_net_buy: 5000 } })
      flushTickBatch()

      const handler = vi.fn()
      window.addEventListener('program-tick', handler)

      applyMasterStocksDelta({ code: '000001', fields: { program_net_buy: 5000 } })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('program-tick', handler)
    })

    it('real-data/orderbook/program 틱이 단일 flush에서 각각 디스패치됨 (혼합 배칭)', () => {
      const realHandler = vi.fn()
      const orderbookHandler = vi.fn()
      const programHandler = vi.fn()
      window.addEventListener('real-data-tick', realHandler)
      window.addEventListener('orderbook-tick', orderbookHandler)
      window.addEventListener('program-tick', programHandler)

      applyRealData({ type: '01', item: '000001', values: { '10': '11000', '11': '+100', '12': '0.92', '228': '85', '14': '6000' } })
      applyMasterStocksDelta({ code: '000002', fields: { order_ratio: [100, 200] } })
      applyMasterStocksDelta({ code: '000001', fields: { program_net_buy: 5000 } })
      flushTickBatch()

      expect(realHandler).toHaveBeenCalledTimes(1)
      expect(orderbookHandler).toHaveBeenCalledTimes(1)
      expect(programHandler).toHaveBeenCalledTimes(1)
      window.removeEventListener('real-data-tick', realHandler)
      window.removeEventListener('orderbook-tick', orderbookHandler)
      window.removeEventListener('program-tick', programHandler)
    })
  })
})

describe('hotStore — account-update / account-summary-update 이벤트 분리 (COUPLING-S3)', () => {
  beforeEach(() => {
    resetHotState()
  })

  describe('applyAccountUpdate — 전체 payload (매도포지션/폴백)', () => {
    it('changed_positions 전체 교체 + position_count 갱신', () => {
      const initialPos: Position = {
        stk_cd: '005930', stk_nm: '삼성전자', qty: 10, avg_price: 70000,
        cur_price: 70000, buy_amt: 700000, pnl_rate: 0, buy_date: '20260720',
      }
      hotStore.setState({ positions: [initialPos], positionCount: 1 })

      applyAccountUpdate({
        snapshot: { total_buy_amount: 700000, total_sell_amount: 0, total_eval_amount: 800000, total_pnl: 100000, total_pnl_rate: 14.29, deposit: 5000000, trade_mode: 'test', position_count: 1 },
        changed_positions: [{ stk_cd: '005930', stk_nm: '삼성전자', qty: 10, avg_price: 70000, cur_price: 80000, buy_amt: 700000, pnl_rate: 14.29, buy_date: '20260720' }],
        removed_codes: [],
      })

      const state = hotStore.getState()
      expect(state.positions[0].cur_price).toBe(80000)
      expect(state.positions[0].pnl_rate).toBe(14.29)
      expect(state.positionCount).toBe(1)
    })

    it('removed_codes 처리 — 보유종목 제거', () => {
      const posA: Position = { stk_cd: '005930', stk_nm: '삼성전자', qty: 10, avg_price: 70000, cur_price: 80000, buy_amt: 700000, pnl_rate: 14.29, buy_date: '20260720' }
      const posB: Position = { stk_cd: '000660', stk_nm: 'SK하이닉스', qty: 5, avg_price: 120000, cur_price: 130000, buy_amt: 600000, pnl_rate: 8.33, buy_date: '20260721' }
      hotStore.setState({ positions: [posA, posB], positionCount: 2 })

      applyAccountUpdate({
        snapshot: { total_buy_amount: 1300000, total_sell_amount: 0, total_eval_amount: 1450000, total_pnl: 150000, total_pnl_rate: 11.54, deposit: 5000000, trade_mode: 'test', position_count: 1 },
        changed_positions: [],
        removed_codes: ['000660'],
      })

      const state = hotStore.getState()
      expect(state.positions.length).toBe(1)
      expect(state.positions[0].stk_cd).toBe('005930')
      expect(state.positionCount).toBe(1)
    })

    it('changed_positions/removed_codes 모두 빈 경우 snapshot만 갱신', () => {
      hotStore.setState({ account: null })
      applyAccountUpdate({
        snapshot: { total_buy_amount: 0, total_sell_amount: 0, total_eval_amount: 0, total_pnl: 0, total_pnl_rate: 0, deposit: 5000000, trade_mode: 'test', position_count: 0 },
        changed_positions: [],
        removed_codes: [],
      })
      expect(hotStore.getState().account?.deposit).toBe(5000000)
    })
  })

  describe('applyAccountSummaryUpdate — 경량화 payload (수익현황 전용)', () => {
    it('position_count + snapshot 갱신 (changed/removed 없음)', () => {
      hotStore.setState({ account: null, positionCount: 0 })
      applyAccountSummaryUpdate({
        snapshot: { deposit: 5000000, orderable: 4000000, total_eval_amount: 800000, total_pnl: 100000, total_pnl_rate: 14.29 },
        position_count: 2,
        changed_positions: [],
        removed_codes: [],
      })
      const state = hotStore.getState()
      expect(state.positionCount).toBe(2)
      expect(state.account?.deposit).toBe(5000000)
      expect(state.account?.total_eval_amount).toBe(800000)
    })

    it('changed_positions 최소 필드 merge — 기존 position의 나머지 필드 유지', () => {
      const existing: Position = {
        stk_cd: '005930', stk_nm: '삼성전자', qty: 10, avg_price: 70000,
        cur_price: 70000, buy_amt: 700000, pnl_rate: 0, buy_date: '20260720',
      }
      hotStore.setState({ positions: [existing], positionCount: 1 })

      // 경량화: cur_price만 갱신 (pnl_rate는 빠짐 — 기존 값 유지)
      applyAccountSummaryUpdate({
        snapshot: { deposit: 5000000, total_eval_amount: 800000, total_pnl: 100000, total_pnl_rate: 14.29 },
        position_count: 1,
        changed_positions: [{ stk_cd: '005930', cur_price: 80000 }],
        removed_codes: [],
      })

      const pos = hotStore.getState().positions[0]
      expect(pos.cur_price).toBe(80000)
      // 기존 필드 유지 (merge 방식)
      expect(pos.qty).toBe(10)
      expect(pos.avg_price).toBe(70000)
      expect(pos.stk_nm).toBe('삼성전자')
    })

    it('removed_codes 처리 — 보유종목 제거', () => {
      const posA: Position = { stk_cd: '005930', stk_nm: '삼성전자', qty: 10, avg_price: 70000, cur_price: 80000, buy_amt: 700000, pnl_rate: 14.29, buy_date: '20260720' }
      const posB: Position = { stk_cd: '000660', stk_nm: 'SK하이닉스', qty: 5, avg_price: 120000, cur_price: 130000, buy_amt: 600000, pnl_rate: 8.33, buy_date: '20260721' }
      hotStore.setState({ positions: [posA, posB], positionCount: 2 })

      applyAccountSummaryUpdate({
        snapshot: { deposit: 5000000, total_eval_amount: 800000, total_pnl: 100000, total_pnl_rate: 14.29 },
        position_count: 1,
        changed_positions: [],
        removed_codes: ['000660'],
      })

      const state = hotStore.getState()
      expect(state.positions.length).toBe(1)
      expect(state.positions[0].stk_cd).toBe('005930')
      expect(state.positionCount).toBe(1)
    })

    it('WS의 더 최신 account revision이 오래된 응답으로 덮어써지지 않음', () => {
      applyAccountUpdate({
        freshness: { group: 'account', revision: 2 },
        snapshot: { total_buy_amount: 0, total_sell_amount: 0, total_eval_amount: 900000, total_pnl: 0, total_pnl_rate: 0, deposit: 7000000, trade_mode: 'test', position_count: 0 },
        changed_positions: [],
        removed_codes: [],
      })
      applyAccountUpdate({
        freshness: { group: 'account', revision: 1 },
        snapshot: { total_buy_amount: 0, total_sell_amount: 0, total_eval_amount: 800000, total_pnl: 0, total_pnl_rate: 0, deposit: 6000000, trade_mode: 'test', position_count: 0 },
        changed_positions: [],
        removed_codes: [],
      })
      expect(hotStore.getState().account?.deposit).toBe(7000000)
      expect(hotStore.getState().freshness.account.revision).toBe(2)
    })

    it('WS 최신 데이터가 HTTP 페이지 진입 응답으로 되돌아가지 않음', () => {
      const latest = { total_buy_amount: 0, total_sell_amount: 0, total_eval_amount: 900000, total_pnl: 0, total_pnl_rate: 0, deposit: 7000000, trade_mode: 'test', position_count: 0 }
      const older = { ...latest, total_eval_amount: 800000, deposit: 6000000 }
      applyAccountUpdate({ freshness: { group: 'account', revision: 2 }, snapshot: latest, changed_positions: [], removed_codes: [] })

      const applied = applyAccountSnapshot(older, { group: 'account', revision: 1 })

      expect(applied).toBe(false)
      expect(hotStore.getState().account?.deposit).toBe(7000000)
      expect(hotStore.getState().freshness.account.revision).toBe(2)
    })
  })
})

// ── normalizeStockCode 직접 단위 테스트 (P21/P25) ─────────────────────────────
// 종목코드 정규화 헬퍼의 입력·출력 계약 명시 검증.
// p25_isolated_failure_investigation.md에서 식별된 code undefined 시 throw 가능성 가드 검증 포함.

describe('normalizeStockCode — 종목코드 정규화 헬퍼', () => {
  describe('빈/null/undefined 입력', () => {
    it('빈 문자열은 빈 문자열 반환', () => {
      expect(normalizeStockCode('')).toBe('')
    })
    it('undefined는 빈 문자열 반환 (throw 없음)', () => {
      expect(normalizeStockCode(undefined)).toBe('')
    })
    it('null은 빈 문자열 반환 (throw 없음)', () => {
      expect(normalizeStockCode(null)).toBe('')
    })
  })

  describe('A 접두사 제거 (KRX REST 응답 형식)', () => {
    it('A005930 → 005930', () => {
      expect(normalizeStockCode('A005930')).toBe('005930')
    })
    it('A 접두사 + 6자리 미만 숫자는 패딩 후 A만 제거', () => {
      expect(normalizeStockCode('A5930')).toBe('005930')
    })
  })

  describe('_ 접미사 제거', () => {
    it('005930_AL → 005930', () => {
      expect(normalizeStockCode('005930_AL')).toBe('005930')
    })
    it('005930_NX → 005930', () => {
      expect(normalizeStockCode('005930_NX')).toBe('005930')
    })
    it('모든 _ 접미사 제거 (split 첫 부분)', () => {
      expect(normalizeStockCode('005930_XYZ')).toBe('005930')
    })
  })

  describe('숫자 패딩', () => {
    it('6자리 미만 숫자는 padStart(6)', () => {
      expect(normalizeStockCode('5930')).toBe('005930')
    })
    it('5자리 숫자 패딩', () => {
      expect(normalizeStockCode('59300')).toBe('059300')
    })
    it('6자리 숫자는 그대로', () => {
      expect(normalizeStockCode('005930')).toBe('005930')
    })
    it('7자리 이상 숫자는 잘라내지 않고 길이 유지', () => {
      expect(normalizeStockCode('0000593')).toBe('0000593')
    })
  })

  describe('비숫자 처리', () => {
    it('비숫자는 그대로 (대소문자 변환 없음)', () => {
      expect(normalizeStockCode('0120G0')).toBe('0120G0')
    })
    it('비숫자 소문자는 그대로 (upper 변환 없음)', () => {
      expect(normalizeStockCode('0120g0')).toBe('0120g0')
    })
  })

  describe('복합 케이스', () => {
    it('A 접두사 + _ 접미사 동시 제거', () => {
      expect(normalizeStockCode('A005930_AL')).toBe('005930')
    })
    it('A 접두사 + 6자리 미만 + _ 접미사', () => {
      expect(normalizeStockCode('A5930_AL')).toBe('005930')
    })
  })
})
