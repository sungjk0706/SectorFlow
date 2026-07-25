// frontend/src/pages/stock-classification.ts
// 업종관리 페이지 — 3컬럼(triple) 레이아웃 전면 재작성

import { shell } from '../main'
import { stockClassificationStore, computeEditWindowOpenByTime, type StockClassificationState } from '../stores/stockClassificationStore'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import { createSettingsManager, type SettingsManager } from '../settings'
import { createCardTitleWithContent } from '../components/common/card-title'
import { toastResult } from '../components/common/toast'
import { showContextPopup, closeContextPopup } from '../components/common/context-popup'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createSectorRowEl } from '../components/common/sector-row'
import { createSolidBtn } from '../components/common/button'
import { createStepLabel } from '../components/common/settings-common'
import { FONT_SIZE, FONT_FAMILY, FONT_WEIGHT, createStockNameColumn, COLOR } from '../components/common/ui-styles'
import type { PageModule } from '../router'
import type { StockClassificationMutationResponse } from '../types'
import {
  handleMutationResult,
  parseBatchInput,
  cardWrap,
  buildMoveMessage,
  type MasterRow,
  type DetailRow,
  type SearchResultRow,
} from './stock-classification-shared'
import {
  getAllStocks,
  addToStaging,
  clearStaging,
  updateStagingPanel,
  updateStagingChipSectors,
  countStocksBySector,
  getStocksForSector,
  initStagingCallbacks,
  resetStagingCallbacks,
} from './stock-classification-staging'

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

/** Task 1.3: 토큰 → 종목코드 매칭. 코드 우선(O(1)), 종목명 차선(O(1)), 미매칭 시 null
 *  "나인테크(267320)" 형태 → 괄호 안 코드 추출 후 매칭, 실패 시 괄호 밖 이름으로 재시도 */
function resolveToken(token: string): string | null {
  if (getAllStocks(state).has(token)) return token
  const codeByName = state.stockNameIndex.get(token)
  if (codeByName !== undefined) return codeByName

  // 괄호 포함 형태: "나인테크(267320)" 또는 "나인테크（267320）"
  const m = token.match(/^(.+?)[(\uff08]([^)\uff09]+)[)\uff09]$/)
  if (m) {
    const name = m[1].trim()
    const code = m[2].trim()
    if (getAllStocks(state).has(code)) return code
    const codeByName2 = state.stockNameIndex.get(name)
    if (codeByName2 !== undefined) return codeByName2
  }

  return null
}

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

/* ── 8.2: tripleHeader — 공통 헤더 (Indicator_Bar) ── */

function buildHeaderLeft(): HTMLElement {
  const left = document.createElement('div')
  Object.assign(left.style, {
    flex: '1', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start', gap: '6px', alignItems: 'flex-start'
  })

  const descLabel = createStepLabel('', '장마감 후 매매적격종목 확정시세 및 5거래일 일봉 거래대금,고가 데이터 저장', { whiteSpace: 'nowrap' })
  left.appendChild(descLabel)

  const buttonContainer = document.createElement('div')
  Object.assign(buttonContainer.style, { display: 'flex', gap: '6px' })

  const btn1 = createSolidBtn({
    label: '⬇️ 일봉차트 시세 다운로드',
    color: COLOR.success,
    hoverColor: '#157347',
    onClick: (e) => onTriggerConfirmedDownload(e),
  })
  const btn2 = createSolidBtn({
    label: '⬇️ 5거래일 일봉차트 거래대금,고가 다운로드',
    color: COLOR.success,
    hoverColor: '#157347',
    onClick: (e) => onTrigger5dDownload(e),
  })

  buttonContainer.appendChild(btn1)
  buttonContainer.appendChild(btn2)
  left.appendChild(buttonContainer)
  return left
}

function buildHeaderCenter(): HTMLElement {
  const center = document.createElement('div')
  Object.assign(center.style, {
    flex: '1', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
    textAlign: 'center', fontSize: FONT_SIZE.title,
    minWidth: '0',
  })
  return center
}

