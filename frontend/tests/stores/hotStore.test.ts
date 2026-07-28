import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  hotStore,
  applySectorStocksRefresh,
  applySectorStocksDelta,
  applyBuyTargetsUpdate,
  applyBuyTargetsDelta,
  applyNewsHit,
  applyRealtimeReset,
  applyRealData,
  applyOrderbookUpdate,
  applyProgramUpdate,
  applyAccountUpdate,
  applyAccountSummaryUpdate,
  flushTickBatch,
  rebuildBuyTargetIndex,
  normalizeStockCode,
  type HotState,
} from '../../src/stores/hotStore'
import type { SectorStock, RealDataEvent, Position } from '../../src/types'

/** 테스트용 초기 상태 — buyTargets와 sectorStocks에 동일 종목이 실시간 필드 포함 */
function makeInitialHotState(): HotState {
  const stockA: SectorStock = {
    code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
    trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true, reason: '',
  }
  const stockB: SectorStock = {
    code: '000002', name: '종목B', cur_price: 20000, change: -200, change_rate: -0.9,
    trade_amount: 3000, strength: 60, sector: '업종2', rank: 2, guard_pass: true, reason: '',
  }
  const sectorStocks: Record<string, SectorStock> = {
    '000001': { ...stockA },
    '000002': { ...stockB },
  }
  const buyTargets = [{ ...stockA }, { ...stockB }]
  rebuildBuyTargetIndex(buyTargets)
  return {
    account: null,
    positions: [],
    positionCount: 0,
    sectorStocks,
    sectorScores: [],
    buyTargets,
    sellHistory: [],
    buyHistory: [],
    dailySummary: [],
  }
}

function resetHotState(): void {
  const initial = makeInitialHotState()
  hotStore.setState(initial)
}

