// frontend/src/pages/stock-classification.ts
// 업종관리 페이지 — 3컬럼(triple) 레이아웃 전면 재작성

import { shell } from '../main'
import { stockClassificationStore, computeEditWindowOpenByTime, type StockClassificationState } from '../stores/stockClassificationStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import { createSettingsManager, type SettingsManager } from '../settings'
import { toastResult } from '../components/common/toast'
import { showContextPopup, closeContextPopup } from '../components/common/context-popup'
import { type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createSectorRowEl } from '../components/common/sector-row'
import { FONT_SIZE, FONT_FAMILY, COLOR } from '../components/common/ui-styles'
import type { PageModule } from '../router'
import type { StockClassificationMutationResponse } from '../types'
import {
  handleMutationResult,
  buildMoveMessage,
  type MasterRow,
  type DetailRow,
  type SearchResultRow,
} from './stock-classification-shared'
import {
  getAllStocks,
  clearStaging,
  updateStagingChipSectors,
  initStagingCallbacks,
  resetStagingCallbacks,
} from './stock-classification-staging'
import {
  buildTripleHeader,
  updateIndicatorBar,
} from './stock-classification-header'
import {
  buildTripleLeft,
  updateMasterPanel,
  getActiveSectors,
  initMasterCallbacks,
  resetMasterCallbacks,
} from './stock-classification-master'
import {
  buildTripleCenter,
  updateCenterPanel,
  initCenterCallbacks,
  resetCenterCallbacks,
} from './stock-classification-center'

/* ── 모듈 상태 (P10 SSOT — 모든 가변 상태를 단일 소스로 관리) ── */

export interface StockClassificationPageState {
  // 캐시 (allStocks 파생)
  cachedSectorStocksRef: StockClassificationState['allStocks'] | null
  cachedAllStocksMap: Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }>
  stockNameIndex: Map<string, string>  // 종목명 → 종목코드 역인덱스
  // 구독/생명주기
  unsubCustom: (() => void) | null
  unsubSse: (() => void) | null
  unsubSettings: (() => void) | null
  unsubHot: (() => void) | null
  settingsMgr: SettingsManager | null
  mounted: boolean  // P19: unmount 후 async 응답으로 인한 store 업데이트 방지
  // Indicator Bar (헤더)
  indicatorLabelMain: HTMLElement | null
  indicatorLabelSub: HTMLElement | null
  // Staging / Selection
  stagingSet: Set<string>
  stagingChipMap: Map<string, HTMLElement>  // 코드 → Chip DOM 매핑
  stagingPanelRef: HTMLElement | null       // Staging_Panel 컨테이너
  stagingCountRef: HTMLElement | null       // "N개 선택" 카운트 라벨
  stagingEmptyRef: HTMLElement | null       // 빈 상태 안내 메시지
  selectedStocks: Set<string>
  // Sector Table (Left)
  selectedSector: string | null
  anchorRow: number
  isDragging: boolean
  masterTableRef: DataTableApi<MasterRow> | null
  statsLabelRef: HTMLElement | null
  addSectorBtnRef: HTMLElement | null
  // Search
  searchInputRef: ReturnType<typeof createSearchInput> | null
  searchResultTableRef: DataTableApi<SearchResultRow> | null
  // Center (Stock List)
  centerContentRef: HTMLElement | null
  centerEmptyRef: HTMLElement | null
  detailTitleRef: HTMLElement | null
  detailTableRef: DataTableApi<DetailRow> | null
  // 이벤트 리스너 — unmount 시 removeEventListener로 제거 (P19 메모리 누수 방지)
  onWindowMouseUp: (() => void) | null
  onDetailKeyDown: ((e: KeyboardEvent) => void) | null
  // Right (Target_Sector_List)
  rightContentRef: HTMLElement | null
  rightEmptyRef: HTMLElement | null
  targetSectorListRef: HTMLElement | null
  sectorRowMap: Map<string, HTMLElement>
  prevTargetSectors: Set<string>
  selectedTargetSector: string | null  // 우측 패널 선택된 대상 업종
}

