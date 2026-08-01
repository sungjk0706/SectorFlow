// frontend/src/pages/stock-classification-center.ts
// 종목분류 페이지 — tripleCenter(Stock_List_Panel + Detail_Table) 분할 (F-04 분할 5단계)
// P10 SSOT/P16 살아있는 경로/P24 단순성 — state 첫 인자 전달 패턴

import { shell } from '../main'
import { stockClassificationStore } from '../stores/stockClassificationStore'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { createSolidBtn } from '../components/common/button'
import { FONT_SIZE, FONT_FAMILY, createStockNameColumn, COLOR, RADIUS } from '../components/common/ui-styles'
import type { DetailRow } from './stock-classification-shared'
import {
  clearStaging,
  updateStagingPanel,
  getStocksForSector,
} from './stock-classification-staging'
import type { StockClassificationPageState } from './stock-classification'

/* ── Center_Panel Callbacks (순환 참조 회피 — main 잔류 함수 연결) ── */

interface CenterPanelCallbacks {
  updateAllInlineMoveButtons: () => void
  setControlsDisabled: (disabled: boolean) => void
}

let callbacks: CenterPanelCallbacks | null = null

export function initCenterCallbacks(cb: CenterPanelCallbacks): void {
  callbacks = cb
}

export function resetCenterCallbacks(): void {
  callbacks = null
}

/* ── 8.4: tripleCenter — Stock_List_Panel ── */

function buildStagingPanel(state: StockClassificationPageState): HTMLElement {
  state.stagingPanelRef = document.createElement('div')
  Object.assign(state.stagingPanelRef.style, {
    padding: '8px 12px', marginBottom: '8px',
    border: '1px solid ' + COLOR.inactiveBg, borderRadius: RADIUS.sm, background: COLOR.surfaceLight,
  })

  // Header row: count label + "전체 해제" button
  const stagingHeader = document.createElement('div')
  Object.assign(stagingHeader.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px',
  })

  state.stagingCountRef = document.createElement('span')
  Object.assign(state.stagingCountRef.style, { fontSize: FONT_SIZE.small, fontWeight: 'normal', color: COLOR.neutral })

  const stagingClearBtn = createSolidBtn({
    label: '전체 해제',
    color: COLOR.tertiary,
    editControl: true,
    onClick: () => clearStaging(state),
  })
  stagingClearBtn.className = 'staging-clear-btn'
  Object.assign(stagingClearBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small, display: 'none' })

  stagingHeader.appendChild(state.stagingCountRef)
  stagingHeader.appendChild(stagingClearBtn)
  state.stagingPanelRef.appendChild(stagingHeader)

  // Chip list container
  const chipList = document.createElement('div')
  chipList.className = 'staging-chip-list'
  Object.assign(chipList.style, { display: 'flex', flexWrap: 'wrap', gap: '4px' })
  state.stagingPanelRef.appendChild(chipList)

  // Empty state message
  state.stagingEmptyRef = document.createElement('div')
  Object.assign(state.stagingEmptyRef.style, {
    color: COLOR.muted, fontSize: FONT_SIZE.small, textAlign: 'center', padding: '8px 0',
  })
  state.stagingEmptyRef.textContent = '검색으로 종목을 추가하세요'
  state.stagingPanelRef.appendChild(state.stagingEmptyRef)

  updateStagingPanel(state)
  return state.stagingPanelRef
}

function handleSelectAll(state: StockClassificationPageState): void {
  if (!state.selectedSector) return
  const stocks = getStocksForSector(state, state.selectedSector)
  state.selectedStocks.clear()
  for (const s of stocks) state.selectedStocks.add(s.code)
  state.anchorRow = stocks.length > 0 ? 0 : -1
  if (state.detailTableRef) state.detailTableRef.updateRows(stocks)
  callbacks!.updateAllInlineMoveButtons()
}

function handleDeselectAll(state: StockClassificationPageState): void {
  state.selectedStocks.clear()
  state.anchorRow = -1
  if (state.selectedSector && state.detailTableRef) {
    const stocks = getStocksForSector(state, state.selectedSector)
    state.detailTableRef.updateRows(stocks)
  }
  callbacks!.updateAllInlineMoveButtons()
}

