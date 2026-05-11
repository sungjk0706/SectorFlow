/**
 * Bug Condition Exploration Test - Position PnL not recalculated on cur_price change
 *
 * Validates: Requirements 1.1, 2.1
 *
 * This test encodes the EXPECTED behavior: when a real-data event changes
 * a position's cur_price, eval_amount/pnl_amount/pnl_rate must be recalculated.
 *
 * On UNFIXED code, this test is EXPECTED TO FAIL — failure confirms the bug exists.
 * After the fix is applied, this test should PASS.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import * as fc from 'fast-check'
import { appStore, applyRealData, rebuildBuyTargetIndex, rebuildPositionIndex } from './appStore'
import type { Position, BuyTarget, SectorStock, RealDataEvent } from '../types'

describe('Bug Condition: Position PnL not recalculated on cur_price change', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    appStore.setState({
      positions: [],
      sectorStocks: {},
      buyTargets: [],
    })
  })

  it('Property 1: When real-data event changes cur_price, eval_amount/pnl_amount/pnl_rate must be recalculated', () => {
    /**
     * Validates: Requirements 1.1, 2.1
     *
     * Bug Condition: X.type IN {'01','0B','0H'} AND X.code IN positions
     *   AND parsePrice(X.values['10']) != pos.cur_price
     *
     * Expected: pos.eval_amount === newPrice * qty,
     *           pos.pnl_amount === evalAmount - buyAmt,
     *           pos.pnl_rate === Math.round((pnlAmount / buyAmt) * 10000) / 100
     */
    fc.assert(
      fc.property(
        // Generate a stock code (6-digit numeric string)
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate qty > 0
        fc.integer({ min: 1, max: 10000 }),
        // Generate buy_amt > 0
        fc.integer({ min: 1000, max: 100000000 }),
        // Generate initial cur_price
        fc.integer({ min: 100, max: 1000000 }),
        // Generate new price (different from cur_price)
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        (stkCd, qty, buyAmt, curPrice, newPrice, eventType) => {
          // Ensure newPrice differs from curPrice (bug condition requirement)
          if (newPrice === curPrice) return // skip trivial case

          // Set up position in store
          const position: Position = {
            stk_cd: stkCd,
            stk_nm: 'TestStock',
            qty: qty,
            buy_amt: buyAmt,
            cur_price: curPrice,
            eval_amount: curPrice * qty,
            pnl_amount: (curPrice * qty) - buyAmt,
            pnl_rate: Math.round(((curPrice * qty - buyAmt) / buyAmt) * 10000) / 100,
          }

          appStore.setState({ positions: [position] })
          rebuildPositionIndex([position])

          // Create real-data event with new price
          const event: RealDataEvent = {
            type: eventType,
            item: stkCd,
            values: { '10': String(newPrice) },
          }

          // Apply the real-data event
          applyRealData(event)

          // Get updated position
          const updatedPositions = appStore.getState().positions
          const updatedPos = updatedPositions.find(p => p.stk_cd === stkCd)

          expect(updatedPos).toBeDefined()
          if (!updatedPos) return

          // Assert cur_price is updated
          expect(updatedPos.cur_price).toBe(newPrice)

          // Assert PnL fields are recalculated (this is the expected behavior)
          const expectedEvalAmount = newPrice * qty
          const expectedPnlAmount = expectedEvalAmount - buyAmt
          const expectedPnlRate = Math.round((expectedPnlAmount / buyAmt) * 10000) / 100

          expect(updatedPos.eval_amount).toBe(expectedEvalAmount)
          expect(updatedPos.pnl_amount).toBe(expectedPnlAmount)
          expect(updatedPos.pnl_rate).toBe(expectedPnlRate)
        },
      ),
      { numRuns: 100 },
    )
  })
})


/**
 * Preservation Property Tests - Non-position stocks and unchanged prices preserve state
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4
 *
 * These tests verify behavior that must NOT change after the fix is applied.
 * On UNFIXED code, these tests are EXPECTED TO PASS.
 */