function createState(): StockClassificationPageState {
  return {
    cachedSectorStocksRef: null,
    cachedAllStocksMap: new Map(),
    stockNameIndex: new Map(),
    unsubCustom: null,
    unsubSse: null,
    unsubSettings: null,
    unsubHot: null,
    settingsMgr: null,
    mounted: false,
    indicatorLabelMain: null,
    indicatorLabelSub: null,
    stagingSet: new Set(),
    stagingChipMap: new Map(),
    stagingPanelRef: null,
    stagingCountRef: null,
    stagingEmptyRef: null,
    selectedStocks: new Set(),
    selectedSector: null,
    anchorRow: -1,
    isDragging: false,
    masterTableRef: null,
    statsLabelRef: null,
    addSectorBtnRef: null,
    searchInputRef: null,
    searchResultTableRef: null,
    centerContentRef: null,
    centerEmptyRef: null,
    detailTitleRef: null,
    detailTableRef: null,
    onWindowMouseUp: null,
    onDetailKeyDown: null,
    rightContentRef: null,
    rightEmptyRef: null,
    targetSectorListRef: null,
    sectorRowMap: new Map(),
    prevTargetSectors: new Set(),
    selectedTargetSector: null,
  }
}

const state: StockClassificationPageState = createState()

/* ── 순수 함수 및 유틸리티 (Task 1) ── */
// parseBatchInput, handleMutationResult, cardWrap, buildMoveMessage 는 stock-classification-shared.ts 로 이관 (F-04 분할)
// getAllStocks, createChip, addToStaging, removeFromStaging, clearStaging, updateStagingPanel,
// updateStagingChipSectors, countStocksBySector, getStocksForSector 는 stock-classification-staging.ts 로 이관 (F-04 분할 2단계)
// resolveToken, buildSectorManageTitle, collectFuzzyResults, handleSearchQuery, buildSearchInputEl,
// handleSearchResultClick, buildSearchResultTable, renderCountCell, renderActionsCell, buildMasterColumns,
// handleMasterRowClick, buildMasterTable, buildSectorManageCard, getActiveSectors, buildMasterRows,
// updateMasterPanel, updateStatsLabel, onRenameSector, onDeleteSector, onAddSector, buildTripleLeft 는
// stock-classification-master.ts 로 이관 (F-04 분할 4단계)
// buildStagingPanel, handleSelectAll, handleDeselectAll, buildDetailTitleRow, buildDetailColumns,
// handleDetailMouseDown, handleDetailMouseOver, buildDetailTable, buildTripleCenter, updateCenterPanel 는
// stock-classification-center.ts 로 이관 (F-04 분할 5단계)

/** Task 1.5: Move_Source 결정 — state.stagingSet 우선, 비어있으면 state.selectedStocks, 둘 다 비면 null */
function getMoveSource(): { source: 'staging' | 'checked'; codes: string[] } | null {
  if (state.stagingSet.size > 0) return { source: 'staging', codes: [...state.stagingSet] }
  if (state.selectedStocks.size > 0) return { source: 'checked', codes: [...state.selectedStocks] }
  return null
}

/** Task 1.5: 이동 가능 종목 수 (버튼 텍스트용) */
function getMovableCount(): number {
  if (state.stagingSet.size > 0) return state.stagingSet.size
  return state.selectedStocks.size
}

/* ── 8.9: editWindowOpen disabled 상태 적용 ── */

function setControlsDisabled(disabled: boolean): void {
  // Query across all 3 columns + header
  const panels = [shell.tripleHeader, shell.tripleLeft, shell.tripleCenter, shell.tripleRight]
  for (const panel of panels) {
    const els = panel.querySelectorAll<HTMLElement>('[data-edit-control]')
    els.forEach(el => {
      if (el instanceof HTMLButtonElement || el instanceof HTMLSelectElement || el instanceof HTMLInputElement) {
        (el as HTMLButtonElement | HTMLSelectElement | HTMLInputElement).disabled = disabled
      }
      el.style.opacity = disabled ? '0.4' : '1'
      el.style.pointerEvents = disabled ? 'none' : 'auto'
    })
  }
}

