// frontend/src/pages/sector-stock-list.ui.ts
// 업종분류 커스텀 페이지 — Staging_Panel + 종목 목록 + 대상 업종 리스트

import { FONT_SIZE, FONT_FAMILY } from '../components/common/ui-styles'
import { createSearchInput } from '../components/common/search-input'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSectorRowEl } from '../components/common/sector-row'
import { createStockNameColumn } from '../components/common/ui-styles'

/* ── Props 타입 ── */

export interface SectorStockListUiProps {
  selectedSector?: string | null
  allStocks?: Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }>
  stockMoves?: Record<string, string>
  sectors?: Record<string, string>
  deletedSectors?: string[]
  mergedSectors?: string[]
  stagingSet?: Set<string>
  selectedStocks?: Set<string>
  onStagingRemove?: (code: string) => void
  onStagingClear?: () => void
  onStockSelect?: (codes: Set<string>) => void
  onMoveStock?: (codes: string[], targetSector: string) => void
}

/* ── 행 데이터 타입 ── */

interface DetailRow {
  code: string
  name: string
  market_type?: string
  nxt_enable?: boolean
}

/* ── UI 참조 ── */

// Staging / Selection 상태
let stagingSet: Set<string> = new Set()
let stagingChipMap: Map<string, HTMLElement> = new Map()
let stagingPanelRef: HTMLElement | null = null
let stagingCountRef: HTMLElement | null = null
let stagingEmptyRef: HTMLElement | null = null
let selectedStocks: Set<string> = new Set()
let anchorRow: number = -1
let highlightStockCode: string | null = null

// Center (Stock List)
let centerContentRef: HTMLElement | null = null
let centerEmptyRef: HTMLElement | null = null
let detailTitleRef: HTMLElement | null = null
let detailTableRef: DataTableApi<DetailRow> | null = null

// Right (Target_Sector_List)
let rightContentRef: HTMLElement | null = null
let rightEmptyRef: HTMLElement | null = null
let targetSectorListRef: HTMLElement | null = null
let sectorRowMap: Map<string, HTMLElement> = new Map()
let prevTargetSectors: Set<string> = new Set()
let selectedTargetSector: string | null = null

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

/* ── Staging_Panel 함수 ── */

function createChip(code: string, props: SectorStockListUiProps): HTMLElement {
  const allStocks = props.allStocks ?? new Map()
  const { stockMoves = {}, sectors = {} } = props
  const stock = allStocks.get(code)
  const stockName = stock?.name ?? code

  let sectorName = stockMoves[code] ?? stock?.sector ?? ''
  if (sectors[sectorName]) sectorName = sectors[sectorName]

  const chip = document.createElement('span')
  chip.className = 'staging-chip'
  chip.setAttribute('data-code', code)
  Object.assign(chip.style, {
    display: 'inline-flex', alignItems: 'center', gap: '4px',
    padding: '2px 8px', borderRadius: '12px',
    background: '#e8f0fe', fontSize: FONT_SIZE.small,
    fontFamily: FONT_FAMILY, cursor: 'default',
  })

  const nameSpan = document.createElement('span')
  nameSpan.className = 'chip-name'
  nameSpan.textContent = stockName

  const sectorSpan = document.createElement('span')
  sectorSpan.className = 'chip-sector'
  Object.assign(sectorSpan.style, { color: '#999', fontSize: FONT_SIZE.chip })
  sectorSpan.textContent = sectorName

  const removeSpan = document.createElement('span')
  removeSpan.className = 'chip-remove'
  Object.assign(removeSpan.style, { cursor: 'pointer', marginLeft: '4px' })
  removeSpan.textContent = '×'
  removeSpan.addEventListener('click', () => {
    if (props.onStagingRemove) {
      props.onStagingRemove(code)
    }
  })

  chip.appendChild(nameSpan)
  chip.appendChild(sectorSpan)
  chip.appendChild(removeSpan)

  chip.addEventListener('mouseenter', () => { chip.style.background = '#d0e2fc' })
  chip.addEventListener('mouseleave', () => { chip.style.background = '#e8f0fe' })

  return chip
}

