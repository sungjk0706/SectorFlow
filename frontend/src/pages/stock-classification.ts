// frontend/src/pages/stock-classification.ts
// 업종분류 커스텀 페이지 — 3컬럼(triple) 레이아웃 전면 재작성

import { shell } from '../main'
import { stockClassificationStore, computeEditWindowOpenByTime, type StockClassificationState } from '../stores/stockClassificationStore'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createSettingsManager, type SettingsManager } from '../settings'
// import { createSettingRow } from '../components/common/setting-row' (removed)
import { createCardTitleWithContent } from '../components/common/card-title'
import { toastResult, showSaveToast } from '../components/common/toast'
import { showContextPopup, closeContextPopup } from '../components/common/context-popup'
import { showConfirmDialog, showAlertDialog } from '../components/common/dialog'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createSectorRowEl } from '../components/common/sector-row'
import { FONT_SIZE, FONT_FAMILY, FONT_WEIGHT, createStockNameColumn } from '../components/common/ui-styles'
import type { PageModule } from '../router'
import type { StockClassificationMutationResponse } from '../types'

/* ── 상수 ── */

/** 뮤테이션 응답 처리 — 성공/실패 토스트 + 장중 warning 토스트 */
function handleMutationResult(res: StockClassificationMutationResponse): void {
  toastResult(res)
  if (res.ok && res.warning) {
    showAlertDialog({ title: '경고', message: res.warning })
  }
}

/* ── 모듈 상태 ── */
// allStocks는 stockClassificationStore.getState().allStocks에서 파생되는 헬퍼 (캐싱)
let cachedSectorStocksRef: any = null;
let cachedAllStocksMap: Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }> = new Map();

function getAllStocks(): Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }> {
  const current = stockClassificationStore.getState().allStocks;
  if (current !== cachedSectorStocksRef) {
    cachedSectorStocksRef = current;
    cachedAllStocksMap = new Map();
    for (const s of current) {
      cachedAllStocksMap.set(s.code, {
        code: s.code,
        name: s.name,
        sector: s.sector || '',
        market_type: s.market_type,
        nxt_enable: s.nxt_enable
      });
    }
  }
  return cachedAllStocksMap;
}

let stockNameIndex: Map<string, string> = new Map()  // 종목명 → 종목코드 역인덱스

let unsubCustom: (() => void) | null = null
let unsubSse: (() => void) | null = null
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let unsubHot: (() => void) | null = null

// UI 참조 — Indicator Bar
let indicatorLabel: HTMLElement | null = null

// UI 참조 — Scheduler (moved to sector-scheduler.ui.ts)
// Staging / Selection 상태
let stagingSet: Set<string> = new Set()
let stagingChipMap: Map<string, HTMLElement> = new Map()  // 코드 → Chip DOM 매핑
let stagingPanelRef: HTMLElement | null = null             // Staging_Panel 컨테이너
let stagingCountRef: HTMLElement | null = null             // "N개 선택" 카운트 라벨
let stagingEmptyRef: HTMLElement | null = null             // 빈 상태 안내 메시지
let selectedStocks: Set<string> = new Set()

// UI 참조 — Sector Table (Left)
let selectedSector: string | null = null
let anchorRow: number = -1
let isDragging: boolean = false
let masterTableRef: DataTableApi<MasterRow> | null = null
let statsLabelRef: HTMLElement | null = null
let addSectorBtnRef: HTMLElement | null = null

// UI 참조 — Search
let searchInputRef: ReturnType<typeof createSearchInput> | null = null
let searchResultTableRef: DataTableApi<SearchResultRow> | null = null
let highlightStockCode: string | null = null

// UI 참조 — Center (Stock List)
let centerContentRef: HTMLElement | null = null
let centerEmptyRef: HTMLElement | null = null
let detailTitleRef: HTMLElement | null = null
let detailTableRef: DataTableApi<DetailRow> | null = null

// UI 참조 — Right (Target_Sector_List)
let rightContentRef: HTMLElement | null = null
let rightEmptyRef: HTMLElement | null = null
let targetSectorListRef: HTMLElement | null = null
let sectorRowMap: Map<string, HTMLElement> = new Map()
let prevTargetSectors: Set<string> = new Set()
let selectedTargetSector: string | null = null  // 우측 패널 선택된 대상 업종

// 현재 상태 캐시 삭제 - 단일 진실 공급원 원칙: store만 참조

/* ── 행 데이터 타입 ── */
interface MasterRow {
  sectorName: string
  stockCount: number
}

interface DetailRow {
  code: string
  name: string
  market_type?: string
  nxt_enable?: boolean
}

interface SearchResultRow {
  code: string
  name: string
  sector: string
  market_type?: string
  nxt_enable?: boolean
}

/* ── API 헬퍼 ── */

async function apiPost<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token') || 'dev-bypass'}`,
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/* ── 순수 함수 및 유틸리티 (Task 1) ── */