function buildDetailTitleRow(state: StockClassificationPageState): HTMLElement {
  const titleRow = document.createElement('div')
  Object.assign(titleRow.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px',
  })

  state.detailTitleRef = document.createElement('div')
  Object.assign(state.detailTitleRef.style, {
    fontSize: FONT_SIZE.section, fontWeight: 'normal', color: COLOR.neutral,
  })
  titleRow.appendChild(state.detailTitleRef)

  const btnGroup = document.createElement('div')
  Object.assign(btnGroup.style, { display: 'flex', gap: '4px' })

  const selectAllBtn = createSolidBtn({
    label: '전체 선택', color: COLOR.down, editControl: true, onClick: () => handleSelectAll(state),
  })
  Object.assign(selectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })

  const deselectAllBtn = createSolidBtn({
    label: '전체 해제', color: COLOR.tertiary, editControl: true, onClick: () => handleDeselectAll(state),
  })
  Object.assign(deselectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })

  btnGroup.appendChild(selectAllBtn)
  btnGroup.appendChild(deselectAllBtn)
  titleRow.appendChild(btnGroup)
  return titleRow
}

function buildDetailColumns(): ColumnDef<DetailRow>[] {
  return [
    {
      key: 'code', label: '종목코드', minWidth: 72, maxWidth: 72, align: 'center',
      cellStyle: { color: COLOR.disabled, fontSize: FONT_SIZE.small },
      render: (row) => row.code,
    },
    createStockNameColumn<DetailRow>(
      (row: DetailRow) => {
        const hotState = hotStore.getState()
        const masterStock = hotState.masterStocks[normalizeStockCode(row.code)]
        return {
          name: row.name,
          market_type: masterStock?.market_type ?? row.market_type,
          nxt_enable: masterStock?.nxt_enable ?? row.nxt_enable
        }
      }
    ),
  ]
}

/** 드래그 시작 및 단일/다중 클릭 핸들러 */
function handleDetailMouseDown(state: StockClassificationPageState, e: MouseEvent): void {
  if (e.button !== 0) return // 좌클릭만 허용
  const tr = (e.target as HTMLElement).closest('tr')
  if (!tr || !state.selectedSector) return
  const clickedCode = tr.dataset.rowKey
  if (!clickedCode) return

  e.preventDefault()
  state.isDragging = true

  const stocks = getStocksForSector(state, state.selectedSector)
  const idx = stocks.findIndex(s => s.code === clickedCode)
  if (idx < 0) return

  if (e.shiftKey && state.anchorRow >= 0) {
    const [start, end] = [Math.min(state.anchorRow, idx), Math.max(state.anchorRow, idx)]
    for (let i = start; i <= end; i++) state.selectedStocks.add(stocks[i].code)
  } else if (e.ctrlKey || e.metaKey) {
    if (state.selectedStocks.has(clickedCode)) state.selectedStocks.delete(clickedCode)
    else state.selectedStocks.add(clickedCode)
    state.anchorRow = idx
  } else {
    state.selectedStocks.clear()
    state.selectedStocks.add(clickedCode)
    state.anchorRow = idx
  }

  if (state.selectedSector) {
    const updatedStocks = getStocksForSector(state, state.selectedSector)
    state.detailTableRef!.updateRows(updatedStocks)
  }
  callbacks!.updateAllInlineMoveButtons()
}

/** 드래그 중 영역 선택 */
function handleDetailMouseOver(state: StockClassificationPageState, e: MouseEvent): void {
  if (!state.isDragging || !state.selectedSector) return
  const tr = (e.target as HTMLElement).closest('tr')
  if (!tr) return
  const clickedCode = tr.dataset.rowKey
  if (!clickedCode) return

  const stocks = getStocksForSector(state, state.selectedSector)
  const idx = stocks.findIndex(s => s.code === clickedCode)
  if (idx < 0 || state.anchorRow < 0) return

  state.selectedStocks.clear()
  const [start, end] = [Math.min(state.anchorRow, idx), Math.max(state.anchorRow, idx)]
  for (let i = start; i <= end; i++) state.selectedStocks.add(stocks[i].code)

  if (state.selectedSector) {
    const updatedStocks = getStocksForSector(state, state.selectedSector)
    state.detailTableRef!.updateRows(updatedStocks)
  }
  callbacks!.updateAllInlineMoveButtons()
}

