import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
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

describe('createDataTable — virtual scroll flash suppression on row recycle', () => {
  let animateMock: ReturnType<typeof vi.fn>
  let originalAnimate: unknown

  beforeEach(() => {
    // triggerFlash uses element.animate() — jsdom에 없으므로 mock 함수 직접 할당
    originalAnimate = (HTMLElement.prototype as any).animate
    animateMock = vi.fn().mockReturnValue({
      cancel: () => {},
      finished: Promise.resolve(),
      oncancel: null,
      onfinish: null,
      play: () => {},
      pause: () => {},
      reverse: () => {},
      finish: () => {},
      currentTime: null,
      startTime: null,
      playbackRate: 1,
      playState: 'finished',
      replaceState: 'active',
      timeline: null,
      id: '',
      effect: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    } as any)
    ;(HTMLElement.prototype as any).animate = animateMock
  })

  afterEach(() => {
    if (originalAnimate) {
      ;(HTMLElement.prototype as any).animate = originalAnimate
    } else {
      delete (HTMLElement.prototype as any).animate
    }
  })

  it('triggers flash when same key data changes (price update)', () => {
    const flashColumns: ColumnDef<TestRow>[] = [
      { key: 'name', label: '종목명', align: 'left', render: (r) => r.name },
      { key: 'price', label: '현재가', align: 'right', flash: true, render: (r) => String(r.price) },
    ]
    const table = createDataTable({
      columns: flashColumns,
      virtualScroll: true,
      keyFn: (row) => row.name,
    })
    document.body.appendChild(table.el)

    table.updateRows([
      { name: 'A', price: 100, change: 0 },
      { name: 'B', price: 200, change: 0 },
    ])
    // 최초 렌더링은 isFirst 경로 → 플래시 없음
    expect(animateMock).not.toHaveBeenCalled()

    // 같은 키, 가격 변경
    table.updateRows([
      { name: 'A', price: 150, change: 0 },
      { name: 'B', price: 250, change: 0 },
    ])

    // 같은 키의 데이터 변경 → 플래시 호출되어야 함
    expect(animateMock).toHaveBeenCalled()
  })

  it('does NOT trigger flash when row element is recycled for different key (scroll)', () => {
    const flashColumns: ColumnDef<TestRow>[] = [
      { key: 'name', label: '종목명', align: 'left', render: (r) => r.name },
      { key: 'price', label: '현재가', align: 'right', flash: true, render: (r) => String(r.price) },
    ]
    const table = createDataTable({
      columns: flashColumns,
      virtualScroll: true,
      keyFn: (row) => row.name,
      rowHeight: 32,
    })
    document.body.appendChild(table.el)

    // 50개 행 생성 (50 * 32 = 1600px, viewport 300px)
    const manyRows: TestRow[] = []
    for (let i = 0; i < 50; i++) {
      manyRows.push({ name: `stock-${i}`, price: 1000 + i, change: 0 })
    }
    table.updateRows(manyRows)
    // 최초 렌더링 → 플래시 없음
    expect(animateMock).not.toHaveBeenCalled()

    // 스크롤 컨테이너 찾기 (wrapper > scrollContainer)
    const scrollContainer = table.el.firstElementChild as HTMLElement
    expect(scrollContainer).toBeTruthy()

    // 스크롤을 아래로 이동 — 새로운 행들이 풀에서 재활용된 DOM 요소로 렌더링됨
    scrollContainer.scrollTop = 1200
    scrollContainer.dispatchEvent(new Event('scroll'))

    // 행 재활용으로 다른 키의 데이터가 표시되므로 플래시 없어야 함
    expect(animateMock).not.toHaveBeenCalled()
  })

  it('triggers flash on same key update after scroll recycles rows', () => {
    const flashColumns: ColumnDef<TestRow>[] = [
      { key: 'name', label: '종목명', align: 'left', render: (r) => r.name },
      { key: 'price', label: '현재가', align: 'right', flash: true, render: (r) => String(r.price) },
    ]
    const table = createDataTable({
      columns: flashColumns,
      virtualScroll: true,
      keyFn: (row) => row.name,
      rowHeight: 32,
    })
    document.body.appendChild(table.el)

    const manyRows: TestRow[] = []
    for (let i = 0; i < 50; i++) {
      manyRows.push({ name: `stock-${i}`, price: 1000 + i, change: 0 })
    }
    table.updateRows(manyRows)

    const scrollContainer = table.el.firstElementChild as HTMLElement

    // 스크롤 이동 (행 재활용 발생, 플래시 없음)
    scrollContainer.scrollTop = 1200
    scrollContainer.dispatchEvent(new Event('scroll'))
    expect(animateMock).not.toHaveBeenCalled()

    // 현재 보이는 행들의 가격을 변경하여 updateRows 호출
    const updatedRows = manyRows.map((r, i) =>
      i >= 35 && i <= 45 ? { ...r, price: r.price + 50 } : r,
    )
    animateMock.mockClear()
    table.updateRows(updatedRows)

    // 같은 키의 가격 변경 → 플래시 호출되어야 함
    expect(animateMock).toHaveBeenCalled()
  })
})
