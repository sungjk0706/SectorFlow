/**
 * Property 15: WS 재연결 스냅샷 적용 테스트
 *
 * Feature: hts-level-optimization, Property 15: 재연결 시 스냅샷 정합성
 *
 * **Validates: Requirements 8.3**
 *
 * For any arbitrary snapshot data, after applyInitialSnapshot is called,
 * the AppStore state SHALL match the snapshot data exactly,
 * and the backfilling flag SHALL be set to false.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import * as fc from 'fast-check'
import {
  appStore,
  applyInitialSnapshot,
  setBackfilling,
  getBuyTargetIndex,
  getPositionIndex,
} from './appStore'
import type {
  AccountSnapshot,
  Position,
  SectorStock,
  SectorScoreRow,
  SectorStatus,
  BuyTarget,
  SnapshotHistory,
} from '../types'

/* ── Generators ── */

const accountSnapshotArb: fc.Arbitrary<AccountSnapshot> = fc.record({
  total_buy_amount: fc.integer({ min: 0, max: 100000000 }),
  total_sell_amount: fc.integer({ min: 0, max: 100000000 }),
  total_eval_amount: fc.integer({ min: 0, max: 100000000 }),
  total_pnl: fc.integer({ min: -50000000, max: 50000000 }),
  total_pnl_rate: fc.float({ min: -100, max: 1000, noNaN: true }),
  deposit: fc.integer({ min: 0, max: 100000000 }),
  trade_mode: fc.constantFrom('real', 'test'),
})

const positionArb: fc.Arbitrary<Position> = fc.record({
  stk_cd: fc.stringMatching(/^[0-9]{6}$/),
  stk_nm: fc.string({ minLength: 1, maxLength: 10 }),
  qty: fc.integer({ min: 0, max: 10000 }),
  buy_amt: fc.integer({ min: 0, max: 100000000 }),
  cur_price: fc.integer({ min: 100, max: 1000000 }),
  pnl_rate: fc.float({ min: -100, max: 1000, noNaN: true }),
})

const sectorStockArb: fc.Arbitrary<SectorStock> = fc.record({
  code: fc.stringMatching(/^[0-9]{6}$/),
  name: fc.string({ minLength: 1, maxLength: 10 }),
  cur_price: fc.integer({ min: 100, max: 1000000 }),
  change_rate: fc.float({ min: -30, max: 30, noNaN: true }),
  trade_amount: fc.integer({ min: 0, max: 10000000000 }),
  sector: fc.string({ minLength: 1, maxLength: 5 }),
  change: fc.integer({ min: -10000, max: 10000 }),
  strength: fc.float({ min: 0, max: 200, noNaN: true }),
})

const sectorScoreRowArb: fc.Arbitrary<SectorScoreRow> = fc.record({
  rank: fc.integer({ min: 1, max: 50 }),
  sector: fc.string({ minLength: 1, maxLength: 5 }),
  final_score: fc.float({ min: 0, max: 100, noNaN: true }),
  total_trade_amount: fc.integer({ min: 0, max: 10000000000 }),
  rise_ratio: fc.float({ min: 0, max: 100, noNaN: true }),
  total: fc.integer({ min: 1, max: 100 }),
})

const sectorStatusArb: fc.Arbitrary<SectorStatus> = fc.record({
  total_stocks: fc.integer({ min: 0, max: 1000 }),
  max_targets: fc.integer({ min: 0, max: 50 }),
})

const buyTargetArb: fc.Arbitrary<BuyTarget> = fc.record({
  rank: fc.integer({ min: 1, max: 999 }),
  name: fc.string({ minLength: 1, maxLength: 10 }),
  code: fc.stringMatching(/^[0-9]{6}$/),
  sector: fc.string({ minLength: 1, maxLength: 5 }),
  change: fc.integer({ min: -10000, max: 10000 }),
  change_rate: fc.float({ min: -30, max: 30, noNaN: true }),
  cur_price: fc.integer({ min: 100, max: 1000000 }),
  strength: fc.float({ min: 0, max: 200, noNaN: true }),
  trade_amount: fc.integer({ min: 0, max: 10000000000 }),
  boost_score: fc.integer({ min: 0, max: 100 }),
  order_ratio: fc.constant(null),
  guard_pass: fc.boolean(),
  reason: fc.string({ maxLength: 20 }),
})

const snapshotHistoryArb: fc.Arbitrary<SnapshotHistory> = fc.record({
  timestamp: fc.string({ minLength: 10, maxLength: 20 }),
  total_buy_amount: fc.integer({ min: 0, max: 100000000 }),
  total_eval_amount: fc.integer({ min: 0, max: 100000000 }),
  total_pnl: fc.integer({ min: -50000000, max: 50000000 }),
  total_pnl_rate: fc.float({ min: -100, max: 1000, noNaN: true }),
})

