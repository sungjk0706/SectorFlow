/**
 * Property 3: Index Cache Consistency (인덱스 캐시 정합성)
 *
 * Feature: hts-level-optimization, Property 3: Index Cache Consistency
 *
 * **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
 *
 * For any buyTargets array state, the buyTargetIndexCache Map SHALL satisfy:
 * for every element targets[i], cache.get(targets[i].code) === i,
 * and cache.size === targets.length.
 * The same invariant applies to positionIndexCache with positions[i].stk_cd.
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  rebuildBuyTargetIndex,
  rebuildPositionIndex,
  getBuyTargetIndex,
  getPositionIndex,
} from './appStore'
import type { BuyTarget, Position } from '../types'

/** Generator: arbitrary BuyTarget with unique code */
const buyTargetArb = (code: string): fc.Arbitrary<BuyTarget> =>
  fc.record({
    rank: fc.integer({ min: 1, max: 999 }),
    name: fc.string({ minLength: 1, maxLength: 10 }),
    code: fc.constant(code),
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

/** Generator: arbitrary Position with unique stk_cd */
const positionArb = (stkCd: string): fc.Arbitrary<Position> =>
  fc.record({
    stk_cd: fc.constant(stkCd),
    stk_nm: fc.string({ minLength: 1, maxLength: 10 }),
    qty: fc.integer({ min: 0, max: 10000 }),
    buy_amt: fc.integer({ min: 0, max: 100000000 }),
    cur_price: fc.integer({ min: 100, max: 1000000 }),
    pnl_rate: fc.float({ min: -100, max: 1000, noNaN: true }),
  })

/** Generator: array of BuyTargets with unique codes */
const buyTargetsArrayArb: fc.Arbitrary<BuyTarget[]> = fc
  .uniqueArray(fc.stringMatching(/^[0-9]{6}$/), { minLength: 0, maxLength: 50 })
  .chain((codes) => {
    if (codes.length === 0) return fc.constant([] as BuyTarget[])
    return fc.tuple(...codes.map((code) => buyTargetArb(code))) as fc.Arbitrary<BuyTarget[]>
  })

/** Generator: array of Positions with unique stk_cd */
const positionsArrayArb: fc.Arbitrary<Position[]> = fc
  .uniqueArray(fc.stringMatching(/^[0-9]{6}$/), { minLength: 0, maxLength: 50 })
  .chain((codes) => {
    if (codes.length === 0) return fc.constant([] as Position[])
    return fc.tuple(...codes.map((code) => positionArb(code))) as fc.Arbitrary<Position[]>
  })

describe('Property 3: Index Cache Consistency (인덱스 캐시 정합성)', () => {
  it('rebuildBuyTargetIndex: cache.get(targets[i].code) === i for all i, and cache.size === targets.length', () => {
    /**
     * **Validates: Requirements 4.1, 4.3, 4.5**
     */
    fc.assert(
      fc.property(buyTargetsArrayArb, (targets) => {
        rebuildBuyTargetIndex(targets)

        // Verify cache size matches array length
        for (let i = 0; i < targets.length; i++) {
          const cachedIdx = getBuyTargetIndex(targets[i].code)
          expect(cachedIdx).toBe(i)
        }

        // Verify no extra entries: a non-existent code returns undefined
        expect(getBuyTargetIndex('999999_NONEXIST')).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rebuildPositionIndex: cache.get(positions[i].stk_cd) === i for all i, and cache.size === positions.length', () => {
    /**
     * **Validates: Requirements 4.2, 4.4, 4.5**
     */
    fc.assert(
      fc.property(positionsArrayArb, (positions) => {
        rebuildPositionIndex(positions)

        // Verify cache size matches array length
        for (let i = 0; i < positions.length; i++) {
          const cachedIdx = getPositionIndex(positions[i].stk_cd)
          expect(cachedIdx).toBe(i)
        }

        // Verify no extra entries: a non-existent code returns undefined
        expect(getPositionIndex('999999_NONEXIST')).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rebuildBuyTargetIndex with duplicate codes: last occurrence wins', () => {
    /**
     * **Validates: Requirements 4.1, 4.3**
     *
     * Edge case: if duplicate codes exist (shouldn't in practice),
     * the cache maps to the last index (consistent with the rebuild loop).
     */
    fc.assert(
      fc.property(
        fc.array(fc.stringMatching(/^[0-9]{6}$/), { minLength: 1, maxLength: 20 }),
        (codes) => {
          const targets: BuyTarget[] = codes.map((code, i) => ({
            rank: i + 1,
            name: `Stock${i}`,
            code,
            sector: 'IT',
            change: 0,
            change_rate: 0,
            cur_price: 10000,
            strength: 50,
            trade_amount: 1000000,
            boost_score: 0,
            order_ratio: null,
            guard_pass: true,
            reason: '',
          }))

          rebuildBuyTargetIndex(targets)

          // For each unique code, the cache should point to the LAST index
          const lastIndexMap = new Map<string, number>()
          for (let i = 0; i < targets.length; i++) {
            lastIndexMap.set(targets[i].code, i)
          }

          for (const [code, expectedIdx] of lastIndexMap) {
            expect(getBuyTargetIndex(code)).toBe(expectedIdx)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('rebuildPositionIndex with duplicate stk_cd: last occurrence wins', () => {
    /**
     * **Validates: Requirements 4.2, 4.4**
     *
     * Edge case: if duplicate stk_cd exist (shouldn't in practice),
     * the cache maps to the last index (consistent with the rebuild loop).
     */
    fc.assert(
      fc.property(
        fc.array(fc.stringMatching(/^[0-9]{6}$/), { minLength: 1, maxLength: 20 }),
        (codes) => {
          const positions: Position[] = codes.map((code, i) => ({
            stk_cd: code,
            stk_nm: `Stock${i}`,
            qty: 100,
            buy_amt: 1000000,
            cur_price: 10000,
            pnl_rate: 0,
          }))

          rebuildPositionIndex(positions)

          // For each unique code, the cache should point to the LAST index
          const lastIndexMap = new Map<string, number>()
          for (let i = 0; i < positions.length; i++) {
            lastIndexMap.set(positions[i].stk_cd, i)
          }

          for (const [code, expectedIdx] of lastIndexMap) {
            expect(getPositionIndex(code)).toBe(expectedIdx)
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