describe('hotStore — sectorStocks ↔ buyTargets 실시간 필드 정합성 (세션 3)', () => {
  beforeEach(() => {
    resetHotState()
  })

  describe('applySectorStocksRefresh', () => {
    it('sectorStocks 교체 후 buyTargets 실시간 필드가 새 sectorStocks와 일치', () => {
      // 새로고침: 종목A의 실시간 값이 변경된 새 목록 수신
      const refreshedStockA: SectorStock = {
        code: '000001', name: '종목A', cur_price: 15000, change: 500, change_rate: 3.5,
        trade_amount: 9999, strength: 95, sector: '업종1',
      }
      const refreshedStockB: SectorStock = {
        code: '000002', name: '종목B', cur_price: 21000, change: 100, change_rate: 0.5,
        trade_amount: 8888, strength: 70, sector: '업종2',
      }
      applySectorStocksRefresh({ stocks: [refreshedStockA, refreshedStockB] })

      const state = hotStore.getState()
      const btA = state.buyTargets.find(t => t.code === '000001')!
      const btB = state.buyTargets.find(t => t.code === '000002')!

      // buyTargets 실시간 필드가 새 sectorStocks 기준으로 재결합되었는지 검증
      expect(btA.cur_price).toBe(15000)
      expect(btA.change).toBe(500)
      expect(btA.change_rate).toBe(3.5)
      expect(btA.trade_amount).toBe(9999)
      expect(btA.strength).toBe(95)

      expect(btB.cur_price).toBe(21000)
      expect(btB.change).toBe(100)
      expect(btB.change_rate).toBe(0.5)
      expect(btB.trade_amount).toBe(8888)
      expect(btB.strength).toBe(70)

      // 정적 필드는 유지 (rank, guard_pass, reason)
      expect(btA.rank).toBe(1)
      expect(btA.guard_pass).toBe(true)
      expect(btA.reason).toBe('')
    })

    it('sectorStocks에 없는 buyTargets 종목은 실시간 필드가 변경되지 않음', () => {
      // 새로고침: 종목A만 포함 (종목B는 sectorStocks에서 제거됨)
      const refreshedStockA: SectorStock = {
        code: '000001', name: '종목A', cur_price: 15000, change: 500, change_rate: 3.5,
        trade_amount: 9999, strength: 95, sector: '업종1',
      }
      applySectorStocksRefresh({ stocks: [refreshedStockA] })

      const state = hotStore.getState()
      const btB = state.buyTargets.find(t => t.code === '000002')!

      // 종목B는 sectorStocks에 없으므로 실시간 필드 유지 (in-place mutation 미발생)
      expect(btB.cur_price).toBe(20000)
      expect(btB.change).toBe(-200)
    })
  })

  describe('applyRealtimeReset', () => {
    it('reset 후 sectorStocks와 buyTargets 실시간 필드 모두 null', () => {
      applyRealtimeReset()

      const state = hotStore.getState()

      // sectorStocks 실시간 필드 null 검증
      const ssA = state.sectorStocks['000001']!
      expect(ssA.cur_price).toBeNull()
      expect(ssA.change).toBeNull()
      expect(ssA.change_rate).toBeNull()
      expect(ssA.trade_amount).toBeNull()
      expect(ssA.strength).toBeNull()

      // buyTargets 실시간 필드 null 검증 (파생 캐시 동기화)
      const btA = state.buyTargets.find(t => t.code === '000001')!
      expect(btA.cur_price).toBeNull()
      expect(btA.change).toBeNull()
      expect(btA.change_rate).toBeNull()
      expect(btA.trade_amount).toBeNull()
      expect(btA.strength).toBeNull()

      // 정적 필드는 유지
      expect(btA.rank).toBe(1)
      expect(btA.guard_pass).toBe(true)
      expect(btA.name).toBe('종목A')
    })
  })

  describe('applyRealData', () => {
    it('real-data 틱 후 sectorStocks와 buyTargets 실시간 필드가 일치', () => {
      // 키움 01 체결 이벤트 — 종목A의 새 가격
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
      const ssA = state.sectorStocks['000001']!
      const btA = state.buyTargets.find(t => t.code === '000001')!

      // sectorStocks(SSOT) 갱신 검증
      expect(ssA.cur_price).toBe(12000)
      expect(ssA.change).toBe(200)
      expect(ssA.change_rate).toBe(1.67)
      expect(ssA.strength).toBe(85)
      expect(ssA.trade_amount).toBe(7000)

      // buyTargets(파생 캐시) 동기화 검증
      expect(btA.cur_price).toBe(ssA.cur_price)
      expect(btA.change).toBe(ssA.change)
      expect(btA.change_rate).toBe(ssA.change_rate)
      expect(btA.strength).toBe(ssA.strength)
      expect(btA.trade_amount).toBe(ssA.trade_amount)
    })

    it('buyTargets에 없는 종목은 sectorStocks만 갱신', () => {
      // 종목C는 sectorStocks에만 있고 buyTargets에 없는 상태로 설정
      hotStore.setState((state) => ({
        sectorStocks: {
          ...state.sectorStocks,
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
      const ssC = state.sectorStocks['000003']!
      expect(ssC.cur_price).toBe(35000)

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

  describe('applySectorStocksDelta', () => {
    it('added 종목이 buyTargets에 있으면 실시간 필드가 새 sectorStocks 기준으로 재결합', () => {
      // 종목A의 실시간 값이 변경된 added 수신 (기존 10000 → 18000)
      const addedStockA: SectorStock = {
        code: '000001', name: '종목A', cur_price: 18000, change: 800, change_rate: 4.6,
        trade_amount: 12345, strength: 99, sector: '업종1',
      }
      applySectorStocksDelta({ added: [addedStockA], removed: [] })

      const state = hotStore.getState()
      const ssA = state.sectorStocks['000001']!
      const btA = state.buyTargets.find(t => t.code === '000001')!

      // sectorStocks 갱신
      expect(ssA.cur_price).toBe(18000)
      expect(ssA.trade_amount).toBe(12345)
      // buyTargets 실시간 필드 재결합
      expect(btA.cur_price).toBe(18000)
      expect(btA.change).toBe(800)
      expect(btA.change_rate).toBe(4.6)
      expect(btA.trade_amount).toBe(12345)
      expect(btA.strength).toBe(99)
      // 정적 필드 유지
      expect(btA.rank).toBe(1)
      expect(btA.name).toBe('종목A')
    })

    it('removed 종목이 buyTargets에 있어도 buyTargets에서 제거되지 않음 (buy-targets-delta가 담당)', () => {
      // 종목A가 sectorStocks에서 제거됨
      applySectorStocksDelta({ added: [], removed: ['000001'] })

      const state = hotStore.getState()
      // sectorStocks에서는 제거
      expect(state.sectorStocks['000001']).toBeUndefined()
      // buyTargets에는 유지 (제거는 buy-targets-delta 이벤트가 담당)
      const btA = state.buyTargets.find(t => t.code === '000001')
      expect(btA).toBeDefined()
    })

    it('added/removed 모두 없으면 상태 변경 없음', () => {
      const prev = hotStore.getState()
      applySectorStocksDelta({ added: [], removed: [] })
      expect(hotStore.getState()).toBe(prev)
    })
  })

  describe('applyBuyTargetsUpdate', () => {
    it('incoming 실시간 필드가 sectorStocks와 불일치 시 sectorStocks 기준으로 재결합', () => {
      // sectorStocks: 종목A cur_price=10000 (초기 상태)
      // 백엔드 buy-targets-update가 stale cur_price=9000 전송 (조회 시점 차이)
      const incoming: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 9000, change: -100, change_rate: -1.0,
          trade_amount: 1000, strength: 50, sector: '업종1', rank: 1, guard_pass: true, reason: '',
        },
        {
          code: '000002', name: '종목B', cur_price: 19000, change: -100, change_rate: -0.5,
          trade_amount: 2000, strength: 55, sector: '업종2', rank: 2, guard_pass: true, reason: '',
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: incoming })

      const state = hotStore.getState()
      const ssA = state.sectorStocks['000001']!
      const btA = state.buyTargets.find(t => t.code === '000001')!

      // sectorStocks는 변경되지 않음 (SSOT)
      expect(ssA.cur_price).toBe(10000)
      // buyTargets는 sectorStocks 기준으로 재결합 (stale 9000이 아닌 10000)
      expect(btA.cur_price).toBe(ssA.cur_price)
      expect(btA.change).toBe(ssA.change)
      expect(btA.change_rate).toBe(ssA.change_rate)
      expect(btA.trade_amount).toBe(ssA.trade_amount)
      expect(btA.strength).toBe(ssA.strength)
    })

    it('sectorStocks에 없는 종목은 incoming 실시간 필드 유지', () => {
      // 종목D는 sectorStocks에 없고 buy-targets-update에만 포함
      const incoming: SectorStock[] = [
        {
          code: '000004', name: '종목D', cur_price: 50000, change: 500, change_rate: 1.0,
          trade_amount: 9999, strength: 70, sector: '업종3', rank: 1, guard_pass: true, reason: '',
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: incoming })

      const state = hotStore.getState()
      const btD = state.buyTargets.find(t => t.code === '000004')!
      // sectorStocks에 없으므로 incoming 값 유지
      expect(btD.cur_price).toBe(50000)
      expect(btD.trade_amount).toBe(9999)
    })
  })

  // ── same 비교 키 백엔드 _BUY_TARGET_CMP_KEYS 일치 검증 ──────────────
  // same 키: 정적 필드만 (rank, boost_score, guard_pass, reason, order_ratio,
  //          program_net_buy, high_5d, avg_amt_5d) + 식별자 (code, name)
  // 실시간 필드(cur_price/change/change_rate/strength/trade_amount)는 same 비교 제외 —
  // 틱 디스패치가 별도 갱신 담당, 매 틱마다 setState 트리거 방지.
  // news_boost 제외 (세션 3 — news-hit 이벤트가 단일 갱신 경로, P10 SSOT).
  describe('applyBuyTargetsUpdate — same 비교 키 (백엔드 cmp_keys 일치)', () => {
    it('실시간 필드만 변경 시 setState 미발화 (same=true)', () => {
      // 초기 buyTargets 설정 (정적 필드 포함)
      const initial: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
          trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0.0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })
      const stateBefore = hotStore.getState()
      const prevTargetsRef = stateBefore.buyTargets

      // 동일 정적 필드 + 실시간 필드만 변경 (cur_price 10000 → 11000)
      const updated: SectorStock[] = [
        {
          ...initial[0],
          cur_price: 11000, change: 200, change_rate: 2.0, trade_amount: 6000, strength: 85,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const stateAfter = hotStore.getState()
      // same=true → buyTargets 배열 참조 동일 (setState 미발화)
      expect(stateAfter.buyTargets).toBe(prevTargetsRef)
    })

    it('avg_amt_5d 변경 시 setState 발화 (same=false)', () => {
      const initial: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
          trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0.0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })

      // avg_amt_5d 변경 (4000 → 5000)
      const updated: SectorStock[] = [{ ...initial[0], avg_amt_5d: 5000 }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets[0].avg_amt_5d).toBe(5000)
    })

    it('news_boost 변경 시 setState 미발화 (same=true, news-hit 단일 경로 — 세션 3)', () => {
      // news_boost는 news-hit 이벤트가 단일 갱신 경로 (P10 SSOT).
      // applyBuyTargetsUpdate same 비교에서 제거 — news_boost만 변경된 incoming은 same=true로
      // 간주해 setState 미발화. news_boost 갱신은 applyNewsHit이 담당 (아래 describe 블록).
      const initial: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
          trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0.0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })
      const prevRef = hotStore.getState().buyTargets

      // news_boost만 변경 (0.0 → 1.5) — same=true, setState 미발화
      const updated: SectorStock[] = [{ ...initial[0], news_boost: 1.5 }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets).toBe(prevRef)            // 참조 동일 — setState 미발화
      expect(state.buyTargets[0].news_boost).toBe(0.0)  // news_boost 무시 (news-hit이 담당)
    })

    it('high_5d 변경 시 setState 발화 (same=false)', () => {
      const initial: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
          trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0.0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })

      // high_5d 변경 (12000 → 13000)
      const updated: SectorStock[] = [{ ...initial[0], high_5d: 13000 }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets[0].high_5d).toBe(13000)
    })

    it('order_ratio 변경 시 setState 발화 (same=false)', () => {
      const initial: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
          trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0.0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })

      // order_ratio 변경 ([100, 200] → [150, 250])
      const updated: SectorStock[] = [{ ...initial[0], order_ratio: [150, 250] }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets[0].order_ratio).toEqual([150, 250])
    })

    it('program_net_buy 변경 시 setState 발화 (same=false)', () => {
      const initial: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 10000, change: 100, change_rate: 1.0,
          trade_amount: 5000, strength: 80, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0.0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: initial })

      // program_net_buy 변경 (null → 5000000)
      const updated: SectorStock[] = [{ ...initial[0], program_net_buy: 5000000 }]
      applyBuyTargetsUpdate({ buy_targets: updated })

      const state = hotStore.getState()
      expect(state.buyTargets[0].program_net_buy).toBe(5000000)
    })
  })

  // ── 세션 4 — news_boost_title 보존 (P22 데이터 정합성) ──
  // news_boost_title은 백엔드 스냅샷에 없음 (news-hit 이벤트가 단일 소스).
  // 전체 새로고침(buy-targets-update) 시 prev에서 보존 — news_boost > 0일 때만.
  describe('applyBuyTargetsUpdate — news_boost_title 보존 (세션 4, P22)', () => {
    it('news_boost > 0 시 prev의 news_boost_title 보존 (전체 새로고침 후에도 툴팁 유지)', () => {
      // 1. applyNewsHit으로 news_boost + title 설정
      applyNewsHit({ codes: ['000001'], scores: [1.5], title: 'A기업 수주 계약' })
      expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('A기업 수주 계약')

      // 2. 전체 새로고침 — 백엔드 스냅샷은 news_boost 포함하지만 title 미포함
      const refreshed: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 11000, change: 200, change_rate: 2.0,
          trade_amount: 6000, strength: 85, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 1.5,
          order_ratio: [100, 200], program_net_buy: null,
        },
        {
          code: '000002', name: '종목B', cur_price: 20000, change: -200, change_rate: -0.9,
          trade_amount: 3000, strength: 60, sector: '업종2', rank: 2, guard_pass: true,
          reason: '', boost_score: 3.0, high_5d: 22000, avg_amt_5d: 5000, news_boost: 0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: refreshed })

      // 3. news_boost > 0 → title 보존됨
      expect(hotStore.getState().buyTargets[0].news_boost).toBe(1.5)
      expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('A기업 수주 계약')
    })

    it('news_boost = 0 시 news_boost_title 소멸 (뉴스 만료 일관성, P22)', () => {
      // 1. applyNewsHit으로 news_boost + title 설정
      applyNewsHit({ codes: ['000001'], scores: [1.5], title: 'A기업 수주 계약' })

      // 2. 전체 새로고침 — news_boost 0 (뉴스 만료/TTL 경과)
      const refreshed: SectorStock[] = [
        {
          code: '000001', name: '종목A', cur_price: 11000, change: 200, change_rate: 2.0,
          trade_amount: 6000, strength: 85, sector: '업종1', rank: 1, guard_pass: true,
          reason: '', boost_score: 5.0, high_5d: 12000, avg_amt_5d: 4000, news_boost: 0,
          order_ratio: [100, 200], program_net_buy: null,
        },
      ]
      applyBuyTargetsUpdate({ buy_targets: refreshed })

      // 3. news_boost = 0 → title 소멸 (만료 일관성)
      expect(hotStore.getState().buyTargets[0].news_boost).toBe(0)
      expect(hotStore.getState().buyTargets[0].news_boost_title).toBeUndefined()
    })
  })
})