function buildHeaderRight(): HTMLElement {
  const right = document.createElement('div')
  Object.assign(right.style, {
    flex: '3', display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
    justifyContent: 'center', textAlign: 'right', minWidth: '0', gap: '2px',
  })

  state.indicatorLabelMain = document.createElement('span')
  Object.assign(state.indicatorLabelMain.style, {
    fontSize: FONT_SIZE.body, color: COLOR.neutral, whiteSpace: 'nowrap',
    overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%',
  })

  state.indicatorLabelSub = document.createElement('span')
  Object.assign(state.indicatorLabelSub.style, {
    fontSize: FONT_SIZE.small, color: COLOR.tertiary, whiteSpace: 'nowrap',
    overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%',
  })

  right.appendChild(state.indicatorLabelMain)
  right.appendChild(state.indicatorLabelSub)
  return right
}

function buildTripleHeader(): void {
  const header = shell.tripleHeader
  while (header.firstChild) header.removeChild(header.firstChild)
  header.style.fontFamily = FONT_FAMILY
  header.appendChild(buildHeaderLeft())
  header.appendChild(buildHeaderCenter())
  header.appendChild(buildHeaderRight())
}

function updateIndicatorBar(): void {
  const storeState = stockClassificationStore.getState()
  const { filter_summary } = storeState
  if (!state.indicatorLabelMain || !state.indicatorLabelSub) return
  if (!filter_summary) {
    state.indicatorLabelMain.textContent = ''
    state.indicatorLabelSub.textContent = ''
    return
  }
  // "전체 N종목 → 매매 가능 N종목 (제외 N종목, N%)" | "주요 제외: ..."
  const sepIdx = filter_summary.indexOf(' | ')
  if (sepIdx === -1) {
    state.indicatorLabelMain.textContent = filter_summary
    state.indicatorLabelSub.textContent = ''
  } else {
    state.indicatorLabelMain.textContent = filter_summary.slice(0, sepIdx)
    state.indicatorLabelSub.textContent = filter_summary.slice(sepIdx + 3)
  }
}

async function onTriggerConfirmedDownload(e: MouseEvent): Promise<void> {
  const label = '일봉차트 시세 다운로드'
  const endpoint = '/api/stock-classification/trigger-confirmed-download'

  // 설정 재로드 완료 확인
  const { engineReloadComplete } = uiStore.getState()
  if (!engineReloadComplete) {
    toastResult({ ok: false, error: '설정 재로드가 완료되지 않았습니다. 잠시 후 다시 시도하세요.' })
    return
  }

  // 당일 데이터 존재 여부 사전 확인 (P21 사용자 투명성)
  let dataExists: boolean
  try {
    const check = await api.get<{ confirmed_exists: boolean; '5d_exists': boolean }>(
      '/api/stock-classification/download-data-exists',
    )
    dataExists = check.confirmed_exists
  } catch {
    // 확인 API 실패 시 기존 동작 유지 (폴백 아님 — 사용자에게 알림)
    toastResult({ ok: false, error: '데이터 저장 여부 확인에 실패했습니다.' })
    return
  }

  const message = dataExists
    ? `이미 당일 시세 데이터가 저장되어 있습니다.\n${label}를 다시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`
    : `${label}를 지금 수동으로 즉시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`

  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: `${label} 실행`,
    message,
    confirmText: '실행',
    confirmColor: COLOR.success,
  })

  if (!result.confirmed) return

  try {
    const res = await api.post<StockClassificationMutationResponse>(endpoint, {})
    handleMutationResult(res)
  } catch {
    toastResult({ ok: false })
  }
}

async function onTrigger5dDownload(e: MouseEvent): Promise<void> {
  const label = '5거래일 일봉차트 거래대금,고가 다운로드'
  const endpoint = '/api/stock-classification/trigger-5d-download'

  // 설정 재로드 완료 확인
  const { engineReloadComplete } = uiStore.getState()
  if (!engineReloadComplete) {
    toastResult({ ok: false, error: '설정 재로드가 완료되지 않았습니다. 잠시 후 다시 시도하세요.' })
    return
  }

  // 당일 데이터 존재 여부 사전 확인 (P21 사용자 투명성)
  let dataExists: boolean
  try {
    const check = await api.get<{ confirmed_exists: boolean; '5d_exists': boolean }>(
      '/api/stock-classification/download-data-exists',
    )
    dataExists = check['5d_exists']
  } catch {
    toastResult({ ok: false, error: '데이터 저장 여부 확인에 실패했습니다.' })
    return
  }

  const message = dataExists
    ? `이미 당일 5거래일 일봉 데이터가 저장되어 있습니다.\n${label}를 다시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`
    : `${label}를 지금 수동으로 즉시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`

  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: `${label} 실행`,
    message,
    confirmText: '실행',
    confirmColor: COLOR.success,
  })

  if (!result.confirmed) return

  try {
    const res = await api.post<StockClassificationMutationResponse>(endpoint, {})
    handleMutationResult(res)
  } catch {
    toastResult({ ok: false })
  }
}



