/**
 * Property 9: Virtual Scroller Fixed-Height Offset (고정 높이 오프셋 산술)
 *
 * Feature: hts-level-optimization, Property 9: Virtual Scroller Fixed-Height Offset
 *
 * **Validates: Requirements 10.1, 10.3, 10.5**
 *
 * For any item count N and fixed row height H, the computed offset for index i
 * SHALL equal i × H, and totalHeight SHALL equal N × H.
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  detectFixedHeight,
  getOffsetFixed,
  getTotalHeightFixed,
} from '../virtual-scroller'

describe('Property 9: Virtual Scroller Fixed-Height Offset (고정 높이 오프셋 산술)', () => {
  it('offset(i) === i × H for all i in [0, N) and totalHeight === N × H', () => {
    /**
     * **Validates: Requirements 10.1, 10.3, 10.5**
     *
     * For any item count N (0..500) and fixed row height H (1..200),
     * getOffsetFixed(i, H) === i * H for all valid indices,
     * and getTotalHeightFixed(N, H) === N * H.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 500 }),   // item count N
        fc.integer({ min: 1, max: 200 }),   // row height H
        (N, H) => {
          // Verify totalHeight === N × H
          expect(getTotalHeightFixed(N, H)).toBe(N * H)

          // Verify offset(i) === i × H for all i in [0, N)
          for (let i = 0; i < N; i++) {
            expect(getOffsetFixed(i, H)).toBe(i * H)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('detectFixedHeight enables fixed mode when all rows have the same height', () => {
    /**
     * **Validates: Requirements 10.1, 10.5**
     *
     * For any item count N (1..100) and uniform row height H (1..200),
     * detectFixedHeight SHALL return { enabled: true, rowHeight: H }.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),   // item count N
        fc.integer({ min: 1, max: 200 }),   // row height H
        (N, H) => {
          // Create items array of length N (content doesn't matter, only getRowHeight)
          const items = Array.from({ length: N }, (_, i) => ({ id: i }))
          const getRowHeight = () => H

          const result = detectFixedHeight(items, getRowHeight)

          expect(result.enabled).toBe(true)
          expect(result.rowHeight).toBe(H)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('detectFixedHeight disables fixed mode when rows have different heights', () => {
    /**
     * **Validates: Requirements 10.1**
     *
     * For any item count N (2..50) and two distinct heights H1 ≠ H2,
     * detectFixedHeight SHALL return { enabled: false, rowHeight: 0 }.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 2, max: 50 }),    // item count N (need at least 2 for different heights)
        fc.integer({ min: 1, max: 100 }),   // base height H1
        fc.integer({ min: 1, max: 100 }),   // delta (to ensure H2 ≠ H1)
        (N, H1, delta) => {
          const H2 = H1 + delta + 1  // ensure H2 ≠ H1

          const items = Array.from({ length: N }, (_, i) => ({ id: i }))
          // First item has height H1, at least one other has height H2
          const getRowHeight = (_item: { id: number }, index: number) =>
            index === 0 ? H1 : H2

          const result = detectFixedHeight(items, getRowHeight)

          expect(result.enabled).toBe(false)
          expect(result.rowHeight).toBe(0)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('detectFixedHeight returns disabled for empty items', () => {
    /**
     * **Validates: Requirements 10.1**
     *
     * Edge case: empty items array → fixed mode disabled.
     */
    const result = detectFixedHeight([], () => 32)
    expect(result.enabled).toBe(false)
    expect(result.rowHeight).toBe(0)
  })

  it('fixed-height offset is consistent with totalHeight boundary', () => {
    /**
     * **Validates: Requirements 10.3, 10.5**
     *
     * For any N and H, the offset of the last item plus H equals totalHeight.
     * offset(N-1) + H === totalHeight (when N > 0).
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 500 }),   // item count N (at least 1)
        fc.integer({ min: 1, max: 200 }),   // row height H
        (N, H) => {
          const lastOffset = getOffsetFixed(N - 1, H)
          const total = getTotalHeightFixed(N, H)

          // Last item's bottom edge should equal totalHeight
          expect(lastOffset + H).toBe(total)
        },
      ),
      { numRuns: 100 },
    )
  })
})