/** Generator: full snapshot data payload (as received from server) */
const snapshotDataArb: fc.Arbitrary<Record<string, unknown>> = fc
  .tuple(
    accountSnapshotArb,
    fc.uniqueArray(positionArb, { selector: (p) => p.stk_cd, minLength: 0, maxLength: 20 }),
    fc.uniqueArray(sectorStockArb, { selector: (s) => s.code, minLength: 0, maxLength: 30 }),
    fc.array(sectorScoreRowArb, { minLength: 0, maxLength: 10 }),
    sectorStatusArb,
    fc.uniqueArray(buyTargetArb, { selector: (b) => b.code, minLength: 0, maxLength: 20 }),
    fc.array(snapshotHistoryArb, { minLength: 0, maxLength: 5 }),
  )
  .map(([account, positions, sectorStocks, sectorScores, sectorStatus, buyTargets, snapshotHistory]) => ({
    _v: 1,
    account,
    positions,
    sector_stocks: sectorStocks,
    sector_scores: sectorScores,
    sector_status: sectorStatus,
    buy_targets: buyTargets,
    snapshot_history: snapshotHistory,
    sell_history: [] as Record<string, unknown>[],
    buy_history: [] as Record<string, unknown>[],
    daily_summary: [] as Record<string, unknown>[],
    buy_limit_status: { daily_buy_spent: 0 },
    ws_subscribe_status: { index_subscribed: false, quote_subscribed: false },
    settings: null,
    status: null,
    sector_summary: null,
    bootstrap_done: true,
    market_phase: { krx: 'open', nxt: 'open' },
  }))

describe('Property 15: WS 재연결 스냅샷 적용 (재연결 시 스냅샷 정합성)', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    appStore.setState({
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
      backfilling: true,
      avgAmtProgress: null,
      bootstrapStage: null,
      selectedSector: null,
      marketPhase: { krx: 'closed', nxt: 'closed' },
    })
  })

  it('applyInitialSnapshot: store state matches snapshot data exactly after application', () => {
    /**
     * **Validates: Requirements 8.3**
     *
     * For any arbitrary snapshot data, after applyInitialSnapshot:
     * - positions matches snapshot positions
     * - buyTargets matches snapshot buy_targets
     * - account matches snapshot account
     * - sectorStocks is built from snapshot sector_stocks
     * - sectorScores matches snapshot sector_scores
     * - backfilling is set to false
     * - initialized is set to true
     */
    fc.assert(
      fc.property(snapshotDataArb, (snapshotData) => {
        // Pre-condition: set backfilling to true (simulating reconnection state)
        setBackfilling(true)
        expect(appStore.getState().backfilling).toBe(true)

        // Apply snapshot
        applyInitialSnapshot(snapshotData)

        const state = appStore.getState()

        // 1. backfilling flag is set to false
        expect(state.backfilling).toBe(false)

        // 2. initialized is set to true
        expect(state.initialized).toBe(true)

        // 3. account matches
        const expectedAccount = snapshotData.account as AccountSnapshot
        expect(state.account).toEqual(expectedAccount)

        // 4. positions match
        const expectedPositions = snapshotData.positions as Position[]
        expect(state.positions).toEqual(expectedPositions)

        // 5. buyTargets match
        const expectedBuyTargets = snapshotData.buy_targets as BuyTarget[]
        expect(state.buyTargets).toEqual(expectedBuyTargets)

        // 6. sectorStocks: verify all stocks from snapshot are present
        const expectedStocks = snapshotData.sector_stocks as SectorStock[]
        for (const stock of expectedStocks) {
          expect(state.sectorStocks[stock.code]).toEqual(stock)
        }
        expect(Object.keys(state.sectorStocks).length).toBe(expectedStocks.length)

        // 7. sectorScores match
        const expectedScores = snapshotData.sector_scores as SectorScoreRow[]
        expect(state.sectorScores).toEqual(expectedScores)

        // 8. sectorOrder derived from scores
        expect(state.sectorOrder).toEqual(expectedScores.map(s => s.sector))

        // 9. Index caches are consistent with new data
        for (let i = 0; i < expectedBuyTargets.length; i++) {
          expect(getBuyTargetIndex(expectedBuyTargets[i].code)).toBe(i)
        }
        for (let i = 0; i < expectedPositions.length; i++) {
          expect(getPositionIndex(expectedPositions[i].stk_cd)).toBe(i)
        }

        // 10. snapshotHistory matches
        expect(state.snapshotHistory).toEqual(snapshotData.snapshot_history)

        // 11. engineReady is true (bootstrap_done is true)
        expect(state.engineReady).toBe(true)

        // 12. marketPhase matches
        expect(state.marketPhase).toEqual(snapshotData.market_phase)
      }),
      { numRuns: 100 },
    )
  })

  it('applyInitialSnapshot replaces previous state completely on reconnection', () => {
    /**
     * **Validates: Requirements 8.3**
     *
     * Simulates a reconnection scenario: store has stale data,
     * then a new snapshot arrives and completely replaces it.
     */
    fc.assert(
      fc.property(snapshotDataArb, snapshotDataArb, (staleSnapshot, freshSnapshot) => {
        // Apply stale data first (simulating pre-disconnect state)
        applyInitialSnapshot(staleSnapshot)

        // Simulate reconnection: set backfilling
        setBackfilling(true)

        // Apply fresh snapshot (simulating post-reconnect snapshot)
        applyInitialSnapshot(freshSnapshot)

        const state = appStore.getState()

        // State should reflect the FRESH snapshot, not the stale one
        expect(state.backfilling).toBe(false)
        expect(state.positions).toEqual(freshSnapshot.positions)
        expect(state.buyTargets).toEqual(freshSnapshot.buy_targets)
        expect(state.account).toEqual(freshSnapshot.account)

        const freshStocks = freshSnapshot.sector_stocks as SectorStock[]
        expect(Object.keys(state.sectorStocks).length).toBe(freshStocks.length)
        for (const stock of freshStocks) {
          expect(state.sectorStocks[stock.code]).toEqual(stock)
        }
      }),
      { numRuns: 100 },
    )
  })
})