function updateStagingPanel(props: SectorStockListUiProps): void {
  stagingSet = props.stagingSet ?? new Set()
  
  // 기존 칩 정리
  for (const [, chip] of stagingChipMap) chip.remove()
  stagingChipMap.clear()

  // 새 칩 생성
  for (const code of stagingSet) {
    const chip = createChip(code, props)
    stagingChipMap.set(code, chip)
    const chipList = stagingPanelRef?.querySelector('.staging-chip-list')
    if (chipList) chipList.appendChild(chip)
  }

  if (stagingCountRef) {
    stagingCountRef.textContent = stagingSet.size > 0 ? `${stagingSet.size}개 선택` : ''
  }
  if (stagingEmptyRef) {
    stagingEmptyRef.style.display = stagingSet.size === 0 ? '' : 'none'
  }
  const clearBtn = stagingPanelRef?.querySelector('.staging-clear-btn') as HTMLElement | null
  if (clearBtn) {
    clearBtn.style.display = stagingSet.size > 0 ? '' : 'none'
  }
}

/* ── Stock_List_Panel 함수 ── */

function getStocksForSector(sectorName: string, props: SectorStockListUiProps): Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> {
  const allStocks = props.allStocks ?? new Map()
  const { stockMoves = {}, sectors = {}, deletedSectors = [] } = props
  const result: Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> = []

  for (const [, stock] of allStocks) {
    let sector = stockMoves[stock.code] ?? stock.sector ?? ''
    if (sectors[sector]) sector = sectors[sector]
    if (deletedSectors.includes(sector)) sector = '업종명없음'
    if (sector === sectorName) result.push({ code: stock.code, name: stock.name, market_type: stock.market_type, nxt_enable: stock.nxt_enable })
  }
  return result.sort((a, b) => a.name.localeCompare(b.name))
}

function updateCenterPanel(props: SectorStockListUiProps): void {
  if (!centerContentRef || !detailTitleRef || !detailTableRef) return

  const selectedSector = props.selectedSector ?? null

  if (selectedSector === null) {
    detailTitleRef.textContent = ''
    detailTableRef.el.style.display = 'none'
    const titleRow = detailTitleRef.parentElement
    if (titleRow) titleRow.style.display = 'none'
    if (!centerEmptyRef) {
      centerEmptyRef = document.createElement('div')
      Object.assign(centerEmptyRef.style, { color: '#aaa', textAlign: 'center', padding: '40px 0' })
      centerEmptyRef.textContent = '좌측에서 업종을 선택하세요'
      centerContentRef.appendChild(centerEmptyRef)
    }
    centerEmptyRef.style.display = ''
    return
  }

  if (centerEmptyRef) centerEmptyRef.style.display = 'none'
  const titleRow = detailTitleRef.parentElement
  if (titleRow) titleRow.style.display = ''
  detailTableRef.el.style.display = ''

  const stocks = getStocksForSector(selectedSector, props)
  detailTitleRef.textContent = `${selectedSector} 종목 목록 (${stocks.length}개)`
  detailTableRef.updateRows(stocks)
}

/* ── Target_Sector_List 함수 ── */

function getTargetSectors(props: SectorStockListUiProps): string[] {
  const selectedSector = props.selectedSector ?? null
  const stagingSet = props.stagingSet ?? new Set()
  const mergedSectors = props.mergedSectors ?? []

  if (selectedSector === null && stagingSet.size > 0) {
    return mergedSectors.slice()
  }
  if (selectedSector === null) return []
  return mergedSectors.filter(s => s !== selectedSector)
}

function getMovableCount(props: SectorStockListUiProps): number {
  const stagingSet = props.stagingSet ?? new Set()
  const selectedStocks = props.selectedStocks ?? new Set()
  if (stagingSet.size > 0) return stagingSet.size
  return selectedStocks.size
}

