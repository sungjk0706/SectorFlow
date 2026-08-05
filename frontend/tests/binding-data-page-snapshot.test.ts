import { describe, it, expect, beforeEach, vi } from 'vitest'
import { bindWSToStore } from '../src/binding'
import { hotStore } from '../src/stores/hotStore'
import { uiStore } from '../src/stores/uiStore'
import { stockClassificationStore } from '../src/stores/stockClassificationStore'

/**
 * 3세션 — 자료 중심 화면 초기 스냅샷 이벤트 수신 검증.
 * binding.ts가 profit-detail-snapshot, stock-classification-snapshot, settings-snapshot 이벤트를
 * 받아 기존 변경 이벤트 apply 함수로 store에 적용하는지 확인 (P10 SSOT, P24 단순성).
 * - profit-detail-snapshot → buyHistory/sellHistory/dailySummary store 갱신
 * - stock-classification-snapshot → stockClassificationStore 갱신
 * - settings-snapshot → uiStore.settings 갱신
 */

function createMockWSClient() {
  const handlers = new Map<string, ((data: unknown) => void)[]>()
  return {
    setConnectionCallbacks: vi.fn(),
    onEvent: vi.fn((type: string, handler: (data: unknown) => void) => {
      const list = handlers.get(type) ?? []
      list.push(handler)
      handlers.set(type, list)
    }),
    offEvent: vi.fn(),
    send: vi.fn(),
    isConnected: vi.fn(() => false),
    disconnect: vi.fn(),
    emit(type: string, data: unknown) {
      const list = handlers.get(type) ?? []
      for (const h of list) h(data)
    },
  }
}

describe('binding — 자료 중심 화면 초기 스냅샷 수신', () => {
  let prices: ReturnType<typeof createMockWSClient>
  let settings: ReturnType<typeof createMockWSClient>
  let orders: ReturnType<typeof createMockWSClient>

  beforeEach(() => {
    hotStore.setState({ buyHistory: [], sellHistory: [], dailySummary: [] })
    stockClassificationStore.setState({
      sectors: {}, stockMoves: {}, mergedSectors: [], noSectorCount: 0, allStocks: [],
    })
    uiStore.setState({ settings: { trade_mode: 'test' } as any })
    prices = createMockWSClient()
    settings = createMockWSClient()
    orders = createMockWSClient()
    bindWSToStore(prices as any, settings as any, orders as any)
  })

  it('profit-detail-snapshot 수신 시 buyHistory/sellHistory/dailySummary 갱신', () => {
    prices.emit('profit-detail-snapshot', {
      page: 'profit-detail',
      data: {
        buy_history: [{ code: 'A', price: 100 }],
        sell_history: [{ code: 'A', price: 110 }],
        daily_summary: [{ date: '2026-08-01' }],
      },
    })
    const state = hotStore.getState()
    expect(state.buyHistory).toHaveLength(1)
    expect(state.buyHistory[0]).toMatchObject({ code: 'A', price: 100 })
    expect(state.sellHistory).toHaveLength(1)
    expect(state.dailySummary).toHaveLength(1)
  })

  it('stock-classification-snapshot 수신 시 stockClassificationStore 갱신', () => {
    prices.emit('stock-classification-snapshot', {
      page: 'stock-classification',
      data: {
        custom_data: { sectors: { 'A': '반도체' }, stock_moves: {} },
        merged_sectors: ['반도체'],
        no_sector_count: 3,
        filter_summary: '필터',
        all_stocks: [{ code: 'A', name: '종목A', sector: '반도체' }],
      },
    })
    const state = stockClassificationStore.getState()
    expect(state.sectors).toEqual({ 'A': '반도체' })
    expect(state.mergedSectors).toEqual(['반도체'])
    expect(state.noSectorCount).toBe(3)
    expect(state.allStocks).toHaveLength(1)
  })

  it('settings-snapshot 수신 시 uiStore.settings 갱신', () => {
    settings.emit('settings-snapshot', {
      page: 'settings',
      data: { trade_mode: 'live', broker_app_key: '***' },
    })
    const state = uiStore.getState()
    expect(state.settings).toMatchObject({ trade_mode: 'live', broker_app_key: '***' })
  })
})
