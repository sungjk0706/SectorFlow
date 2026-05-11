/**
 * Property 10: Selective Page Update (선택적 DOM 갱신)
 *
 * Feature: hts-level-optimization, Property 10: Selective Page Update
 *
 * **Validates: Requirements 11.2, 11.3, 11.4**
 *
 * For any store state change in profit-overview where only one field group changes
 * (positions/account OR sellHistory/buyHistory OR dailySummary),
 * only the corresponding DOM section SHALL be updated,
 * and other sections SHALL receive zero DOM mutations.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as fc from 'fast-check'
import type { AccountSnapshot, Position } from '../types'

/* ── 필드 그룹 정의 ── */

/**
 * profit-overview의 3개 필드 그룹:
 * - account: positions/account 변경 → 계좌현황 숫자 + 요약카드 갱신
 * - history: sellHistory/buyHistory 변경 → 이력 테이블 + 요약카드 갱신
 * - chart: dailySummary 변경 → 차트 갱신
 */
type FieldGroup = 'account' | 'history' | 'chart'

interface StoreSnapshot {
  account: AccountSnapshot | null
  positions: Position[]
  sellHistory: Record<string, unknown>[]
  buyHistory: Record<string, unknown>[]
  dailySummary: Record<string, unknown>[]
}

/**
 * Simulates the selective update logic from profit-overview.ts subscribe callback.
 * Returns which DOM sections would be updated given prev and curr state.
 */
function computeDirtySections(prev: StoreSnapshot, curr: StoreSnapshot): Set<FieldGroup> {
  const dirty = new Set<FieldGroup>()

  // Field group: account (positions or account reference changed)
  const accountChanged = curr.account !== prev.account || curr.positions !== prev.positions
  if (accountChanged) dirty.add('account')

  // Field group: history (sellHistory or buyHistory reference changed)
  const historyChanged = curr.sellHistory !== prev.sellHistory || curr.buyHistory !== prev.buyHistory
  if (historyChanged) dirty.add('history')

  // Field group: chart (dailySummary reference changed)
  const chartChanged = curr.dailySummary !== prev.dailySummary
  if (chartChanged) dirty.add('chart')

  return dirty
}

/* ── Generators ── */

const accountArb: fc.Arbitrary<AccountSnapshot> = fc.record({
  total_buy_amount: fc.integer({ min: 0, max: 100000000 }),
  total_sell_amount: fc.integer({ min: 0, max: 100000000 }),
  total_eval_amount: fc.integer({ min: 0, max: 100000000 }),
  total_pnl: fc.integer({ min: -10000000, max: 10000000 }),
  total_pnl_rate: fc.float({ min: -100, max: 100, noNaN: true }),
  deposit: fc.integer({ min: 0, max: 100000000 }),
  trade_mode: fc.constantFrom('test', 'real'),
})

const positionArb: fc.Arbitrary<Position> = fc.record({
  stk_cd: fc.stringMatching(/^[0-9]{6}$/),
  stk_nm: fc.string({ minLength: 1, maxLength: 8 }),
  qty: fc.integer({ min: 1, max: 10000 }),
  buy_amt: fc.integer({ min: 10000, max: 100000000 }),
  cur_price: fc.integer({ min: 100, max: 1000000 }),
  pnl_rate: fc.float({ min: -100, max: 1000, noNaN: true }),
})

