// frontend/src/pages/stock-detail.ts
// 종목상세 페이지 — 5일봉 거래대금/고가 배열 테이블

import type { PageModule } from '../router'
import { api } from '../api/client'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createCardTitle } from '../components/common/card-title'
import { FONT_SIZE, FONT_WEIGHT, COLOR, fmtComma } from '../components/common/ui-styles'

interface StockDetail5dItem {
  code: string
  name: string
  day1_amount: number | null
  day2_amount: number | null
  day3_amount: number | null
  day4_amount: number | null
  day5_amount: number | null
  day1_high: number | null
  day2_high: number | null
  day3_high: number | null
  day4_high: number | null
  day5_high: number | null
}

interface StockDetail5dResponse {
  date: string
  items: StockDetail5dItem[]
}

let tableRef: DataTableApi<StockDetail5dItem> | null = null
let searchInputRef: ReturnType<typeof createSearchInput> | null = null
let allItems: StockDetail5dItem[] = []
let searchQuery = ''

function fmtAmount(v: number | null): string {
  if (v === null || v === undefined) return '-'
  return (v / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

function fmtHigh(v: number | null): string {
  if (v === null || v === undefined) return '-'
  return fmtComma(v)
}

function makeAmountColumn(key: string, label: string): ColumnDef<StockDetail5dItem> {
  return {
    key,
    label,
    align: 'right',
    render: (row) => fmtAmount(row[key as keyof StockDetail5dItem] as number | null),
  }
}

function makeHighColumn(key: string, label: string): ColumnDef<StockDetail5dItem> {
  return {
    key,
    label,
    align: 'right',
    render: (row) => fmtHigh(row[key as keyof StockDetail5dItem] as number | null),
  }
}

const columns: ColumnDef<StockDetail5dItem>[] = [
  { key: 'code', label: '종목코드', align: 'center', minWidth: 72, maxWidth: 72, render: (row) => row.code },
  { key: 'name', label: '종목명', align: 'left', minWidth: 80, render: (row) => row.name },
  makeAmountColumn('day1_amount', '당일 거래대금(억)'),
  makeAmountColumn('day2_amount', '직전1일(억)'),
  makeAmountColumn('day3_amount', '직전2일(억)'),
  makeAmountColumn('day4_amount', '직전3일(억)'),
  makeAmountColumn('day5_amount', '직전4일(억)'),
  makeHighColumn('day1_high', '당일 고가'),
  makeHighColumn('day2_high', '직전1일 고가'),
  makeHighColumn('day3_high', '직전2일 고가'),
  makeHighColumn('day4_high', '직전3일 고가'),
  makeHighColumn('day5_high', '직전4일 고가'),
]

function applySearchFilter(): void {
  if (!tableRef) return
  const q = searchQuery.toLowerCase()
  if (!q) {
    tableRef.updateRows(allItems)
    return
  }
  const matched = allItems.filter(
    (item) => item.code.toLowerCase().includes(q) || item.name.toLowerCase().includes(q),
  )
  tableRef.updateRows(matched)
}

function rowStyle(row: StockDetail5dItem): Partial<CSSStyleDeclaration> | undefined {
  if (!searchQuery) return undefined
  const q = searchQuery.toLowerCase()
  const isMatch = row.code.toLowerCase().includes(q) || row.name.toLowerCase().includes(q)
  if (isMatch) {
    return { background: COLOR.warningBg }
  }
  return { opacity: '0.4' }
}

function mount(container: HTMLElement): void {
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  root.appendChild(createCardTitle('종목상세'))

  // 기준일 + 검색 입력란
  const headerBar = document.createElement('div')
  Object.assign(headerBar.style, {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    marginBottom: '8px',
    flexShrink: '0',
  })

  const dateLabel = document.createElement('span')
  Object.assign(dateLabel.style, {
    fontSize: FONT_SIZE.label,
    color: COLOR.secondary,
    fontWeight: FONT_WEIGHT.normal,
    flexShrink: '0',
    whiteSpace: 'nowrap',
  })
  dateLabel.textContent = '기준일: -'
  headerBar.appendChild(dateLabel)

  const searchWrapper = document.createElement('div')
  Object.assign(searchWrapper.style, { flex: '1', maxWidth: '400px' })

  searchInputRef = createSearchInput({
    placeholder: '종목명 또는 코드 검색',
    onSearch: (query) => {
      searchQuery = query
      applySearchFilter()
    },
  })
  searchWrapper.appendChild(searchInputRef.el)
  headerBar.appendChild(searchWrapper)

  root.appendChild(headerBar)

  // 테이블
  tableRef = createDataTable<StockDetail5dItem>({
    columns,
    virtualScroll: false,
    keyFn: (row) => row.code,
    stickyHeader: true,
    emptyText: '데이터가 없습니다.',
    rowStyle,
    zebraStriping: true,
  })
  Object.assign(tableRef.el.style, { flex: '1', minHeight: '0' })
  root.appendChild(tableRef.el)

  container.appendChild(root)

  // 데이터 로드
  api.getStockDetail5d().then((data: StockDetail5dResponse) => {
    allItems = data.items
    if (data.date) {
      dateLabel.textContent = `기준일: ${data.date}`
    }
    if (tableRef) {
      tableRef.updateRows(allItems)
    }
  }).catch((err) => {
    console.error('[stock-detail] 데이터 로드 실패:', err)
  })
}

function unmount(): void {
  if (tableRef) {
    tableRef.destroy()
    tableRef = null
  }
  if (searchInputRef) {
    searchInputRef.clear()
    searchInputRef = null
  }
  allItems = []
  searchQuery = ''
}

export default { mount, unmount } satisfies PageModule
