// frontend/src/pages/stock-classification-master.ts
// 종목분류 페이지 — tripleLeft(Sector_Table + 검색) 분할 (F-04 분할 4단계)
// P10 SSOT/P16 살아있는 경로/P24 단순성 — state 첫 인자 전달 패턴

import { shell } from '../main'
import { stockClassificationStore } from '../stores/stockClassificationStore'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import { api } from '../api/client'
import { createCardTitleWithContent } from '../components/common/card-title'
import { toastResult } from '../components/common/toast'
import { showContextPopup } from '../components/common/context-popup'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createSolidBtn } from '../components/common/button'
import { createStepLabel } from '../components/common/settings-common'
import { FONT_SIZE, FONT_FAMILY, FONT_WEIGHT, createStockNameColumn, COLOR } from '../components/common/ui-styles'
import type { StockClassificationMutationResponse } from '../types'
import {
  handleMutationResult,
  parseBatchInput,
  cardWrap,
  type MasterRow,
  type SearchResultRow,
} from './stock-classification-shared'
import {
  getAllStocks,
  addToStaging,
  countStocksBySector,
} from './stock-classification-staging'
import type { StockClassificationPageState } from './stock-classification'

/* ── Master_Panel Callbacks (순환 참조 회피 — main 잔류 함수 연결) ── */

interface MasterPanelCallbacks {
  setControlsDisabled: (disabled: boolean) => void
  onRowClickUpdatePanels: () => void  // updateCenterPanel() + updateRightPanel()
}

let callbacks: MasterPanelCallbacks | null = null

export function initMasterCallbacks(cb: MasterPanelCallbacks): void {
  callbacks = cb
}

export function resetMasterCallbacks(): void {
  callbacks = null
}

/* ── 검색 유틸 ── */

/** Task 1.3: 토큰 → 종목코드 매칭. 코드 우선(O(1)), 종목명 차선(O(1)), 미매칭 시 null
 *  "나인테크(267320)" 형태 → 괄호 안 코드 추출 후 매칭, 실패 시 괄호 밖 이름으로 재시도 */
function resolveToken(state: StockClassificationPageState, token: string): string | null {
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

/* ── 종목분류 테이블 (Sector_Table) ── */

function buildSectorManageTitle(state: StockClassificationPageState): HTMLElement {
  const titleContainer = document.createElement('div')
  Object.assign(titleContainer.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
  })
  const titleText = document.createElement('span')
  titleText.textContent = '종목 분류'
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
function collectFuzzyResults(state: StockClassificationPageState, q: string): SearchResultRow[] {
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
function handleSearchQuery(state: StockClassificationPageState, query: string): void {
  if (!state.searchResultTableRef || !state.masterTableRef) return
  if (!query) {
    state.searchResultTableRef.el.style.display = 'none'
    state.masterTableRef.el.style.display = ''
    return
  }

  const tokens = parseBatchInput(query)
  const matchedCodes: string[] = []
  for (const token of tokens) {
    const code = resolveToken(state, token)
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
  const results = collectFuzzyResults(state, query.toLowerCase())
  state.searchResultTableRef.updateRows(results)
  state.searchResultTableRef.el.style.display = ''
  state.masterTableRef.el.style.display = 'none'
}

function buildSearchInputEl(state: StockClassificationPageState): HTMLElement {
  state.searchInputRef = createSearchInput({
    label: '종목명/코드',
    labelColor: COLOR.down,
    placeholder: '종목명/코드 검색',
    width: '100%',
    borderColor: COLOR.down,
    onSearch: (query) => handleSearchQuery(state, query),
  })
  return state.searchInputRef.el
}

/** 검색 결과 클릭 → Staging_Set에 추가 (Req 1.1, 1.3, 1.4) */
function handleSearchResultClick(state: StockClassificationPageState, e: Event): void {
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
  const results = collectFuzzyResults(state, q)
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

function buildSearchResultTable(state: StockClassificationPageState): HTMLElement {
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
  state.searchResultTableRef.el.addEventListener('click', (e) => handleSearchResultClick(state, e))
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
function handleMasterRowClick(state: StockClassificationPageState, e: Event): void {
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
  const masterRows = buildMasterRows(state)
  if (idx >= masterRows.length) return
  const clickedRow = masterRows[idx]
  state.selectedSector = state.selectedSector === clickedRow.sectorName ? null : clickedRow.sectorName
  state.selectedStocks.clear()
  state.anchorRow = -1
  updateMasterPanel(state)
  callbacks!.onRowClickUpdatePanels()
}

function buildMasterTable(state: StockClassificationPageState): HTMLElement {
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
  state.masterTableRef.el.addEventListener('click', (e) => handleMasterRowClick(state, e))
  return state.masterTableRef.el
}

function buildSectorManageCard(state: StockClassificationPageState): HTMLElement {
  const card = cardWrap()
  card.appendChild(buildSectorManageTitle(state))
  card.appendChild(createStepLabel('', '업종명을 변경하거나, 새 업종을 만들거나, 불필요한 업종을 삭제할 수 있습니다'))
  card.appendChild(buildSearchInputEl(state))
  card.appendChild(buildSearchResultTable(state))
  card.appendChild(buildMasterTable(state))
  return card
}

/* ── Master_Panel 갱신 ── */

export function getActiveSectors(state: StockClassificationPageState): string[] {
  const counts = countStocksBySector(state)
  const storeState = stockClassificationStore.getState()
  const allSectors = new Set(storeState.mergedSectors)
  for (const s of Object.keys(counts)) allSectors.add(s)
  return Array.from(allSectors).filter(s => s !== '').sort((a, b) => a.localeCompare(b))
}

function buildMasterRows(state: StockClassificationPageState): MasterRow[] {
  const counts = countStocksBySector(state)
  const activeSectors = getActiveSectors(state)
  let seq = 0
  const rows: MasterRow[] = activeSectors.map(s => ({
    sectorName: s,
    stockCount: counts[s] ?? 0,
    seq: s === '미분류' ? null : ++seq,
  }))
  return rows
}

export function updateMasterPanel(state: StockClassificationPageState): void {
  if (!state.masterTableRef) return
  const rows = buildMasterRows(state)
  state.masterTableRef.updateRows(rows)
  updateStatsLabel(state)
  const storeState = stockClassificationStore.getState()
  callbacks!.setControlsDisabled(!storeState.editWindowOpen)
}

function updateStatsLabel(state: StockClassificationPageState): void {
  if (!state.statsLabelRef) return
  const counts = countStocksBySector(state)
  const activeSectors = getActiveSectors(state)
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

export function buildTripleLeft(state: StockClassificationPageState): void {
  const left = shell.tripleLeft
  while (left.firstChild) left.removeChild(left.firstChild)
  left.style.fontFamily = FONT_FAMILY
  left.appendChild(buildSectorManageCard(state))
}