/* ── 업종 관리 테이블 (Sector_Table) ── */

function buildSectorManageTitle(): HTMLElement {
  const titleContainer = document.createElement('div')
  Object.assign(titleContainer.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
  })
  const titleText = document.createElement('span')
  titleText.textContent = '업종 관리'
  state.statsLabelRef = document.createElement('span')
  Object.assign(state.statsLabelRef.style, { fontSize: FONT_SIZE.small, color: COLOR.tertiary, fontWeight: FONT_WEIGHT.normal })

  // "새 업종 추가"는 중요 액션 → md 사이즈로 작업 컬럼 버튼(sm)보다 한 단계 크게
  state.addSectorBtnRef = createSolidBtn({
    label: '+ 새 업종 추가',
    color: COLOR.down,
    size: 'md',
    editControl: true,
    onClick: (e: MouseEvent) => onAddSector(e),
  })

  const titleRightContainer = document.createElement('div')
  Object.assign(titleRightContainer.style, { display: 'flex', alignItems: 'center', gap: '8px' })
  titleRightContainer.appendChild(state.statsLabelRef)
  titleRightContainer.appendChild(state.addSectorBtnRef)

  titleContainer.appendChild(titleText)
  titleContainer.appendChild(titleRightContainer)
  return createCardTitleWithContent(titleContainer)
}

/** fuzzy 검색 결과 수집 — onSearch 핸들러와 검색 결과 클릭 핸들러에서 공통 사용 (F04-16 중복 제거) */
function collectFuzzyResults(q: string): SearchResultRow[] {
  const storeState = stockClassificationStore.getState()
  const { stockMoves, sectors } = storeState
  const searchTokens = q.split(/[\s()（）]+/).filter(t => t.length > 0)
  const results: SearchResultRow[] = []
  for (const [, stock] of getAllStocks(state)) {
    const nameLower = stock.name.toLowerCase()
    const codeLower = stock.code.toLowerCase()
    const matched = searchTokens.some(t => nameLower.includes(t) || codeLower.includes(t))
    if (matched) {
      let sector = stockMoves[stock.code] ?? stock.sector ?? ''
      if (sectors[sector]) sector = sectors[sector]
      results.push({ code: stock.code, name: stock.name, sector, market_type: stock.market_type, nxt_enable: stock.nxt_enable })
    }
  }
  return results
}

/** onSearch 콜백 — 토큰 분리 후 정확 매칭 시도 → 성공 시 Staging 추가, 실패 시 fuzzy 검색 */
function handleSearchQuery(query: string): void {
  if (!state.searchResultTableRef || !state.masterTableRef) return
  if (!query) {
    state.searchResultTableRef.el.style.display = 'none'
    state.masterTableRef.el.style.display = ''
    return
  }

  const tokens = parseBatchInput(query)
  const matchedCodes: string[] = []
  for (const token of tokens) {
    const code = resolveToken(token)
    if (code && !matchedCodes.includes(code)) matchedCodes.push(code)
  }

  if (matchedCodes.length > 0) {
    for (const code of matchedCodes) {
      if (!state.stagingSet.has(code)) addToStaging(state, code)
    }
    if (state.searchInputRef) {
      state.searchInputRef.clear()
      const inputEl = state.searchInputRef.el.querySelector('input')
      if (inputEl) inputEl.focus()
    }
    return
  }

  // 정확 매칭 실패 → fuzzy 검색 결과 표시
  const results = collectFuzzyResults(query.toLowerCase())
  state.searchResultTableRef.updateRows(results)
  state.searchResultTableRef.el.style.display = ''
  state.masterTableRef.el.style.display = 'none'
}

