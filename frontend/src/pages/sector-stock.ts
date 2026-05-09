// frontend/src/pages/sector-stock.ts
// 업종별 종목 실시간 시세 — Vanilla TS PageModule (DataTable 적용)

import { createDataTable, type DataTableApi, type ColumnDef, type GroupRow as DataTableGroupRow, type TableRow } from '../components/common/data-table'
import { appStore, setSelectedSector } from '../stores/appStore'
import { createStockNameColumn, makeSeqColumn, makeCodeColumn, makePriceColumn, makeChangeColumn, makeRateColumn, makeStrengthColumn, makeAmountColumn, makeAvgAmountColumn, FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import { createWsStatusBadge } from '../components/common/setting-row'
import { createCardTitleWithContent } from '../components/common/card-title'
import { createSearchInput } from '../components/common/search-input'
import type { SectorStock, SectorScoreRow } from '../types'

/* ── ColumnDef 배열 (10개 컬럼) ── */

const COLUMNS: ColumnDef<DataRowItem>[] = [
  makeSeqColumn<DataRowItem>((item) => item.seq),
  makeCodeColumn<DataRowItem>((item) => item.stock.code),
  createStockNameColumn<DataRowItem>(
    (item: DataRowItem) => ({
      name: item.stock.name,
      market_type: item.stock.market_type,
      nxt_enable: item.stock.nxt_enable
    })
  ),
  makePriceColumn<DataRowItem>(
    (item) => Number(item.stock.cur_price) || 0,
    (item) => Number(item.stock.change_rate) || 0,
  ),
  makeChangeColumn<DataRowItem>((item) => Number(item.stock.change) || 0),
  makeRateColumn<DataRowItem>((item) => Number(item.stock.change_rate) || 0),
  makeStrengthColumn<DataRowItem>((item) => parseFloat(String(item.stock.strength ?? '')) || 0),
  makeAmountColumn<DataRowItem>((item) => Number(item.stock.trade_amount) || 0),
  makeAvgAmountColumn<DataRowItem>((item) => Number(item.stock.avg_amt_5d) || 0),
]

/* ── 헬퍼 함수 ── */

export function scoreColor(score: number): string {
  const t = Math.max(0, Math.min(score, 100)) / 100
  const r = Math.round(240 + (230 - 240) * t)
  const g = Math.round(192 + (81 - 192) * t)
  const b = Math.round(128 + (0 - 128) * t)
  return `rgb(${r},${g},${b})`
}

/* ── 행 타입 ── */

interface GroupRowItem {
  type: 'group'
  sector: string
  label: string
  score?: number
  dim: boolean
}

interface DataRowItem {
  type: 'data'
  stock: SectorStock
  dim: boolean
  seq: number
}

type RowItem = GroupRowItem | DataRowItem

/* ── 검색 필터링 (export for PBT) ── */

export function filterStocksBySearch(
  stocks: Iterable<SectorStock>,
  query: string,
): Set<string> | null {
  const q = query.trim().toLowerCase()
  if (!q) return null
  const codes = new Set<string>()
  for (const s of stocks) {
    if (s.code.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q)) {
      codes.add(s.code)
    }
  }
  return codes
}

/* ── 업종 필터링 (export for PBT) ── */

export function filterStocksBySector(
  stocks: Iterable<SectorStock>,
  selectedSector: string | null,
): SectorStock[] {
  if (!selectedSector) return [...stocks]
  const result: SectorStock[] = []
  for (const s of stocks) {
    if ((s.sector || '기타') === selectedSector) result.push(s)
  }
  return result
}

/* ── RowItem → TableRow<DataRowItem> 매핑 ── */

function mapRowsToTableRows(rows: RowItem[]): TableRow<DataRowItem>[] {
  return rows.map(item => {
    if (item.type === 'group') {
      return {
        type: 'group' as const,
        label: item.label,
        key: 'g-' + item.sector,
        score: item.score,
        style: { opacity: item.dim ? '0.65' : '1' },
      } satisfies DataTableGroupRow
    }
    return item
  })
}

/* ── rows 계산 ── */

