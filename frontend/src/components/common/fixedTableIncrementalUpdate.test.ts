/**
 * Property 7: FixedTable Incremental Update (rowKey 기반 증분 갱신)
 *
 * Feature: hts-level-optimization, Property 7: FixedTable Incremental Update
 *
 * **Validates: Requirements 7.1, 7.2, 7.3**
 *
 * For any two consecutive row arrays oldRows and newRows, after updateRows(newRows):
 * (a) rows with keys in newRows but not oldRows have new DOM nodes inserted
 * (b) rows with keys in oldRows but not newRows have their DOM nodes removed
 * (c) rows with keys in both have only changed cells updated (cell-level diff)
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { createFixedTable, type ColDef, type TableRow } from './fixed-table'

/* ── Test row type ── */
interface TestRow {
  id: string
  name: string
  value: number
}

/* ── Column definitions for testing ── */
const testColumns: ColDef<TestRow>[] = [
  { key: 'id', label: 'ID', width: '80px', render: (row) => row.id },
  { key: 'name', label: 'Name', width: '120px', render: (row) => row.name },
  { key: 'value', label: 'Value', width: '100px', align: 'right', render: (row) => String(row.value) },
]

/* ── Generators ── */

/** Generator: a single TestRow with a given id */
const testRowArb = (id: string): fc.Arbitrary<TestRow> =>
  fc.record({
    id: fc.constant(id),
    name: fc.string({ minLength: 1, maxLength: 8 }),
    value: fc.integer({ min: 0, max: 999999 }),
  })

/** Generator: array of TestRows with unique ids */
const testRowsArrayArb: fc.Arbitrary<TestRow[]> = fc
  .uniqueArray(fc.stringMatching(/^[A-Z][0-9]{3}$/), { minLength: 0, maxLength: 20 })
  .chain((ids) => {
    if (ids.length === 0) return fc.constant([] as TestRow[])
    return fc.tuple(...ids.map((id) => testRowArb(id))) as fc.Arbitrary<TestRow[]>
  })

/** Generator: pair of old/new row arrays with overlapping keys */
const oldNewRowsPairArb: fc.Arbitrary<{ oldRows: TestRow[]; newRows: TestRow[] }> = fc
  .uniqueArray(fc.stringMatching(/^[A-Z][0-9]{3}$/), { minLength: 1, maxLength: 30 })
  .chain((allIds) => {
    // Split ids into: only-old, only-new, shared
    const n = allIds.length
    return fc
      .tuple(
        fc.array(fc.boolean(), { minLength: n, maxLength: n }), // in old?
        fc.array(fc.boolean(), { minLength: n, maxLength: n }), // in new?
      )
      .chain(([inOld, inNew]) => {
        // Ensure at least one row in old and one in new
        const oldIds = allIds.filter((_, i) => inOld[i] || (!inOld[i] && !inNew[i]))
        const newIds = allIds.filter((_, i) => inNew[i] || (!inOld[i] && !inNew[i]))
        // Guarantee non-empty arrays
        const finalOldIds = oldIds.length > 0 ? oldIds : [allIds[0]]
        const finalNewIds = newIds.length > 0 ? newIds : [allIds[0]]

        const oldRowsArb =
          finalOldIds.length === 0
            ? fc.constant([] as TestRow[])
            : (fc.tuple(...finalOldIds.map((id) => testRowArb(id))) as fc.Arbitrary<TestRow[]>)
        const newRowsArb =
          finalNewIds.length === 0
            ? fc.constant([] as TestRow[])
            : (fc.tuple(...finalNewIds.map((id) => testRowArb(id))) as fc.Arbitrary<TestRow[]>)

        return fc.tuple(oldRowsArb, newRowsArb).map(([oldRows, newRows]) => ({
          oldRows,
          newRows,
        }))
      })
  })

/* ── Helper: create a FixedTable instance for testing ── */
function createTestTable() {
  return createFixedTable<TestRow>({
    columns: testColumns,
    rowKey: (row) => row.id,
  })
}

/* ── Helper: get all row keys currently in the tbody ── */
function getRenderedKeys(tableEl: HTMLElement): string[] {
  const tbody = tableEl.querySelector('tbody')!
  const keys: string[] = []
  for (const tr of Array.from(tbody.children)) {
    const key = (tr as HTMLElement).dataset.rowKey
    if (key) keys.push(key)
  }
  return keys
}

/* ── Helper: get cell text content for a row by key ── */
function getCellTexts(tableEl: HTMLElement, rowKey: string): string[] {
  const tbody = tableEl.querySelector('tbody')!
  for (const tr of Array.from(tbody.children)) {
    if ((tr as HTMLElement).dataset.rowKey === rowKey) {
      return Array.from(tr.children).map((td) => td.textContent || '')
    }
  }
  return []
}