/* ── 8.5: tripleRight — Target_Sector_List ── */

/** 대상 업종 목록 반환: activeSectors에서 state.selectedSector 제외 */
function getTargetSectors(): string[] {
  const activeSectors = getActiveSectors(state)
  // 배치 입력: state.selectedSector 없어도 staging에 종목이 있으면 전체 업종 표시
  if (state.selectedSector === null && state.stagingSet.size > 0) {
    return activeSectors
  }
  if (state.selectedSector === null) return []
  return activeSectors.filter(s => s !== state.selectedSector)
}

/** 업종 행 하나 생성: [업종명 span (flex:1)] + [이동 버튼] */
function createSectorRow(sectorName: string): HTMLElement {
  const count = getMovableCount()
  const row = createSectorRowEl({
    sectorName,
    btnText: count > 0 ? `${count}개 이동` : '이동',
    btnDisabled: count === 0,
    onBtnClick: (e) => onMoveStock(e, sectorName),
    onRowClick: () => {
      const prev = state.selectedTargetSector
      state.selectedTargetSector = state.selectedTargetSector === sectorName ? null : sectorName
      if (prev && state.sectorRowMap.has(prev)) {
        state.sectorRowMap.get(prev)!.style.background = ''
      }
      if (state.selectedTargetSector) {
        row.style.background = COLOR.downBg
      } else {
        row.style.background = ''
      }
    },
  })

  // hover 시 배경색 (선택 상태가 아닐 때만)
  row.addEventListener('mouseenter', () => {
    if (state.selectedTargetSector !== sectorName) row.style.background = COLOR.neutralBg
  })
  row.addEventListener('mouseleave', () => {
    if (state.selectedTargetSector !== sectorName) row.style.background = ''
  })

  return row
}