function buildSearchInputEl(): HTMLElement {
  state.searchInputRef = createSearchInput({
    label: '종목명/코드',
    labelColor: COLOR.down,
    placeholder: '종목명/코드 검색',
    width: '100%',
    borderColor: COLOR.down,
    onSearch: (query) => handleSearchQuery(query),
  })
  return state.searchInputRef.el
}

/** 검색 결과 클릭 → Staging_Set에 추가 (Req 1.1, 1.3, 1.4) */
function handleSearchResultClick(e: Event): void {
  const target = e.target as HTMLElement
  const tr = target.closest('tr')
  if (!tr || tr.getAttribute('data-row-type') !== 'data') return
  const tbody = state.searchResultTableRef?.el.querySelector('tbody')
  if (!tbody) return
  const rows = Array.from(tbody.querySelectorAll('tr[data-row-type="data"]'))
  const idx = rows.indexOf(tr as HTMLTableRowElement)
  if (idx < 0) return
  const q = state.searchInputRef?.getValue()?.toLowerCase() ?? ''
  if (!q) return
  const results = collectFuzzyResults(q)
  if (idx >= results.length) return
  const clicked = results[idx]

  // 왼쪽 검색 결과 클릭 시: Staging_Set에만 추가하고 선택된 업종은 변경하지 않음 (UX 개선)
  const added = addToStaging(state, clicked.code)
  if (added && state.searchInputRef) {
    state.searchInputRef.clear()
    const inputEl = state.searchInputRef.el.querySelector('input')
    if (inputEl) inputEl.focus()
  }
}

function buildSearchResultTable(): HTMLElement {
  const searchColumns: ColumnDef<SearchResultRow>[] = [
    {
      key: 'code', label: '종목코드', align: 'center', type: 'code',
      cellStyle: { color: COLOR.disabled, fontSize: FONT_SIZE.small },
      render: (row) => row.code
    },
    createStockNameColumn<SearchResultRow>(
      (row: SearchResultRow) => {
        const hotState = hotStore.getState()
        const sectorStock = hotState.sectorStocks[normalizeStockCode(row.code)]
        return {
          name: row.name,
          market_type: sectorStock?.market_type ?? row.market_type,
          nxt_enable: sectorStock?.nxt_enable ?? row.nxt_enable
        }
      }
    ),
    {
      key: 'sector', label: '소속업종', align: 'left', type: 'sector',
      cellStyle: { fontWeight: 'normal', color: COLOR.neutral },
      render: (row) => row.sector
    },
  ]
  state.searchResultTableRef = createDataTable<SearchResultRow>({
    columns: searchColumns,
    emptyText: '검색 결과가 없습니다.',
    stickyHeader: false,
    rowStyle: () => ({ cursor: 'pointer' }),
  })
  state.searchResultTableRef.el.style.display = 'none'
  state.searchResultTableRef.el.addEventListener('click', handleSearchResultClick)
  return state.searchResultTableRef.el
}

function renderCountCell(row: MasterRow): HTMLElement | string {
  if (row.sectorName === '미분류' && row.stockCount > 0) {
    const badge = document.createElement('span')
    Object.assign(badge.style, {
      background: COLOR.up,
      color: COLOR.white,
      borderRadius: '50%',
      fontSize: FONT_SIZE.chip,
      minWidth: '18px',
      height: '18px',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontWeight: '600',
    })
    badge.textContent = String(row.stockCount)
    return badge
  }
  return String(row.stockCount)
}

function renderActionsCell(row: MasterRow): HTMLElement {
  const container = document.createElement('div')
  Object.assign(container.style, { display: 'flex', gap: '4px', justifyContent: 'center' })
  const renameBtn = createSolidBtn({
    label: '이름변경',
    color: COLOR.tertiary,
    editControl: true,
    onClick: (e: MouseEvent) => {
      e.stopPropagation()
      onRenameSector(row.sectorName, e)
    },
  })
  const deleteBtn = createSolidBtn({
    label: '삭제',
    color: COLOR.up,
    editControl: true,
    onClick: (e: MouseEvent) => {
      e.stopPropagation()
      onDeleteSector(row.sectorName, e)
    },
  })
  container.appendChild(renameBtn)
  container.appendChild(deleteBtn)
  return container
}