function computeRows(
  stockMap: Record<string, SectorStock>,
  sectorOrder: string[],
  sectorScores: SectorScoreRow[],
  maxTargets: number,
  selectedSector: string | null,
  matchedCodes: Set<string> | null,
  rowCache: Map<string, { stock: SectorStock; row: DataRowItem }>,
): RowItem[] {
  // 업종별 종목 그룹핑
  const grouped = new Map<string, string[]>()
  for (const s of Object.values(stockMap)) {
    const sector = s.sector || '기타'
    if (selectedSector && sector !== selectedSector) continue
    if (matchedCodes && !matchedCodes.has(s.code)) continue
    let arr = grouped.get(sector)
    if (!arr) { arr = []; grouped.set(sector, arr) }
    arr.push(s.code)
  }

  // sectorOrder 순서 유지 + 미포함 업종 추가
  // 단, selectedSector가 있으면 해당 업종만 표시하므로 sectorOrder 정렬 불필요
  const orderedSectors: string[] = []
  if (selectedSector) {
    if (grouped.has(selectedSector)) orderedSectors.push(selectedSector)
  } else {
    const seen = new Set<string>()
    for (const s of sectorOrder) {
      if (grouped.has(s)) { orderedSectors.push(s); seen.add(s) }
    }
    for (const s of grouped.keys()) {
      if (!seen.has(s)) orderedSectors.push(s)
    }
  }

  const scoreMap = new Map<string, number>()
  for (const sc of sectorScores) scoreMap.set(sc.sector, sc.final_score)

  const sectorRankMap = new Map<string, number>()
  for (let i = 0; i < sectorOrder.length; i++) sectorRankMap.set(sectorOrder[i], i + 1)

  const rows: RowItem[] = []
  let groupIdx = 0
  let stockSeq = 0

  for (const sector of orderedSectors) {
    const codes = grouped.get(sector)
    if (!codes) continue
    groupIdx++
    const realRank = sectorRankMap.get(sector) ?? groupIdx
    const dim = realRank > maxTargets
    const score = scoreMap.get(sector)

    rows.push({
      type: 'group',
      sector,
      label: `${realRank}. ${sector}`,
      score,
      dim,
    })

    // selectedSector 모드: 종목코드 기준 안정 정렬 (Map 삽입순서 변동 방지)
    const sortedCodes = selectedSector ? [...codes].sort() : codes

    for (const code of sortedCodes) {
      stockSeq++
      const stock = stockMap[code]
      if (!stock) continue

      // 행 객체 캐시: stock 참조가 같으면 이전 행 재사용
      const cached = rowCache.get(code)
      if (cached && cached.stock === stock && cached.row.dim === dim && cached.row.seq === stockSeq) {
        rows.push(cached.row)
      } else {
        const row: DataRowItem = { type: 'data', stock, dim, seq: stockSeq }
        rowCache.set(code, { stock, row })
        rows.push(row)
      }
    }
  }

  return rows
}


/* ── 모듈 상태 ── */

let rootEl: HTMLElement | null = null
let dataTable: DataTableApi<DataRowItem> | null = null
let unsubStore: (() => void) | null = null
let searchInput: ReturnType<typeof createSearchInput> | null = null
let searchTerm = ''
let currentMatchedCodes: Set<string> | null = null
let rowCache = new Map<string, { stock: SectorStock; row: DataRowItem }>()

// DOM 참조
let titleH3: HTMLElement | null = null
let filterBadge: HTMLElement | null = null
let warningDiv: HTMLElement | null = null
let emptyDiv: HTMLElement | null = null
let scrollContainer: HTMLElement | null = null
let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null
let _rafId: number | null = null

/* ── mount ── */