describe('Property 7: FixedTable Incremental Update (rowKey 기반 증분 갱신)', () => {
  it('newly inserted rows appear in DOM after updateRows', () => {
    /**
     * **Validates: Requirements 7.1**
     *
     * For any old/new row arrays, rows with keys in newRows but not oldRows
     * have new DOM nodes inserted.
     */
    fc.assert(
      fc.property(oldNewRowsPairArb, ({ oldRows, newRows }) => {
        const table = createTestTable()
        document.body.appendChild(table.el)

        try {
          // Initial render (triggers _initialLoaded)
          table.updateRows(oldRows as TableRow<TestRow>[])

          // Incremental update
          table.updateRows(newRows as TableRow<TestRow>[])

          const renderedKeys = getRenderedKeys(table.el)
          const oldKeySet = new Set(oldRows.map((r) => r.id))

          // All new rows that were NOT in old should now be in DOM
          for (const row of newRows) {
            if (!oldKeySet.has(row.id)) {
              expect(renderedKeys).toContain(row.id)
            }
          }
        } finally {
          table.destroy()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('removed rows are deleted from DOM after updateRows', () => {
    /**
     * **Validates: Requirements 7.2**
     *
     * For any old/new row arrays, rows with keys in oldRows but not newRows
     * have their DOM nodes removed.
     */
    fc.assert(
      fc.property(oldNewRowsPairArb, ({ oldRows, newRows }) => {
        const table = createTestTable()
        document.body.appendChild(table.el)

        try {
          // Initial render
          table.updateRows(oldRows as TableRow<TestRow>[])

          // Incremental update
          table.updateRows(newRows as TableRow<TestRow>[])

          const renderedKeys = getRenderedKeys(table.el)
          const newKeySet = new Set(newRows.map((r) => r.id))

          // All old rows that are NOT in new should be removed from DOM
          for (const row of oldRows) {
            if (!newKeySet.has(row.id)) {
              expect(renderedKeys).not.toContain(row.id)
            }
          }
        } finally {
          table.destroy()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('existing rows with changed data have only cells updated (cell-level diff)', () => {
    /**
     * **Validates: Requirements 7.3**
     *
     * For any old/new row arrays, rows with keys in both have only changed
     * cells updated — the tr element reference is preserved.
     */
    fc.assert(
      fc.property(oldNewRowsPairArb, ({ oldRows, newRows }) => {
        const table = createTestTable()
        document.body.appendChild(table.el)

        try {
          // Initial render
          table.updateRows(oldRows as TableRow<TestRow>[])

          // Capture tr element references for shared keys
          const oldKeySet = new Set(oldRows.map((r) => r.id))
          const newKeySet = new Set(newRows.map((r) => r.id))
          const sharedKeys = [...oldKeySet].filter((k) => newKeySet.has(k))

          const trRefs = new Map<string, Element>()
          const tbody = table.el.querySelector('tbody')!
          for (const tr of Array.from(tbody.children)) {
            const key = (tr as HTMLElement).dataset.rowKey
            if (key && sharedKeys.includes(key)) {
              trRefs.set(key, tr)
            }
          }

          // Incremental update
          table.updateRows(newRows as TableRow<TestRow>[])

          // For shared keys: tr element reference should be preserved (same DOM node)
          for (const key of sharedKeys) {
            const oldTr = trRefs.get(key)
            // Find current tr with this key
            let currentTr: Element | null = null
            for (const tr of Array.from(tbody.children)) {
              if ((tr as HTMLElement).dataset.rowKey === key) {
                currentTr = tr
                break
              }
            }
            expect(currentTr).toBe(oldTr)
          }

          // For shared keys: cell content should match new data
          for (const newRow of newRows) {
            if (oldKeySet.has(newRow.id)) {
              const cellTexts = getCellTexts(table.el, newRow.id)
              expect(cellTexts[0]).toBe(newRow.id)
              expect(cellTexts[1]).toBe(newRow.name)
              expect(cellTexts[2]).toBe(String(newRow.value))
            }
          }
        } finally {
          table.destroy()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('after updateRows, DOM contains exactly the new rows in correct order', () => {
    /**
     * **Validates: Requirements 7.1, 7.2, 7.3**
     *
     * Combined property: after incremental update, the rendered DOM should
     * contain exactly the keys from newRows in the correct order.
     */
    fc.assert(
      fc.property(oldNewRowsPairArb, ({ oldRows, newRows }) => {
        const table = createTestTable()
        document.body.appendChild(table.el)

        try {
          // Initial render
          table.updateRows(oldRows as TableRow<TestRow>[])

          // Incremental update
          table.updateRows(newRows as TableRow<TestRow>[])

          const renderedKeys = getRenderedKeys(table.el)
          const expectedKeys = newRows.map((r) => r.id)

          // DOM should contain exactly the new rows
          expect(renderedKeys).toEqual(expectedKeys)

          // Each row's cell content should match the new data
          for (const row of newRows) {
            const cellTexts = getCellTexts(table.el, row.id)
            expect(cellTexts[0]).toBe(row.id)
            expect(cellTexts[1]).toBe(row.name)
            expect(cellTexts[2]).toBe(String(row.value))
          }
        } finally {
          table.destroy()
        }
      }),
      { numRuns: 100 },
    )
  })
})