function buildMasterColumns(): ColumnDef<MasterRow>[] {
  return [
    {
      key: 'seq', label: '순번', align: 'center', type: 'seq',
      cellStyle: { color: COLOR.disabled, fontSize: FONT_SIZE.small },
      render: (row) => row.seq === null ? '' : String(row.seq),
    },
    {
      key: 'name', label: '업종명', align: 'left', type: 'sector',
      cellStyle: { fontWeight: 'normal', color: COLOR.neutral },
      render: (row) => row.sectorName,
    },
    {
      key: 'count', label: '종목수', align: 'center', type: 'count',
      render: (row) => renderCountCell(row),
    },
    {
      key: 'actions', label: '작업', align: 'center', type: 'actions',
      render: (row) => renderActionsCell(row),
    },
  ]
}

/** Row click handler via event delegation */
function handleMasterRowClick(e: Event): void {
  const target = e.target as HTMLElement
  if (target.closest('button')) return
  const tr = target.closest('tr')
  if (!tr) return
  const tbody = state.masterTableRef?.el.querySelector('tbody')
  if (!tbody) return
  // emptyTr 제외하고 실제 데이터 행만 찾아서 인덱싱
  const rows = Array.from(tbody.querySelectorAll('tr[data-row-type="data"]'))
  const idx = rows.indexOf(tr as HTMLTableRowElement)
  if (idx < 0) return
  const masterRows = buildMasterRows()
  if (idx >= masterRows.length) return
  const clickedRow = masterRows[idx]
  state.selectedSector = state.selectedSector === clickedRow.sectorName ? null : clickedRow.sectorName
  state.selectedStocks.clear()
  state.anchorRow = -1
  updateMasterPanel()
  updateCenterPanel()
  updateRightPanel()
}

function buildMasterTable(): HTMLElement {
  state.masterTableRef = createDataTable<MasterRow>({
    columns: buildMasterColumns(),
    emptyText: '업종이 없습니다.',
    stickyHeader: false,
    rowStyle: (row) => {
      const style: Partial<CSSStyleDeclaration> = { cursor: 'pointer', background: '', borderLeft: '' }
      if (state.selectedSector === row.sectorName) {
        style.background = COLOR.downBg
        style.borderLeft = '3px solid ' + COLOR.down
      }
      return style
    },
  })
  state.masterTableRef.el.addEventListener('click', handleMasterRowClick)
  return state.masterTableRef.el
}

function buildSectorManageCard(): HTMLElement {
  const card = cardWrap()
  card.appendChild(buildSectorManageTitle())
  card.appendChild(createStepLabel('', '업종명을 변경하거나, 새 업종을 만들거나, 불필요한 업종을 삭제할 수 있습니다'))
  card.appendChild(buildSearchInputEl())
  card.appendChild(buildSearchResultTable())
  card.appendChild(buildMasterTable())
  return card
}

/* ── Master_Panel 갱신 ── */

function getActiveSectors(): string[] {
  const counts = countStocksBySector(state)
  const storeState = stockClassificationStore.getState()
  const allSectors = new Set(storeState.mergedSectors)
  for (const s of Object.keys(counts)) allSectors.add(s)
  return Array.from(allSectors).filter(s => s !== '').sort((a, b) => a.localeCompare(b))
}

function buildMasterRows(): MasterRow[] {
  const counts = countStocksBySector(state)
  const activeSectors = getActiveSectors()
  let seq = 0
  const rows: MasterRow[] = activeSectors.map(s => ({
    sectorName: s,
    stockCount: counts[s] ?? 0,
    seq: s === '미분류' ? null : ++seq,
  }))
  return rows
}

function updateMasterPanel(): void {
  if (!state.masterTableRef) return
  const rows = buildMasterRows()
  state.masterTableRef.updateRows(rows)
  updateStatsLabel()
  const storeState = stockClassificationStore.getState()
  setControlsDisabled(!storeState.editWindowOpen)
}