// ── COUPLING-S8 후속 — binding.ts 인라인 → action 추출 (P23/P24) ──────────────
describe('hotStore — applyBuyTargetsDelta (COUPLING-S8 후속)', () => {
  beforeEach(() => {
    resetHotState()
  })

  it('removed: 해당 종목을 buyTargets에서 제거', () => {
    applyBuyTargetsDelta({ removed: ['000001'] })
    const state = hotStore.getState()
    expect(state.buyTargets.find(t => t.code === '000001')).toBeUndefined()
    expect(state.buyTargets.find(t => t.code === '000002')).toBeDefined()
  })

  it('removed: 빈 배열/누락 시 buyTargets 변경 없음 (setState 미발화)', () => {
    const prev = hotStore.getState().buyTargets
    applyBuyTargetsDelta({ removed: [] })
    expect(hotStore.getState().buyTargets).toBe(prev)
    applyBuyTargetsDelta({})
    expect(hotStore.getState().buyTargets).toBe(prev)
  })

  it('changed: 기존 종목 정적 필드 교체 + 실시간 필드는 sectorStocks 기준 재결합', () => {
    // sectorStocks 종목A: cur_price=10000 (초기 상태)
    // 백엔드 changed가 stale cur_price=9000 전송 → sectorStocks 기준으로 10000 재결합
    const changed: SectorStock[] = [
      {
        code: '000001', name: '종목A-리네임', cur_price: 9000, change: -100, change_rate: -1.0,
        trade_amount: 1000, strength: 50, sector: '업종1', rank: 3, guard_pass: false, reason: 'r',
      },
    ]
    applyBuyTargetsDelta({ changed })

    const state = hotStore.getState()
    const btA = state.buyTargets.find(t => t.code === '000001')!
    const ssA = state.sectorStocks['000001']!
    // 정적 필드는 changed 값으로 교체
    expect(btA.name).toBe('종목A-리네임')
    expect(btA.rank).toBe(3)
    expect(btA.guard_pass).toBe(false)
    // 실시간 필드는 sectorStocks 기준 (stale 9000이 아닌 10000)
    expect(btA.cur_price).toBe(ssA.cur_price)
    expect(btA.change).toBe(ssA.change)
    expect(btA.change_rate).toBe(ssA.change_rate)
    expect(btA.trade_amount).toBe(ssA.trade_amount)
    expect(btA.strength).toBe(ssA.strength)
    // sectorStocks는 SSOT이므로 변경 없음
    expect(ssA.cur_price).toBe(10000)
  })

  it('changed: buyTargets에 없는 종목은 스킵 (추가되지 않음)', () => {
    const changed: SectorStock[] = [
      {
        code: '000999', name: '종목X', cur_price: 5000, change: 0, change_rate: 0,
        trade_amount: 0, strength: 0, sector: '업종X', rank: 9, guard_pass: true, reason: '',
      },
    ]
    const prevCount = hotStore.getState().buyTargets.length
    applyBuyTargetsDelta({ changed })
    // buyTargets에 없으므로 추가되지 않음 — 기존 종목 수 유지
    const after = hotStore.getState().buyTargets
    expect(after.length).toBe(prevCount)
    expect(after.find(t => t.code === '000999')).toBeUndefined()
    // 기존 종목은 변경 없음 (000001/000002 그대로)
    expect(after.find(t => t.code === '000001')!.name).toBe('종목A')
    expect(after.find(t => t.code === '000002')!.name).toBe('종목B')
  })

  it('added: 새 종목 추가 + 실시간 필드는 sectorStocks 기준 재결합', () => {
    // sectorStocks에 종목C 추가 (실시간 필드 포함)
    const stateBefore = hotStore.getState()
    const stockC: SectorStock = {
      code: '000003', name: '종목C', cur_price: 30000, change: 300, change_rate: 1.0,
      trade_amount: 7000, strength: 90, sector: '업종3', rank: 3, guard_pass: true, reason: '',
    }
    hotStore.setState({ sectorStocks: { ...stateBefore.sectorStocks, '000003': stockC } })

    // 백엔드 added가 stale cur_price=25000 전송 → sectorStocks 기준 30000 재결합
    const added: SectorStock[] = [
      {
        code: '000003', name: '종목C', cur_price: 25000, change: -300, change_rate: -1.0,
        trade_amount: 2000, strength: 30, sector: '업종3', rank: 3, guard_pass: true, reason: '',
      },
    ]
    applyBuyTargetsDelta({ added })

    const state = hotStore.getState()
    const btC = state.buyTargets.find(t => t.code === '000003')!
    expect(btC).toBeDefined()
    // 실시간 필드는 sectorStocks 기준 (stale 25000이 아닌 30000)
    expect(btC.cur_price).toBe(30000)
    expect(btC.change).toBe(300)
    expect(btC.change_rate).toBe(1.0)
    expect(btC.trade_amount).toBe(7000)
    expect(btC.strength).toBe(90)
  })

  it('added: sectorStocks에 없는 종목은 incoming 실시간 필드 유지 (applyBuyTargetsUpdate와 P23 일치)', () => {
    // COUPLING-S8 후속2 — applyBuyTargetsUpdate는 sectorStocks 누락 시 incoming 실시간 필드 유지.
    // applyBuyTargetsDelta도 동일 패턴으로 일치화 — undefined 덮어쓰기 제거 (P23 일관성).
    const added: SectorStock[] = [
      {
        code: '000005', name: '종목E', cur_price: 50000, change: 500, change_rate: 1.0,
        trade_amount: 9999, strength: 70, sector: '업종5', rank: 5, guard_pass: true, reason: '',
      },
    ]
    applyBuyTargetsDelta({ added })
    const btE = hotStore.getState().buyTargets.find(t => t.code === '000005')!
    // 정적 필드는 유지
    expect(btE.name).toBe('종목E')
    expect(btE.rank).toBe(5)
    expect(btE.sector).toBe('업종5')
    // 실시간 필드도 incoming 값 유지 (sectorStocks에 없으므로 incoming 그대로)
    expect(btE.cur_price).toBe(50000)
    expect(btE.change).toBe(500)
    expect(btE.change_rate).toBe(1.0)
    expect(btE.trade_amount).toBe(9999)
    expect(btE.strength).toBe(70)
  })

  it('changed: sectorStocks에 없는 종목은 incoming 실시간 필드 유지 (applyBuyTargetsUpdate와 P23 일치)', () => {
    // COUPLING-S8 후속2 — changed 케이스도 added와 동일하게 incoming 유지.
    // sectorStocks에 없는 종목의 changed 이벤트 수신 시 undefined 덮어쓰기 방지.
    // 먼저 buyTargets에 000001 추가 (초기 상태에 이미 있음 — 종목A)
    const changed: SectorStock[] = [
      {
        code: '000001', name: '종목A-리네임', cur_price: 9000, change: -100, change_rate: -1.0,
        trade_amount: 1000, strength: 50, sector: '업종1', rank: 3, guard_pass: false, reason: 'r',
      },
    ]
    // sectorStocks에서 000001 제거하여 누락 상태 시뮬레이션
    const stateBefore = hotStore.getState()
    const { ['000001']: _removed, ...remainingStocks } = stateBefore.sectorStocks
    hotStore.setState({ sectorStocks: remainingStocks })

    applyBuyTargetsDelta({ changed })

    const btA = hotStore.getState().buyTargets.find(t => t.code === '000001')!
    // 정적 필드는 changed 값으로 교체
    expect(btA.name).toBe('종목A-리네임')
    expect(btA.rank).toBe(3)
    expect(btA.guard_pass).toBe(false)
    // 실시간 필드도 incoming 값 유지 (sectorStocks에 없으므로 incoming 그대로)
    expect(btA.cur_price).toBe(9000)
    expect(btA.change).toBe(-100)
    expect(btA.change_rate).toBe(-1.0)
    expect(btA.trade_amount).toBe(1000)
    expect(btA.strength).toBe(50)
  })

  it('added/removed/changed 동시 적용 시 순서대로 처리 (removed → changed → added)', () => {
    // sectorStocks에 종목C 추가
    const stateBefore = hotStore.getState()
    const stockC: SectorStock = {
      code: '000003', name: '종목C', cur_price: 30000, change: 300, change_rate: 1.0,
      trade_amount: 7000, strength: 90, sector: '업종3', rank: 3, guard_pass: true, reason: '',
    }
    hotStore.setState({ sectorStocks: { ...stateBefore.sectorStocks, '000003': stockC } })

    applyBuyTargetsDelta({
      removed: ['000002'],
      changed: [
        {
          code: '000001', name: '종목A-리네임', cur_price: 9000, change: -100, change_rate: -1.0,
          trade_amount: 1000, strength: 50, sector: '업종1', rank: 5, guard_pass: false, reason: 'r',
        },
      ],
      added: [
        {
          code: '000003', name: '종목C', cur_price: 25000, change: -300, change_rate: -1.0,
          trade_amount: 2000, strength: 30, sector: '업종3', rank: 3, guard_pass: true, reason: '',
        },
      ],
    })

    const state = hotStore.getState()
    // removed: 000002 제거
    expect(state.buyTargets.find(t => t.code === '000002')).toBeUndefined()
    // changed: 000001 리네임 + sectorStocks 실시간 필드 재결합
    const btA = state.buyTargets.find(t => t.code === '000001')!
    expect(btA.name).toBe('종목A-리네임')
    expect(btA.cur_price).toBe(10000)
    // added: 000003 추가 + sectorStocks 실시간 필드 재결합
    const btC = state.buyTargets.find(t => t.code === '000003')!
    expect(btC.cur_price).toBe(30000)
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
})

// ── 세션 3 — news-hit 단일 갱신 경로 (P10 SSOT, P25 격리된 실패) ──────────────
describe('hotStore — applyNewsHit (news-hit 단일 갱신 경로, 세션 3)', () => {
  beforeEach(() => {
    resetHotState()
  })

  it('해당 종목의 news_boost만 patch (다른 필드 불변, 미해당 종목 불변)', () => {
    // 초기 buyTargets: 종목A(000001) news_boost=0.0, 종목B(000002) news_boost=undefined
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
    // 종목B: 미해당 — 불변 (참조 동일)
    expect(state.buyTargets[1]).toBe(prev[1])
    expect(state.buyTargets[1]).toEqual(prevB)
  })

  it('복수 종목 동시 갱신 — codes 순서대로 scores 매핑', () => {
    applyNewsHit({ codes: ['000001', '000002'], scores: [1.5, 2.0] })

    const state = hotStore.getState()
    expect(state.buyTargets[0].news_boost).toBe(1.5)
    expect(state.buyTargets[1].news_boost).toBe(2.0)
  })

  it('종목코드 정규화 — A 접두사/패딩 처리', () => {
    applyNewsHit({ codes: ['A000001'], scores: [1.5] })
    expect(hotStore.getState().buyTargets[0].news_boost).toBe(1.5)
  })

  it('buyTargets에 없는 종목은 무시 (다른 종목 정상 갱신)', () => {
    const prev = hotStore.getState().buyTargets
    applyNewsHit({ codes: ['999999', '000001'], scores: [9.9, 1.5] })

    const state = hotStore.getState()
    expect(state.buyTargets[0].news_boost).toBe(1.5)
    // buyTargets 길이 불변 — 999999 추가되지 않음
    expect(state.buyTargets.length).toBe(prev.length)
  })

  it('빈 codes 시 setState 미발화 (배열 참조 동일, P25)', () => {
    const prev = hotStore.getState().buyTargets
    applyNewsHit({ codes: [], scores: [] })
    expect(hotStore.getState().buyTargets).toBe(prev)
  })

  it('codes 누락 시 setState 미발화 (P20 명시적 빈 배열 처리)', () => {
    const prev = hotStore.getState().buyTargets
    applyNewsHit({} as { codes: string[]; scores: number[] })
    expect(hotStore.getState().buyTargets).toBe(prev)
  })

  it('scores 요소 부재 시 0으로 처리 (P20 명시적 값)', () => {
    applyNewsHit({ codes: ['000001'], scores: [] })
    expect(hotStore.getState().buyTargets[0].news_boost).toBe(0)
  })

  // ── 세션 4 — title 보관 (📰 툴팁 표시용, P21 투명성) ──
  it('title 보관 — buyTargets[i].news_boost_title에 저장 (세션 4)', () => {
    applyNewsHit({ codes: ['000001'], scores: [1.5], title: 'A기업 대규모 수주 계약 체결' })
    expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('A기업 대규모 수주 계약 체결')
  })

  it('title 누락 시 빈 문자열 보관 (P20 명시적 값)', () => {
    applyNewsHit({ codes: ['000001'], scores: [1.5] })
    expect(hotStore.getState().buyTargets[0].news_boost_title).toBe('')
  })

  it('복수 종목 동시 갱신 시 동일 title 적용 (단일 뉴스 = 단일 title)', () => {
    applyNewsHit({ codes: ['000001', '000002'], scores: [1.5, 2.0], title: '업종 호재 뉴스' })
    const state = hotStore.getState()
    expect(state.buyTargets[0].news_boost_title).toBe('업종 호재 뉴스')
    expect(state.buyTargets[1].news_boost_title).toBe('업종 호재 뉴스')
  })
})

describe('hotStore — applyRealData 갱신 계약 + rAF 배칭 (세션 7)', () => {
  beforeEach(() => {
    resetHotState()
    // rAF 스케줄러 pending 상태 리셋 + dirty Set 클리어
    flushTickBatch()
    // rAF 자동 실행 차단 — 테스트가 flushTickBatch()로 명시적으로 flush 제어
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1)
  })

  afterEach(() => {
    flushTickBatch()
    vi.restoreAllMocks()
  })

  describe('in-place mutation 계약 (subscribe 미발화)', () => {
    it('applyRealData 틱 후 hotStore.subscribe() 리스너 미발화', () => {
      const listener = vi.fn()
      const unsub = hotStore.subscribe(listener)

      const event: RealDataEvent = {
        type: '01',
        item: '000001',
        values: { '10': '15000', '11': '+100', '12': '0.67', '228': '90', '14': '8000' },
      }
      applyRealData(event)
      flushTickBatch()

      // 핵심 계약: in-place mutation은 setState를 호출하지 않으므로 subscribe 리스너 미발화
      expect(listener).not.toHaveBeenCalled()
      unsub()
    })

    it('applyOrderbookUpdate 후 hotStore.subscribe() 리스너 미발화', () => {
      const listener = vi.fn()
      const unsub = hotStore.subscribe(listener)

      applyOrderbookUpdate({ code: '000001', bid: 100, ask: 200 })
      flushTickBatch()

      expect(listener).not.toHaveBeenCalled()
      unsub()
    })

    it('applyProgramUpdate 후 hotStore.subscribe() 리스너 미발화', () => {
      const listener = vi.fn()
      const unsub = hotStore.subscribe(listener)

      applyProgramUpdate({ code: '000001', net_buy: 5000 })
      flushTickBatch()

      expect(listener).not.toHaveBeenCalled()
      unsub()
    })
  })

  describe('real-data-tick 디스패치 계약', () => {
    it('변경 시 real-data-tick 이벤트가 code payload로 디스패치됨', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      const event: RealDataEvent = {
        type: '01',
        item: '000001',
        values: { '10': '15000', '11': '+100', '12': '0.67', '228': '90', '14': '8000' },
      }
      applyRealData(event)
      // rAF 배칭 — flush 전에는 디스패치 안 됨
      expect(handler).not.toHaveBeenCalled()
      flushTickBatch()

      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      window.removeEventListener('real-data-tick', handler)
    })

    it('no-change 틱(동일 값) 시 디스패치 안 함', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      // 초기 상태: 종목A cur_price=10000, change=100, change_rate=1.0, strength=80, trade_amount=5000
      const sameEvent: RealDataEvent = {
        type: '01',
        item: '000001',
        values: { '10': '10000', '11': '+100', '12': '1.0', '228': '80', '14': '5000' },
      }
      applyRealData(sameEvent)
      flushTickBatch()

      // 값이 동일하므로 changed=false → 디스패치 안 함
      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('real-data-tick', handler)
    })

    it('미지원 type(0A) 시 디스패치 안 함 + 상태 미변경', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)
      const before = hotStore.getState().sectorStocks['000001']

      const unsupportedEvent: RealDataEvent = {
        type: '0A',  // 미지원 type
        item: '000001',
        values: { '10': '99999', '11': '+999', '12': '9.99', '228': '99', '14': '9999' },
      }
      applyRealData(unsupportedEvent)
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      const after = hotStore.getState().sectorStocks['000001']
      expect(after.cur_price).toBe(before.cur_price)
      expect(after.change).toBe(before.change)
      window.removeEventListener('real-data-tick', handler)
    })

    it('rawPrice 부재 시 디스패치 안 함', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      const noPriceEvent: RealDataEvent = {
        type: '01',
        item: '000001',
        values: { '11': '+100', '12': '0.67' },  // '10' 부재
      }
      applyRealData(noPriceEvent)
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('real-data-tick', handler)
    })
  })

  describe('rAF 배칭 계약 (coalescing / last-write-wins)', () => {
    it('여러 종목 틱이 단일 flush에서 모두 디스패치됨', () => {
      const handler = vi.fn()
      window.addEventListener('real-data-tick', handler)

      // 종목A, 종목B 틱을 연속 호출
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
      expect(hotStore.getState().sectorStocks['000001']!.cur_price).toBe(13000)
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

  describe('orderbook-tick / program-tick 디스패치 계약', () => {
    it('applyOrderbookUpdate 변경 시 orderbook-tick 디스패치', () => {
      const handler = vi.fn()
      window.addEventListener('orderbook-tick', handler)

      applyOrderbookUpdate({ code: '000001', bid: 100, ask: 200 })
      flushTickBatch()

      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      window.removeEventListener('orderbook-tick', handler)
    })

    it('applyOrderbookUpdate no-change(동일 bid/ask) 시 디스패치 안 함', () => {
      // 먼저 000001의 order_ratio를 [100, 200]으로 설정
      applyOrderbookUpdate({ code: '000001', bid: 100, ask: 200 })
      flushTickBatch()

      const handler = vi.fn()
      window.addEventListener('orderbook-tick', handler)

      // 동일 값 재호출
      applyOrderbookUpdate({ code: '000001', bid: 100, ask: 200 })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('orderbook-tick', handler)
    })

    it('applyOrderbookUpdate — buyTargets에 없는 종목은 스킵', () => {
      const handler = vi.fn()
      window.addEventListener('orderbook-tick', handler)

      // 종목C는 sectorStocks에만 있고 buyTargets에 없음
      hotStore.setState((state) => ({
        sectorStocks: {
          ...state.sectorStocks,
          '000003': { code: '000003', name: '종목C', cur_price: 30000, change: 0, change_rate: 0 },
        },
      }))

      applyOrderbookUpdate({ code: '000003', bid: 100, ask: 200 })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('orderbook-tick', handler)
    })

    it('applyProgramUpdate 변경 시 program-tick 디스패치', () => {
      const handler = vi.fn()
      window.addEventListener('program-tick', handler)

      applyProgramUpdate({ code: '000001', net_buy: 5000 })
      flushTickBatch()

      expect(handler).toHaveBeenCalledTimes(1)
      expect((handler.mock.calls[0][0] as CustomEvent<string>).detail).toBe('000001')
      window.removeEventListener('program-tick', handler)
    })

    it('applyProgramUpdate no-change(동일 net_buy) 시 디스패치 안 함', () => {
      applyProgramUpdate({ code: '000001', net_buy: 5000 })
      flushTickBatch()

      const handler = vi.fn()
      window.addEventListener('program-tick', handler)

      applyProgramUpdate({ code: '000001', net_buy: 5000 })
      flushTickBatch()

      expect(handler).not.toHaveBeenCalled()
      window.removeEventListener('program-tick', handler)
    })

    it('applyProgramUpdate — buyTargets에 없는 종목은 스킵', () => {
      const handler = vi.fn()
      window.addEventListener('program-tick', handler)

      hotStore.setState((state) => ({
        sectorStocks: {
          ...state.sectorStocks,
          '000003': { code: '000003', name: '종목C', cur_price: 30000, change: 0, change_rate: 0 },
        },
      }))

      applyProgramUpdate({ code: '000003', net_buy: 9999 })
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
      applyOrderbookUpdate({ code: '000002', bid: 100, ask: 200 })
      applyProgramUpdate({ code: '000001', net_buy: 5000 })
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