function createSectorRow(sectorName: string, props: SectorStockListUiProps): HTMLElement {
  const count = getMovableCount(props)
  const row = createSectorRowEl({
    sectorName,
    btnText: count > 0 ? `${count}개 이동` : '이동',
    btnDisabled: count === 0,
    onBtnClick: () => {
      const stagingSet = props.stagingSet ?? new Set()
      const selectedStocks = props.selectedStocks ?? new Set()
      const codes = stagingSet.size > 0 ? [...stagingSet] : [...selectedStocks]
      if (codes.length === 0) return
      if (confirm(`${codes.length}개 종목을 "${sectorName}" 업종으로 이동하시겠습니까?`) && props.onMoveStock) {
        props.onMoveStock(codes, sectorName)
      }
    },
    onRowClick: () => {
      const prev = selectedTargetSector
      selectedTargetSector = selectedTargetSector === sectorName ? null : sectorName
      if (prev && sectorRowMap.has(prev)) {
        sectorRowMap.get(prev)!.style.background = ''
      }
      if (selectedTargetSector) {
        row.style.background = '#e3f2fd'
      } else {
        row.style.background = ''
      }
    },
  })

  row.addEventListener('mouseenter', () => {
    if (selectedTargetSector !== sectorName) row.style.background = '#f5f5f5'
  })
  row.addEventListener('mouseleave', () => {
    if (selectedTargetSector !== sectorName) row.style.background = ''
  })

  return row
}

function updateTargetSectorList(props: SectorStockListUiProps): void {
  if (!targetSectorListRef) return
  const newTargets = getTargetSectors(props)
  const newSet = new Set(newTargets)

  for (const s of prevTargetSectors) {
    if (!newSet.has(s)) {
      sectorRowMap.get(s)?.remove()
      sectorRowMap.delete(s)
    }
  }

  for (const s of newTargets) {
    if (!prevTargetSectors.has(s) && !sectorRowMap.has(s)) {
      const row = createSectorRow(s, props)
      sectorRowMap.set(s, row)
      targetSectorListRef.appendChild(row)
    }
  }

  prevTargetSectors = newSet
}

function updateAllInlineMoveButtons(props: SectorStockListUiProps): void {
  const count = getMovableCount(props)
  const disabled = count === 0
  for (const [, row] of sectorRowMap) {
    const btn = row.querySelector('button')
    if (btn) {
      btn.textContent = count > 0 ? `${count}개 이동` : '이동'
      btn.disabled = disabled
      btn.style.opacity = disabled ? '0.4' : '1'
      btn.style.pointerEvents = disabled ? 'none' : 'auto'
    }
  }
}

function updateRightPanel(props: SectorStockListUiProps): void {
  if (!rightContentRef) return

  const selectedSector = props.selectedSector ?? null
  const stagingSet = props.stagingSet ?? new Set()

  if (selectedSector === null && stagingSet.size === 0) {
    for (const child of Array.from(rightContentRef.children)) {
      (child as HTMLElement).style.display = 'none'
    }
    if (!rightEmptyRef) {
      rightEmptyRef = document.createElement('div')
      Object.assign(rightEmptyRef.style, { color: '#aaa', textAlign: 'center', padding: '40px 0' })
      rightEmptyRef.textContent = '좌측에서 업종을 선택하세요'
      rightContentRef.appendChild(rightEmptyRef)
    }
    rightEmptyRef.style.display = ''
    return
  }

  if (rightEmptyRef) rightEmptyRef.style.display = 'none'
  for (const child of Array.from(rightContentRef.children)) {
    if (child !== rightEmptyRef) (child as HTMLElement).style.display = ''
  }
  if (targetSectorListRef) targetSectorListRef.style.display = ''

  if (!targetSectorListRef) {
    buildTripleRight(rightContentRef, props)
    return
  }

  updateTargetSectorList(props)
  updateAllInlineMoveButtons(props)
}

/* ── tripleCenter — Stock_List_Panel ── */