function buildTripleRight(): void {
  const right = shell.tripleRight
  while (right.firstChild) right.removeChild(right.firstChild)
  right.style.fontFamily = FONT_FAMILY

  state.rightContentRef = document.createElement('div')
  Object.assign(state.rightContentRef.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  right.appendChild(state.rightContentRef)

  // 제목
  const title = document.createElement('div')
  Object.assign(title.style, {
    fontSize: FONT_SIZE.section, fontWeight: 'normal', color: COLOR.neutral, marginBottom: '8px',
  })
  title.textContent = '대상 업종'
  state.rightContentRef.appendChild(title)

  // 업종 검색란
  const targetSearchInput = createSearchInput({
    label: '업종 검색',
    labelColor: COLOR.warning,
    placeholder: '업종 검색',
    width: '100%',
    borderColor: COLOR.warning,
    onSearch: (query) => {
      const q = query.toLowerCase()
      for (const [name, row] of state.sectorRowMap) {
        row.style.display = (!q || name.toLowerCase().includes(q)) ? 'flex' : 'none'
      }
    },
  })
  state.rightContentRef.appendChild(targetSearchInput.el)

  // Target_Sector_List 컨테이너
  state.targetSectorListRef = document.createElement('div')
  Object.assign(state.targetSectorListRef.style, { overflowY: 'auto', flex: '1' })
  state.rightContentRef.appendChild(state.targetSectorListRef)

  // 초기화
  state.sectorRowMap = new Map()
  state.prevTargetSectors = new Set()

  // 초기 행 렌더링
  updateTargetSectorList()

  // 초기 상태
  updateRightPanel()
}

/** Target_Sector_List 델타 갱신 */
function updateTargetSectorList(): void {
  if (!state.targetSectorListRef) return
  const newTargets = getTargetSectors()
  const newSet = new Set(newTargets)

  // 제거: 이전에 있었지만 새 목록에 없는 업종
  for (const s of state.prevTargetSectors) {
    if (!newSet.has(s)) {
      state.sectorRowMap.get(s)?.remove()
      state.sectorRowMap.delete(s)
    }
  }

  // 추가: 새 목록에 있지만 이전에 없던 업종
  for (const s of newTargets) {
    if (!state.prevTargetSectors.has(s) && !state.sectorRowMap.has(s)) {
      const row = createSectorRow(s)
      state.sectorRowMap.set(s, row)
      state.targetSectorListRef.appendChild(row)
    }
  }

  state.prevTargetSectors = newSet
}

/** 모든 인라인 이동 버튼의 텍스트 + disabled 상태 갱신 (Task 8.1, 8.3) */
function updateAllInlineMoveButtons(): void {
  const count = getMovableCount()
  const disabled = count === 0
  for (const [, row] of state.sectorRowMap) {
    const btn = row.querySelector('button')
    if (btn) {
      btn.textContent = count > 0 ? `${count}개 이동` : '이동'
      btn.disabled = disabled
      btn.style.opacity = disabled ? '0.4' : '1'
      btn.style.pointerEvents = disabled ? 'none' : 'auto'
    }
  }
}

function updateRightPanel(): void {
  if (!state.rightContentRef) return

  if (state.selectedSector === null && state.stagingSet.size === 0) {
    // Hide all children via CSS display, show empty message
    for (const child of Array.from(state.rightContentRef.children)) {
      (child as HTMLElement).style.display = 'none'
    }
    if (!state.rightEmptyRef) {
      state.rightEmptyRef = document.createElement('div')
      Object.assign(state.rightEmptyRef.style, { color: COLOR.muted, textAlign: 'center', padding: '40px 0' })
      state.rightEmptyRef.textContent = '좌측에서 업종을 선택하세요'
      state.rightContentRef.appendChild(state.rightEmptyRef)
    }
    state.rightEmptyRef.style.display = ''
    return
  }

  // Hide empty message, show all children
  if (state.rightEmptyRef) state.rightEmptyRef.style.display = 'none'
  for (const child of Array.from(state.rightContentRef.children)) {
    if (child !== state.rightEmptyRef) (child as HTMLElement).style.display = ''
  }
  // Restore flex display on the container's direct children that need it
  if (state.targetSectorListRef) state.targetSectorListRef.style.display = ''

  // If refs were cleared (e.g. after unmount/remount), rebuild
  if (!state.targetSectorListRef) {
    buildTripleRight()
    return
  }

  updateTargetSectorList()
  updateAllInlineMoveButtons()
  const storeState = stockClassificationStore.getState()
  setControlsDisabled(!storeState.editWindowOpen)
}

async function onMoveStock(e: MouseEvent, targetSector: string): Promise<void> {
  const moveSource = getMoveSource()
  if (!moveSource) return
  const codes = moveSource.codes

  // 이동 전 확인 팝업 (마우스 위치 기반 — 전체 화면 오버레이 없음)
  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: '종목 이동',
    message: buildMoveMessage(codes, getAllStocks(state), targetSector),
    confirmText: '이동',
    cancelText: '취소',
  })
  if (!result.confirmed) return

  try {
    const lastRes = await api.post<StockClassificationMutationResponse>('/api/stock-classification/move-stocks', {
      stock_codes: codes,
      target_sector: targetSector,
    })
    handleMutationResult(lastRes)

    // unmount 후 응답 도착 시 store 업데이트 차단 (P19 race condition 방지)
    if (!state.mounted) return

    // 서버 응답 기반 로컬 상태 업데이트 — allStocks + stockMoves 통합 setState (1회 렌더)
    if (lastRes.ok && lastRes.all_stocks && Array.isArray(lastRes.all_stocks)) {
      const currentState = stockClassificationStore.getState()
      const newStockMoves = { ...currentState.stockMoves }
      for (const code of codes) {
        newStockMoves[code] = targetSector
      }
      stockClassificationStore.setState({ allStocks: lastRes.all_stocks, stockMoves: newStockMoves })
    }

    if (moveSource.source === 'staging') {
      clearStaging(state)
    }
  } catch { toastResult({ ok: false }) }
}

/* ── 8.0: store의 allStocks로 state.stockNameIndex 업데이트 ── */

