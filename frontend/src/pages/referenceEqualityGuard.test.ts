/**
 * Property 1: Reference Equality Guard (상태 참조 미변경 시 갱신 생략)
 *
 * Feature: hts-level-optimization, Property 1: Reference Equality Guard
 *
 * **Validates: Requirements 1.1, 1.2, 2.2, 12.1, 12.3**
 *
 * For any sequence of store state changes where the monitored field reference
 * (positions, buyTargets, etc.) remains identical (`===`), the page's DOM
 * update logic (updateRows, sort, etc.) SHALL NOT be invoked.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import * as fc from 'fast-check'
import { createStore, type StoreApi } from '../stores/store'
import type { AppState } from '../stores/appStore'
import type { Position, BuyTarget } from '../types'

/**
 * We test the reference equality guard pattern in isolation by simulating
 * the subscription logic used in sell-position.ts, buy-target.ts, and
 * profit-overview.ts. This avoids DOM dependencies while validating the
 * core property: if the monitored reference doesn't change, the update
 * function is never called.
 */

/* ── Minimal AppState for testing ── */
function createMinimalState(overrides?: Partial<AppState>): AppState {
  return {
    account: null,
    positions: [],
    sectorStocks: {},
    sectorOrder: [],
    sectorScores: [],
    sectorStatus: null,
    sectorSummary: null,
    buyTargets: [],
    settings: null,
    status: null,
    snapshotHistory: [],
    sellHistory: [],
    buyHistory: [],
    dailySummary: [],
    buyLimitStatus: { daily_buy_spent: 0 },
    wsSubscribeStatus: { index_subscribed: false, quote_subscribed: false },
    connected: false,
    initialized: false,
    engineReady: false,
    backfilling: false,
    avgAmtProgress: null,
    bootstrapStage: null,
    selectedSector: null,
    marketPhase: { krx: 'closed', nxt: 'closed' },
    ...overrides,
  }
}

/* ── Generators ── */

/** Generator: arbitrary "unrelated" state field changes that do NOT touch positions or buyTargets references */
const unrelatedFieldChangeArb: fc.Arbitrary<Partial<AppState>> = fc.oneof(
  fc.record({ connected: fc.boolean() }),
  fc.record({ initialized: fc.boolean() }),
  fc.record({ engineReady: fc.boolean() }),
  fc.record({ backfilling: fc.boolean() }),
  fc.record({ selectedSector: fc.option(fc.string({ minLength: 1, maxLength: 5 }), { nil: null }) }),
  fc.record({ buyLimitStatus: fc.record({ daily_buy_spent: fc.integer({ min: 0, max: 10000000 }) }) }),
  fc.record({ wsSubscribeStatus: fc.record({ index_subscribed: fc.boolean(), quote_subscribed: fc.boolean() }) }),
  fc.record({ marketPhase: fc.record({ krx: fc.constantFrom('closed', 'pre', 'regular', 'after'), nxt: fc.constantFrom('closed', 'pre', 'main', 'after') }) }),
)

/** Generator: sequence of N unrelated state changes */
const stateChangeSequenceArb = (minLen: number, maxLen: number) =>
  fc.array(unrelatedFieldChangeArb, { minLength: minLen, maxLength: maxLen })