function mount(container: HTMLElement): void {
  searchTerm = ''
  currentMatchedCodes = null
  rowCache = new Map()

  rootEl = document.createElement('div')
  Object.assign(rootEl.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  // 1. 카드 타이틀
  const titleContent = document.createElement('span')
  titleContent.textContent = '업종별 종목 실시간 시세'
  titleH3 = createCardTitleWithContent(titleContent)
  rootEl.appendChild(titleH3)

  // 2. 선택된 업종 필터 배지
  filterBadge = document.createElement('div')
  Object.assign(filterBadge.style, {
    display: 'none',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '8px',
    padding: '6px 12px',
    background: '#e8f0fe',
    borderRadius: '6px',
    border: '1px solid #1a73e8',
  })
  const badgeLabel = document.createElement('span')
  Object.assign(badgeLabel.style, { fontSize: FONT_SIZE.badge, color: '#1a73e8', fontWeight: FONT_WEIGHT.normal })
  badgeLabel.className = 'badge-label'
  filterBadge.appendChild(badgeLabel)

  const clearBtn = document.createElement('button')
  Object.assign(clearBtn.style, {
    marginLeft: 'auto',
    background: 'none',
    border: '1px solid #1a73e8',
    borderRadius: '4px',
    color: '#1a73e8',
    cursor: 'pointer',
    fontSize: FONT_SIZE.badge,
    padding: '2px 8px',
  })
  clearBtn.textContent = '전체 보기'
  clearBtn.addEventListener('click', () => setSelectedSector(null))
  filterBadge.appendChild(clearBtn)
  rootEl.appendChild(filterBadge)

  // 3. 종목 수 초과 경고
  warningDiv = document.createElement('div')
  Object.assign(warningDiv.style, {
    display: 'none',
    background: '#fff3cd',
    color: '#856404',
    border: '1px solid #ffc107',
    borderRadius: '6px',
    padding: '6px 12px',
    marginBottom: '8px',
    fontSize: FONT_SIZE.badge,
  })
  rootEl.appendChild(warningDiv)

  // 4. 검색 + WS 상태 배지
  const searchRow = document.createElement('div')
  Object.assign(searchRow.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '12px',
    marginBottom: '4px',
  })

  searchInput = createSearchInput({
    placeholder: '종목명 / 코드 검색',
    width: '220px',
    onSearch: (query) => {
      searchTerm = query
      refreshRows()
    },
  })
  searchRow.appendChild(searchInput.el)

  const wsWrap = document.createElement('span')
  wsWrap.style.marginLeft = 'auto'
  wsBadge = createWsStatusBadge({ subscribed: false, broker: 'kiwoom' })
  wsWrap.appendChild(wsBadge.el)
  searchRow.appendChild(wsWrap)
  rootEl.appendChild(searchRow)

  // 5. 빈 상태 메시지
  emptyDiv = document.createElement('div')
  Object.assign(emptyDiv.style, {
    display: 'none',
    color: '#aaa',
    padding: '20px 0',
    textAlign: 'center',
    fontSize: FONT_SIZE.badge,
  })
  emptyDiv.textContent = '종목 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.'
  rootEl.appendChild(emptyDiv)

  // 6. 스크롤 컨테이너 (DataTable.el을 삽입)
  scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, { flex: '1', minHeight: '200px', display: 'flex', flexDirection: 'column' })

  // 7. DataTable 생성
  dataTable = createDataTable<DataRowItem>({
    columns: COLUMNS,
    virtualScroll: true,
    keyFn: (item) => item.stock.code,
    emptyText: '종목 데이터가 없습니다. 엔진이 기동 중인지 확인해주세요.',
    stickyHeader: true,
    groupRowHeight: 48,
    rowHeight: 32,
    rowStyle: (row, _idx) => ({
      opacity: row.dim ? '0.65' : '1',
      background: currentMatchedCodes?.has(row.stock.code) ? '#fff9c4' : '',
    }),
  })

  scrollContainer.appendChild(dataTable.el)
  rootEl.appendChild(scrollContainer)
  container.appendChild(rootEl)

  // 초기 데이터
  const initialRows = buildRows()
  const mappedRows = mapRowsToTableRows(initialRows)
  dataTable.updateRows(mappedRows)
  updateUI(initialRows)

  // Store 구독 — 선택적 구독 가드 (Bug 0 fix: sector-stock interest keys only)
  {
    const initState = appStore.getState()
    let prevSectorStocks = initState.sectorStocks
    let prevSectorScores = initState.sectorScores
    let prevSectorOrder = initState.sectorOrder
    let prevSelectedSector = initState.selectedSector
    let prevWsSubscribeStatus = initState.wsSubscribeStatus
    let prevSettings = initState.settings

    unsubStore = appStore.subscribe((state) => {
      // selectedSector가 있으면 sectorOrder 변동은 무시 (종목 순서 안정화)
      // 순위 숫자는 sectorScores 변동으로 갱신됨
      const orderRelevant = !state.selectedSector && state.sectorOrder !== prevSectorOrder
      const changed =
        state.sectorStocks !== prevSectorStocks ||
        state.sectorScores !== prevSectorScores ||
        orderRelevant ||
        state.selectedSector !== prevSelectedSector ||
        state.wsSubscribeStatus !== prevWsSubscribeStatus ||
        state.settings !== prevSettings

      prevSectorStocks = state.sectorStocks
      prevSectorScores = state.sectorScores
      prevSectorOrder = state.sectorOrder
      prevSelectedSector = state.selectedSector
      prevWsSubscribeStatus = state.wsSubscribeStatus
      prevSettings = state.settings

      if (!changed) return

      if (_rafId === null) {
        _rafId = requestAnimationFrame(() => {
          _rafId = null
          refreshRows()
        })
      }
    })
  }

  // 초기 렌더링
  refreshRows()
}