function buildDetailTable(state: StockClassificationPageState): HTMLElement {
  state.detailTableRef = createDataTable<DetailRow>({
    columns: buildDetailColumns(),
    emptyText: '종목이 없습니다.',
    stickyHeader: true,
    keyFn: (row) => row.code,
    rowStyle: (row) => {
      if (state.selectedStocks.has(row.code)) {
        return { cursor: 'pointer', background: COLOR.downBg, transition: '' }
      }
      return { cursor: 'pointer', background: '', transition: '' }
    },
  })

  state.detailTableRef.el.tabIndex = 0

  // 전역 마우스 업 이벤트로 드래그 상태 해제
  state.onWindowMouseUp = () => { state.isDragging = false }
  window.addEventListener('mouseup', state.onWindowMouseUp)

  state.detailTableRef.el.addEventListener('mousedown', (e) => handleDetailMouseDown(state, e))
  state.detailTableRef.el.addEventListener('mouseover', (e) => handleDetailMouseOver(state, e))

  // Esc 키 → 전체 선택 해제
  state.onDetailKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      state.selectedStocks.clear()
      state.anchorRow = -1
      if (state.selectedSector && state.detailTableRef) {
        const updatedStocks = getStocksForSector(state, state.selectedSector)
        state.detailTableRef.updateRows(updatedStocks)
      }
      callbacks!.updateAllInlineMoveButtons()
    }
  }
  state.detailTableRef.el.addEventListener('keydown', state.onDetailKeyDown)
  return state.detailTableRef.el
}

export function buildTripleCenter(state: StockClassificationPageState): void {
  const center = shell.tripleCenter
  while (center.firstChild) center.removeChild(center.firstChild)
  center.style.fontFamily = FONT_FAMILY

  state.centerContentRef = document.createElement('div')
  center.appendChild(state.centerContentRef)
  state.centerContentRef.appendChild(buildStagingPanel(state))
  state.centerContentRef.appendChild(buildDetailTitleRow(state))
  state.centerContentRef.appendChild(buildDetailTable(state))

  // 초기 빈 상태
  updateCenterPanel(state)
}

export function updateCenterPanel(state: StockClassificationPageState): void {
  if (!state.centerContentRef || !state.detailTitleRef || !state.detailTableRef) return

  if (state.selectedSector === null) {
    state.detailTitleRef.textContent = ''
    state.detailTableRef.el.style.display = 'none'
    // Hide title row via CSS display
    const titleRow = state.detailTitleRef.parentElement
    if (titleRow) titleRow.style.display = 'none'
    // Show empty message
    if (!state.centerEmptyRef) {
      state.centerEmptyRef = document.createElement('div')
      Object.assign(state.centerEmptyRef.style, { color: COLOR.muted, textAlign: 'center', padding: '40px 0' })
      state.centerEmptyRef.textContent = '좌측에서 업종을 선택하세요'
      state.centerContentRef.appendChild(state.centerEmptyRef)
    }
    state.centerEmptyRef.style.display = ''
    return
  }

  // Hide empty message, show title row + table
  if (state.centerEmptyRef) state.centerEmptyRef.style.display = 'none'
  const titleRow = state.detailTitleRef.parentElement
  if (titleRow) titleRow.style.display = ''
  state.detailTableRef.el.style.display = ''

  const stocks = getStocksForSector(state, state.selectedSector)
  state.detailTitleRef.textContent = `${state.selectedSector} 종목 목록 (${stocks.length}개)`
  state.detailTableRef.updateRows(stocks)

  const storeState = stockClassificationStore.getState()
  callbacks!.setControlsDisabled(!storeState.editWindowOpen)
}
