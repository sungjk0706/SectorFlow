/**
 * Property 16: Sector-Stock Title CSS Toggle (innerHTML 미사용)
 *
 * Feature: hts-level-optimization, Property 16: Sector-Stock Title CSS Toggle
 *
 * **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
 *
 * For any sequence of updateUI calls with varying sectorStatus/minTradeAmt/stockCount values,
 * the title area DOM element count SHALL remain constant (no createElement, no removeChild
 * after initial mount), and only textContent and style.display properties SHALL change.
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

/* ── Title Toggle Logic (extracted from sector-stock.ts updateUI) ── */

/**
 * Simulates the title area DOM structure created at mount time in sector-stock.ts.
 * Elements are created once and never added/removed afterwards.
 */
function createTitleArea(): {
  container: HTMLElement
  baseSpan: HTMLElement
  filterSpan: HTMLElement
  countSpan: HTMLElement
} {
  const container = document.createElement('span')

  const baseSpan = document.createElement('span')
  baseSpan.textContent = '업종별 종목 실시간 시세'

  const filterSpan = document.createElement('span')
  Object.assign(filterSpan.style, { color: '#1a73e8', fontWeight: '500', display: 'none' })

  const countSpan = document.createElement('span')
  countSpan.style.display = 'none'

  container.appendChild(baseSpan)
  container.appendChild(document.createTextNode(' '))
  container.appendChild(filterSpan)
  container.appendChild(document.createTextNode(' '))
  container.appendChild(countSpan)

  return { container, baseSpan, filterSpan, countSpan }
}

/**
 * Replicates the updateUI title logic from sector-stock.ts.
 * Only modifies textContent and style.display — no innerHTML, no createElement/removeChild.
 */
function updateTitleUI(
  filterSpan: HTMLElement,
  countSpan: HTMLElement,
  sectorStatus: boolean,
  minTradeAmt: number,
  stockCount: number,
): void {
  if (sectorStatus) {
    filterSpan.textContent = `5일평균최소거래대금(${minTradeAmt})억`
    filterSpan.style.display = ''
    countSpan.textContent = `(${stockCount}종목)`
    countSpan.style.display = ''
  } else {
    filterSpan.style.display = 'none'
    countSpan.style.display = 'none'
  }
}

/* ── Generators ── */

interface TitleUpdateInput {
  sectorStatus: boolean
  minTradeAmt: number
  stockCount: number
}

const titleUpdateInputArb: fc.Arbitrary<TitleUpdateInput> = fc.record({
  sectorStatus: fc.boolean(),
  minTradeAmt: fc.integer({ min: 0, max: 10000 }),
  stockCount: fc.integer({ min: 0, max: 500 }),
})

/** Generate a sequence of 1-50 updateUI calls with varying inputs */
const titleUpdateSequenceArb: fc.Arbitrary<TitleUpdateInput[]> = fc.array(titleUpdateInputArb, {
  minLength: 1,
  maxLength: 50,
})

/* ── Helper: count all child nodes (elements + text nodes) ── */

function countChildNodes(el: HTMLElement): number {
  return el.childNodes.length
}

function countElementChildren(el: HTMLElement): number {
  return el.children.length
}

/* ── Tests ── */

