/**
 * Property 5: applyRealData No-Op Guard (변경 없으면 상태 유지)
 *
 * Feature: hts-level-optimization, Property 5: applyRealData No-Op Guard
 *
 * **Validates: Requirements 5.3, 12.3**
 *
 * For any real-data tick where the target code does not exist in
 * buyTargets/positions, or where all compared fields (cur_price, change,
 * change_rate, strength, trade_amount) are identical to existing values,
 * applyRealData SHALL return the existing state object without calling
 * Zustand setState (no state mutation occurs).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as fc from 'fast-check'
import {
  appStore,
  applyRealData,
  rebuildBuyTargetIndex,
  rebuildPositionIndex,
} from './appStore'
import type { BuyTarget, Position, SectorStock, RealDataEvent } from '../types'

describe('Property 5: applyRealData No-Op Guard (변경 없으면 상태 유지)', () => {
  beforeEach(() => {
    appStore.setState({
      positions: [],
      sectorStocks: {},
      buyTargets: [],
    })
    rebuildBuyTargetIndex([])
    rebuildPositionIndex([])
  })

  it('Non-existent code: setState subscriber is NOT notified when tick code does not exist in any collection', () => {
    /**
     * **Validates: Requirements 5.3, 12.3**
     *
     * Generate ticks with codes that do NOT exist in sectorStocks, buyTargets,
     * or positions. Verify that store subscribers are never notified (no state mutation).
     */
    fc.assert(
      fc.property(
        // Generate a set of "existing" codes for sectorStocks/buyTargets/positions
        fc.uniqueArray(fc.stringMatching(/^[0-9]{6}$/), { minLength: 1, maxLength: 10 }),
        // Generate a "non-existent" code that is NOT in the existing set
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        // Generate arbitrary price/change values for the tick
        fc.integer({ min: 100, max: 1000000 }),
        fc.integer({ min: -10000, max: 10000 }),
        fc.float({ min: -30, max: 30, noNaN: true }),
        fc.float({ min: 0, max: 200, noNaN: true }),
        fc.integer({ min: 0, max: 10000000 }),
        (existingCodes, tickCode, eventType, price, change, changeRate, strength, amount) => {
          // Ensure tickCode is NOT in existingCodes
          if (existingCodes.includes(tickCode)) return

          // Set up store with existing codes in sectorStocks and buyTargets
          const sectorStocks: Record<string, SectorStock> = {}
          const buyTargets: BuyTarget[] = []
          const positions: Position[] = []

          for (const code of existingCodes) {
            sectorStocks[code] = {
              code,
              name: `Stock_${code}`,
              cur_price: 50000,
              change: 500,
              change_rate: 1.0,
              strength: 70,
              trade_amount: 1000000000,
            }
            buyTargets.push({
              rank: 1,
              name: `Target_${code}`,
              code,
              sector: 'IT',
              change: 500,
              change_rate: 1.0,
              cur_price: 50000,
              strength: 70,
              trade_amount: 1000000000,
              boost_score: 5,
              order_ratio: null,
              guard_pass: true,
              reason: '',
            })
            positions.push({
              stk_cd: code,
              stk_nm: `Pos_${code}`,
              qty: 100,
              buy_amt: 5000000,
              cur_price: 50000,
              pnl_rate: 0,
            })
          }

          appStore.setState({ sectorStocks, buyTargets, positions })
          rebuildBuyTargetIndex(buyTargets)
          rebuildPositionIndex(positions)

          // Subscribe to detect any state changes
          const listener = vi.fn()
          const unsub = appStore.subscribe(listener)

          // Capture state references before
          const stateBefore = appStore.getState()

          // Create real-data event with non-existent code
          const event: RealDataEvent = {
            type: eventType,
            item: tickCode,
            values: {
              '10': String(price),
              '11': String(change),
              '12': String(changeRate),
              '228': String(strength),
              '14': String(amount),
            },
          }

          applyRealData(event)

          // Verify: subscriber was NOT notified (no state mutation)
          expect(listener).not.toHaveBeenCalled()

          // Verify: state references are identical
          const stateAfter = appStore.getState()
          expect(stateAfter.sectorStocks).toBe(stateBefore.sectorStocks)
          expect(stateAfter.buyTargets).toBe(stateBefore.buyTargets)
          expect(stateAfter.positions).toBe(stateBefore.positions)

          unsub()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Identical field values: setState subscriber is NOT notified when all fields match existing values', () => {
    /**
     * **Validates: Requirements 5.3, 12.3**
     *
     * Generate ticks where the code EXISTS in sectorStocks/buyTargets/positions,
     * but all compared fields are identical to existing values.
     * Verify that store subscribers are never notified.
     */
    fc.assert(
      fc.property(
        // Generate a stock code
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        // Generate field values that will be set as BOTH existing and incoming
        fc.integer({ min: 100, max: 1000000 }),
        fc.integer({ min: -10000, max: 10000 }),
        fc.float({ min: -30, max: 30, noNaN: true }),
        fc.float({ min: 0, max: 200, noNaN: true }),
        fc.integer({ min: 1, max: 10000000 }),
        (code, eventType, price, change, changeRate, strength, amount) => {
          // Set up store with the code having these exact field values
          const sectorStocks: Record<string, SectorStock> = {
            [code]: {
              code,
              name: `Stock_${code}`,
              cur_price: price,
              change: change,
              change_rate: changeRate,
              strength: strength,
              trade_amount: amount * 1000000, // applyRealData multiplies by 1000000
            },
          }

          const buyTargets: BuyTarget[] = [{
            rank: 1,
            name: `Target_${code}`,
            code,
            sector: 'IT',
            change: change,
            change_rate: changeRate,
            cur_price: price,
            strength: strength,
            trade_amount: amount * 1000000,
            boost_score: 5,
            order_ratio: null,
            guard_pass: true,
            reason: '',
          }]

          const positions: Position[] = [{
            stk_cd: code,
            stk_nm: `Pos_${code}`,
            qty: 100,
            buy_amt: 5000000,
            cur_price: price,
            pnl_rate: 0,
          }]

          appStore.setState({ sectorStocks, buyTargets, positions })
          rebuildBuyTargetIndex(buyTargets)
          rebuildPositionIndex(positions)

          // Subscribe to detect any state changes
          const listener = vi.fn()
          const unsub = appStore.subscribe(listener)

          // Capture state references before
          const stateBefore = appStore.getState()

          // Create real-data event with IDENTICAL values
          // Note: applyRealData parses values and multiplies amount by 1000000
          const event: RealDataEvent = {
            type: eventType,
            item: code,
            values: {
              '10': String(price),
              '11': String(change),
              '12': String(changeRate),
              '228': String(strength),
              '14': String(amount), // will be multiplied by 1000000 in applyRealData
            },
          }

          applyRealData(event)

          // Verify: subscriber was NOT notified (no state mutation)
          expect(listener).not.toHaveBeenCalled()

          // Verify: state references are identical
          const stateAfter = appStore.getState()
          expect(stateAfter.sectorStocks).toBe(stateBefore.sectorStocks)
          expect(stateAfter.buyTargets).toBe(stateBefore.buyTargets)
          expect(stateAfter.positions).toBe(stateBefore.positions)

          unsub()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Mixed scenario: code exists in sectorStocks only (not in buyTargets/positions) with identical values → no-op', () => {
    /**
     * **Validates: Requirements 5.3, 12.3**
     *
     * Code exists in sectorStocks with identical values, but NOT in
     * buyTargets or positions. No state change should occur.
     */
    fc.assert(
      fc.property(
        fc.stringMatching(/^[0-9]{6}$/),
        fc.constantFrom('01', '0B', '0H'),
        fc.integer({ min: 100, max: 1000000 }),
        fc.integer({ min: -10000, max: 10000 }),
        fc.float({ min: -30, max: 30, noNaN: true }),
        fc.float({ min: 0, max: 200, noNaN: true }),
        fc.integer({ min: 1, max: 10000000 }),
        (code, eventType, price, change, changeRate, strength, amount) => {
          // Only in sectorStocks, not in buyTargets or positions
          const sectorStocks: Record<string, SectorStock> = {
            [code]: {
              code,
              name: `Stock_${code}`,
              cur_price: price,
              change: change,
              change_rate: changeRate,
              strength: strength,
              trade_amount: amount * 1000000,
            },
          }

          appStore.setState({ sectorStocks, buyTargets: [], positions: [] })
          rebuildBuyTargetIndex([])
          rebuildPositionIndex([])

          // Subscribe to detect any state changes
          const listener = vi.fn()
          const unsub = appStore.subscribe(listener)

          // Create real-data event with identical values
          const event: RealDataEvent = {
            type: eventType,
            item: code,
            values: {
              '10': String(price),
              '11': String(change),
              '12': String(changeRate),
              '228': String(strength),
              '14': String(amount),
            },
          }

          applyRealData(event)

          // Verify: no state mutation
          expect(listener).not.toHaveBeenCalled()

          unsub()
        },
      ),
      { numRuns: 100 },
    )
  })
})
