// frontend/src/pages/stock-classification.ts
// 종목분류 페이지 — 3컬럼(triple) 레이아웃 전면 재작성

import { shell } from '../main'
import { stockClassificationStore, computeEditWindowOpenByTime, type StockClassificationState } from '../stores/stockClassificationStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createPageRefreshStatus } from '../utils/page-refresh'
import { createSettingsManager, type SettingsManager } from '../settings'
import { closeContextPopup } from '../components/common/context-popup'
import { type DataTableApi } from '../components/common/data-table'
import type { createSearchInput } from '../components/common/search-input'
import type { PageModule } from '../router'
import {
  type MasterRow,
  type DetailRow,
  type SearchResultRow,
} from './stock-classification-shared'
import {
  getAllStocks,
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
import {
  buildTripleRight,
  updateRightPanel,
  updateAllInlineMoveButtons,
  initRightCallbacks,
  resetRightCallbacks,
} from './stock-classification-right'

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
  refreshStatus: ReturnType<typeof createPageRefreshStatus> | null
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
    refreshStatus: null,
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
// getMoveSource, getMovableCount, getTargetSectors, createSectorRow, buildTripleRight, updateTargetSectorList,
// updateAllInlineMoveButtons, updateRightPanel, onMoveStock 는 stock-classification-right.ts 로 이관 (F-04 분할 6단계)

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
  updateRightPanel(state)
  updateStagingChipSectors(state)
}

/** stockClassificationStore 구독 콜백 */
function handleStockClassificationChange(storeState: StockClassificationState, prev: StockClassificationState | null): void {
  if (!prev) {
    // 첫 호출: 초기 렌더링
    updateStockNameIndex()
    updateMasterPanel(state)
    updateCenterPanel(state)
    updateRightPanel(state)
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
  initStagingCallbacks({ updateAllInlineMoveButtons: () => updateAllInlineMoveButtons(state), updateRightPanel: () => updateRightPanel(state) })
  // Master 분할 모듈에 main 잔류 함수 주입 (순환 참조 해결 — F-04 분할 4단계)
  initMasterCallbacks({ setControlsDisabled, onRowClickUpdatePanels: () => { updateCenterPanel(state); updateRightPanel(state) } })
  // Center 분할 모듈에 main 잔류 함수 주입 (순환 참조 해결 — F-04 분할 5단계)
  initCenterCallbacks({ updateAllInlineMoveButtons: () => updateAllInlineMoveButtons(state), setControlsDisabled })
  // Right 분할 모듈에 main 잔류 함수 주입 (순환 참조 해결 — F-04 분할 6단계)
  initRightCallbacks({ setControlsDisabled })
  buildTripleHeader(state)
  buildTripleLeft(state)
  buildTripleCenter(state)
  buildTripleRight(state)
  state.refreshStatus = createPageRefreshStatus()
  shell.tripleHeader.insertBefore(state.refreshStatus.el, shell.tripleHeader.firstChild)

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
  updateRightPanel(state)
  // 초기 자료는 서버가 stock-classification-snapshot 이벤트로 전송 — binding.ts가 store에 적용.
  // 페이지 진입 시 별도 HTTP 조회를 하지 않고 store 구독으로 자동 갱신.
}

/* ── 8.8: unmount ── */

function unmount(): void {
  notifyPageInactive('stock-classification')
  state.mounted = false
  resetStagingCallbacks()
  resetMasterCallbacks()
  resetCenterCallbacks()
  resetRightCallbacks()
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
  state.refreshStatus = null

  // Clear shell triple panels
  while (shell.tripleHeader.firstChild) shell.tripleHeader.removeChild(shell.tripleHeader.firstChild)
  while (shell.tripleLeft.firstChild) shell.tripleLeft.removeChild(shell.tripleLeft.firstChild)
  while (shell.tripleCenter.firstChild) shell.tripleCenter.removeChild(shell.tripleCenter.firstChild)
  while (shell.tripleRight.firstChild) shell.tripleRight.removeChild(shell.tripleRight.firstChild)
}

const pageModule: PageModule = { mount, unmount }
export default pageModule
