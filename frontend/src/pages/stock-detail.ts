// frontend/src/pages/stock-detail.ts
// 종목상세 페이지 — 5거래일 일봉 거래대금/고가 배열 테이블

import type { PageModule } from '../router'
import { api } from '../api/client'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { virtualScrollOptions } from '../components/common/table-options'
import { createSearchInput } from '../components/common/search-input'
import { createCardTitle } from '../components/common/card-title'
import { createMarketCountRow, type MarketCountRowHandle } from '../components/common/market-count-row'
import { FONT_SIZE, FONT_WEIGHT, COLOR, fmtComma, fmtMillionsToBillion, createStockNameColumn, createSeqCell } from '../components/common/ui-styles'

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
let dateLabelRef: HTMLSpanElement | null = null
let tableSlotRef: HTMLDivElement | null = null
let tableDates: string[] = []
let loadGeneration = 0

function updateDateLabel(snapshot: StockDetail5dResponse): void {
  if (!dateLabelRef) return
  dateLabelRef.textContent = snapshot.date ? `기준일: ${shortDate(snapshot.date)}` : '기준일: -'
}

function getTableDates(items: StockDetail5dItem[]): string[] {
  return Array.from({ length: 5 }, (_, idx) => items[0]?.bars[idx]?.dt ?? '')
}

/** 자료로 테이블 생성·갱신 — 초기 조회와 재조회 시 공통 사용. */
function renderTable(): void {
  if (!tableSlotRef) return
  const nextDates = getTableDates(allItems)
  const datesChanged = tableDates.length !== nextDates.length
    || tableDates.some((date, idx) => date !== nextDates[idx])

  if (!tableRef || datesChanged) {
    if (tableRef) tableRef.destroy()
    const sampleBars = allItems[0]?.bars ?? []
    tableRef = createDataTable<StockDetail5dItem>(
      virtualScrollOptions<StockDetail5dItem>({
        columns: buildColumns(sampleBars),
        keyFn: (row) => row.code,
        emptyText: '데이터가 없습니다.',
        zebraStriping: true,
        rowStyle: (_row, _idx) => searchQuery
          ? { background: COLOR.downBg }
          : { background: '' },
      }),
    )
    Object.assign(tableRef.el.style, { flex: '1', minHeight: '0' })
    tableSlotRef.appendChild(tableRef.el)
    tableDates = nextDates
  }

  tableRef.updateRows(allItems)
  updateSummary(allItems)
}

async function loadStockDetail(): Promise<void> {
  const generation = ++loadGeneration
  try {
    const snapshot = await api.getStockDetail5d()
    if (!_mounted || generation !== loadGeneration) return
    allItems = snapshot.items
    updateDateLabel(snapshot)
    renderTable()
  } catch (error) {
    if (!_mounted || generation !== loadGeneration) return
    allItems = []
    if (tableRef) tableRef.updateRows(allItems)
    updateSummary(allItems)
    if (dateLabelRef) dateLabelRef.textContent = '자료를 불러오지 못했습니다'
    console.error('[stock-detail] 자료 조회 실패', error)
  }
}

function fmtAmount(v: number | null): string {
  if (v === null || v === undefined) return '-'
  return fmtMillionsToBillion(v)
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
  // 설계서 4.6·5.1: 종목명 없음을 종목코드로 바꾸지 않고 "이름 없음"으로 표시 (세션 7)
  const nameCol = createStockNameColumn<StockDetail5dItem>(
    (item) => ({ name: item.name || '이름 없음', market_type: item.market_type || undefined, nxt_enable: item.nxt_enable })
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
    // 설계서 4.5: 5일 자료가 부족하면 부족한 날짜는 "자료 없음"으로 구분 표시 (세션 7)
    const dateLabel = dt ? shortDate(dt) : '자료 없음'
    cols.push(makeAmountColumn(i, makeDateHeader(dateLabel, ' 거래대금')))
  }
  for (let i = 0; i < 5; i++) {
    const dt = sampleBars[i]?.dt ?? ''
    const dateLabel = dt ? shortDate(dt) : '자료 없음'
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
  dateLabelRef = dateLabel
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

  // 단위 라벨 — 헤더에서 (억) 제거에 따른 단위 표시 (P21 사용자 투명성, P23 일관성)
  const unitLabel = document.createElement('span')
  Object.assign(unitLabel.style, {
    fontSize: FONT_SIZE.label,
    color: COLOR.tertiary,
    fontWeight: FONT_WEIGHT.normal,
    flexShrink: '0',
    whiteSpace: 'nowrap',
  })
  unitLabel.textContent = '거래대금: 억 / 고가: 원'
  headerBar.appendChild(unitLabel)

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

  // 테이블 자리 (snapshot 도착 후 실제 날짜 라벨 컬럼으로 생성)
  const tableSlot = document.createElement('div')
  Object.assign(tableSlot.style, {
    display: 'flex',
    flexDirection: 'column',
    flex: '1',
    minHeight: '0',
  })
  root.appendChild(tableSlot)
  tableSlotRef = tableSlot

  container.appendChild(root)

  // 초기 자료는 종목상세 전용 저장 자료 조회로 수신 — 실시간 통신과 분리.
  void loadStockDetail()
}

function unmount(): void {
  _mounted = false
  loadGeneration++
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
  tableDates = []
  summaryRow = null
  dateLabelRef = null
  tableSlotRef = null
}

export default { mount, unmount } satisfies PageModule