function updateStockNameIndex(): void {
  const allStocks = getAllStocks(state)
  state.stockNameIndex = new Map()
  for (const [code, stock] of allStocks) {
    state.stockNameIndex.set(stock.name, code)
  }
}

/* ── 8.1 + 8.8: mount / unmount ── */

/** stockClassificationStore 구독 — 데이터 변경 시 이동한 종목만 선택 상태에서 제거 */
function handleStockDataChange(storeState: StockClassificationState, prev: StockClassificationState): void {
  if (storeState.allStocks !== prev.allStocks) {
    updateStockNameIndex()
  }

  // Check if state.selectedSector still exists (미분류 등 특수 카테고리 포함)
  if (state.selectedSector && !getActiveSectors(state).includes(state.selectedSector)) {
    state.selectedSector = null
  }

  // 이동한 종목 코드 식별 (stockMoves가 변경된 종목)
  const prevStockMoves = prev.stockMoves
  const newStockMoves = storeState.stockMoves
  const movedCodes: string[] = []
  for (const code of state.selectedStocks) {
    if (prevStockMoves[code] !== newStockMoves[code]) {
      movedCodes.push(code)
    }
  }

  // 이동한 종목만 선택 상태에서 제거
  for (const code of movedCodes) {
    state.selectedStocks.delete(code)
  }

  // 모든 종목이 이동한 경우 state.anchorRow 초기화
  if (state.selectedStocks.size === 0) {
    state.anchorRow = -1
  }

  updateMasterPanel(state)
  updateCenterPanel(state)
  updateRightPanel()
  updateStagingChipSectors(state)
}

/** stockClassificationStore 구독 콜백 */
function handleStockClassificationChange(storeState: StockClassificationState, prev: StockClassificationState | null): void {
  if (!prev) {
    // 첫 호출: 초기 렌더링
    updateStockNameIndex()
    updateMasterPanel(state)
    updateCenterPanel(state)
    updateRightPanel()
    updateStagingChipSectors(state)
    updateIndicatorBar(state)
    return
  }

  if (storeState.allStocks !== prev.allStocks || storeState.mergedSectors !== prev.mergedSectors || storeState.sectors !== prev.sectors || storeState.stockMoves !== prev.stockMoves) {
    handleStockDataChange(storeState, prev)
  }

  if (storeState.allStocks !== prev.allStocks || storeState.editWindowOpen !== prev.editWindowOpen || storeState.filter_summary !== prev.filter_summary) {
    updateIndicatorBar(state)
    setControlsDisabled(!storeState.editWindowOpen)
  }
}

/** uiStore 구독 콜백 — settings 변경 시 editWindowOpen 재계산 */
function handleUiStoreChange(uiState: { settings: ReturnType<typeof uiStore.getState>['settings'] }, prevSettingsRef: { settings: ReturnType<typeof uiStore.getState>['settings'] }): void {
  if (uiState.settings !== prevSettingsRef.settings) {
    prevSettingsRef.settings = uiState.settings
    const newEditWindowOpen = computeEditWindowOpenByTime(uiState.settings)
    if (newEditWindowOpen !== stockClassificationStore.getState().editWindowOpen) {
      stockClassificationStore.setState({ editWindowOpen: newEditWindowOpen })
    }
  }
}

