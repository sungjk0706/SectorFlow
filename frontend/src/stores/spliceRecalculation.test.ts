/**
 * Property 4: Splice + Derived Field Recalculation (증분 갱신 정확성)
 *
 * Feature: hts-level-optimization, Property 4: Splice + Derived Field Recalculation
 *
 * **Validates: Requirements 5.1, 5.2**
 *
 * For any position with buy_amt > 0, qty > 0, and a new cur_price,
 * after splice update:
 *   eval_amount === cur_price × qty,
 *   pnl_amount === eval_amount − buy_amt,
 *   pnl_rate === round((pnl_amount / buy_amt) × 100, 2)
 */
import { describe, it, expect, beforeEach } from 'vitest'
import * as fc from 'fast-check'
import {
  appStore,
  applyRealData,
  rebuildPositionIndex,
  rebuildBuyTargetIndex,
} from './appStore'
import type { Position, RealDataEvent } from '../types'

describe('Property 4: Splice + Derived Field Recalculation (증분 갱신 정확성)', () => {
  beforeEach(() => {
    appStore.setState({
      positions: [],
      sectorStocks: {},
      buyTargets: [],
    })
  })

  it('splice 후 eval_amount === cur_price × qty, pnl_amount === eval_amount − buy_amt, pnl_rate === round((pnl_amount / buy_amt) × 100, 2)', () => {
    /**
     * **Validates: Requirements 5.1, 5.2**
     *
     * Generate arbitrary Position with buy_amt > 0 and qty > 0,
     * apply a new cur_price via applyRealData (splice-based update),
     * and verify derived fields are correctly recalculated.
     */
    fc.assert(
      fc.property(
        // Generate a 6-digit stock code
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate qty > 0
        fc.integer({ min: 1, max: 10000 }),
        // Generate buy_amt > 0
        fc.integer({ min: 1, max: 100000000 }),
        // Generate initial cur_price
        fc.integer({ min: 100, max: 1000000 }),
        // Generate new cur_price (must differ from initial)
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event type (01/0B/0H are stock trade types)
        fc.constantFrom('01', '0B', '0H'),
        (stkCd, qty, buyAmt, curPrice, newPrice, eventType) => {
          // Skip trivial case where price doesn't change
          if (newPrice === curPrice) return

          // Set up position with buy_amt > 0 and qty > 0
          const position: Position = {
            stk_cd: stkCd,
            stk_nm: 'TestStock',
            qty,
            buy_amt: buyAmt,
            cur_price: curPrice,
            eval_amount: curPrice * qty,
            pnl_amount: (curPrice * qty) - buyAmt,
            pnl_rate: Math.round(((curPrice * qty - buyAmt) / buyAmt) * 10000) / 100,
          }

          appStore.setState({ positions: [position], sectorStocks: {}, buyTargets: [] })
          rebuildPositionIndex([position])
          rebuildBuyTargetIndex([])

          // Apply real-data event with new price (triggers splice + recalculation)
          const event: RealDataEvent = {
            type: eventType,
            item: stkCd,
            values: { '10': String(newPrice) },
          }

          applyRealData(event)

          // Verify derived fields
          const updatedPos = appStore.getState().positions.find(p => p.stk_cd === stkCd)
          expect(updatedPos).toBeDefined()
          if (!updatedPos) return

          // Property assertions
          const expectedEvalAmount = newPrice * qty
          const expectedPnlAmount = expectedEvalAmount - buyAmt
          const expectedPnlRate = Math.round((expectedPnlAmount / buyAmt) * 10000) / 100

          expect(updatedPos.cur_price).toBe(newPrice)
          expect(updatedPos.eval_amount).toBe(expectedEvalAmount)
          expect(updatedPos.pnl_amount).toBe(expectedPnlAmount)
          expect(updatedPos.pnl_rate).toBe(expectedPnlRate)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('splice 갱신은 동일 배열 참조를 유지한다 (Zustand 증분 갱신)', () => {
    /**
     * **Validates: Requirements 5.2**
     *
     * After splice-based update, the positions array reference passed to
     * setState should be the same array object (splice mutates in-place).
     */
    fc.assert(
      fc.property(
        fc.stringMatching(/^[0-9]{6}$/),
        fc.integer({ min: 1, max: 10000 }),
        fc.integer({ min: 1, max: 100000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        fc.constantFrom('01', '0B', '0H'),
        (stkCd, qty, buyAmt, curPrice, newPrice, eventType) => {
          if (newPrice === curPrice) return

          const position: Position = {
            stk_cd: stkCd,
            stk_nm: 'TestStock',
            qty,
            buy_amt: buyAmt,
            cur_price: curPrice,
            eval_amount: curPrice * qty,
            pnl_amount: (curPrice * qty) - buyAmt,
            pnl_rate: Math.round(((curPrice * qty - buyAmt) / buyAmt) * 10000) / 100,
          }

          const positions = [position]
          appStore.setState({ positions, sectorStocks: {}, buyTargets: [] })
          rebuildPositionIndex(positions)
          rebuildBuyTargetIndex([])

          // Capture array reference before
          const arrBefore = appStore.getState().positions

          const event: RealDataEvent = {
            type: eventType,
            item: stkCd,
            values: { '10': String(newPrice) },
          }

          applyRealData(event)

          // After splice, the same array reference is used (splice mutates in-place)
          const arrAfter = appStore.getState().positions
          expect(arrAfter).toBe(arrBefore)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('다중 포지션에서 대상 종목만 갱신되고 나머지는 불변', () => {
    /**
     * **Validates: Requirements 5.1, 5.2**
     *
     * When multiple positions exist, only the target position's derived
     * fields are recalculated; other positions remain unchanged.
     */
    fc.assert(
      fc.property(
        // Target stock code
        fc.stringMatching(/^[1-4][0-9]{5}$/),
        // Other stock code (different range to avoid collision)
        fc.stringMatching(/^[5-9][0-9]{5}$/),
        // Target position fields
        fc.integer({ min: 1, max: 10000 }),
        fc.integer({ min: 1, max: 100000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        // Other position fields
        fc.integer({ min: 1, max: 10000 }),
        fc.integer({ min: 1, max: 100000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        // New price for target
        fc.integer({ min: 100, max: 1000000 }),
        (targetCode, otherCode, tQty, tBuyAmt, tCurPrice, oQty, oBuyAmt, oCurPrice, newPrice) => {
          if (newPrice === tCurPrice) return
          if (targetCode === otherCode) return

          const targetPos: Position = {
            stk_cd: targetCode,
            stk_nm: 'Target',
            qty: tQty,
            buy_amt: tBuyAmt,
            cur_price: tCurPrice,
            eval_amount: tCurPrice * tQty,
            pnl_amount: (tCurPrice * tQty) - tBuyAmt,
            pnl_rate: Math.round(((tCurPrice * tQty - tBuyAmt) / tBuyAmt) * 10000) / 100,
          }

          const otherPos: Position = {
            stk_cd: otherCode,
            stk_nm: 'Other',
            qty: oQty,
            buy_amt: oBuyAmt,
            cur_price: oCurPrice,
            eval_amount: oCurPrice * oQty,
            pnl_amount: (oCurPrice * oQty) - oBuyAmt,
            pnl_rate: Math.round(((oCurPrice * oQty - oBuyAmt) / oBuyAmt) * 10000) / 100,
          }

          const positions = [targetPos, otherPos]
          appStore.setState({ positions, sectorStocks: {}, buyTargets: [] })
          rebuildPositionIndex(positions)
          rebuildBuyTargetIndex([])

          const event: RealDataEvent = {
            type: '01',
            item: targetCode,
            values: { '10': String(newPrice) },
          }

          applyRealData(event)

          const updatedPositions = appStore.getState().positions

          // Target position: derived fields recalculated
          const updated = updatedPositions.find(p => p.stk_cd === targetCode)!
          expect(updated.eval_amount).toBe(newPrice * tQty)
          expect(updated.pnl_amount).toBe(newPrice * tQty - tBuyAmt)
          expect(updated.pnl_rate).toBe(Math.round(((newPrice * tQty - tBuyAmt) / tBuyAmt) * 10000) / 100)

          // Other position: unchanged
          const other = updatedPositions.find(p => p.stk_cd === otherCode)!
          expect(other.cur_price).toBe(oCurPrice)
          expect(other.eval_amount).toBe(oCurPrice * oQty)
          expect(other.pnl_amount).toBe((oCurPrice * oQty) - oBuyAmt)
          expect(other.pnl_rate).toBe(Math.round(((oCurPrice * oQty - oBuyAmt) / oBuyAmt) * 10000) / 100)
        },
      ),
      { numRuns: 100 },
    )
  })
})