export function parseBatchInput(input: string): string[] {
  // 따옴표 제거 후 쉼표, 탭, 줄바꿈, 공백, 괄호 기준으로 분리
  const cleaned = input.replace(/["']/g, '')
  return cleaned.split(/[\s,()（）]+/).map(t => t.trim()).filter(t => t.length > 0)
}

/** Task 1.3: 토큰 → 종목코드 매칭. 코드 우선(O(1)), 종목명 차선(O(1)), 미매칭 시 null
 *  "나인테크(267320)" 형태 → 괄호 안 코드 추출 후 매칭, 실패 시 괄호 밖 이름으로 재시도 */
export function resolveToken(token: string): string | null {
  if (getAllStocks().has(token)) return token
  const codeByName = stockNameIndex.get(token)
  if (codeByName !== undefined) return codeByName

  // 괄호 포함 형태: "나인테크(267320)" 또는 "나인테크（267320）"
  const m = token.match(/^(.+?)[(\uff08]([^)\uff09]+)[)\uff09]$/)
  if (m) {
    const name = m[1].trim()
    const code = m[2].trim()
    if (getAllStocks().has(code)) return code
    const codeByName2 = stockNameIndex.get(name)
    if (codeByName2 !== undefined) return codeByName2
  }

  return null
}

/** Task 1.5: Move_Source 결정 — stagingSet 우선, 비어있으면 selectedStocks, 둘 다 비면 null */
export function getMoveSource(): { source: 'staging' | 'checked'; codes: string[] } | null {
  if (stagingSet.size > 0) return { source: 'staging', codes: [...stagingSet] }
  if (selectedStocks.size > 0) return { source: 'checked', codes: [...selectedStocks] }
  return null
}

/** Task 1.5: 이동 가능 종목 수 (버튼 텍스트용) */
export function getMovableCount(): number {
  if (stagingSet.size > 0) return stagingSet.size
  return selectedStocks.size
}

/* ── Staging_Panel 함수 (Task 4) ── */

/** Task 4.4: Chip DOM 생성 — 종목명 + 업종명 + × 버튼 */
export function createChip(code: string): HTMLElement {
  const stock = getAllStocks().get(code)
  const stockName = stock?.name ?? code

  // 업종명 해석: stockMoves 우선, 없으면 getAllStocks().sector, sectors 리네임 적용
  const state = stockClassificationStore.getState()
  const { stockMoves, sectors } = state
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
  removeSpan.addEventListener('click', () => removeFromStaging(code))

  chip.appendChild(nameSpan)
  chip.appendChild(sectorSpan)
  chip.appendChild(removeSpan)

  // Hover 강조
  chip.addEventListener('mouseenter', () => { chip.style.background = '#d0e2fc' })
  chip.addEventListener('mouseleave', () => { chip.style.background = '#e8f0fe' })

  return chip
}

/** Task 4.2: Staging_Set에 종목 추가. 중복 시 false + 토스트 */
export function addToStaging(code: string): boolean {
  if (stagingSet.has(code)) {
    showSaveToast('error', '이미 추가된 종목입니다')
    return false
  }
  stagingSet.add(code)
  const chip = createChip(code)
  stagingChipMap.set(code, chip)
  // Chip 목록 컨테이너에 삽입 (stagingPanelRef의 chip-list 영역)
  const chipList = stagingPanelRef?.querySelector('.staging-chip-list')
  if (chipList) chipList.appendChild(chip)
  updateStagingPanel()
  updateAllInlineMoveButtons()
  updateRightPanel()
  return true
}

/** Task 4.2: Staging_Set에서 종목 제거 + 해당 Chip DOM만 삭제 (전체 리렌더링 금지) */
export function removeFromStaging(code: string): void {
  stagingSet.delete(code)
  const chip = stagingChipMap.get(code)
  if (chip) chip.remove()
  stagingChipMap.delete(code)
  updateStagingPanel()
  updateAllInlineMoveButtons()
  updateRightPanel()
}

/** Task 4.2: Staging_Set 전체 비우기 + 모든 Chip DOM 삭제 */
export function clearStaging(): void {
  stagingSet.clear()
  for (const [, chip] of stagingChipMap) chip.remove()
  stagingChipMap.clear()
  updateStagingPanel()
  updateAllInlineMoveButtons()
  updateRightPanel()
}

/** Task 4.5: Staging_Panel 카운트/빈 상태 갱신 */
function updateStagingPanel(): void {
  if (stagingCountRef) {
    stagingCountRef.textContent = stagingSet.size > 0 ? `${stagingSet.size}개 선택` : ''
  }
  if (stagingEmptyRef) {
    stagingEmptyRef.style.display = stagingSet.size === 0 ? '' : 'none'
  }
  // "전체 해제" 버튼 표시/숨김
  const clearBtn = stagingPanelRef?.querySelector('.staging-clear-btn') as HTMLElement | null
  if (clearBtn) {
    clearBtn.style.display = stagingSet.size > 0 ? '' : 'none'
  }
}

/** Task 9.1: SSE 수신 시 모든 Chip의 업종명 텍스트만 갱신 (전체 리렌더링 금지) */
function updateStagingChipSectors(): void {
  const state = stockClassificationStore.getState()
  const { stockMoves, sectors, deletedSectors } = state
  for (const [code, chip] of stagingChipMap) {
    const stock = getAllStocks().get(code)
    let sectorName = stockMoves[code] ?? stock?.sector ?? ''
    if (sectors[sectorName]) sectorName = sectors[sectorName]
    if (deletedSectors.includes(sectorName)) sectorName = '미분류'
    const sectorSpan = chip.querySelector('.chip-sector')
    if (sectorSpan) sectorSpan.textContent = sectorName
  }
}

/* ── Moved_Stock_List 함수 (Task 7) ── */

/* ── 8.6: countStocksBySector / getStocksForSector — getAllStocks() 기반 ── */

function countStocksBySector(): Record<string, number> {
  const counts: Record<string, number> = {}
  const state = stockClassificationStore.getState()
  const { stockMoves, sectors, deletedSectors, mergedSectors } = state
  for (const s of mergedSectors) counts[s] = 0

  for (const [, stock] of getAllStocks()) {
    let sector = stockMoves[stock.code] ?? stock.sector
    if (sector === undefined || sector === null) sector = '미분류'
    if (sectors[sector]) sector = sectors[sector]
    if (deletedSectors.includes(sector)) sector = '업종명없음'
    if (sector && counts[sector] !== undefined) counts[sector]++
    else if (sector) counts[sector] = 1
  }
  return counts
}

function getStocksForSector(sectorName: string): Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> {
  const state = stockClassificationStore.getState()
  const { stockMoves, sectors, deletedSectors } = state
  const result: Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> = []

  for (const [, stock] of getAllStocks()) {
    let sector = stockMoves[stock.code] ?? stock.sector
    if (sector === undefined || sector === null) sector = '미분류'
    if (sectors[sector]) sector = sectors[sector]
    if (deletedSectors.includes(sector)) sector = '업종명없음'
    if (sector === sectorName) result.push({ code: stock.code, name: stock.name, market_type: stock.market_type, nxt_enable: stock.nxt_enable })
  }
  return result.sort((a, b) => a.name.localeCompare(b.name))
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

/* ── 공통: 액션 버튼 ── */
function actionBtn(text: string, color = '#198754'): HTMLButtonElement {
  const btn = document.createElement('button')
  btn.setAttribute('data-edit-control', '')
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

/* ── 8.2: tripleHeader — 공통 헤더 (Indicator_Bar) ── */

function buildTripleHeader(): void {
  const header = shell.tripleHeader
  while (header.firstChild) header.removeChild(header.firstChild)
  header.style.fontFamily = FONT_FAMILY

  // 좌측: 수동 갱신 버튼 배치 (기존 타이틀 자리)
  const left = document.createElement('div')
  Object.assign(left.style, {
    flex: '1', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start', gap: '6px', alignItems: 'flex-start'
  })

  // 버튼 공통 스타일 (크기 및 폰트 축소)
  const btnStyle = {
    padding: '4px 10px', border: 'none', borderRadius: '4px',
    background: '#198754', color: '#fff', cursor: 'pointer',
    fontSize: FONT_SIZE.small, fontFamily: FONT_FAMILY,
    fontWeight: 'normal', whiteSpace: 'nowrap',
    transition: 'background-color 0.2s',
  }

  // 설명라벨
  const descLabel = document.createElement('span')
  Object.assign(descLabel.style, { fontSize: FONT_SIZE.small, color: '#999', whiteSpace: 'nowrap' })
  descLabel.textContent = '장마감 후 매매적격종목 확정시세 및 5일봉 거래대금,고가 데이터 저장'
  left.appendChild(descLabel)

  // 버튼 컨테이너 (가로 정렬)
  const buttonContainer = document.createElement('div')
  Object.assign(buttonContainer.style, { display: 'flex', gap: '6px' })

  const btn1 = document.createElement('button')
  Object.assign(btn1.style, btnStyle)
  btn1.textContent = '⬇️ 1일봉챠트 시세 다운로드'
  btn1.addEventListener('mouseenter', () => btn1.style.background = '#157347')
  btn1.addEventListener('mouseleave', () => btn1.style.background = '#198754')
  btn1.addEventListener('click', () => onTriggerConfirmedDownload())

  const btn2 = document.createElement('button')
  Object.assign(btn2.style, btnStyle)
  btn2.textContent = '⬇️ 5일봉챠트 거래대금,고가 다운로드'
  btn2.addEventListener('mouseenter', () => btn2.style.background = '#157347')
  btn2.addEventListener('mouseleave', () => btn2.style.background = '#198754')
  btn2.addEventListener('click', () => onTrigger5dDownload())

  buttonContainer.appendChild(btn1)
  buttonContainer.appendChild(btn2)
  indicatorLabel = document.createElement('span')
  Object.assign(indicatorLabel.style, {
    fontSize: FONT_SIZE.body,
    color: '#6c757d',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    display: 'flex',
    alignItems: 'center',
    marginLeft: '8px',
    minWidth: '0',
  })
  
  buttonContainer.appendChild(btn2)
  buttonContainer.appendChild(indicatorLabel)
  left.appendChild(buttonContainer)
  header.appendChild(left)

  // 중앙: Indicator_Bar — dot + label (flex:1, text-align:center, fontSize: FONT_SIZE.title)
  const center = document.createElement('div')
  Object.assign(center.style, {
    flex: '5', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
    textAlign: 'center', fontSize: FONT_SIZE.title,
    minWidth: '0',
  })

  header.appendChild(center)

  // 우측: 공백
  const right = document.createElement('div')
  right.style.flex = '1'

  header.appendChild(right)
}

function updateIndicatorBar(): void {
  const state = stockClassificationStore.getState()
  const { filter_summary } = state
  if (indicatorLabel) {
    indicatorLabel.textContent = filter_summary || ''
  }
}

// buildSchedulerCard removed.
async function onTriggerConfirmedDownload(): Promise<void> {
  const label = '1일봉챠트 시세 다운로드'
  const endpoint = '/api/stock-classification/trigger-confirmed-download'

  // 엔진 재시작 완료 확인
  const { engineReloadComplete } = uiStore.getState()
  if (!engineReloadComplete) {
    toastResult({ ok: false, error: '엔진 재시작이 완료되지 않았습니다. 잠시 후 다시 시도하세요.' })
    return
  }

  const result = await showContextPopup({
    type: 'confirm',
    x: window.innerWidth / 2,
    y: window.innerHeight / 2,
    title: `${label} 실행`,
    message: `${label}를 지금 수동으로 즉시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`,
    confirmText: '실행',
    confirmColor: '#198754',
  })

  if (!result.confirmed) return

  try {
    const res = await apiPost<StockClassificationMutationResponse>(endpoint, {})
    handleMutationResult(res)
  } catch {
    toastResult({ ok: false })
  }
}

async function onTrigger5dDownload(): Promise<void> {
  const label = '5일봉챠트 거래대금,고가 다운로드'
  const endpoint = '/api/stock-classification/trigger-5d-download'

  // 엔진 재시작 완료 확인
  const { engineReloadComplete } = uiStore.getState()
  if (!engineReloadComplete) {
    toastResult({ ok: false, error: '엔진 재시작이 완료되지 않았습니다. 잠시 후 다시 시도하세요.' })
    return
  }

  const result = await showContextPopup({
    type: 'confirm',
    x: window.innerWidth / 2,
    y: window.innerHeight / 2,
    title: `${label} 실행`,
    message: `${label}를 지금 수동으로 즉시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`,
    confirmText: '실행',
    confirmColor: '#198754',
  })

  if (!result.confirmed) return

  try {
    const res = await apiPost<StockClassificationMutationResponse>(endpoint, {})
    handleMutationResult(res)
  } catch {
    toastResult({ ok: false })
  }
}



/* ── 업종 관리 테이블 (Sector_Table) ── */

function buildSectorManageCard(): HTMLElement {
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

  // 우측 컨테이너: 통계 레이블 + 새 업종 추가 버튼
  addSectorBtnRef = actionBtn('+ 새 업종 추가', '#0d6efd')
  Object.assign(addSectorBtnRef.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })
  addSectorBtnRef.addEventListener('click', (e: MouseEvent) => onAddSector(e))

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

  // ── 종목 검색 UI ──
  searchInputRef = createSearchInput({
    placeholder: '종목명 또는 코드 검색',
    onSearch: (query) => {
      if (!searchResultTableRef || !masterTableRef) return
      if (!query) {
        searchResultTableRef.el.style.display = 'none'
        masterTableRef.el.style.display = ''
        return
      }

      // 통합 파이프라인: 토큰 분리 후 정확 매칭 시도 → 성공 시 Staging 추가, 실패 시 fuzzy 검색
      const tokens = parseBatchInput(query)
      const matchedCodes: string[] = []
      for (const token of tokens) {
        const code = resolveToken(token)
        if (code && !matchedCodes.includes(code)) matchedCodes.push(code)
      }

      if (matchedCodes.length > 0) {
        for (const code of matchedCodes) {
          if (!stagingSet.has(code)) addToStaging(code)
        }
        if (searchInputRef) {
          searchInputRef.clear()
          const inputEl = searchInputRef.el.querySelector('input')
          if (inputEl) inputEl.focus()
        }
        return
      }

      // 정확 매칭 실패 → fuzzy 검색 결과 표시
      const q = query.toLowerCase()
      const state = stockClassificationStore.getState()
      const { stockMoves, sectors } = state
      const results: SearchResultRow[] = []

      const searchTokens = q.split(/[\s()（）]+/).filter(t => t.length > 0)

      for (const [, stock] of getAllStocks()) {
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
      (row: SearchResultRow) => {
        const state = hotStore.getState()
        const sectorStock = state.sectorStocks[normalizeStockCode(row.code)]
        return {
          name: row.name,
          market_type: sectorStock?.market_type ?? row.market_type,
          nxt_enable: sectorStock?.nxt_enable ?? row.nxt_enable
        }
      }
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

  // 검색 결과 클릭 → Staging_Set에 추가 (Req 1.1, 1.3, 1.4)
  searchResultTableRef.el.addEventListener('click', (e: Event) => {
    const target = e.target as HTMLElement
    const tr = target.closest('tr')
    if (!tr || tr.getAttribute('data-row-type') !== 'data') return
    const tbody = searchResultTableRef?.el.querySelector('tbody')
    if (!tbody) return
    const rows = Array.from(tbody.querySelectorAll('tr[data-row-type="data"]'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    if (idx < 0) return
    // 현재 검색 결과에서 클릭된 행 찾기
    const q = searchInputRef?.getValue()?.toLowerCase() ?? ''
    if (!q) return
    const state = stockClassificationStore.getState()
    const { stockMoves, sectors } = state
    const results: SearchResultRow[] = []
    const searchTokens = q.split(/[\s()（）]+/).filter(t => t.length > 0)
    for (const [, stock] of getAllStocks()) {
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

    // 왼쪽 검색 결과 클릭 시: Staging_Set에만 추가하고 선택된 업종은 변경하지 않음 (UX 개선)
    const added = addToStaging(clicked.code)
    if (added) {
      // 검색창 초기화 및 포커스 복원 (Req 1.5)
      if (searchInputRef) {
        searchInputRef.clear()
        const inputEl = searchInputRef.el.querySelector('input')
        if (inputEl) inputEl.focus()
      }
    }
  })

  card.appendChild(searchResultTableRef.el)

  const masterColumns: ColumnDef<MasterRow>[] = [
    {
      key: 'name', label: '업종명', align: 'left',
      cellStyle: { fontWeight: 'normal', color: '#111' },
      render: (row) => {
        return row.sectorName
      },
    },
    {
      key: 'count', label: '종목수', align: 'center',
      render: (row) => {
        if (row.sectorName === '미분류' && row.stockCount > 0) {
          const badge = document.createElement('span')
          Object.assign(badge.style, {
            background: '#dc3545',
            color: '#fff',
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
      },
    },
    {
      key: 'actions', label: '작업', align: 'center',
      render: (row) => {
        const container = document.createElement('div')
        Object.assign(container.style, { display: 'flex', gap: '4px', justifyContent: 'center' })
        const renameBtn = actionBtn('이름변경', '#6c757d')
        renameBtn.addEventListener('click', (e: MouseEvent) => {
          e.stopPropagation()
          onRenameSector(row.sectorName, e)
        })
        const deleteBtn = actionBtn('삭제', '#dc3545')
        deleteBtn.addEventListener('click', (e: MouseEvent) => {
          e.stopPropagation()
          onDeleteSector(row.sectorName, e)
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
      const style: Partial<CSSStyleDeclaration> = { cursor: 'pointer', background: '', borderLeft: '' }
      if (selectedSector === row.sectorName) {
        style.background = '#e3f2fd'
        style.borderLeft = '3px solid #1976d2'
      } else if (row.sectorName === '업종명없음' && row.stockCount > 0) {
        style.background = '#fff3cd'
      }
      return style
    },
  })

  // Row click handler via event delegation
  masterTableRef.el.addEventListener('click', (e: Event) => {
    const target = e.target as HTMLElement
    if (target.closest('button')) return
    const tr = target.closest('tr')
    if (!tr) return
    const tbody = masterTableRef?.el.querySelector('tbody')
    if (!tbody) return
    // emptyTr 제외하고 실제 데이터 행만 찾아서 인덱싱
    const rows = Array.from(tbody.querySelectorAll('tr[data-row-type="data"]'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    if (idx < 0) return
    const masterRows = buildMasterRows()
    if (idx >= masterRows.length) return
    const clickedRow = masterRows[idx]
    selectedSector = selectedSector === clickedRow.sectorName ? null : clickedRow.sectorName
    highlightStockCode = null
    selectedStocks.clear()
    anchorRow = -1
    updateMasterPanel()
    updateCenterPanel()
    updateRightPanel()
  })

  card.appendChild(masterTableRef.el)

  return card
}

/* ── Master_Panel 갱신 ── */

function getActiveSectors(): string[] {
  const counts = countStocksBySector()
  const state = stockClassificationStore.getState()
  const allSectors = new Set(state.mergedSectors)
  for (const s of Object.keys(counts)) allSectors.add(s)
  return Array.from(allSectors).filter(s => s !== '').sort((a, b) => a.localeCompare(b))
}

function buildMasterRows(): MasterRow[] {
  const counts = countStocksBySector()
  const activeSectors = getActiveSectors()
  const rows: MasterRow[] = activeSectors.map(s => ({
    sectorName: s,
    stockCount: counts[s] ?? 0,
  }))
  return rows
}

function updateMasterPanel(): void {
  if (!masterTableRef) return
  const rows = buildMasterRows()
  masterTableRef.updateRows(rows)
  updateStatsLabel()
  const state = stockClassificationStore.getState()
  setControlsDisabled(!state.editWindowOpen)
}

function updateStatsLabel(): void {
  if (!statsLabelRef) return
  const counts = countStocksBySector()
  const activeSectors = getActiveSectors()
  const sectorCount = activeSectors.length
  let totalStocks = 0
  for (const c of Object.values(counts)) totalStocks += c
  statsLabelRef.textContent = `업종 ${sectorCount}개 · 전체 종목 ${totalStocks}개`
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
    const res = await apiPost<StockClassificationMutationResponse>('/api/stock-classification/rename', { old_name: oldName, new_name: newName })
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
    confirmColor: '#dc3545',
  })
  if (!result.confirmed) return
  try {
    const res = await apiPost<StockClassificationMutationResponse>('/api/stock-classification/delete', { name })
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
    const res = await apiPost<StockClassificationMutationResponse>('/api/stock-classification/create', { name })
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

function buildTripleCenter(): void {
  const center = shell.tripleCenter
  while (center.firstChild) center.removeChild(center.firstChild)
  center.style.fontFamily = FONT_FAMILY

  centerContentRef = document.createElement('div')
  center.appendChild(centerContentRef)

  // ── Staging_Panel (Task 4.5) ──
  stagingPanelRef = document.createElement('div')
  Object.assign(stagingPanelRef.style, {
    padding: '8px 12px', marginBottom: '8px',
    border: '1px solid #e0e0e0', borderRadius: '6px', background: '#fafafa',
  })

  // Header row: count label + "전체 해제" button
  const stagingHeader = document.createElement('div')
  Object.assign(stagingHeader.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px',
  })

  stagingCountRef = document.createElement('span')
  Object.assign(stagingCountRef.style, { fontSize: FONT_SIZE.small, fontWeight: 'normal', color: '#333' })

  const stagingClearBtn = actionBtn('전체 해제', '#6c757d')
  stagingClearBtn.className = 'staging-clear-btn'
  Object.assign(stagingClearBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small, display: 'none' })
  stagingClearBtn.addEventListener('click', () => clearStaging())

  stagingHeader.appendChild(stagingCountRef)
  stagingHeader.appendChild(stagingClearBtn)
  stagingPanelRef.appendChild(stagingHeader)

  // Chip list container
  const chipList = document.createElement('div')
  chipList.className = 'staging-chip-list'
  Object.assign(chipList.style, { display: 'flex', flexWrap: 'wrap', gap: '4px' })
  stagingPanelRef.appendChild(chipList)

  // Empty state message
  stagingEmptyRef = document.createElement('div')
  Object.assign(stagingEmptyRef.style, {
    color: '#aaa', fontSize: FONT_SIZE.small, textAlign: 'center', padding: '8px 0',
  })
  stagingEmptyRef.textContent = '검색으로 종목을 추가하세요'
  stagingPanelRef.appendChild(stagingEmptyRef)

  centerContentRef.appendChild(stagingPanelRef)

  // Initialize staging panel state
  updateStagingPanel()

  // 제목 + 전체 선택/해제 버튼 컨테이너
  const titleRow = document.createElement('div')
  Object.assign(titleRow.style, {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px',
  })

  detailTitleRef = document.createElement('div')
  Object.assign(detailTitleRef.style, {
    fontSize: FONT_SIZE.title, fontWeight: 'normal', color: '#333',
  })
  titleRow.appendChild(detailTitleRef)

  // "전체 선택" / "전체 해제" 버튼
  const btnGroup = document.createElement('div')
  Object.assign(btnGroup.style, { display: 'flex', gap: '4px' })

  const selectAllBtn = actionBtn('전체 선택', '#0d6efd')
  Object.assign(selectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })
  selectAllBtn.addEventListener('click', () => {
    if (!selectedSector) return
    const stocks = getStocksForSector(selectedSector)
    selectedStocks.clear()
    for (const s of stocks) selectedStocks.add(s.code)
    anchorRow = stocks.length > 0 ? 0 : -1
    if (detailTableRef) detailTableRef.updateRows(stocks)
    updateAllInlineMoveButtons()
  })

  const deselectAllBtn = actionBtn('전체 해제', '#6c757d')
  Object.assign(deselectAllBtn.style, { padding: '2px 8px', fontSize: FONT_SIZE.small })
  deselectAllBtn.addEventListener('click', () => {
    selectedStocks.clear()
    anchorRow = -1
    if (selectedSector && detailTableRef) {
      const stocks = getStocksForSector(selectedSector)
      detailTableRef.updateRows(stocks)
    }
    updateAllInlineMoveButtons()
  })

  btnGroup.appendChild(selectAllBtn)
  btnGroup.appendChild(deselectAllBtn)
  titleRow.appendChild(btnGroup)

  centerContentRef.appendChild(titleRow)

  // 종목 테이블 — 체크박스 컬럼 제거, cellStyle 적용
  const detailColumns: ColumnDef<DetailRow>[] = [
    {
      key: 'code', label: '종목코드', minWidth: 80, align: 'center',
      cellStyle: { color: '#999', fontSize: FONT_SIZE.small },
      render: (row) => row.code,
    },
    createStockNameColumn<DetailRow>(
      (row: DetailRow) => {
        const state = hotStore.getState()
        const sectorStock = state.sectorStocks[normalizeStockCode(row.code)]
        return {
          name: row.name,
          market_type: sectorStock?.market_type ?? row.market_type,
          nxt_enable: sectorStock?.nxt_enable ?? row.nxt_enable
        }
      }
    ),
  ]

  detailTableRef = createDataTable<DetailRow>({
    columns: detailColumns,
    emptyText: '종목이 없습니다.',
    stickyHeader: true,
    keyFn: (row) => row.code,
    rowStyle: (row) => {
      if (highlightStockCode && row.code === highlightStockCode) {
        return { cursor: 'pointer', background: '#fff3cd', transition: 'background 0.3s' }
      }
      if (selectedStocks.has(row.code)) {
        return { cursor: 'pointer', background: '#e3f2fd', transition: '' }
      }
      return { cursor: 'pointer', background: '', transition: '' }
    },
  })

  // 키보드 포커스 가능하게 설정
  detailTableRef.el.tabIndex = 0

  // 전역 마우스 업 이벤트로 드래그 상태 해제
  window.addEventListener('mouseup', () => {
    isDragging = false
  })

  // 드래그 시작 및 단일/다중 클릭 핸들러
  detailTableRef.el.addEventListener('mousedown', (e: MouseEvent) => {
    if (e.button !== 0) return // 좌클릭만 허용
    const tr = (e.target as HTMLElement).closest('tr')
    if (!tr || !selectedSector) return
    const clickedCode = tr.dataset.rowKey
    if (!clickedCode) return

    // 텍스트 선택 방지
    e.preventDefault()
    isDragging = true

    const stocks = getStocksForSector(selectedSector)
    const idx = stocks.findIndex(s => s.code === clickedCode)
    if (idx < 0) return

    if (e.shiftKey && anchorRow >= 0) {
      // Shift+클릭: anchorRow ~ idx 범위 선택
      const [start, end] = [Math.min(anchorRow, idx), Math.max(anchorRow, idx)]
      for (let i = start; i <= end; i++) selectedStocks.add(stocks[i].code)
    } else if (e.ctrlKey || e.metaKey) {
      // Ctrl+클릭: 토글
      if (selectedStocks.has(clickedCode)) selectedStocks.delete(clickedCode)
      else selectedStocks.add(clickedCode)
      anchorRow = idx
    } else {
      // 일반 클릭: 단일 선택
      selectedStocks.clear()
      selectedStocks.add(clickedCode)
      anchorRow = idx
    }

    if (selectedSector) {
      const updatedStocks = getStocksForSector(selectedSector)
      detailTableRef!.updateRows(updatedStocks)
    }
    updateAllInlineMoveButtons()
  })

  // 드래그 중 영역 선택
  detailTableRef.el.addEventListener('mouseover', (e: MouseEvent) => {
    if (!isDragging || !selectedSector) return
    const tr = (e.target as HTMLElement).closest('tr')
    if (!tr) return
    const clickedCode = tr.dataset.rowKey
    if (!clickedCode) return

    const stocks = getStocksForSector(selectedSector)
    const idx = stocks.findIndex(s => s.code === clickedCode)
    if (idx < 0 || anchorRow < 0) return

    selectedStocks.clear()
    const [start, end] = [Math.min(anchorRow, idx), Math.max(anchorRow, idx)]
    for (let i = start; i <= end; i++) selectedStocks.add(stocks[i].code)

    if (selectedSector) {
      const updatedStocks = getStocksForSector(selectedSector)
      detailTableRef!.updateRows(updatedStocks)
    }
    updateAllInlineMoveButtons()
  })

  // Esc 키 → 전체 선택 해제
  detailTableRef.el.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      selectedStocks.clear()
      anchorRow = -1
      if (selectedSector && detailTableRef) {
        const updatedStocks = getStocksForSector(selectedSector)
        detailTableRef.updateRows(updatedStocks)
      }
      updateAllInlineMoveButtons()
    }
  })

  centerContentRef.appendChild(detailTableRef.el)

  // 초기 빈 상태
  updateCenterPanel()
}

function updateCenterPanel(): void {
  if (!centerContentRef || !detailTitleRef || !detailTableRef) return

  if (selectedSector === null) {
    detailTitleRef.textContent = ''
    detailTableRef.el.style.display = 'none'
    // Hide title row via CSS display
    const titleRow = detailTitleRef.parentElement
    if (titleRow) titleRow.style.display = 'none'
    // Show empty message
    if (!centerEmptyRef) {
      centerEmptyRef = document.createElement('div')
      Object.assign(centerEmptyRef.style, { color: '#aaa', textAlign: 'center', padding: '40px 0' })
      centerEmptyRef.textContent = '좌측에서 업종을 선택하세요'
      centerContentRef.appendChild(centerEmptyRef)
    }
    centerEmptyRef.style.display = ''
    return
  }

  // Hide empty message, show title row + table
  if (centerEmptyRef) centerEmptyRef.style.display = 'none'
  const titleRow = detailTitleRef.parentElement
  if (titleRow) titleRow.style.display = ''
  detailTableRef.el.style.display = ''

  const stocks = getStocksForSector(selectedSector)
  detailTitleRef.textContent = `${selectedSector} 종목 목록 (${stocks.length}개)`
  detailTableRef.updateRows(stocks)

  const state = stockClassificationStore.getState()
  setControlsDisabled(!state.editWindowOpen)
}

/* ── 8.5: tripleRight — Target_Sector_List ── */

/** 대상 업종 목록 반환: activeSectors에서 selectedSector 제외 */
function getTargetSectors(): string[] {
  const activeSectors = getActiveSectors()
  // 배치 입력: selectedSector 없어도 staging에 종목이 있으면 전체 업종 표시
  if (selectedSector === null && stagingSet.size > 0) {
    return activeSectors
  }
  if (selectedSector === null) return []
  return activeSectors.filter(s => s !== selectedSector)
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

  // hover 시 배경색 (선택 상태가 아닐 때만)
  row.addEventListener('mouseenter', () => {
    if (selectedTargetSector !== sectorName) row.style.background = '#f5f5f5'
  })
  row.addEventListener('mouseleave', () => {
    if (selectedTargetSector !== sectorName) row.style.background = ''
  })

  return row
}

function buildTripleRight(): void {
  const right = shell.tripleRight
  while (right.firstChild) right.removeChild(right.firstChild)
  right.style.fontFamily = FONT_FAMILY

  rightContentRef = document.createElement('div')
  Object.assign(rightContentRef.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  right.appendChild(rightContentRef)

  // 제목
  const title = document.createElement('div')
  Object.assign(title.style, {
    fontSize: FONT_SIZE.title, fontWeight: 'normal', color: '#333', marginBottom: '8px',
  })
  title.textContent = '대상 업종'
  rightContentRef.appendChild(title)

  // 업종 검색란
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

  // Target_Sector_List 컨테이너
  targetSectorListRef = document.createElement('div')
  Object.assign(targetSectorListRef.style, { overflowY: 'auto', flex: '1' })
  rightContentRef.appendChild(targetSectorListRef)

  // 초기화
  sectorRowMap = new Map()
  prevTargetSectors = new Set()

  // 초기 행 렌더링
  updateTargetSectorList()

  // 초기 상태
  updateRightPanel()
}

/** Target_Sector_List 델타 갱신 */
function updateTargetSectorList(): void {
  if (!targetSectorListRef) return
  const newTargets = getTargetSectors()
  const newSet = new Set(newTargets)

  // 제거: 이전에 있었지만 새 목록에 없는 업종
  for (const s of prevTargetSectors) {
    if (!newSet.has(s)) {
      sectorRowMap.get(s)?.remove()
      sectorRowMap.delete(s)
    }
  }

  // 추가: 새 목록에 있지만 이전에 없던 업종
  for (const s of newTargets) {
    if (!prevTargetSectors.has(s) && !sectorRowMap.has(s)) {
      const row = createSectorRow(s)
      sectorRowMap.set(s, row)
      targetSectorListRef.appendChild(row)
    }
  }

  prevTargetSectors = newSet
}

/** 모든 인라인 이동 버튼의 텍스트 + disabled 상태 갱신 (Task 8.1, 8.3) */
function updateAllInlineMoveButtons(): void {
  const count = getMovableCount()
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

function updateRightPanel(): void {
  if (!rightContentRef) return

  if (selectedSector === null && stagingSet.size === 0) {
    // Hide all children via CSS display, show empty message
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

  // Hide empty message, show all children
  if (rightEmptyRef) rightEmptyRef.style.display = 'none'
  for (const child of Array.from(rightContentRef.children)) {
    if (child !== rightEmptyRef) (child as HTMLElement).style.display = ''
  }
  // Restore flex display on the container's direct children that need it
  if (targetSectorListRef) targetSectorListRef.style.display = ''

  // If refs were cleared (e.g. after unmount/remount), rebuild
  if (!targetSectorListRef) {
    buildTripleRight()
    return
  }

  updateTargetSectorList()
  updateAllInlineMoveButtons()
  const state = stockClassificationStore.getState()
  setControlsDisabled(!state.editWindowOpen)
}

/** 이동 확인 팝업 메시지 생성 (순수 함수) */
export function buildMoveMessage(
  codes: string[],
  allStocks: Map<string, { code: string; name: string }>,
  targetSector: string,
): string {
  const firstCode = codes[0]
  const firstName = allStocks.get(firstCode)?.name ?? firstCode
  if (codes.length === 1) {
    return `${firstName} 을(를) ${targetSector} 업종으로 이동하시겠습니까?`
  }
  return `${firstName} 외 ${codes.length - 1}개 종목을 ${targetSector} 업종으로 이동하시겠습니까?`
}

async function onMoveStock(_e: MouseEvent, targetSector: string): Promise<void> {
  const moveSource = getMoveSource()
  if (!moveSource) return
  const codes = moveSource.codes

  // 이동 전 확인 팝업
  const confirmed = await showConfirmDialog({
    title: '종목 이동',
    message: buildMoveMessage(codes, getAllStocks(), targetSector),
    confirmText: '이동',
    cancelText: '취소',
  })
  if (!confirmed) return

  try {
    const lastRes = await apiPost<StockClassificationMutationResponse>('/api/stock-classification/move-stocks', {
      stock_codes: codes,
      target_sector: targetSector,
    })
    handleMutationResult(lastRes)

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
      clearStaging()
    }
  } catch { toastResult({ ok: false }) }
}

/* ── 8.0: store의 allStocks로 stockNameIndex 업데이트 ── */

function updateStockNameIndex(): void {
  const allStocks = getAllStocks()
  stockNameIndex = new Map()
  for (const [code, stock] of allStocks) {
    stockNameIndex.set(stock.name, code)
  }
}

/* ── 8.1 + 8.8: mount / unmount ── */

function mount(_container: HTMLElement): void {
  notifyPageActive('stock-classification')
  // 8.2: Build tripleHeader
  buildTripleHeader()

  // 8.3: Build tripleLeft
  buildTripleLeft()

  // 8.4: Build tripleCenter
  buildTripleCenter()

  // 8.5: Build tripleRight
  buildTripleRight()

  // settingsManager for scheduler toggles
  settingsMgr = createSettingsManager()

  // Initialize editWindowOpen state
  const initialSettings = uiStore.getState().settings
  const initialEditWindowOpen = computeEditWindowOpenByTime(initialSettings)
  stockClassificationStore.setState({ editWindowOpen: initialEditWindowOpen })

  // stockClassificationStore 구독
  let prevState: StockClassificationState | null = null
  unsubCustom = stockClassificationStore.subscribe((state) => {
    const prev = prevState
    prevState = state

    if (!prev) {
      // 첫 호출: 초기 렌더링
      updateStockNameIndex()
      updateMasterPanel()
      updateCenterPanel()
      updateRightPanel()
      updateStagingChipSectors()
      updateIndicatorBar()
      return
    }

    if (state.allStocks !== prev.allStocks || state.mergedSectors !== prev.mergedSectors || state.sectors !== prev.sectors || state.deletedSectors !== prev.deletedSectors || state.stockMoves !== prev.stockMoves) {
      if (state.allStocks !== prev.allStocks) {
        updateStockNameIndex()
      }

      // Check if selectedSector still exists
      if (selectedSector && !state.mergedSectors.includes(selectedSector)) {
        selectedSector = null
      }

      // 데이터 변경 시 이동한 종목만 선택 상태에서 제거 (나머지 선택 유지)
      const prevStockMoves = prev.stockMoves
      const newStockMoves = state.stockMoves

      // 이동한 종목 코드 식별 (stockMoves가 변경된 종목)
      const movedCodes: string[] = []
      for (const code of selectedStocks) {
        if (prevStockMoves[code] !== newStockMoves[code]) {
          movedCodes.push(code)
        }
      }

      // 이동한 종목만 선택 상태에서 제거
      for (const code of movedCodes) {
        selectedStocks.delete(code)
      }

      // 모든 종목이 이동한 경우 anchorRow 초기화
      if (selectedStocks.size === 0) {
        anchorRow = -1
      }

      updateMasterPanel()
      updateCenterPanel()
      updateRightPanel()
      updateStagingChipSectors()
    }

    if (state.allStocks !== prev.allStocks || state.editWindowOpen !== prev.editWindowOpen || state.filter_summary !== prev.filter_summary) {
      updateIndicatorBar()
      setControlsDisabled(!state.editWindowOpen)
    }
  })

  // uiStore 구독 — settings 변경 시 editWindowOpen 재계산 + 토글 갱신
  let prevSettings = uiStore.getState().settings
  unsubSse = uiStore.subscribe((state) => {
    // Settings check
    if (state.settings !== prevSettings) {
      prevSettings = state.settings
      const newEditWindowOpen = computeEditWindowOpenByTime(state.settings)
      if (newEditWindowOpen !== stockClassificationStore.getState().editWindowOpen) {
        stockClassificationStore.setState({ editWindowOpen: newEditWindowOpen })
      }
    }
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
  if (unsubCustom) { unsubCustom(); unsubCustom = null }
  if (unsubSse) { unsubSse(); unsubSse = null }
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (unsubHot) { unsubHot(); unsubHot = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  closeContextPopup()

  // Null all DOM refs
  indicatorLabel = null
  masterTableRef = null
  statsLabelRef = null
  addSectorBtnRef = null
  searchInputRef = null
  searchResultTableRef = null
  highlightStockCode = null
  centerContentRef = null
  centerEmptyRef = null
  detailTitleRef = null
  detailTableRef = null
  rightContentRef = null
  rightEmptyRef = null
  targetSectorListRef = null
  sectorRowMap = new Map()
  prevTargetSectors = new Set()

  selectedSector = null
  selectedTargetSector = null
  anchorRow = -1
  stagingSet = new Set()
  stagingChipMap = new Map()
  stagingPanelRef = null
  stagingCountRef = null
  stagingEmptyRef = null
  selectedStocks = new Set()
  stockNameIndex = new Map()
  cachedSectorStocksRef = null
  cachedAllStocksMap = new Map()

  // Clear shell triple panels
  while (shell.tripleHeader.firstChild) shell.tripleHeader.removeChild(shell.tripleHeader.firstChild)
  while (shell.tripleLeft.firstChild) shell.tripleLeft.removeChild(shell.tripleLeft.firstChild)
  while (shell.tripleCenter.firstChild) shell.tripleCenter.removeChild(shell.tripleCenter.firstChild)
  while (shell.tripleRight.firstChild) shell.tripleRight.removeChild(shell.tripleRight.firstChild)
}

const pageModule: PageModule = { mount, unmount }
export default pageModule

/* ── 테스트 전용 상태 설정 헬퍼 (export for testing) ── */
export function _testSetState(opts: {
  allStocks?: Map<string, { code: string; name: string; sector: string }>
  stockNameIndex?: Map<string, string>
  stagingSet?: Set<string>
  selectedStocks?: Set<string>
}): void {
  if (opts.stockNameIndex !== undefined) stockNameIndex = opts.stockNameIndex
  if (opts.stagingSet !== undefined) stagingSet = opts.stagingSet
  if (opts.selectedStocks !== undefined) selectedStocks = opts.selectedStocks
}