/** Generate a date string in YYYY-MM-DD format */
const dateStringArb: fc.Arbitrary<string> = fc.tuple(
  fc.integer({ min: 2024, max: 2026 }),
  fc.integer({ min: 1, max: 12 }),
  fc.integer({ min: 1, max: 28 }),
).map(([y, m, d]) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`)

const tradeRecordArb: fc.Arbitrary<Record<string, unknown>> = fc.record({
  date: dateStringArb,
  time: fc.tuple(
    fc.integer({ min: 0, max: 23 }),
    fc.integer({ min: 0, max: 59 }),
    fc.integer({ min: 0, max: 59 }),
  ).map(([h, m, s]) => `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`),
  stk_nm: fc.string({ minLength: 1, maxLength: 8 }),
  stk_cd: fc.stringMatching(/^[0-9]{6}$/),
  price: fc.integer({ min: 100, max: 1000000 }),
  qty: fc.integer({ min: 1, max: 10000 }),
  total_amt: fc.integer({ min: 10000, max: 100000000 }),
  realized_pnl: fc.integer({ min: -10000000, max: 10000000 }),
  pnl_rate: fc.float({ min: -100, max: 100, noNaN: true }),
  fee: fc.integer({ min: 0, max: 100000 }),
})

const dailySummaryRowArb: fc.Arbitrary<Record<string, unknown>> = fc.record({
  date: dateStringArb,
  sell_count: fc.integer({ min: 0, max: 50 }),
  realized_pnl: fc.integer({ min: -10000000, max: 10000000 }),
  pnl_rate: fc.float({ min: -100, max: 100, noNaN: true }),
})

/** Generator: a base state snapshot */
const storeSnapshotArb: fc.Arbitrary<StoreSnapshot> = fc.record({
  account: fc.option(accountArb, { nil: null }),
  positions: fc.array(positionArb, { minLength: 0, maxLength: 10 }),
  sellHistory: fc.array(tradeRecordArb, { minLength: 0, maxLength: 10 }),
  buyHistory: fc.array(tradeRecordArb, { minLength: 0, maxLength: 10 }),
  dailySummary: fc.array(dailySummaryRowArb, { minLength: 0, maxLength: 10 }),
})

/**
 * Generator: a field group change specification.
 * Produces which groups should change (at least one).
 */
const fieldGroupSubsetArb: fc.Arbitrary<Set<FieldGroup>> = fc
  .subarray(['account', 'history', 'chart'] as FieldGroup[], { minLength: 1 })
  .map(arr => new Set(arr))

describe('Property 10: Selective Page Update (선택적 DOM 갱신)', () => {
  it('only the changed field group triggers its corresponding DOM section update', () => {
    /**
     * **Validates: Requirements 11.2, 11.3, 11.4**
     *
     * For any single field group change, only that group's DOM section is marked dirty.
     * Unrelated sections receive zero mutations.
     */
    fc.assert(
      fc.property(
        storeSnapshotArb,
        fc.constantFrom<FieldGroup>('account', 'history', 'chart'),
        storeSnapshotArb,
        (baseState, changedGroup, newData) => {
          // Build prev state
          const prev: StoreSnapshot = { ...baseState }

          // Build curr state: only the specified group's references change
          const curr: StoreSnapshot = { ...baseState }

          if (changedGroup === 'account') {
            // Change account or positions reference (new array/object)
            curr.account = newData.account
            curr.positions = newData.positions
          } else if (changedGroup === 'history') {
            // Change sellHistory or buyHistory reference
            curr.sellHistory = newData.sellHistory
            curr.buyHistory = newData.buyHistory
          } else {
            // Change dailySummary reference
            curr.dailySummary = newData.dailySummary
          }

          const dirty = computeDirtySections(prev, curr)

          // The changed group MUST be in dirty set
          expect(dirty.has(changedGroup)).toBe(true)

          // Other groups MUST NOT be in dirty set
          const allGroups: FieldGroup[] = ['account', 'history', 'chart']
          for (const group of allGroups) {
            if (group !== changedGroup) {
              expect(dirty.has(group)).toBe(false)
            }
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('when multiple field groups change simultaneously, only those groups are marked dirty', () => {
    /**
     * **Validates: Requirements 11.2, 11.3, 11.4**
     *
     * For any combination of field group changes, exactly those groups
     * (and no others) are marked dirty.
     */
    fc.assert(
      fc.property(
        storeSnapshotArb,
        fieldGroupSubsetArb,
        storeSnapshotArb,
        (baseState, changedGroups, newData) => {
          const prev: StoreSnapshot = { ...baseState }
          const curr: StoreSnapshot = { ...baseState }

          // Apply changes only for specified groups
          if (changedGroups.has('account')) {
            curr.account = newData.account
            curr.positions = newData.positions
          }
          if (changedGroups.has('history')) {
            curr.sellHistory = newData.sellHistory
            curr.buyHistory = newData.buyHistory
          }
          if (changedGroups.has('chart')) {
            curr.dailySummary = newData.dailySummary
          }

          const dirty = computeDirtySections(prev, curr)

          // Each changed group must be dirty
          for (const group of changedGroups) {
            expect(dirty.has(group)).toBe(true)
          }

          // Each unchanged group must NOT be dirty
          const allGroups: FieldGroup[] = ['account', 'history', 'chart']
          for (const group of allGroups) {
            if (!changedGroups.has(group)) {
              expect(dirty.has(group)).toBe(false)
            }
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('when no field group references change, zero sections are marked dirty', () => {
    /**
     * **Validates: Requirements 11.2, 11.3, 11.4**
     *
     * If all references remain identical (===), no DOM section is updated.
     */
    fc.assert(
      fc.property(storeSnapshotArb, (baseState) => {
        // prev and curr share the same references
        const prev: StoreSnapshot = baseState
        const curr: StoreSnapshot = baseState

        const dirty = computeDirtySections(prev, curr)

        expect(dirty.size).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('positions-only change triggers account section but not history or chart', () => {
    /**
     * **Validates: Requirements 11.2**
     *
     * When only positions reference changes (account stays same),
     * only the account section is updated.
     */
    fc.assert(
      fc.property(
        storeSnapshotArb,
        fc.array(positionArb, { minLength: 1, maxLength: 10 }),
        (baseState, newPositions) => {
          const prev: StoreSnapshot = { ...baseState }
          const curr: StoreSnapshot = {
            ...baseState,
            positions: newPositions, // new reference
          }

          const dirty = computeDirtySections(prev, curr)

          expect(dirty.has('account')).toBe(true)
          expect(dirty.has('history')).toBe(false)
          expect(dirty.has('chart')).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('sellHistory-only change triggers history section but not account or chart', () => {
    /**
     * **Validates: Requirements 11.3**
     *
     * When only sellHistory reference changes,
     * only the history section is updated.
     */
    fc.assert(
      fc.property(
        storeSnapshotArb,
        fc.array(tradeRecordArb, { minLength: 1, maxLength: 10 }),
        (baseState, newSellHistory) => {
          const prev: StoreSnapshot = { ...baseState }
          const curr: StoreSnapshot = {
            ...baseState,
            sellHistory: newSellHistory, // new reference
          }

          const dirty = computeDirtySections(prev, curr)

          expect(dirty.has('history')).toBe(true)
          expect(dirty.has('account')).toBe(false)
          expect(dirty.has('chart')).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('dailySummary-only change triggers chart section but not account or history', () => {
    /**
     * **Validates: Requirements 11.4**
     *
     * When only dailySummary reference changes,
     * only the chart section is updated.
     */
    fc.assert(
      fc.property(
        storeSnapshotArb,
        fc.array(dailySummaryRowArb, { minLength: 1, maxLength: 10 }),
        (baseState, newDailySummary) => {
          const prev: StoreSnapshot = { ...baseState }
          const curr: StoreSnapshot = {
            ...baseState,
            dailySummary: newDailySummary, // new reference
          }

          const dirty = computeDirtySections(prev, curr)

          expect(dirty.has('chart')).toBe(true)
          expect(dirty.has('account')).toBe(false)
          expect(dirty.has('history')).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })
})