describe('Property 1: Reference Equality Guard (상태 참조 미변경 시 갱신 생략)', () => {
  let store: StoreApi<AppState>
  let mockRaf: (cb: FrameRequestCallback) => number
  let rafCallbacks: FrameRequestCallback[]

  beforeEach(() => {
    rafCallbacks = []
    // Mock requestAnimationFrame to capture callbacks
    mockRaf = vi.fn((cb: FrameRequestCallback) => {
      rafCallbacks.push(cb)
      return rafCallbacks.length
    })
    vi.stubGlobal('requestAnimationFrame', mockRaf)
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sell-position pattern: positions reference unchanged → updateRows NOT called', () => {
    /**
     * **Validates: Requirements 1.1, 1.2, 12.1, 12.3**
     *
     * Simulates the sell-position.ts subscription pattern:
     * - Tracks prevPositions reference
     * - Only schedules rAF when positions reference changes
     * - If positions reference stays the same, updateRows is never called
     */
    fc.assert(
      fc.property(
        stateChangeSequenceArb(1, 50),
        (changes) => {
          // Create a fresh store for each test run
          const positions: Position[] = [
            { stk_cd: '005930', stk_nm: '삼성전자', qty: 100, buy_amt: 7000000, cur_price: 72000, pnl_rate: 2.86 },
          ]
          store = createStore<AppState>(createMinimalState({ positions }))

          const updateRows = vi.fn()
          let prevPositions = store.getState().positions

          // Subscribe with the same pattern as sell-position.ts
          store.subscribe((state) => {
            const positionsChanged = state.positions !== prevPositions
            prevPositions = state.positions

            if (!positionsChanged) return

            // Would schedule rAF → updateRows
            updateRows(state.positions)
          })

          // Apply all state changes (none of which change positions reference)
          for (const change of changes) {
            store.setState(change)
          }

          // positions reference never changed → updateRows never called
          expect(updateRows).not.toHaveBeenCalled()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('buy-target pattern: buyTargets reference unchanged → sort + updateRows NOT called', () => {
    /**
     * **Validates: Requirements 2.2, 12.1, 12.3**
     *
     * Simulates the buy-target.ts subscription pattern:
     * - Tracks lastRenderedBuyTargets reference
     * - Only schedules rAF when buyTargets reference changes
     * - If buyTargets reference stays the same, sort + updateRows is never called
     */
    fc.assert(
      fc.property(
        stateChangeSequenceArb(1, 50),
        (changes) => {
          const buyTargets: BuyTarget[] = [
            { rank: 1, name: '삼성전자', code: '005930', sector: 'IT', change: 1000, change_rate: 1.41, cur_price: 72000, strength: 120, trade_amount: 5000000000, boost_score: 0, order_ratio: null, guard_pass: true, reason: '' },
          ]
          store = createStore<AppState>(createMinimalState({ buyTargets }))

          const sortAndUpdateRows = vi.fn()
          let lastRenderedBuyTargets = store.getState().buyTargets

          // Subscribe with the same pattern as buy-target.ts
          store.subscribe((state) => {
            const buyTargetsChanged = state.buyTargets !== lastRenderedBuyTargets

            if (!buyTargetsChanged) return

            lastRenderedBuyTargets = state.buyTargets
            sortAndUpdateRows(state.buyTargets)
          })

          // Apply all state changes (none of which change buyTargets reference)
          for (const change of changes) {
            store.setState(change)
          }

          // buyTargets reference never changed → sort + updateRows never called
          expect(sortAndUpdateRows).not.toHaveBeenCalled()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('profit-overview pattern: positions/account/history/dailySummary references unchanged → DOM update NOT called', () => {
    /**
     * **Validates: Requirements 1.1, 12.1, 12.3**
     *
     * Simulates the profit-overview.ts subscription pattern:
     * - Tracks multiple field group references (account, positions, sellHistory, buyHistory, dailySummary)
     * - Only marks dirty flags when specific references change
     * - If none of the monitored references change, no DOM update is scheduled
     */
    fc.assert(
      fc.property(
        // Generate changes that only touch fields NOT monitored by profit-overview
        fc.array(
          fc.oneof(
            fc.record({ connected: fc.boolean() }),
            fc.record({ initialized: fc.boolean() }),
            fc.record({ engineReady: fc.boolean() }),
            fc.record({ backfilling: fc.boolean() }),
            fc.record({ selectedSector: fc.option(fc.string({ minLength: 1, maxLength: 5 }), { nil: null }) }),
            fc.record({ buyLimitStatus: fc.record({ daily_buy_spent: fc.integer({ min: 0, max: 10000000 }) }) }),
            fc.record({ wsSubscribeStatus: fc.record({ index_subscribed: fc.boolean(), quote_subscribed: fc.boolean() }) }),
            fc.record({ marketPhase: fc.record({ krx: fc.constantFrom('closed', 'pre', 'regular', 'after'), nxt: fc.constantFrom('closed', 'pre', 'main', 'after') }) }),
            // buyTargets changes are also unrelated to profit-overview
            fc.record({ sectorOrder: fc.array(fc.string({ minLength: 1, maxLength: 5 }), { maxLength: 5 }) }),
          ),
          { minLength: 1, maxLength: 50 },
        ),
        (changes) => {
          const positions: Position[] = [
            { stk_cd: '005930', stk_nm: '삼성전자', qty: 100, buy_amt: 7000000, cur_price: 72000, pnl_rate: 2.86 },
          ]
          store = createStore<AppState>(createMinimalState({
            positions,
            account: { total_buy_amount: 7000000, total_sell_amount: 0, total_eval_amount: 7200000, total_pnl: 200000, total_pnl_rate: 2.86, deposit: 10000000, trade_mode: 'test' },
            sellHistory: [{ date: '2026-04-14', stk_nm: '삼성전자', realized_pnl: 100000 }],
            buyHistory: [{ date: '2026-04-14', stk_nm: '삼성전자', total_amt: 7000000 }],
            dailySummary: [{ date: '2026-04-14', sell_count: 1, realized_pnl: 100000, pnl_rate: 1.43 }],
          }))

          const renderAccountVals = vi.fn()
          const showTable = vi.fn()
          const updateChart = vi.fn()

          let prevAccountRef = store.getState().account
          let prevPositionsRef = store.getState().positions
          let prevSellRef = store.getState().sellHistory
          let prevBuyRef = store.getState().buyHistory
          let prevDailySummaryRef = store.getState().dailySummary

          // Subscribe with the same pattern as profit-overview.ts
          store.subscribe((curr) => {
            const accountChanged = curr.account !== prevAccountRef || curr.positions !== prevPositionsRef
            const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
            const chartChanged = curr.dailySummary !== prevDailySummaryRef

            if (!accountChanged && !historyChanged && !chartChanged) return

            if (accountChanged) {
              prevAccountRef = curr.account
              prevPositionsRef = curr.positions
              renderAccountVals()
            }
            if (historyChanged) {
              prevSellRef = curr.sellHistory
              prevBuyRef = curr.buyHistory
              showTable()
            }
            if (chartChanged) {
              prevDailySummaryRef = curr.dailySummary
              updateChart()
            }
          })

          // Apply all state changes (none of which change monitored references)
          for (const change of changes) {
            store.setState(change)
          }

          // No monitored references changed → no DOM update functions called
          expect(renderAccountVals).not.toHaveBeenCalled()
          expect(showTable).not.toHaveBeenCalled()
          expect(updateChart).not.toHaveBeenCalled()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('mixed pages: same reference across arbitrary number of setState calls → zero DOM updates', () => {
    /**
     * **Validates: Requirements 1.1, 1.2, 2.2, 12.1, 12.3**
     *
     * Comprehensive test: for any N setState calls that preserve all monitored
     * references (positions, buyTargets, account, sellHistory, buyHistory,
     * dailySummary), ALL page update functions remain uncalled.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        stateChangeSequenceArb(1, 100),
        (_n, changes) => {
          const positions: Position[] = [
            { stk_cd: '005930', stk_nm: '삼성전자', qty: 100, buy_amt: 7000000, cur_price: 72000, pnl_rate: 2.86 },
          ]
          const buyTargets: BuyTarget[] = [
            { rank: 1, name: '삼성전자', code: '005930', sector: 'IT', change: 1000, change_rate: 1.41, cur_price: 72000, strength: 120, trade_amount: 5000000000, boost_score: 0, order_ratio: null, guard_pass: true, reason: '' },
          ]
          store = createStore<AppState>(createMinimalState({ positions, buyTargets }))

          const sellPositionUpdate = vi.fn()
          const buyTargetUpdate = vi.fn()

          // sell-position guard
          let prevPositions = store.getState().positions
          store.subscribe((state) => {
            if (state.positions !== prevPositions) {
              prevPositions = state.positions
              sellPositionUpdate()
            }
          })

          // buy-target guard
          let lastBuyTargets = store.getState().buyTargets
          store.subscribe((state) => {
            if (state.buyTargets !== lastBuyTargets) {
              lastBuyTargets = state.buyTargets
              buyTargetUpdate()
            }
          })

          // Apply all state changes
          for (const change of changes) {
            store.setState(change)
          }

          expect(sellPositionUpdate).not.toHaveBeenCalled()
          expect(buyTargetUpdate).not.toHaveBeenCalled()
        },
      ),
      { numRuns: 100 },
    )
  })
})