export function buildTripleCenter(container: HTMLElement, props: SectorStockListUiProps): void {
  while (container.firstChild) container.removeChild(container.firstChild)
  container.style.fontFamily = FONT_FAMILY

  centerContentRef = document.createElement('div')
  container.appendChild(centerContentRef)

  // Staging_Panel
  stagingPanelRef = document.createElement('div')
  Object.assign(stagingPanelRef.style, {
    padding: '8px 12px', marginBottom: '8px',
    border: '1px solid #e0e0e0', borderRadius: '6px', background: '#fafafa',
  })

  const stagingHeader = document.createElement('div')
  Object.assign(stagingHeader.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px',
  })

  stagingCountRef = document.createElement('span')
  Object.assign(stagingCountRef.style, { fontSize: FONT_SIZE.small, fontWeight: 'normal', color: '#333' })

  const stagingClearBtn = actionBtn('전체 해제', '#6c757d')
  stagingClearBtn.className = 'staging-clear-btn'
  Object.assign(stagingClearBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small, display: 'none' })
  stagingClearBtn.addEventListener('click', () => {
    if (props.onStagingClear) {
      props.onStagingClear()
    }
  })

  stagingHeader.appendChild(stagingCountRef)
  stagingHeader.appendChild(stagingClearBtn)
  stagingPanelRef.appendChild(stagingHeader)

  const chipList = document.createElement('div')
  chipList.className = 'staging-chip-list'
  Object.assign(chipList.style, { display: 'flex', flexWrap: 'wrap', gap: '4px' })
  stagingPanelRef.appendChild(chipList)

  stagingEmptyRef = document.createElement('div')
  Object.assign(stagingEmptyRef.style, {
    color: '#aaa', fontSize: FONT_SIZE.small, textAlign: 'center', padding: '8px 0',
  })
  stagingEmptyRef.textContent = '검색으로 종목을 추가하세요'
  stagingPanelRef.appendChild(stagingEmptyRef)

  centerContentRef.appendChild(stagingPanelRef)
  updateStagingPanel(props)

  // 제목 + 전체 선택/해제 버튼
  const titleRow = document.createElement('div')
  Object.assign(titleRow.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px',
  })

  detailTitleRef = document.createElement('div')
  Object.assign(detailTitleRef.style, {
    fontSize: FONT_SIZE.title, fontWeight: 'normal', color: '#333',
  })
  titleRow.appendChild(detailTitleRef)

  const btnGroup = document.createElement('div')
  Object.assign(btnGroup.style, { display: 'flex', gap: '4px' })

  const selectAllBtn = actionBtn('전체 선택', '#0d6efd')
  Object.assign(selectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })
  selectAllBtn.addEventListener('click', () => {
    const selectedSector = props.selectedSector
    if (!selectedSector) return
    const stocks = getStocksForSector(selectedSector, props)
    selectedStocks.clear()
    for (const s of stocks) selectedStocks.add(s.code)
    anchorRow = stocks.length > 0 ? 0 : -1
    if (detailTableRef) detailTableRef.updateRows(stocks)
    if (props.onStockSelect) {
      props.onStockSelect(selectedStocks)
    }
  })

  const deselectAllBtn = actionBtn('전체 해제', '#6c757d')
  Object.assign(deselectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })
  deselectAllBtn.addEventListener('click', () => {
    selectedStocks.clear()
    anchorRow = -1
    const selectedSector = props.selectedSector
    if (selectedSector && detailTableRef) {
      const stocks = getStocksForSector(selectedSector, props)
      detailTableRef.updateRows(stocks)
    }
    if (props.onStockSelect) {
      props.onStockSelect(selectedStocks)
    }
  })

  btnGroup.appendChild(selectAllBtn)
  btnGroup.appendChild(deselectAllBtn)
  titleRow.appendChild(btnGroup)

  centerContentRef.appendChild(titleRow)

  // 종목 테이블
  const detailColumns: ColumnDef<DetailRow>[] = [
    {
      key: 'code', label: '종목코드', minWidth: 80, align: 'center',
      cellStyle: { color: '#999', fontSize: FONT_SIZE.small },
      render: (row) => row.code,
    },
    createStockNameColumn<DetailRow>(
      (row: DetailRow) => ({
        name: row.name,
        market_type: row.market_type,
        nxt_enable: row.nxt_enable
      })
    ),
  ]

  detailTableRef = createDataTable<DetailRow>({
    columns: detailColumns,
    emptyText: '종목이 없습니다.',
    stickyHeader: true,
    rowStyle: (row) => {
      if (highlightStockCode && row.code === highlightStockCode) {
        return { background: '#fff3cd', transition: 'background 0.3s' }
      }
      if (selectedStocks.has(row.code)) {
        return { background: '#e3f2fd' }
      }
      return undefined
    },
  })

  detailTableRef.el.tabIndex = 0

  detailTableRef.el.addEventListener('click', (e: MouseEvent) => {
    const tr = (e.target as HTMLElement).closest('tr')
    if (!tr) return
    const tbody = detailTableRef?.el.querySelector('tbody')
    if (!tbody) return
    const rows = Array.from(tbody.querySelectorAll('tr'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    const selectedSector = props.selectedSector
    if (idx < 0 || !selectedSector) return
    const stocks = getStocksForSector(selectedSector, props)
    if (idx >= stocks.length) return

    if (e.shiftKey && anchorRow >= 0) {
      const [start, end] = [Math.min(anchorRow, idx), Math.max(anchorRow, idx)]
      for (let i = start; i <= end; i++) selectedStocks.add(stocks[i].code)
    } else if (e.ctrlKey || e.metaKey) {
      const code = stocks[idx].code
      if (selectedStocks.has(code)) selectedStocks.delete(code)
      else selectedStocks.add(code)
      anchorRow = idx
    } else {
      selectedStocks.clear()
      selectedStocks.add(stocks[idx].code)
      anchorRow = idx
    }

    if (selectedSector) {
      const updatedStocks = getStocksForSector(selectedSector, props)
      detailTableRef!.updateRows(updatedStocks)
    }
    if (props.onStockSelect) {
      props.onStockSelect(selectedStocks)
    }
  })

  detailTableRef.el.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      selectedStocks.clear()
      anchorRow = -1
      const selectedSector = props.selectedSector
      if (selectedSector && detailTableRef) {
        const updatedStocks = getStocksForSector(selectedSector, props)
        detailTableRef.updateRows(updatedStocks)
      }
      if (props.onStockSelect) {
        props.onStockSelect(selectedStocks)
      }
    }
  })

  centerContentRef.appendChild(detailTableRef.el)
  updateCenterPanel(props)
}