function updateStatsLabel(): void {
  if (!state.statsLabelRef) return
  const counts = countStocksBySector(state)
  const activeSectors = getActiveSectors()
  // 미분류는 임시 보관함이므로 업종 수에서 제외
  const sectorCount = activeSectors.filter(s => s !== '미분류').length
  let totalStocks = 0
  for (const c of Object.values(counts)) totalStocks += c

  state.statsLabelRef.replaceChildren()
  const labelText = (text: string): HTMLSpanElement => {
    const span = document.createElement('span')
    span.textContent = text
    Object.assign(span.style, { color: COLOR.tertiary, fontSize: FONT_SIZE.small })
    return span
  }
  const numText = (text: string): HTMLSpanElement => {
    const span = document.createElement('span')
    span.textContent = text
    Object.assign(span.style, { color: COLOR.down, fontSize: FONT_SIZE.small, fontWeight: FONT_WEIGHT.medium })
    return span
  }
  state.statsLabelRef.appendChild(labelText('업종 '))
  state.statsLabelRef.appendChild(numText(`${sectorCount}개`))
  state.statsLabelRef.appendChild(labelText(' · 전체 종목 '))
  state.statsLabelRef.appendChild(numText(`${totalStocks}개`))
}

/* ── Master_Panel 액션 핸들러 ── */

async function onRenameSector(oldName: string, e: MouseEvent): Promise<void> {
  const result = await showContextPopup({
    type: 'input',
    x: e.clientX,
    y: e.clientY,
    title: '업종명 변경',
    defaultValue: oldName,
    confirmText: '변경',
  })
  if (!result.confirmed) return
  const newName = ('value' in result) ? result.value.trim() : ''
  if (!newName || newName === oldName) return
  try {
    const res = await api.post<StockClassificationMutationResponse>('/api/stock-classification/rename', { old_name: oldName, new_name: newName })
    handleMutationResult(res)
  } catch { toastResult({ ok: false }) }
}

async function onDeleteSector(name: string, e: MouseEvent): Promise<void> {
  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: '업종 삭제',
    message: `"${name}" 업종을 삭제하시겠습니까?\n해당 업종의 종목은 미매핑 상태가 됩니다.`,
    confirmText: '삭제',
    confirmColor: COLOR.up,
  })
  if (!result.confirmed) return
  try {
    const res = await api.post<StockClassificationMutationResponse>('/api/stock-classification/delete', { name })
    handleMutationResult(res)
  } catch { toastResult({ ok: false }) }
}

async function onAddSector(e: MouseEvent): Promise<void> {
  const result = await showContextPopup({
    type: 'input',
    x: e.clientX,
    y: e.clientY,
    title: '새 업종 추가',
    placeholder: '업종명 입력',
    confirmText: '추가',
  })
  if (!result.confirmed) return
  const name = ('value' in result) ? result.value.trim() : ''
  if (!name) return
  try {
    const res = await api.post<StockClassificationMutationResponse>('/api/stock-classification/create', { name })
    handleMutationResult(res)
  } catch { toastResult({ ok: false }) }
}

/* ── tripleLeft 빌드 ── */

function buildTripleLeft(): void {
  const left = shell.tripleLeft
  while (left.firstChild) left.removeChild(left.firstChild)
  left.style.fontFamily = FONT_FAMILY
  left.appendChild(buildSectorManageCard())
}

/* ── 8.4: tripleCenter — Stock_List_Panel ── */

function buildStagingPanel(): HTMLElement {
  state.stagingPanelRef = document.createElement('div')
  Object.assign(state.stagingPanelRef.style, {
    padding: '8px 12px', marginBottom: '8px',
    border: '1px solid ' + COLOR.inactiveBg, borderRadius: '6px', background: COLOR.surfaceLight,
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

function handleSelectAll(): void {
  if (!state.selectedSector) return
  const stocks = getStocksForSector(state, state.selectedSector)
  state.selectedStocks.clear()
  for (const s of stocks) state.selectedStocks.add(s.code)
  state.anchorRow = stocks.length > 0 ? 0 : -1
  if (state.detailTableRef) state.detailTableRef.updateRows(stocks)
  updateAllInlineMoveButtons()
}

function handleDeselectAll(): void {
  state.selectedStocks.clear()
  state.anchorRow = -1
  if (state.selectedSector && state.detailTableRef) {
    const stocks = getStocksForSector(state, state.selectedSector)
    state.detailTableRef.updateRows(stocks)
  }
  updateAllInlineMoveButtons()
}

function buildDetailTitleRow(): HTMLElement {
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
    label: '전체 선택', color: COLOR.down, editControl: true, onClick: () => handleSelectAll(),
  })
  Object.assign(selectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })

  const deselectAllBtn = createSolidBtn({
    label: '전체 해제', color: COLOR.tertiary, editControl: true, onClick: () => handleDeselectAll(),
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
        const sectorStock = hotState.sectorStocks[normalizeStockCode(row.code)]
        return {
          name: row.name,
          market_type: sectorStock?.market_type ?? row.market_type,
          nxt_enable: sectorStock?.nxt_enable ?? row.nxt_enable
        }
      }
    ),
  ]
}

