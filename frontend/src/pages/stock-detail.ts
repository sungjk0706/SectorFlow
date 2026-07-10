// frontend/src/pages/stock-detail.ts
// 종목상세 페이지 — 5일봉 거래대금/고가 배열 테이블

import type { PageModule } from '../router'
import { api } from '../api/client'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createCardTitle } from '../components/common/card-title'
import { FONT_SIZE, FONT_WEIGHT, COLOR, fmtComma, createStockNameColumn, createSeqCell } from '../components/common/ui-styles'

interface StockDetail5dItem {
  code: string
  name: string
  market_type: string
  nxt_enable: boolean
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
let summaryEls: {
  total: HTMLSpanElement
  krx: HTMLSpanElement
  nxt: HTMLSpanElement
  kospi: HTMLSpanElement
  kosdaq: HTMLSpanElement
} | null = null

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
  { key: 'seq', label: '순번', align: 'center', minWidth: 36, maxWidth: 36, render: (_t, idx) => createSeqCell(idx + 1) },
  { key: 'code', label: '종목코드', align: 'center', minWidth: 72, maxWidth: 72, render: (row) => row.code },
  createStockNameColumn<StockDetail5dItem>(
    (item) => ({ name: item.name, market_type: item.market_type || undefined, nxt_enable: item.nxt_enable })
  ),
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

function updateSummary(items: StockDetail5dItem[]): void {
  if (!summaryEls) return
  const total = items.length
  const krx = items.filter(s => !s.nxt_enable).length
  const nxt = items.filter(s => s.nxt_enable).length
  const kospi = items.filter(s => s.market_type === '0').length
  const kosdaq = items.filter(s => s.market_type === '10').length
  summaryEls.total.textContent = String(total)
  summaryEls.krx.textContent = String(krx)
  summaryEls.nxt.textContent = String(nxt)
  summaryEls.kospi.textContent = String(kospi)
  summaryEls.kosdaq.textContent = String(kosdaq)
}

function applySearchFilter(): void {
  if (!tableRef) return
  const q = searchQuery.trim().toLowerCase()
  if (!q) {
    tableRef.updateRows(allItems)
    updateSummary(allItems)
    return
  }
  const filtered = allItems.filter(
    (item) => item.code.toLowerCase().includes(q) || item.name.toLowerCase().includes(q)
  )
  tableRef.updateRows(filtered)
  updateSummary(filtered)
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
    color: COLOR.tertiary,
    fontWeight: FONT_WEIGHT.normal,
    flexShrink: '0',
    whiteSpace: 'nowrap',
  })
  dateLabel.textContent = '기준일: -'
  headerBar.appendChild(dateLabel)

  const searchWrapper = document.createElement('div')
  Object.assign(searchWrapper.style, { flex: '1', maxWidth: '400px' })

  searchInputRef = createSearchInput({
    label: '종목명/코드',
    labelColor: COLOR.down,
    placeholder: '종목명/코드 검색',
    borderColor: COLOR.down,
    onSearch: (query) => {
      searchQuery = query
      applySearchFilter()
    },
  })
  searchWrapper.appendChild(searchInputRef.el)
  headerBar.appendChild(searchWrapper)

  root.appendChild(headerBar)

  // 합계 정보 바
  const summaryBar = document.createElement('div')
  Object.assign(summaryBar.style, {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    marginBottom: '8px',
    flexShrink: '0',
    fontSize: FONT_SIZE.label,
    fontWeight: FONT_WEIGHT.normal,
  })

  function appendSummaryItem(label: string, labelColor: string): HTMLSpanElement {
    const text = document.createElement('span')
    Object.assign(text.style, { color: labelColor })
    text.textContent = label
    summaryBar.appendChild(text)
    const numSpan = document.createElement('span')
    Object.assign(numSpan.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.semibold })
    summaryBar.appendChild(numSpan)
    const suffix = document.createElement('span')
    Object.assign(suffix.style, { color: COLOR.neutral })
    suffix.textContent = '종목'
    summaryBar.appendChild(suffix)
    return numSpan
  }

  const totalSpan = appendSummaryItem('합계:', COLOR.neutral)
  const krxSpan = appendSummaryItem(' KRX:', COLOR.neutral)

  // NXT: 삼각이모지가 콜론과 숫자 사이에 위치하도록 수동 빌드
  const nxtLabel = document.createElement('span')
  Object.assign(nxtLabel.style, { color: COLOR.up })
  nxtLabel.textContent = ' NXT:'
  summaryBar.appendChild(nxtLabel)
  const nxtTri = document.createElement('span')
  Object.assign(nxtTri.style, {
    display: 'inline-block',
    width: '0',
    height: '0',
    borderLeft: '5px solid transparent',
    borderBottom: `5px solid ${COLOR.up}`,
    marginRight: '3px',
    verticalAlign: 'middle',
  })
  summaryBar.appendChild(nxtTri)
  const nxtSpan = document.createElement('span')
  Object.assign(nxtSpan.style, { color: COLOR.down, fontWeight: FONT_WEIGHT.semibold })
  summaryBar.appendChild(nxtSpan)
  const nxtSuffix = document.createElement('span')
  Object.assign(nxtSuffix.style, { color: COLOR.neutral })
  nxtSuffix.textContent = '종목'
  summaryBar.appendChild(nxtSuffix)

  const kospiSpan = appendSummaryItem(' 코스피:', COLOR.neutral)
  const kosdaqSpan = appendSummaryItem(' 코스닥:', COLOR.kosdaq)
  summaryEls = { total: totalSpan, krx: krxSpan, nxt: nxtSpan, kospi: kospiSpan, kosdaq: kosdaqSpan }

  root.appendChild(summaryBar)

  // 테이블
  tableRef = createDataTable<StockDetail5dItem>({
    columns,
    virtualScroll: false,
    keyFn: (row) => row.code,
    stickyHeader: true,
    emptyText: '데이터가 없습니다.',
    zebraStriping: true,
    rowStyle: (_row, _idx) => searchQuery
      ? { outline: `2px solid ${COLOR.down}` }
      : { outline: 'none' },
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
    updateSummary(allItems)
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
  summaryEls = null
}

export default { mount, unmount } satisfies PageModule