/* ── tripleRight — Target_Sector_List ── */

function buildTripleRight(container: HTMLElement, props: SectorStockListUiProps): void {
  rightContentRef = container
  while (rightContentRef.firstChild) rightContentRef.removeChild(rightContentRef.firstChild)
  rightContentRef.style.fontFamily = FONT_FAMILY

  Object.assign(rightContentRef.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  const title = document.createElement('div')
  Object.assign(title.style, {
    fontSize: FONT_SIZE.title, fontWeight: 'normal', color: '#333', marginBottom: '8px',
  })
  title.textContent = '대상 업종'
  rightContentRef.appendChild(title)

  const targetSearchInput = createSearchInput({
    placeholder: '업종 검색',
    onSearch: (query) => {
      const q = query.toLowerCase()
      for (const [name, row] of sectorRowMap) {
        row.style.display = (!q || name.toLowerCase().includes(q)) ? 'flex' : 'none'
      }
    },
  })
  rightContentRef.appendChild(targetSearchInput.el)

  targetSectorListRef = document.createElement('div')
  Object.assign(targetSectorListRef.style, { overflowY: 'auto', flex: '1' })
  rightContentRef.appendChild(targetSectorListRef)

  sectorRowMap = new Map()
  prevTargetSectors = new Set()

  updateTargetSectorList(props)
  updateRightPanel(props)
}

/* ── 메인 렌더 함수 ── */

export function renderSectorStockListUi(
  tripleCenter: HTMLElement,
  tripleRight: HTMLElement,
  props: SectorStockListUiProps
): void {
  buildTripleCenter(tripleCenter, props)
  buildTripleRight(tripleRight, props)
}

/* ── Props 갱신 ── */

export function updateSectorStockListUi(props: SectorStockListUiProps): void {
  updateStagingPanel(props)
  selectedStocks = props.selectedStocks ?? new Set()
  updateCenterPanel(props)
  updateRightPanel(props)
}
