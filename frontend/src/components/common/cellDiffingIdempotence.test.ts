/**
 * Property 6: Cell Diffing Idempotence (동일 데이터 재렌더링 시 DOM 무변경)
 *
 * Feature: hts-level-optimization, Property 6: Cell Diffing Idempotence
 *
 * **Validates: Requirements 3.1, 3.2**
 *
 * For any row data T and its corresponding rendered row element,
 * calling renderRow with the same data a second time SHALL produce
 * zero DOM mutations (no textContent writes, no appendChild, no removeChild).
 */
import { describe, it, expect, beforeEach } from 'vitest'
import * as fc from 'fast-check'
import { createDataTable, type ColumnDef } from './data-table'

/* ── Test Row Type ── */

interface TestRow {
  code: string
  name: string
  price: number
  change: string
  rate: string
}

/* ── Generators ── */

const testRowArb: fc.Arbitrary<TestRow> = fc.record({
  code: fc.stringMatching(/^[0-9]{6}$/),
  name: fc.string({ minLength: 1, maxLength: 10 }),
  price: fc.integer({ min: 100, max: 9999999 }),
  change: fc.oneof(
    fc.integer({ min: -99999, max: 99999 }).map(v => (v >= 0 ? `+${v}` : `${v}`)),
  ),
  rate: fc.float({ min: -30, max: 30, noNaN: true }).map(v => `${v.toFixed(2)}%`),
})

/* ── Column Definitions (string-only cells for deterministic comparison) ── */

const stringColumns: ColumnDef<TestRow>[] = [
  { key: 'code', label: '종목코드', align: 'center', render: (row) => row.code },
  { key: 'name', label: '종목명', align: 'left', render: (row) => row.name },
  { key: 'price', label: '현재가', align: 'right', render: (row) => row.price.toLocaleString() },
  { key: 'change', label: '대비', align: 'right', render: (row) => row.change },
  { key: 'rate', label: '등락률', align: 'right', render: (row) => row.rate },
]

/* ── Column Definitions (HTMLElement cells) ── */

const elementColumns: ColumnDef<TestRow>[] = [
  { key: 'code', label: '종목코드', align: 'center', render: (row) => row.code },
  { key: 'name', label: '종목명', align: 'left', render: (row) => row.name },
  {
    key: 'price',
    label: '현재가',
    align: 'right',
    render: (row) => {
      const span = document.createElement('span')
      span.textContent = row.price.toLocaleString()
      span.style.color = row.price >= 0 ? 'red' : 'blue'
      return span
    },
  },
  {
    key: 'change',
    label: '대비',
    align: 'right',
    render: (row) => {
      const span = document.createElement('span')
      span.textContent = row.change
      return span
    },
  },
  { key: 'rate', label: '등락률', align: 'right', render: (row) => row.rate },
]

/* ── MutationObserver-based DOM mutation counter ── */

function countMutations(target: HTMLElement, action: () => void): number {
  let mutationCount = 0
  const observer = new MutationObserver((mutations) => {
    mutationCount += mutations.length
  })
  observer.observe(target, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
  })
  action()
  observer.disconnect()
  return mutationCount
}

/* ── Tests ── */

describe('Property 6: Cell Diffing Idempotence (동일 데이터 재렌더링 시 DOM 무변경)', () => {
  let container: HTMLElement

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    return () => {
      document.body.removeChild(container)
    }
  })

  it('string cells: second renderRow with same data produces zero DOM mutations', () => {
    /**
     * **Validates: Requirements 3.1, 3.2**
     *
     * For any row data with string cell content, calling renderRow twice
     * with identical data SHALL produce zero DOM mutations on the second call.
     */
    fc.assert(
      fc.property(testRowArb, (row) => {
        // Create a DataTable with virtual scroll (uses cell diffing renderRow)
        const table = createDataTable<TestRow>({
          columns: stringColumns,
          virtualScroll: true,
          keyFn: (r) => r.code,
          rowHeight: 32,
        })
        container.appendChild(table.el)

        // First render — populates the DOM
        table.updateRows([row])

        // Get the rendered row element from the virtual scroller
        const rowEl = table.el.querySelector('.data-table-row') as HTMLElement
        expect(rowEl).not.toBeNull()
        expect(rowEl!.childElementCount).toBe(stringColumns.length)

        // Second render with same data — should produce zero mutations
        const mutations = countMutations(rowEl!, () => {
          table.updateRows([row])
        })

        expect(mutations).toBe(0)

        table.destroy()
      }),
      { numRuns: 100 },
    )
  })

  it('HTMLElement cells: second renderRow with same data produces zero DOM mutations', () => {
    /**
     * **Validates: Requirements 3.1, 3.2**
     *
     * For any row data with HTMLElement cell content, calling renderRow twice
     * with identical data SHALL produce zero DOM mutations on the second call.
     */
    fc.assert(
      fc.property(testRowArb, (row) => {
        const table = createDataTable<TestRow>({
          columns: elementColumns,
          virtualScroll: true,
          keyFn: (r) => r.code,
          rowHeight: 32,
        })
        container.appendChild(table.el)

        // First render
        table.updateRows([row])

        const rowEl = table.el.querySelector('.data-table-row') as HTMLElement
        expect(rowEl).not.toBeNull()
        expect(rowEl!.childElementCount).toBe(elementColumns.length)

        // Second render with same data — should produce zero mutations
        const mutations = countMutations(rowEl!, () => {
          table.updateRows([row])
        })

        expect(mutations).toBe(0)

        table.destroy()
      }),
      { numRuns: 100 },
    )
  })

  it('multiple rows: re-rendering identical array produces zero DOM mutations per row', () => {
    /**
     * **Validates: Requirements 3.1, 3.2**
     *
     * For any array of row data, calling updateRows twice with the same data
     * SHALL produce zero DOM mutations on the second call for all rows.
     */
    fc.assert(
      fc.property(
        fc.array(testRowArb, { minLength: 1, maxLength: 10 }).map(rows => {
          // Ensure unique codes for keyFn
          const seen = new Set<string>()
          return rows.filter(r => {
            if (seen.has(r.code)) return false
            seen.add(r.code)
            return true
          })
        }).filter(rows => rows.length > 0),
        (rows) => {
          const table = createDataTable<TestRow>({
            columns: stringColumns,
            virtualScroll: true,
            keyFn: (r) => r.code,
            rowHeight: 32,
          })
          container.appendChild(table.el)

          // First render
          table.updateRows(rows)

          // Get all rendered row elements
          const rowEls = table.el.querySelectorAll('.data-table-row')
          expect(rowEls.length).toBeGreaterThan(0)

          // Second render with same data — count total mutations across all rows
          let totalMutations = 0
          const observer = new MutationObserver((mutations) => {
            // Filter out mutations that are not related to row content
            for (const m of mutations) {
              // Only count mutations within data-table-row elements
              const target = m.target as HTMLElement
              if (target.closest?.('.data-table-row')) {
                totalMutations++
              }
            }
          })
          observer.observe(table.el, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
          })

          table.updateRows(rows)

          observer.disconnect()

          expect(totalMutations).toBe(0)

          table.destroy()
        },
      ),
      { numRuns: 50 },
    )
  })
})
