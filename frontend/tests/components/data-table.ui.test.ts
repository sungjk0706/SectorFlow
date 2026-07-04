import { describe, it, expect, beforeEach } from 'vitest'
import { createDataTable, type ColumnDef } from '../../src/components/common/data-table'

interface TestRow {
  name: string
  price: number
  change: number
}

const COLUMNS: ColumnDef<TestRow>[] = [
  { key: 'name', label: '종목명', align: 'left', render: (r) => r.name },
  { key: 'price', label: '현재가', align: 'right', render: (r) => String(r.price) },
  { key: 'change', label: '등락', align: 'center', render: (r) => `${r.change > 0 ? '+' : ''}${r.change}%` },
]

const TEST_DATA: TestRow[] = [
  { name: '삼성전자', price: 70000, change: 2.5 },
  { name: 'SK하이닉스', price: 120000, change: -1.0 },
  { name: '삼성전기', price: 90000, change: 0.5 },
]

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('createDataTable — fixed mode', () => {
  it('creates wrapper element', () => {
    const table = createDataTable({ columns: COLUMNS })
    expect(table.el).toBeTruthy()
    expect(table.el.tagName).toBe('DIV')
  })

  it('renders column headers', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    const headers = table.el.querySelectorAll('th')
    expect(headers.length).toBe(3)
    expect(headers[0].textContent).toBe('종목명')
    expect(headers[1].textContent).toBe('현재가')
    expect(headers[2].textContent).toBe('등락')
  })

  it('shows empty text when no rows', () => {
    const table = createDataTable({ columns: COLUMNS, emptyText: '데이터 없음' })
    document.body.appendChild(table.el)
    table.updateRows([])
    expect(table.el.textContent).toContain('데이터 없음')
  })

  it('renders data rows after updateRows', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    table.updateRows(TEST_DATA)
    const dataRows = table.el.querySelectorAll('tr[data-row-type="data"]')
    expect(dataRows.length).toBe(3)
  })

  it('renders cell content from render function', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    table.updateRows(TEST_DATA)
    const dataRows = table.el.querySelectorAll('tr[data-row-type="data"]')
    const firstRowCells = dataRows[0].querySelectorAll('td')
    expect(firstRowCells[0].textContent).toBe('삼성전자')
    expect(firstRowCells[1].textContent).toBe('70000')
    expect(firstRowCells[2].textContent).toBe('+2.5%')
  })

  it('renders group rows with label', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    table.updateRows([
      { type: 'group', label: '반도체', key: 'semi' },
      ...TEST_DATA,
    ])
    const groupRows = table.el.querySelectorAll('tr[data-row-type="group"]')
    expect(groupRows.length).toBe(1)
    expect(groupRows[0].textContent).toContain('반도체')
  })

  it('renders group row with score when provided', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    table.updateRows([
      { type: 'group', label: '반도체', key: 'semi', score: 85.5 },
      ...TEST_DATA,
    ])
    const groupRow = table.el.querySelector('tr[data-row-type="group"]')!
    expect(groupRow.textContent).toContain('85.5')
  })

  it('applies zebra striping when enabled', () => {
    const table = createDataTable({ columns: COLUMNS, zebraStriping: true })
    document.body.appendChild(table.el)
    table.updateRows(TEST_DATA)
    const dataRows = table.el.querySelectorAll<HTMLElement>('tr[data-row-type="data"]')
    expect(dataRows[1].style.backgroundColor).toBe('#f9f9f9')
    expect(dataRows[0].style.backgroundColor).not.toBe('#f9f9f9')
  })

  it('applies custom rowStyle', () => {
    const table = createDataTable({
      columns: COLUMNS,
      rowStyle: (row) => ({ color: row.change > 0 ? 'red' : 'blue' }),
    })
    document.body.appendChild(table.el)
    table.updateRows(TEST_DATA)
    const dataRows = table.el.querySelectorAll<HTMLElement>('tr[data-row-type="data"]')
    expect(dataRows[0].style.color).toBe('red')
    expect(dataRows[1].style.color).toBe('blue')
  })

  it('replaces rows on subsequent updateRows call', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    table.updateRows(TEST_DATA)
    table.updateRows([{ name: '새종목', price: 5000, change: 3.0 }])
    const visibleRows = table.el.querySelectorAll<HTMLElement>('tr[data-row-type="data"]')
    const visible = Array.from(visibleRows).filter(r => r.style.display !== 'none')
    expect(visible.length).toBe(1)
    expect(visible[0].textContent).toContain('새종목')
  })

  it('destroy removes element from DOM', () => {
    const table = createDataTable({ columns: COLUMNS })
    document.body.appendChild(table.el)
    expect(document.body.contains(table.el)).toBe(true)
    table.destroy()
    expect(document.body.contains(table.el)).toBe(false)
  })

  it('renders HTMLElement returned from render function', () => {
    const customColumns: ColumnDef<TestRow>[] = [
      { key: 'name', label: '종목명', align: 'left', render: (r) => {
        const span = document.createElement('span')
        span.textContent = r.name
        span.className = 'stock-name'
        return span
      }},
    ]
    const table = createDataTable({ columns: customColumns })
    document.body.appendChild(table.el)
    table.updateRows(TEST_DATA)
    const nameEl = table.el.querySelector('.stock-name')
    expect(nameEl).toBeTruthy()
    expect(nameEl?.textContent).toBe('삼성전자')
  })
})

describe('createDataTable — virtual scroll mode', () => {
  it('throws when virtualScroll is true but keyFn is missing', () => {
    expect(() => createDataTable({
      columns: COLUMNS,
      virtualScroll: true,
    })).toThrow('keyFn')
  })

  it('creates table with keyFn', () => {
    const table = createDataTable({
      columns: COLUMNS,
      virtualScroll: true,
      keyFn: (row) => row.name,
    })
    expect(table.el).toBeTruthy()
  })
})