/* ── 행 빌드 + UI 갱신 ── */

function buildRows(): RowItem[] {
  const state = appStore.getState()
  currentMatchedCodes = filterStocksBySearch(Object.values(state.sectorStocks), searchTerm)
  const maxTargets = Number(state.settings?.sector_max_targets) || (state.sectorStatus?.max_targets ?? 10)
  return computeRows(
    state.sectorStocks,
    state.sectorOrder,
    state.sectorScores,
    maxTargets,
    state.selectedSector,
    currentMatchedCodes,
    rowCache,
  )
}

function refreshRows(): void {
  const rows = buildRows()
  const mappedRows = mapRowsToTableRows(rows)
  if (dataTable) dataTable.updateRows(mappedRows)
  updateUI(rows)
}

function updateUI(rows: RowItem[]): void {
  const state = appStore.getState()
  const stockCount = Object.keys(state.sectorStocks).length
  const minTradeAmt = state.settings?.sector_min_trade_amt ?? 0

  // 타이틀 갱신 — 델타 비교 (innerHTML 파괴 금지 → 레이아웃 재계산 방지)
  if (titleH3) {
    const newTitle = state.sectorStatus
      ? `업종별 종목 실시간 시세 <span style="color:#1a73e8;font-weight:500">5일평균최소거래대금(${minTradeAmt})억</span> (${stockCount}종목)`
      : '업종별 종목 실시간 시세'
    const existing = titleH3.firstElementChild as HTMLElement | null
    if (!existing || existing.innerHTML !== newTitle) {
      titleH3.innerHTML = ''
      const titleSpan = document.createElement('span')
      if (state.sectorStatus) {
        titleSpan.innerHTML = newTitle
      } else {
        titleSpan.textContent = newTitle
      }
      Object.assign(titleH3.style, { fontSize: FONT_SIZE.title, margin: '0 0 8px', color: '#333' })
      titleH3.appendChild(titleSpan)
    }
  }

  // 업종 필터 배지
  if (filterBadge) {
    const selected = state.selectedSector
    if (selected) {
      filterBadge.style.display = 'flex'
      const label = filterBadge.querySelector('.badge-label') as HTMLElement
      if (label) label.textContent = `📌 ${selected}`
    } else {
      filterBadge.style.display = 'none'
    }
  }

  // 종목 수 경고
  if (warningDiv) {
    if (stockCount > 170) {
      warningDiv.style.display = ''
      warningDiv.textContent = `⚠️ 종목 수가 ${stockCount}개로 170개를 초과했습니다. 실시간 연결이 불안정할 수 있습니다.`
    } else {
      warningDiv.style.display = 'none'
    }
  }

  // WS 상태 배지
  if (wsBadge) {
    const sub = state.wsSubscribeStatus.quote_subscribed
    wsBadge.update(sub, 'kiwoom')
  }

  // 빈 상태 / 스크롤 영역 표시 토글
  const hasRows = rows.length > 0
  if (emptyDiv) emptyDiv.style.display = hasRows ? 'none' : ''
  if (scrollContainer) scrollContainer.style.display = hasRows ? 'flex' : 'none'
}

/* ── unmount ── */

function unmount(): void {
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  if (rootEl && rootEl.parentNode) rootEl.parentNode.removeChild(rootEl)
  rootEl = null
  titleH3 = null
  filterBadge = null
  warningDiv = null
  emptyDiv = null
  scrollContainer = null
  searchInput = null
  wsBadge = null
  rowCache = new Map()
  currentMatchedCodes = null
  searchTerm = ''
}

export default { mount, unmount }