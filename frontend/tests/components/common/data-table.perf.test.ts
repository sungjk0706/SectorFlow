/**
 * DataTable 성능 테스트
 *
 * 대량 데이터 렌더링 성능 측정 (performance.now() 사용)
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createDataTable, type ColumnDef } from '../../../src/components/common/data-table'

/* ── 테스트 데이터 타입 ── */

interface PerfRow {
  code: string
  name: string
  price: number
  change: string
  rate: string
}

/* ── 컬럼 정의 ── */

const columns: ColumnDef<PerfRow>[] = [
  { key: 'code', label: '코드', align: 'left', render: (row) => row.code },
  { key: 'name', label: '이름', align: 'left', render: (row) => row.name },
  { key: 'price', label: '가격', align: 'right', render: (row) => String(row.price) },
  { key: 'change', label: '등락', align: 'right', render: (row) => row.change },
  { key: 'rate', label: '등락률', align: 'right', render: (row) => row.rate },
]

/* ── 테스트 데이터 생성 ── */

function generateRows(count: number): PerfRow[] {
  const rows: PerfRow[] = []
  for (let i = 0; i < count; i++) {
    rows.push({
      code: String(i).padStart(6, '0'),
      name: `종목${i}`,
      price: 10000 + Math.random() * 50000,
      change: (Math.random() * 1000 - 500).toFixed(2),
      rate: (Math.random() * 10 - 5).toFixed(2),
    })
  }
  return rows
}

/* ── 성능 테스트 ── */

describe('DataTable Performance Test', () => {
  let container: HTMLElement

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
  })

  afterEach(() => {
    document.body.removeChild(container)
  })

  describe('고정 모드 (virtualScroll: false)', () => {
    it('100행 렌더링 < 500ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: false,
        keyFn: (row) => row.code,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(100))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(500)
    })

    it('500행 렌더링 < 1500ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: false,
        keyFn: (row) => row.code,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(500))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(1500)
    })

    it('1000행 렌더링 < 2000ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: false,
        keyFn: (row) => row.code,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(1000))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(2000)
    })

    it('100행 업데이트 (고정 스크롤) < 50ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: false,
        keyFn: (row) => row.code,
      })
      container.appendChild(table.el)
      table.updateRows(generateRows(100))

      const start = performance.now()
      table.updateRows(generateRows(100))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(50)
    })
  })

  describe('가상 스크롤 모드 (virtualScroll: true)', () => {
    it('100행 렌더링 < 50ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: true,
        keyFn: (row) => row.code,
        rowHeight: 32,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(100))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(50)
    })

    it('500행 렌더링 < 100ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: true,
        keyFn: (row) => row.code,
        rowHeight: 32,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(500))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(100)
    })

    it('1000행 렌더링 < 200ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: true,
        keyFn: (row) => row.code,
        rowHeight: 32,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(1000))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(200)
    })

    it('5000행 렌더링 < 500ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: true,
        keyFn: (row) => row.code,
        rowHeight: 32,
      })
      container.appendChild(table.el)

      const start = performance.now()
      table.updateRows(generateRows(5000))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(500)
    })
  })

  describe('업데이트 성능', () => {
    it('100행 업데이트 (가상 스크롤) < 50ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: true,
        keyFn: (row) => row.code,
        rowHeight: 32,
      })
      container.appendChild(table.el)
      table.updateRows(generateRows(100))

      const start = performance.now()
      table.updateRows(generateRows(100))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(50)
    })

    it('1000행 업데이트 (가상 스크롤) < 200ms', () => {
      const table = createDataTable<PerfRow>({
        columns,
        virtualScroll: true,
        keyFn: (row) => row.code,
        rowHeight: 32,
      })
      container.appendChild(table.el)
      table.updateRows(generateRows(1000))

      const start = performance.now()
      table.updateRows(generateRows(1000))
      const end = performance.now()

      table.destroy()
      expect(end - start).toBeLessThan(200)
    })
  })
})
