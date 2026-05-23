// frontend/src/pages/stock-classification.ui.ts
// 업종분류 커스텀 페이지 — 메인 컨테이너 + tripleHeader + 업종 관리 테이블

import { FONT_SIZE, FONT_FAMILY, FONT_WEIGHT } from '../components/common/ui-styles'
import { createCardTitleWithContent } from '../components/common/card-title'
import { createSearchInput } from '../components/common/search-input'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createStockNameColumn } from '../components/common/ui-styles'

/* ── Props 타입 ── */

export interface StockClassificationUiProps {
  editWindowOpen?: boolean
  sectors?: Record<string, string>
  stockMoves?: Record<string, string>
  deletedSectors?: string[]
  mergedSectors?: string[]
  allStocks?: Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }>
  onRenameSector?: (oldName: string, newName: string) => void
  onDeleteSector?: (name: string) => void
  onAddSector?: (name: string) => void
  onSearchResultClick?: (code: string, sector: string) => void
  onSectorSelect?: (sectorName: string | null) => void
}

/* ── 행 데이터 타입 ── */

interface MasterRow {
  sectorName: string
  stockCount: number
}

interface SearchResultRow {
  code: string
  name: string
  sector: string
  market_type?: string
  nxt_enable?: boolean
}

/* ── UI 참조 ── */

let indicatorDot: HTMLElement | null = null
let indicatorLabel: HTMLElement | null = null
let masterTableRef: DataTableApi<MasterRow> | null = null
let statsLabelRef: HTMLElement | null = null
let addSectorBtnRef: HTMLElement | null = null
let searchInputRef: ReturnType<typeof createSearchInput> | null = null
let searchResultTableRef: DataTableApi<SearchResultRow> | null = null
let selectedSector: string | null = null

/* ── 공통: 액션 버튼 ── */
function actionBtn(text: string, color = '#198754'): HTMLButtonElement {
  const btn = document.createElement('button')
  Object.assign(btn.style, {
    padding: '4px 10px', border: 'none', borderRadius: '4px',
    background: color, color: '#fff', cursor: 'pointer',
    fontSize: FONT_SIZE.small, fontFamily: FONT_FAMILY,
    flexShrink: '0', whiteSpace: 'nowrap',
  })
  btn.textContent = text
  return btn
}

/* ── 공통: 카드 래퍼 ── */
function cardWrap(): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, {
    background: '#fff', border: '1px solid #ddd', borderRadius: '8px',
    padding: '16px', marginBottom: '12px',
  })
  return div
}

/* ── 공통: 설명 레이블 ── */
function descLabel(text: string): HTMLElement {
  const p = document.createElement('p')
  Object.assign(p.style, { fontSize: FONT_SIZE.badge, color: '#888', margin: '0 0 10px' })
  p.textContent = text
  return p
}

/* ── tripleHeader — 공통 헤더 (Indicator_Bar) ── */

export function buildTripleHeader(container: HTMLElement, props: StockClassificationUiProps): void {
  while (container.firstChild) container.removeChild(container.firstChild)
  container.style.fontFamily = FONT_FAMILY

  // 좌측: 타이틀 + 증권사 라벨 (flex:1)
  const left = document.createElement('div')
  left.style.flex = '1'
  left.style.display = 'flex'
  left.style.alignItems = 'center'
  left.style.gap = '10px'

  const h4 = document.createElement('h4')
  h4.style.margin = '0'
  h4.textContent = '업종분류'
  left.appendChild(h4)

  const brokerLabel = document.createElement('span')
  brokerLabel.textContent = '(키움증권 REST API 기준)'
  brokerLabel.style.fontSize = '12px'
  brokerLabel.style.color = '#666'
  left.appendChild(brokerLabel)

  container.appendChild(left)

  // 중앙: Indicator_Bar — dot + label (flex:1, text-align:center)
  const center = document.createElement('div')
  Object.assign(center.style, {
    flex: '1', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
    textAlign: 'center', fontSize: FONT_SIZE.title,
  })

  indicatorDot = document.createElement('span')
  Object.assign(indicatorDot.style, {
    width: '8px', height: '8px', borderRadius: '50%', display: 'inline-block',
  })

  indicatorLabel = document.createElement('span')
  indicatorLabel.style.fontSize = FONT_SIZE.title

  center.appendChild(indicatorDot)
  center.appendChild(indicatorLabel)
  container.appendChild(center)

  // 우측: 여백 (flex:1, text-align:right)
  const right = document.createElement('div')
  Object.assign(right.style, { flex: '1', textAlign: 'right' })
  container.appendChild(right)

  updateIndicatorBar(props.editWindowOpen ?? false)
}

