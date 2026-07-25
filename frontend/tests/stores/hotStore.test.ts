import { describe, it, expect, beforeEach } from 'vitest'
import {
  hotStore,
  applySectorStocksRefresh,
  applyRealtimeReset,
  applyRealData,
  rebuildBuyTargetIndex,
  type HotState,
} from '../../src/stores/hotStore'
import type { SectorStock, RealDataEvent } from '../../src/types'

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
