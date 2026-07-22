// frontend/src/pages/stock-detail.ts
// 종목상세 페이지 — 5일봉 거래대금/고가 배열 테이블

import type { PageModule } from '../router'
import { api } from '../api/client'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createCardTitle } from '../components/common/card-title'
import { createMarketCountRow, type MarketCountRowHandle } from '../components/common/market-count-row'
import { FONT_SIZE, FONT_WEIGHT, COLOR, fmtComma, createStockNameColumn, createSeqCell } from '../components/common/ui-styles'

interface StockDetail5dBar {
  dt: string
  trade_amount: number | null
  high_price: number | null
}

interface StockDetail5dItem {
  code: string
  name: string
  market_type: string
  nxt_enable: boolean
  bars: StockDetail5dBar[]
}

interface StockDetail5dResponse {
  date: string
  items: StockDetail5dItem[]
}

let tableRef: DataTableApi<StockDetail5dItem> | null = null
let searchInputRef: ReturnType<typeof createSearchInput> | null = null
let allItems: StockDetail5dItem[] = []
let searchQuery = ''
let summaryRow: MarketCountRowHandle | null = null
let _mounted = false

function fmtAmount(v: number | null): string {
  if (v === null || v === undefined) return '-'
  return (v / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

function fmtHigh(v: number | null): string {
  if (v === null || v === undefined) return '-'
  return fmtComma(v)
}

/** 날짜(파랑) + 접미사(검정)로 구성된 헤더 HTMLElement 생성. */
function makeDateHeader(dateLabel: string, suffix: string): HTMLElement {
  const frag = document.createElement('span')
  const dateSpan = document.createElement('span')
  Object.assign(dateSpan.style, { color: COLOR.down })
  dateSpan.textContent = dateLabel
  frag.appendChild(dateSpan)
  frag.appendChild(document.createTextNode(suffix))
  return frag
}

function makeAmountColumn(idx: number, label: HTMLElement): ColumnDef<StockDetail5dItem> {
  return {
    key: `amt${idx}`,
    label,
    align: 'right',
    type: 'amount',
    render: (row) => fmtAmount(row.bars[idx]?.trade_amount ?? null),
  }
}

function makeHighColumn(idx: number, label: HTMLElement): ColumnDef<StockDetail5dItem> {
  return {
    key: `high${idx}`,
    label,
    align: 'right',
    type: 'high',
    render: (row) => fmtHigh(row.bars[idx]?.high_price ?? null),
  }
}

/** "YYYY-MM-DD" 또는 "YYYYMMDD" → "MM-DD" 단축 날짜. 형식 불일치 시 원본 그대로 반환. */
function shortDate(dt: string): string {
  const m = dt.match(/^\d{4}-?(\d{2})-?(\d{2})$/)
  return m ? `${m[1]}-${m[2]}` : dt
}

/** 첫 종목 bars에서 5개 날짜를 추출해 컬럼 배열 동적 생성. */
function buildColumns(sampleBars: StockDetail5dBar[]): ColumnDef<StockDetail5dItem>[] {
  const nameCol = createStockNameColumn<StockDetail5dItem>(
    (item) => ({ name: item.name, market_type: item.market_type || undefined, nxt_enable: item.nxt_enable })
  )
  nameCol.minWidth = 53
  nameCol.maxWidth = 133
  const cols: ColumnDef<StockDetail5dItem>[] = [
    { key: 'seq', label: '순번', align: 'center', type: 'seq', render: (_t, idx) => createSeqCell(idx + 1) },
    { key: 'code', label: '종목코드', align: 'center', type: 'code', render: (row) => row.code },
    nameCol,
  ]
  for (let i = 0; i < 5; i++) {
    const dt = sampleBars[i]?.dt ?? ''
    const dateLabel = dt ? shortDate(dt) : (i === 0 ? '당일' : `직전${i}일`)
    cols.push(makeAmountColumn(i, makeDateHeader(dateLabel, ' 거래대금(억)')))
  }
  for (let i = 0; i < 5; i++) {
    const dt = sampleBars[i]?.dt ?? ''
    const dateLabel = dt ? shortDate(dt) : (i === 0 ? '당일' : `직전${i}일`)
    cols.push(makeHighColumn(i, makeDateHeader(dateLabel, ' 고가')))
  }
  return cols
}

function updateSummary(items: StockDetail5dItem[]): void {
  if (!summaryRow) return
  const total = items.length
  const krx = items.filter(s => !s.nxt_enable).length
  const nxt = items.filter(s => s.nxt_enable).length
  const kospi = items.filter(s => s.market_type === '0').length
  const kosdaq = items.filter(s => s.market_type === '10').length
  summaryRow.updateCounts({ total, krx, nxt, kospi, kosdaq })
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
  _mounted = true
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

  // 합계 정보 바 — 공통 컴포넌트 (sector-stock.ts 동일 패턴, P23 일관성)
  summaryRow = createMarketCountRow()
  Object.assign(summaryRow.el.style, {
    marginBottom: '8px',
    flexShrink: '0',
    fontSize: FONT_SIZE.label,
    fontWeight: FONT_WEIGHT.normal,
  })
  root.appendChild(summaryRow.el)

  // 테이블 자리 (데이터 로드 후 실제 날짜 라벨 컬럼으로 생성)
  const tableSlot = document.createElement('div')
  Object.assign(tableSlot.style, { flex: '1', minHeight: '0' })
  root.appendChild(tableSlot)

  container.appendChild(root)

  // 데이터 로드 → 날짜 라벨 컬럼 생성 → 테이블 생성
  // _mounted 가드: 페이지 이탈 후 비동기 콜백 실행 시 DOM 조작/DataTable 생성 차단 (P19)
  api.getStockDetail5d().then((data: StockDetail5dResponse) => {
    if (!_mounted) return
    allItems = data.items
    if (data.date) {
      dateLabel.textContent = `기준일: ${data.date}`
    }
    const sampleBars = allItems[0]?.bars ?? []
    const columns = buildColumns(sampleBars)
    tableRef = createDataTable<StockDetail5dItem>({
      columns,
      virtualScroll: false,
      keyFn: (row) => row.code,
      stickyHeader: true,
      emptyText: '데이터가 없습니다.',
      zebraStriping: true,
      rowStyle: (_row, _idx) => searchQuery
        ? { background: COLOR.downBg }
        : { background: '' },
    })
    Object.assign(tableRef.el.style, { flex: '1', minHeight: '0' })
    tableSlot.appendChild(tableRef.el)
    tableRef.updateRows(allItems)
    updateSummary(allItems)
  }).catch((err) => {
    if (!_mounted) return
    console.error('[stock-detail] 데이터 로드 실패:', err)
    const errEl = document.createElement('div')
    Object.assign(errEl.style, {
      flex: '1', minHeight: '0', display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: COLOR.down, fontSize: FONT_SIZE.label,
    })
    errEl.textContent = '데이터를 불러오지 못했습니다.'
    tableSlot.appendChild(errEl)
  })
}

function unmount(): void {
  _mounted = false
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
  summaryRow = null
}

export default { mount, unmount } satisfies PageModule