export function updateIndicatorBar(editWindowOpen: boolean): void {
  if (indicatorDot) {
    indicatorDot.style.background = editWindowOpen ? '#198754' : '#dc3545'
  }
  if (indicatorLabel) {
    indicatorLabel.textContent = editWindowOpen
      ? '✏️ 수정 가능'
      : '⚠️ 거래시간중 편집시에는 업종순위에 변동이 있을수 있습니다.'
  }
}

/* ── 업종 관리 테이블 (Sector_Table) ── */

export function buildSectorManageCard(container: HTMLElement, props: StockClassificationUiProps): void {
  const card = cardWrap()

  // Card title: "업종 관리" (left) + stats (right)
  const titleContainer = document.createElement('div')
  Object.assign(titleContainer.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
  })
  const titleText = document.createElement('span')
  titleText.textContent = '업종 관리'
  statsLabelRef = document.createElement('span')
  Object.assign(statsLabelRef.style, { fontSize: FONT_SIZE.label, color: '#888', fontWeight: FONT_WEIGHT.normal })

  addSectorBtnRef = actionBtn('+ 새 업종 추가', '#0d6efd')
  Object.assign(addSectorBtnRef.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })
  addSectorBtnRef.addEventListener('click', () => {
    const name = prompt('새 업종 이름을 입력하세요:')
    if (name && props.onAddSector) {
      props.onAddSector(name)
    }
  })

  const titleRightContainer = document.createElement('div')
  Object.assign(titleRightContainer.style, { display: 'flex', alignItems: 'center', gap: '8px' })
  titleRightContainer.appendChild(statsLabelRef)
  titleRightContainer.appendChild(addSectorBtnRef)

  titleContainer.appendChild(titleText)
  titleContainer.appendChild(titleRightContainer)
  const sectorManageTitle = createCardTitleWithContent(titleContainer)
  sectorManageTitle.style.fontSize = FONT_SIZE.section
  card.appendChild(sectorManageTitle)

  card.appendChild(descLabel('업종명을 변경하거나, 새 업종을 만들거나, 불필요한 업종을 삭제할 수 있습니다'))

  // 종목 검색 UI
  searchInputRef = createSearchInput({
    placeholder: '종목명 또는 코드 검색',
    onSearch: (query) => {
      if (!searchResultTableRef || !masterTableRef) return
      if (!query) {
        searchResultTableRef.el.style.display = 'none'
        masterTableRef.el.style.display = ''
        return
      }

      const q = query.toLowerCase()
      const { stockMoves = {}, sectors = {} } = props
      const allStocks = props.allStocks ?? new Map()
      const results: SearchResultRow[] = []

      const searchTokens = q.split(/[\s()（）]+/).filter(t => t.length > 0)

      for (const [, stock] of allStocks) {
        const nameLower = stock.name.toLowerCase()
        const codeLower = stock.code.toLowerCase()
        const matched = searchTokens.some(t => nameLower.includes(t) || codeLower.includes(t))
        if (matched) {
          let sector = stockMoves[stock.code] ?? stock.sector ?? ''
          if (sectors[sector]) sector = sectors[sector]
          results.push({ code: stock.code, name: stock.name, sector, market_type: stock.market_type, nxt_enable: stock.nxt_enable })
        }
      }
      searchResultTableRef.updateRows(results)
      searchResultTableRef.el.style.display = ''
      masterTableRef.el.style.display = 'none'
    },
  })
  card.appendChild(searchInputRef.el)

  // 검색 결과 테이블
  const searchColumns: ColumnDef<SearchResultRow>[] = [
    {
      key: 'code', label: '종목코드', align: 'center',
      cellStyle: { color: '#999', fontSize: FONT_SIZE.small },
      render: (row) => row.code
    },
    createStockNameColumn<SearchResultRow>(
      (row: SearchResultRow) => ({
        name: row.name,
        market_type: row.market_type,
        nxt_enable: row.nxt_enable
      })
    ),
    {
      key: 'sector', label: '소속업종', align: 'left',
      cellStyle: { fontWeight: 'normal', color: '#111' },
      render: (row) => row.sector
    },
  ]
  searchResultTableRef = createDataTable<SearchResultRow>({
    columns: searchColumns,
    emptyText: '검색 결과가 없습니다.',
    stickyHeader: false,
    rowStyle: () => ({ cursor: 'pointer' }),
  })
  searchResultTableRef.el.style.display = 'none'

  searchResultTableRef.el.addEventListener('click', (e: Event) => {
    const target = e.target as HTMLElement
    const tr = target.closest('tr')
    if (!tr) return
    const tbody = searchResultTableRef?.el.querySelector('tbody')
    if (!tbody) return
    const rows = Array.from(tbody.querySelectorAll('tr'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    if (idx < 0) return
    
    const q = searchInputRef?.getValue()?.toLowerCase() ?? ''
    if (!q) return
    const { stockMoves = {}, sectors = {} } = props
    const allStocks = props.allStocks ?? new Map()
    const results: SearchResultRow[] = []
    const searchTokens = q.split(/[\s()（）]+/).filter(t => t.length > 0)
    for (const [, stock] of allStocks) {
      const nameLower = stock.name.toLowerCase()
      const codeLower = stock.code.toLowerCase()
      const matched = searchTokens.some(t => nameLower.includes(t) || codeLower.includes(t))
      if (matched) {
        let sector = stockMoves[stock.code] ?? stock.sector ?? ''
        if (sectors[sector]) sector = sectors[sector]
        results.push({ code: stock.code, name: stock.name, sector, market_type: stock.market_type, nxt_enable: stock.nxt_enable })
      }
    }
    if (idx >= results.length) return
    const clicked = results[idx]

    if (props.onSearchResultClick) {
      props.onSearchResultClick(clicked.code, clicked.sector)
    }
  })

  card.appendChild(searchResultTableRef.el)

  const masterColumns: ColumnDef<MasterRow>[] = [
    {
      key: 'name', label: '업종명', align: 'left',
      cellStyle: { fontWeight: 'normal', color: '#111' },
      render: (row) => row.sectorName,
    },
    {
      key: 'count', label: '종목수', align: 'center',
      render: (row) => String(row.stockCount),
    },
    {
      key: 'actions', label: '작업', align: 'center',
      render: (row) => {
        const container = document.createElement('div')
        Object.assign(container.style, { display: 'flex', gap: '4px', justifyContent: 'center' })
        const renameBtn = actionBtn('이름변경', '#6c757d')
        renameBtn.addEventListener('click', (e: MouseEvent) => {
          e.stopPropagation()
          const newName = prompt(`${row.sectorName}의 새 이름을 입력하세요:`, row.sectorName)
          if (newName && newName !== row.sectorName && props.onRenameSector) {
            props.onRenameSector(row.sectorName, newName)
          }
        })
        const deleteBtn = actionBtn('삭제', '#dc3545')
        deleteBtn.addEventListener('click', (e: MouseEvent) => {
          e.stopPropagation()
          if (confirm(`"${row.sectorName}" 업종을 삭제하시겠습니까?\n해당 업종의 종목은 미매핑 상태가 됩니다.`) && props.onDeleteSector) {
            props.onDeleteSector(row.sectorName)
          }
        })
        container.appendChild(renameBtn)
        container.appendChild(deleteBtn)
        return container
      },
    },
  ]

  masterTableRef = createDataTable<MasterRow>({
    columns: masterColumns,
    emptyText: '업종이 없습니다.',
    stickyHeader: false,
    rowStyle: (row) => {
      const style: Partial<CSSStyleDeclaration> = { cursor: 'pointer' }
      if (selectedSector === row.sectorName) {
        style.background = '#e3f2fd'
        style.borderLeft = '3px solid #1976d2'
      } else if (row.sectorName === '업종명없음' && row.stockCount > 0) {
        style.background = '#fff3cd'
      }
      return style
    },
  })

  masterTableRef.el.addEventListener('click', (e: Event) => {
    const target = e.target as HTMLElement
    if (target.closest('button')) return
    const tr = target.closest('tr')
    if (!tr) return
    const tbody = masterTableRef?.el.querySelector('tbody')
    if (!tbody) return
    const rows = Array.from(tbody.querySelectorAll('tr'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    if (idx < 0) return
    const masterRows = buildMasterRows(props)
    if (idx >= masterRows.length) return
    const clickedRow = masterRows[idx]
    selectedSector = selectedSector === clickedRow.sectorName ? null : clickedRow.sectorName
    
    if (props.onSectorSelect) {
      props.onSectorSelect(selectedSector)
    }
    
    updateMasterPanel(props)
  })

  card.appendChild(masterTableRef.el)
  container.appendChild(card)

  updateMasterPanel(props)
}

function buildMasterRows(props: StockClassificationUiProps): MasterRow[] {
  const allStocks = props.allStocks ?? new Map()
  const { stockMoves = {}, sectors = {}, deletedSectors = [], mergedSectors = [] } = props
  const counts: Record<string, number> = {}

  for (const s of mergedSectors) counts[s] = 0

  for (const [, stock] of allStocks) {
    let sector = stockMoves[stock.code] ?? stock.sector ?? ''
    if (sectors[sector]) sector = sectors[sector]
    if (deletedSectors.includes(sector)) sector = '업종명없음'
    if (sector && counts[sector] !== undefined) counts[sector]++
    else if (sector) counts[sector] = 1
  }

  const rows: MasterRow[] = mergedSectors.map(s => ({
    sectorName: s,
    stockCount: counts[s] ?? 0,
  }))
  return rows
}

function updateMasterPanel(props: StockClassificationUiProps): void {
  if (!masterTableRef) return
  const rows = buildMasterRows(props)
  masterTableRef.updateRows(rows)
  updateStatsLabel(props)
}

function updateStatsLabel(props: StockClassificationUiProps): void {
  if (!statsLabelRef) return
  const allStocks = props.allStocks ?? new Map()
  const { stockMoves = {}, sectors = {}, deletedSectors = [], mergedSectors = [] } = props
  const counts: Record<string, number> = {}

  for (const s of mergedSectors) counts[s] = 0

  for (const [, stock] of allStocks) {
    let sector = stockMoves[stock.code] ?? stock.sector ?? ''
    if (sectors[sector]) sector = sectors[sector]
    if (deletedSectors.includes(sector)) sector = '업종명없음'
    if (sector && counts[sector] !== undefined) counts[sector]++
    else if (sector) counts[sector] = 1
  }

  const sectorCount = mergedSectors.length
  let totalStocks = 0
  for (const c of Object.values(counts)) totalStocks += c
  statsLabelRef.textContent = `업종 ${sectorCount}개 · 전체 종목 ${totalStocks}개`
}

/* ── 메인 렌더 함수 ── */

export function renderStockClassificationUi(
  tripleHeader: HTMLElement,
  tripleLeft: HTMLElement,
  props: StockClassificationUiProps
): void {
  buildTripleHeader(tripleHeader, props)
  buildSectorManageCard(tripleLeft, props)
}

/* ── Props 갱신 ── */

export function updateStockClassificationUi(props: StockClassificationUiProps): void {
  updateIndicatorBar(props.editWindowOpen ?? false)
  updateMasterPanel(props)
}