/** 드래그 시작 및 단일/다중 클릭 핸들러 */
function handleDetailMouseDown(e: MouseEvent): void {
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
  updateAllInlineMoveButtons()
}

/** 드래그 중 영역 선택 */
function handleDetailMouseOver(e: MouseEvent): void {
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
  updateAllInlineMoveButtons()
}

function buildDetailTable(): HTMLElement {
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

  state.detailTableRef.el.addEventListener('mousedown', handleDetailMouseDown)
  state.detailTableRef.el.addEventListener('mouseover', handleDetailMouseOver)

  // Esc 키 → 전체 선택 해제
  state.onDetailKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      state.selectedStocks.clear()
      state.anchorRow = -1
      if (state.selectedSector && state.detailTableRef) {
        const updatedStocks = getStocksForSector(state, state.selectedSector)
        state.detailTableRef.updateRows(updatedStocks)
      }
      updateAllInlineMoveButtons()
    }
  }
  state.detailTableRef.el.addEventListener('keydown', state.onDetailKeyDown)
  return state.detailTableRef.el
}

function buildTripleCenter(): void {
  const center = shell.tripleCenter
  while (center.firstChild) center.removeChild(center.firstChild)
  center.style.fontFamily = FONT_FAMILY

  state.centerContentRef = document.createElement('div')
  center.appendChild(state.centerContentRef)
  state.centerContentRef.appendChild(buildStagingPanel())
  state.centerContentRef.appendChild(buildDetailTitleRow())
  state.centerContentRef.appendChild(buildDetailTable())

  // 초기 빈 상태
  updateCenterPanel()
}

function updateCenterPanel(): void {
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
  setControlsDisabled(!storeState.editWindowOpen)
}

/* ── 8.5: tripleRight — Target_Sector_List ── */

/** 대상 업종 목록 반환: activeSectors에서 state.selectedSector 제외 */
function getTargetSectors(): string[] {
  const activeSectors = getActiveSectors()
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
  if (state.selectedSector && !getActiveSectors().includes(state.selectedSector)) {
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

  updateMasterPanel()
  updateCenterPanel()
  updateRightPanel()
  updateStagingChipSectors(state)
}

/** stockClassificationStore 구독 콜백 */
function handleStockClassificationChange(storeState: StockClassificationState, prev: StockClassificationState | null): void {
  if (!prev) {
    // 첫 호출: 초기 렌더링
    updateStockNameIndex()
    updateMasterPanel()
    updateCenterPanel()
    updateRightPanel()
    updateStagingChipSectors(state)
    updateIndicatorBar()
    return
  }

  if (storeState.allStocks !== prev.allStocks || storeState.mergedSectors !== prev.mergedSectors || storeState.sectors !== prev.sectors || storeState.stockMoves !== prev.stockMoves) {
    handleStockDataChange(storeState, prev)
  }

  if (storeState.allStocks !== prev.allStocks || storeState.editWindowOpen !== prev.editWindowOpen || storeState.filter_summary !== prev.filter_summary) {
    updateIndicatorBar()
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
  buildTripleHeader()
  buildTripleLeft()
  buildTripleCenter()
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
  updateIndicatorBar()
  updateMasterPanel()
  updateCenterPanel()
  updateRightPanel()
}

/* ── 8.8: unmount ── */

function unmount(): void {
  notifyPageInactive('stock-classification')
  state.mounted = false
  resetStagingCallbacks()
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