function mount(_container: HTMLElement): void {
  notifyPageActive('stock-classification')
  state.mounted = true
  // Staging 분할 모듈에 main 잔류 함수 주입 (순환 참조 해결 — F-04 분할 2단계)
  initStagingCallbacks({ updateAllInlineMoveButtons, updateRightPanel })
  // Master 분할 모듈에 main 잔류 함수 주입 (순환 참조 해결 — F-04 분할 4단계)
  initMasterCallbacks({ setControlsDisabled, onRowClickUpdatePanels: () => { updateCenterPanel(state); updateRightPanel() } })
  // Center 분할 모듈에 main 잔류 함수 주입 (순환 참조 해결 — F-04 분할 5단계)
  initCenterCallbacks({ updateAllInlineMoveButtons, setControlsDisabled })
  buildTripleHeader(state)
  buildTripleLeft(state)
  buildTripleCenter(state)
  buildTripleRight()

  state.settingsMgr = createSettingsManager()

  // Initialize editWindowOpen state
  const initialSettings = uiStore.getState().settings
  const initialEditWindowOpen = computeEditWindowOpenByTime(initialSettings)
  stockClassificationStore.setState({ editWindowOpen: initialEditWindowOpen })

  // stockClassificationStore 구독
  let prevState: StockClassificationState | null = null
  state.unsubCustom = stockClassificationStore.subscribe((storeState) => {
    const prev = prevState
    prevState = storeState
    handleStockClassificationChange(storeState, prev)
  })

  // uiStore 구독 — settings 변경 시 editWindowOpen 재계산 + 토글 갱신
  const prevSettingsRef = { settings: uiStore.getState().settings }
  state.unsubSse = uiStore.subscribe((uiState) => {
    handleUiStoreChange(uiState, prevSettingsRef)
  })

  // 초기 렌더링 강제 실행 (초기 상태 반영)
  updateStockNameIndex()
  updateIndicatorBar(state)
  updateMasterPanel(state)
  updateCenterPanel(state)
  updateRightPanel()
}

/* ── 8.8: unmount ── */

function unmount(): void {
  notifyPageInactive('stock-classification')
  state.mounted = false
  resetStagingCallbacks()
  resetMasterCallbacks()
  resetCenterCallbacks()
  if (state.unsubCustom) { state.unsubCustom(); state.unsubCustom = null }
  if (state.unsubSse) { state.unsubSse(); state.unsubSse = null }
  if (state.unsubSettings) { state.unsubSettings(); state.unsubSettings = null }
  if (state.unsubHot) { state.unsubHot(); state.unsubHot = null }
  if (state.settingsMgr) { state.settingsMgr.destroy(); state.settingsMgr = null }
  closeContextPopup()

  // 전역/요소 이벤트 리스너 제거 (P19 메모리 누수 방지)
  if (state.onWindowMouseUp) { window.removeEventListener('mouseup', state.onWindowMouseUp); state.onWindowMouseUp = null }
  if (state.onDetailKeyDown && state.detailTableRef) { state.detailTableRef.el.removeEventListener('keydown', state.onDetailKeyDown); state.onDetailKeyDown = null }

  // Null all DOM refs
  state.indicatorLabelMain = null
  state.indicatorLabelSub = null
  state.masterTableRef = null
  state.statsLabelRef = null
  state.addSectorBtnRef = null
  state.searchInputRef = null
  state.searchResultTableRef = null
  state.centerContentRef = null
  state.centerEmptyRef = null
  state.detailTitleRef = null
  state.detailTableRef = null
  state.rightContentRef = null
  state.rightEmptyRef = null
  state.targetSectorListRef = null
  state.sectorRowMap = new Map()
  state.prevTargetSectors = new Set()

  state.selectedSector = null
  state.selectedTargetSector = null
  state.anchorRow = -1
  state.stagingSet = new Set()
  state.stagingChipMap = new Map()
  state.stagingPanelRef = null
  state.stagingCountRef = null
  state.stagingEmptyRef = null
  state.selectedStocks = new Set()
  state.stockNameIndex = new Map()
  state.cachedSectorStocksRef = null
  state.cachedAllStocksMap = new Map()

  // Clear shell triple panels
  while (shell.tripleHeader.firstChild) shell.tripleHeader.removeChild(shell.tripleHeader.firstChild)
  while (shell.tripleLeft.firstChild) shell.tripleLeft.removeChild(shell.tripleLeft.firstChild)
  while (shell.tripleCenter.firstChild) shell.tripleCenter.removeChild(shell.tripleCenter.firstChild)
  while (shell.tripleRight.firstChild) shell.tripleRight.removeChild(shell.tripleRight.firstChild)
}

const pageModule: PageModule = { mount, unmount }
export default pageModule