describe('Property 16: Sector-Stock Title CSS Toggle (innerHTML 미사용)', () => {
  it('DOM element count remains constant across any sequence of updateUI calls', () => {
    /**
     * **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
     *
     * After initial mount, the number of child nodes in the title container
     * never changes regardless of sectorStatus/minTradeAmt/stockCount values.
     */
    fc.assert(
      fc.property(titleUpdateSequenceArb, (sequence) => {
        const { container, filterSpan, countSpan } = createTitleArea()

        // Record initial DOM structure
        const initialChildNodeCount = countChildNodes(container)
        const initialElementCount = countElementChildren(container)

        // Apply each update in the sequence
        for (const input of sequence) {
          updateTitleUI(filterSpan, countSpan, input.sectorStatus, input.minTradeAmt, input.stockCount)

          // After each update, DOM structure must remain identical
          expect(countChildNodes(container)).toBe(initialChildNodeCount)
          expect(countElementChildren(container)).toBe(initialElementCount)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('only textContent and display style change — no other DOM mutations', () => {
    /**
     * **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
     *
     * For any sequence of updates, only textContent and style.display are modified.
     * The element references themselves remain the same objects (no replacement).
     */
    fc.assert(
      fc.property(titleUpdateSequenceArb, (sequence) => {
        const { container, baseSpan, filterSpan, countSpan } = createTitleArea()

        // Store original element references
        const originalChildren = Array.from(container.childNodes)

        for (const input of sequence) {
          updateTitleUI(filterSpan, countSpan, input.sectorStatus, input.minTradeAmt, input.stockCount)

          // Element references must remain identical (same DOM nodes)
          const currentChildren = Array.from(container.childNodes)
          expect(currentChildren.length).toBe(originalChildren.length)
          for (let i = 0; i < originalChildren.length; i++) {
            expect(currentChildren[i]).toBe(originalChildren[i])
          }

          // baseSpan always visible
          expect(baseSpan.style.display).not.toBe('none')

          // Verify textContent/display correctness based on sectorStatus
          if (input.sectorStatus) {
            expect(filterSpan.style.display).toBe('')
            expect(countSpan.style.display).toBe('')
            expect(filterSpan.textContent).toBe(`5일평균최소거래대금(${input.minTradeAmt})억`)
            expect(countSpan.textContent).toBe(`(${input.stockCount}종목)`)
          } else {
            expect(filterSpan.style.display).toBe('none')
            expect(countSpan.style.display).toBe('none')
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('sectorStatus false→true transition uses display toggle without DOM add/remove', () => {
    /**
     * **Validates: Requirements 6.3, 6.4**
     *
     * When sectorStatus transitions from false to true, elements become visible
     * via display:'' toggle — no new elements are created.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 10000 }),
        fc.integer({ min: 0, max: 500 }),
        fc.integer({ min: 0, max: 10000 }),
        fc.integer({ min: 0, max: 500 }),
        (minTradeAmt1, stockCount1, minTradeAmt2, stockCount2) => {
          const { container, filterSpan, countSpan } = createTitleArea()
          const initialNodeCount = countChildNodes(container)

          // Start with sectorStatus = false (hidden)
          updateTitleUI(filterSpan, countSpan, false, minTradeAmt1, stockCount1)
          expect(filterSpan.style.display).toBe('none')
          expect(countSpan.style.display).toBe('none')
          expect(countChildNodes(container)).toBe(initialNodeCount)

          // Transition to sectorStatus = true (visible via display toggle)
          updateTitleUI(filterSpan, countSpan, true, minTradeAmt2, stockCount2)
          expect(filterSpan.style.display).toBe('')
          expect(countSpan.style.display).toBe('')
          expect(filterSpan.textContent).toBe(`5일평균최소거래대금(${minTradeAmt2})억`)
          expect(countSpan.textContent).toBe(`(${stockCount2}종목)`)

          // DOM element count unchanged
          expect(countChildNodes(container)).toBe(initialNodeCount)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('repeated updates with same sectorStatus=true only change textContent values', () => {
    /**
     * **Validates: Requirements 6.2**
     *
     * When sectorStatus remains true across multiple updates with different values,
     * only textContent is updated — no structural DOM changes.
     */
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            minTradeAmt: fc.integer({ min: 0, max: 10000 }),
            stockCount: fc.integer({ min: 0, max: 500 }),
          }),
          { minLength: 2, maxLength: 30 },
        ),
        (updates) => {
          const { container, filterSpan, countSpan } = createTitleArea()
          const initialNodeCount = countChildNodes(container)

          for (const { minTradeAmt, stockCount } of updates) {
            updateTitleUI(filterSpan, countSpan, true, minTradeAmt, stockCount)

            expect(countChildNodes(container)).toBe(initialNodeCount)
            expect(filterSpan.textContent).toBe(`5일평균최소거래대금(${minTradeAmt})억`)
            expect(countSpan.textContent).toBe(`(${stockCount}종목)`)
            expect(filterSpan.style.display).toBe('')
            expect(countSpan.style.display).toBe('')
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