describe('Preservation: Non-position stocks and unchanged prices preserve state', () => {
  beforeEach(() => {
    appStore.setState({
      positions: [],
      sectorStocks: {},
      buyTargets: [],
    })
  })

  it('Property 2a: When real-data event arrives for a code NOT in positions, positions array reference is unchanged', () => {
    /**
     * Validates: Requirements 3.2
     *
     * Observe: when `real-data` event arrives for a code NOT in positions,
     * `positions` array reference is unchanged.
     */
    fc.assert(
      fc.property(
        // Generate a position stock code
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate a different event stock code (NOT in positions)
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate position fields
        fc.integer({ min: 1, max: 10000 }),
        fc.integer({ min: 1000, max: 100000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event price
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        (posCode, eventCode, qty, buyAmt, curPrice, eventPrice, eventType) => {
          // Ensure eventCode is different from posCode (not in positions)
          if (eventCode === posCode) return

          // Set up a position and a sectorStock for the event code
          const position: Position = {
            stk_cd: posCode,
            stk_nm: 'PositionStock',
            qty,
            buy_amt: buyAmt,
            cur_price: curPrice,
            eval_amount: curPrice * qty,
            pnl_amount: (curPrice * qty) - buyAmt,
            pnl_rate: Math.round(((curPrice * qty - buyAmt) / buyAmt) * 10000) / 100,
          }

          const sectorStock: SectorStock = {
            code: eventCode,
            name: 'SectorStock',
            cur_price: 50000,
            change_rate: 1.5,
          }

          appStore.setState({
            positions: [position],
            sectorStocks: { [eventCode]: sectorStock },
            buyTargets: [],
          })
          rebuildPositionIndex([position])
          rebuildBuyTargetIndex([])

          // Capture positions reference before event
          const positionsBefore = appStore.getState().positions

          // Create real-data event for a code NOT in positions
          const event: RealDataEvent = {
            type: eventType,
            item: eventCode,
            values: { '10': String(eventPrice), '11': '100', '12': '1.5', '228': '80', '14': '500' },
          }

          applyRealData(event)

          // Assert positions reference is unchanged (no unnecessary re-render)
          const positionsAfter = appStore.getState().positions
          expect(positionsAfter).toBe(positionsBefore)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 2b: When real-data event arrives with same price as pos.cur_price, positions array reference is unchanged', () => {
    /**
     * Validates: Requirements 3.3
     *
     * Observe: when `real-data` event arrives with same price as `pos.cur_price`,
     * `positions` array reference is unchanged.
     */
    fc.assert(
      fc.property(
        // Generate stock code
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate position fields
        fc.integer({ min: 1, max: 10000 }),
        fc.integer({ min: 1000, max: 100000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        (stkCd, qty, buyAmt, curPrice, eventType) => {
          // Set up position
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

          appStore.setState({
            positions: [position],
            sectorStocks: { [stkCd]: { code: stkCd, name: 'Test', cur_price: curPrice, change_rate: 0 } },
            buyTargets: [],
          })
          rebuildPositionIndex([position])
          rebuildBuyTargetIndex([])

          // Capture positions reference before event
          const positionsBefore = appStore.getState().positions

          // Create real-data event with SAME price as cur_price
          const event: RealDataEvent = {
            type: eventType,
            item: stkCd,
            values: { '10': String(curPrice), '11': '0', '12': '0', '228': '80', '14': '500' },
          }

          applyRealData(event)

          // Assert positions reference is unchanged (no re-render for same price)
          const positionsAfter = appStore.getState().positions
          expect(positionsAfter).toBe(positionsBefore)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 2c: sectorStocks and buyTargets continue to update normally for non-position codes', () => {
    /**
     * Validates: Requirements 3.2
     *
     * Observe: `sectorStocks` and `buyTargets` continue to update normally
     * for non-position codes.
     */
    fc.assert(
      fc.property(
        // Generate stock code for sector/buyTarget (not in positions)
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate new price
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        (code, newPrice, eventType) => {
          // Set up sectorStock and buyTarget for this code, no positions
          const sectorStock: SectorStock = {
            code,
            name: 'TestSector',
            cur_price: 50000,
            change_rate: 1.0,
            change: 500,
            strength: 70,
            trade_amount: 1000000000,
          }

          const buyTargetsList = [{
              rank: 1,
              name: 'TestTarget',
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
            }]

          appStore.setState({
            positions: [],
            sectorStocks: { [code]: sectorStock },
            buyTargets: buyTargetsList,
          })
          rebuildBuyTargetIndex(buyTargetsList as BuyTarget[])
          rebuildPositionIndex([])

          // Create real-data event
          const event: RealDataEvent = {
            type: eventType,
            item: code,
            values: { '10': String(newPrice), '11': '100', '12': '1.5', '228': '80', '14': '500' },
          }

          applyRealData(event)

          // Assert sectorStocks updated with new price
          const updatedSectorStock = appStore.getState().sectorStocks[code]
          expect(updatedSectorStock).toBeDefined()
          expect(updatedSectorStock.cur_price).toBe(newPrice)

          // Assert buyTargets updated with new price
          const updatedBuyTarget = appStore.getState().buyTargets.find(t => t.code === code)
          expect(updatedBuyTarget).toBeDefined()
          if (updatedBuyTarget) {
            expect(updatedBuyTarget.cur_price).toBe(newPrice)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Edge case: position with buy_amt = 0 or qty = 0 does not cause division-by-zero', () => {
    /**
     * Validates: Requirements 3.4
     *
     * Edge case: position with `buy_amt = 0` or `qty = 0` does not cause
     * division-by-zero when price changes.
     */
    fc.assert(
      fc.property(
        // Generate stock code
        fc.stringMatching(/^[0-9]{6}$/),
        // Generate either buy_amt=0 or qty=0
        fc.oneof(
          fc.record({ qty: fc.constant(0), buy_amt: fc.integer({ min: 1000, max: 100000000 }) }),
          fc.record({ qty: fc.integer({ min: 1, max: 10000 }), buy_amt: fc.constant(0) }),
          fc.record({ qty: fc.constant(0), buy_amt: fc.constant(0) }),
        ),
        // Generate cur_price and new price
        fc.integer({ min: 100, max: 1000000 }),
        fc.integer({ min: 100, max: 1000000 }),
        // Generate event type
        fc.constantFrom('01', '0B', '0H'),
        (stkCd, amounts, curPrice, newPrice, eventType) => {
          // Ensure price actually changes
          if (newPrice === curPrice) return

          const position: Position = {
            stk_cd: stkCd,
            stk_nm: 'TestStock',
            qty: amounts.qty,
            buy_amt: amounts.buy_amt,
            cur_price: curPrice,
            eval_amount: curPrice * amounts.qty,
            pnl_amount: 0,
            pnl_rate: 0,
          }

          appStore.setState({
            positions: [position],
            sectorStocks: {},
            buyTargets: [],
          })
          rebuildPositionIndex([position])
          rebuildBuyTargetIndex([])

          // Create real-data event with different price
          const event: RealDataEvent = {
            type: eventType,
            item: stkCd,
            values: { '10': String(newPrice) },
          }

          // This should NOT throw (no division-by-zero)
          expect(() => applyRealData(event)).not.toThrow()

          // Verify position still exists and cur_price is updated
          const updatedPos = appStore.getState().positions.find(p => p.stk_cd === stkCd)
          expect(updatedPos).toBeDefined()
          if (updatedPos) {
            expect(updatedPos.cur_price).toBe(newPrice)
            // pnl_rate should be a finite number (no NaN/Infinity from division by zero)
            expect(Number.isFinite(updatedPos.pnl_rate)).toBe(true)
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
