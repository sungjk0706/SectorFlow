// frontend/src/pages/sector-custom.ts
// 업종분류 커스텀 페이지 — 3컬럼(triple) 레이아웃 전면 재작성

import { shell } from '../main'
import { sectorCustomStore, computeEditWindowOpenByTime, type SectorCustomState } from '../stores/sectorCustomStore'
import { appStore } from '../stores/appStore'
import { createSettingsManager, type SettingsManager } from '../settings'
import { createSettingRow, createToggleBtn } from '../components/common/setting-row'
import { createCardTitleWithContent } from '../components/common/card-title'
import { toastResult, showSaveToast } from '../components/common/save-toast'
import { showContextPopup, closeContextPopup } from '../components/common/context-popup'
import { showConfirmModal } from '../components/common/confirm-modal'
import { createDataTable, type ColumnDef, type DataTableApi } from '../components/common/data-table'
import { createSearchInput } from '../components/common/search-input'
import { createSectorRowEl } from '../components/common/sector-row'
import { FONT_SIZE, FONT_FAMILY, FONT_WEIGHT, createStockNameColumn } from '../components/common/ui-styles'
import { showPopup } from '../components/common/popup'
import type { PageModule } from '../router'
import type { SectorCustomResponse, SectorCustomMutationResponse } from '../types'

/* ── 상수 ── */

/** 뮤테이션 응답 처리 — 성공/실패 토스트 + 장중 warning 토스트 */
function handleMutationResult(res: SectorCustomMutationResponse): void {
  toastResult(res)
  if (res.ok && res.warning) {
    const msgEl = document.createElement('div')
    msgEl.textContent = res.warning
    showPopup('경고', msgEl, [{ label: '확인', onClick: () => { }, variant: 'primary' }])
  }
}

/* ── 모듈 상태 ── */
let allStocks: Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }> = new Map()
let stockNameIndex: Map<string, string> = new Map()  // 종목명 → 종목코드 역인덱스

let unsubCustom: (() => void) | null = null
let unsubSse: (() => void) | null = null
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null

// UI 참조 — Indicator Bar
let indicatorDot: HTMLElement | null = null
let indicatorLabel: HTMLElement | null = null

// UI 참조 — Scheduler
let schedulerToggle1: ReturnType<typeof createToggleBtn> | null = null
let schedulerToggle2: ReturnType<typeof createToggleBtn> | null = null

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

// 현재 상태 캐시
let currentState: SectorCustomState = sectorCustomStore.getState()

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

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Authorization': `Bearer ${localStorage.getItem('token') || 'dev-bypass'}` },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

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

/** Task 1.1: 쉼표, 공백, 줄바꿈으로 토큰 분리 후 빈 문자열 제거 */
export function parseBatchInput(input: string): string[] {
  return input.split(/,/).map(t => t.trim()).filter(t => t.length > 0)
}

/** Task 1.3: 토큰 → 종목코드 매칭. 코드 우선(O(1)), 종목명 차선(O(1)), 미매칭 시 null
 *  "나인테크(267320)" 형태 → 괄호 안 코드 추출 후 매칭, 실패 시 괄호 밖 이름으로 재시도 */
export function resolveToken(token: string): string | null {
  if (allStocks.has(token)) return token
  const codeByName = stockNameIndex.get(token)
  if (codeByName !== undefined) return codeByName

  // 괄호 포함 형태: "나인테크(267320)" 또는 "나인테크（267320）"
  const m = token.match(/^(.+?)[(\uff08]([^)\uff09]+)[)\uff09]$/)
  if (m) {
    const name = m[1].trim()
    const code = m[2].trim()
    if (allStocks.has(code)) return code
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
  const stock = allStocks.get(code)
  const stockName = stock?.name ?? code

  // 업종명 해석: stockMoves 우선, 없으면 allStocks.sector, sectors 리네임 적용
  const { stockMoves, sectors } = currentState
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
  const { stockMoves, sectors, deletedSectors } = currentState
  for (const [code, chip] of stagingChipMap) {
    const stock = allStocks.get(code)
    let sectorName = stockMoves[code] ?? stock?.sector ?? ''
    if (sectors[sectorName]) sectorName = sectors[sectorName]
    if (deletedSectors.includes(sectorName)) sectorName = '업종명없음'
    const sectorSpan = chip.querySelector('.chip-sector')
    if (sectorSpan) sectorSpan.textContent = sectorName
  }
}

/* ── Moved_Stock_List 함수 (Task 7) ── */

/* ── 8.6: countStocksBySector / getStocksForSector — allStocks 기반 ── */

function countStocksBySector(): Record<string, number> {
  const counts: Record<string, number> = {}
  const { stockMoves, sectors, deletedSectors, mergedSectors } = currentState
  for (const s of mergedSectors) counts[s] = 0

  for (const [, stock] of allStocks) {
    let sector = stockMoves[stock.code] ?? stock.sector ?? ''
    if (sectors[sector]) sector = sectors[sector]
    if (deletedSectors.includes(sector)) sector = '업종명없음'
    if (sector && counts[sector] !== undefined) counts[sector]++
    else if (sector) counts[sector] = 1
  }
  return counts
}

function getStocksForSector(sectorName: string): Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> {
  const { stockMoves, sectors, deletedSectors } = currentState
  const result: Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> = []

  for (const [, stock] of allStocks) {
    let sector = stockMoves[stock.code] ?? stock.sector ?? ''
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
  header.innerHTML = ''
  header.style.fontFamily = FONT_FAMILY

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

  // [추가] REST API 기준 증권사 라벨
  const brokerLabel = document.createElement('span')
  brokerLabel.textContent = '(키움증권 REST API 기준)'
  brokerLabel.style.fontSize = '12px'
  brokerLabel.style.color = '#666'
  left.appendChild(brokerLabel)

  header.appendChild(left)

  // 중앙: Indicator_Bar — dot + label (flex:1, text-align:center, fontSize: FONT_SIZE.title)
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
  header.appendChild(center)

  // 우측: 여백 (flex:1, text-align:right)
  const right = document.createElement('div')
  Object.assign(right.style, { flex: '1', textAlign: 'right' })

  header.appendChild(right)
}

function updateIndicatorBar(): void {
  const { editWindowOpen } = currentState
  if (indicatorDot) {
    indicatorDot.style.background = editWindowOpen ? '#198754' : '#dc3545'
  }
  if (indicatorLabel) {
    indicatorLabel.textContent = editWindowOpen
      ? '✏️ 수정 가능'
      : '⚠️ 거래시간중 편집시에는 업종순위에 변동이 있을수 있습니다.'
  }
}

/* ── 8.3: tripleLeft — 스케줄러 카드 + 데이터 관리 카드 + 업종 테이블 ── */

function buildSchedulerCard(): HTMLElement {
  const card = cardWrap()
  const schedulerTitle = createCardTitleWithContent('장마감 후 데이터 갱신 (키움증권 기준)')
  schedulerTitle.style.fontSize = FONT_SIZE.section
  card.appendChild(schedulerTitle)

  const settings = appStore.getState().settings
  schedulerToggle1 = createToggleBtn({
    on: settings?.scheduler_market_close_on ?? true,
    onClick: () => onToggleScheduler('scheduler_market_close_on', schedulerToggle1!),
  })
  const row1Label = document.createElement('div')
  const row1Title = document.createElement('div')
  row1Title.style.fontWeight = FONT_WEIGHT.normal
  row1Title.textContent = '전종목 확정시세 다운로드(매일 20:30)'
  const row1Desc = document.createElement('div')
  Object.assign(row1Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  row1Desc.textContent = '전종목 목록 + 확정 시세 + 당일 거래대금 롤링'
  row1Label.appendChild(row1Title)
  row1Label.appendChild(row1Desc)
  card.appendChild(createSettingRow(row1Label, schedulerToggle1.el))

  schedulerToggle2 = createToggleBtn({
    on: settings?.scheduler_5d_download_on ?? true,
    onClick: () => onToggleScheduler('scheduler_5d_download_on', schedulerToggle2!),
  })
  const row2Label = document.createElement('div')
  const row2Title = document.createElement('div')
  row2Title.style.fontWeight = FONT_WEIGHT.normal
  row2Title.textContent = '전종목 5일 거래대금 다운로드'
  const row2Desc = document.createElement('div')
  Object.assign(row2Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  row2Desc.textContent = '전종목 5일 거래대금 REST 다운로드 (캐시 만료 시 자동 실행)'
  row2Label.appendChild(row2Title)
  row2Label.appendChild(row2Desc)
  card.appendChild(createSettingRow(row2Label, schedulerToggle2.el))

  return card
}

async function onToggleScheduler(key: string, toggle: ReturnType<typeof createToggleBtn>): Promise<void> {
  const currentVal = appStore.getState().settings?.[key] as boolean ?? true
  const newVal = !currentVal
  const label = key === 'scheduler_market_close_on' ? '전종목 확정시세 다운로드' : '전종목 5일 거래대금 다운로드'
  const result = await showContextPopup({
    type: 'confirm',
    x: window.innerWidth / 2,
    y: window.innerHeight / 2,
    title: `${label} ${newVal ? '활성화' : '비활성화'}`,
    message: `${label}을(를) ${newVal ? '켜시' : '끄시'}겠습니까?`,
  })
  if (!result.confirmed) return
  if (!settingsMgr) return
  const res = await settingsMgr.saveSection({ [key]: newVal })
  toastResult(res)
  if (res.ok) toggle.setOn(newVal)
}

function updateSchedulerToggles(): void {
  const settings = appStore.getState().settings
  schedulerToggle1?.setOn(settings?.scheduler_market_close_on ?? true)
  schedulerToggle2?.setOn(settings?.scheduler_5d_download_on ?? true)
}

function buildDataManageCard(): HTMLElement {
  const card = cardWrap()
  const dataManageTitle = createCardTitleWithContent('데이터 관리 (키움증권 기준)')
  dataManageTitle.style.fontSize = FONT_SIZE.section
  card.appendChild(dataManageTitle)

  // 시세 캐시 삭제
  const cache1Row = document.createElement('div')
  Object.assign(cache1Row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #eee' })
  const cache1Info = document.createElement('div')
  const cache1Title = document.createElement('div')
  cache1Title.style.fontWeight = FONT_WEIGHT.normal
  cache1Title.textContent = '🗑️ 전종목 확정시세 캐시 삭제'
  const cache1Desc = document.createElement('div')
  Object.assign(cache1Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  cache1Desc.textContent = '확정 시세 + 종목명 + 업종 레이아웃 캐시를 삭제합니다. 장마감 전종목 확정시세 다운로드로 복구됩니다'
  cache1Info.appendChild(cache1Title)
  cache1Info.appendChild(cache1Desc)
  const cacheSnapshotBtn = actionBtn('삭제', '#dc3545')
  cacheSnapshotBtn.addEventListener('click', (e: MouseEvent) => onDeleteCache('snapshot', e))
  cache1Row.appendChild(cache1Info)
  cache1Row.appendChild(cacheSnapshotBtn)
  card.appendChild(cache1Row)

  // 전종목 5일 거래대금 캐시 삭제
  const cache2Row = document.createElement('div')
  Object.assign(cache2Row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' })
  const cache2Info = document.createElement('div')
  const cache2Title = document.createElement('div')
  cache2Title.style.fontWeight = FONT_WEIGHT.normal
  cache2Title.textContent = '🗑️ 전종목 5일 거래대금,고가 저장데이터 삭제'
  const cache2Desc = document.createElement('div')
  Object.assign(cache2Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  cache2Desc.textContent = '전종목 5일 거래대금,고가 저장데이터를 삭제합니다. 전종목 5일 전체 다운로드로 복구됩니다'
  cache2Info.appendChild(cache2Title)
  cache2Info.appendChild(cache2Desc)
  const cacheAvgAmtBtn = actionBtn('삭제', '#dc3545')
  cacheAvgAmtBtn.addEventListener('click', (e: MouseEvent) => onDeleteCache('avg_amt', e))
  cache2Row.appendChild(cache2Info)
  cache2Row.appendChild(cacheAvgAmtBtn)
  card.appendChild(cache2Row)

  return card
}

async function onDeleteCache(type: 'snapshot' | 'avg_amt', e: MouseEvent): Promise<void> {
  const label = type === 'snapshot' ? '전종목 확정시세 저장데이터' : '전종목 5일 거래대금,고가 저장데이터'
  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: `${label} 삭제`,
    message: `${label}를 삭제하시겠습니까?`,
    confirmText: '삭제',
    confirmColor: '#dc3545',
  })
  if (!result.confirmed) return
  try {
    const res = await apiPost<SectorCustomMutationResponse>('/api/sector-custom/delete-cache', { type })
    handleMutationResult(res)
  } catch { toastResult({ ok: false }) }
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

      // Batch_Code_Input 감지: 쉼표 포함 시 배치 모드 (Req 1.5, 1.6, 1.7, 1.8, 1.9)
      if (query.includes(',')) {
        const tokens = parseBatchInput(query)
        for (const token of tokens) {
          const code = resolveToken(token)
          if (code) addToStaging(code)
        }
        // 처리 완료 후 검색 입력 비우기 → onSearch('') 트리거로 검색 결과 숨김 + 업종 테이블 복원
        if (searchInputRef) {
          searchInputRef.clear()
          // clear() triggers onSearch('') which hides results and shows master table
          // 포커스 유지
          const inputEl = searchInputRef.el.querySelector('input')
          if (inputEl) inputEl.focus()
        }
        return
      }

      const q = query.toLowerCase()
      const { stockMoves, sectors } = currentState
      const results: SearchResultRow[] = []

      // 포괄적 검색: 괄호/공백으로 분리된 토큰 중 하나라도 매칭되면 결과에 포함
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
      (row: SearchResultRow) => {
        const state = appStore.getState()
        const sectorStock = state.sectorStocks[row.code || '']
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
    if (!tr) return
    const tbody = searchResultTableRef?.el.querySelector('tbody')
    if (!tbody) return
    const rows = Array.from(tbody.querySelectorAll('tr'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    if (idx < 0) return
    // 현재 검색 결과에서 클릭된 행 찾기
    const q = searchInputRef?.getValue()?.toLowerCase() ?? ''
    if (!q) return
    const { stockMoves, sectors } = currentState
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

    // Staging_Set에 추가 + 기존 동작(업종 선택 + 종목 하이라이트) 유지
    addToStaging(clicked.code)
    selectedSector = clicked.sector
    highlightStockCode = clicked.code
    selectedStocks.clear()
    anchorRow = -1
    updateMasterPanel()
    updateCenterPanel()
    updateRightPanel()
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

  // Row click handler via event delegation
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

function buildMasterRows(): MasterRow[] {
  const counts = countStocksBySector()
  const { mergedSectors } = currentState
  const rows: MasterRow[] = mergedSectors.map(s => ({
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
  setControlsDisabled(!currentState.editWindowOpen)
}

function updateStatsLabel(): void {
  if (!statsLabelRef) return
  const counts = countStocksBySector()
  const sectorCount = currentState.mergedSectors.length
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
    const res = await apiPost<SectorCustomMutationResponse>('/api/sector-custom/rename', { old_name: oldName, new_name: newName })
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
    const res = await apiPost<SectorCustomMutationResponse>('/api/sector-custom/delete', { name })
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
    const res = await apiPost<SectorCustomMutationResponse>('/api/sector-custom/create', { name })
    handleMutationResult(res)
  } catch { toastResult({ ok: false }) }
}

/* ── tripleLeft 빌드 ── */

function buildTripleLeft(): void {
  const left = shell.tripleLeft
  left.innerHTML = ''
  left.style.fontFamily = FONT_FAMILY
  left.appendChild(buildSectorManageCard())
  left.appendChild(buildSchedulerCard())
  left.appendChild(buildDataManageCard())
}

/* ── 8.4: tripleCenter — Stock_List_Panel ── */

function buildTripleCenter(): void {
  const center = shell.tripleCenter
  center.innerHTML = ''
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
        const state = appStore.getState()
        const sectorStock = state.sectorStocks[row.code || '']
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

  // 키보드 포커스 가능하게 설정
  detailTableRef.el.tabIndex = 0

  // 클릭 이벤트 위임: 일반 클릭(단일 선택), Ctrl+클릭(토글), Shift+클릭(범위 선택)
  detailTableRef.el.addEventListener('click', (e: MouseEvent) => {
    const tr = (e.target as HTMLElement).closest('tr')
    if (!tr) return
    const tbody = detailTableRef?.el.querySelector('tbody')
    if (!tbody) return
    const rows = Array.from(tbody.querySelectorAll('tr'))
    const idx = rows.indexOf(tr as HTMLTableRowElement)
    if (idx < 0 || !selectedSector) return
    const stocks = getStocksForSector(selectedSector)
    if (idx >= stocks.length) return

    if (e.shiftKey && anchorRow >= 0) {
      // Shift+클릭: anchorRow ~ idx 범위 선택
      const [start, end] = [Math.min(anchorRow, idx), Math.max(anchorRow, idx)]
      for (let i = start; i <= end; i++) selectedStocks.add(stocks[i].code)
    } else if (e.ctrlKey || e.metaKey) {
      // Ctrl+클릭: 토글
      const code = stocks[idx].code
      if (selectedStocks.has(code)) selectedStocks.delete(code)
      else selectedStocks.add(code)
      anchorRow = idx
    } else {
      // 일반 클릭: 단일 선택
      selectedStocks.clear()
      selectedStocks.add(stocks[idx].code)
      anchorRow = idx
    }

    // 행 스타일 갱신 — updateRows만 호출 (innerHTML 클리어 없이 델타 갱신)
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

  setControlsDisabled(!currentState.editWindowOpen)
}

/* ── 8.5: tripleRight — Target_Sector_List ── */

/** 대상 업종 목록 반환: mergedSectors에서 selectedSector 제외 */
function getTargetSectors(): string[] {
  // 배치 입력: selectedSector 없어도 staging에 종목이 있으면 전체 업종 표시
  if (selectedSector === null && stagingSet.size > 0) {
    return currentState.mergedSectors.slice()
  }
  if (selectedSector === null) return []
  return currentState.mergedSectors.filter(s => s !== selectedSector)
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
  right.innerHTML = ''
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
  setControlsDisabled(!currentState.editWindowOpen)
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
  const confirmed = await showConfirmModal({
    title: '종목 이동',
    message: buildMoveMessage(codes, allStocks, targetSector),
    confirmText: '이동',
    cancelText: '취소',
  })
  if (!confirmed) return

  try {
    const lastRes = await apiPost<SectorCustomMutationResponse>('/api/sector-custom/move-stocks', {
      stock_codes: codes,
      target_sector: targetSector,
    })
    handleMutationResult(lastRes)

    if (moveSource.source === 'staging') {
      clearStaging()
    } else {
      selectedStocks.clear()
      anchorRow = -1
    }
    updateAllInlineMoveButtons()
    updateMasterPanel()
    updateCenterPanel()
    updateRightPanel()

    // 이동 완료 팝업
    const msg = document.createElement('p')
    Object.assign(msg.style, { margin: '0', fontSize: FONT_SIZE.body, color: '#333' })
    msg.textContent = `${codes.length}개 종목이 "${targetSector}" 업종으로 이동되었습니다.`
    showPopup('✅ 이동 완료', msg, [
      { label: '확인', onClick: () => { }, variant: 'primary' },
    ])
  } catch { toastResult({ ok: false }) }
}

/* ── 전체 UI 갱신 ── */
function renderAll(): void {
  updateIndicatorBar()
  updateMasterPanel()
  updateCenterPanel()
  updateRightPanel()
  updateSchedulerToggles()
  updateStagingPanel()
  setControlsDisabled(!currentState.editWindowOpen)
}

/* ── 8.7: loadInitialData + SSE 델타 갱신 ── */

async function loadInitialData(): Promise<void> {
  try {
    sectorCustomStore.setState({ loading: true })

    // Parallel fetch: sector-custom config + all-stocks
    const [data, stocksData] = await Promise.all([
      apiGet<SectorCustomResponse>('/api/sector-custom'),
      apiGet<{ stocks: Array<{ code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }> }>('/api/sector-custom/all-stocks').catch(err => {
        console.error('[SectorCustom] all-stocks 로드 실패:', err)
        return { stocks: [] }
      }),
    ])

    // Build allStocks Map
    allStocks = new Map()
    for (const s of stocksData.stocks) {
      allStocks.set(s.code, { code: s.code, name: s.name, sector: s.sector, market_type: s.market_type, nxt_enable: s.nxt_enable })
    }

    // Task 1.3: Build stockNameIndex (종목명 → 종목코드) 역인덱스 1회 구축
    stockNameIndex = new Map()
    for (const [code, stock] of allStocks) {
      stockNameIndex.set(stock.name, code)
    }

    sectorCustomStore.setState({
      sectors: data.custom_data.sectors,
      stockMoves: data.custom_data.stock_moves,
      deletedSectors: data.custom_data.deleted_sectors,
      mergedSectors: data.merged_sectors,
      editWindowOpen: computeEditWindowOpenByTime(appStore.getState().settings),
      noSectorCount: data.no_sector_count ?? 0,
      loading: false,
    })
    currentState = sectorCustomStore.getState()

    renderAll()

    // "업종명없음" 업종 안내 팝업
    const noNameStocks = getStocksForSector("업종명없음")
    if (noNameStocks.length > 0) {
      const msg = document.createElement('p')
      Object.assign(msg.style, { margin: '0', fontSize: FONT_SIZE.label, color: '#333' })
      msg.textContent = `"업종명없음" 업종에 ${noNameStocks.length}개 종목이 있습니다. 업종을 지정해 주세요.`
      showPopup('⚠️ 업종명없음 종목 안내', msg, [
        { label: '확인', onClick: () => { }, variant: 'primary' },
      ])
    }
  } catch (e) {
    console.error('[SectorCustom] 초기 데이터 로드 실패:', e)
    sectorCustomStore.setState({ loading: false })
  }
}

/** SSE sector-custom-changed 시 allStocks 델타 갱신 */
function applyStockMovesDelta(prevMoves: Record<string, string>, newMoves: Record<string, string>): void {
  // Find changed stock moves
  const changedCodes = new Set<string>()
  for (const code of Object.keys(newMoves)) {
    if (prevMoves[code] !== newMoves[code]) changedCodes.add(code)
  }
  // Also check removed moves
  for (const code of Object.keys(prevMoves)) {
    if (!(code in newMoves)) changedCodes.add(code)
  }

  // Note: allStocks stores base sector from API. stockMoves override is applied at query time
  // in countStocksBySector/getStocksForSector. So delta update only needs to re-render.
}

/* ── 8.1 + 8.8: mount / unmount ── */

function mount(_container: HTMLElement): void {
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
  unsubSettings = settingsMgr.subscribe(() => updateSchedulerToggles())

  // sectorCustomStore 구독
  unsubCustom = sectorCustomStore.subscribe((state) => {
    const prev = currentState
    currentState = state

    if (state.mergedSectors !== prev.mergedSectors || state.sectors !== prev.sectors || state.deletedSectors !== prev.deletedSectors || state.stockMoves !== prev.stockMoves) {
      // SSE delta: apply stockMoves changes to allStocks awareness
      applyStockMovesDelta(prev.stockMoves, state.stockMoves)

      // Check if selectedSector still exists
      if (selectedSector && !state.mergedSectors.includes(selectedSector)) {
        selectedSector = null
      }
      selectedStocks.clear()
      anchorRow = -1
      updateMasterPanel()
      updateCenterPanel()
      updateRightPanel()
      updateStagingChipSectors()
    }

    if (state.editWindowOpen !== prev.editWindowOpen) {
      updateIndicatorBar()
      setControlsDisabled(!state.editWindowOpen)
    }
  })

  // appStore 구독 — settings 변경 시 editWindowOpen 재계산 + 토글 갱신
  let prevSettings = appStore.getState().settings
  unsubSse = appStore.subscribe((state) => {
    if (state.settings !== prevSettings) {
      prevSettings = state.settings
      const newEditWindowOpen = computeEditWindowOpenByTime(state.settings)
      if (newEditWindowOpen !== sectorCustomStore.getState().editWindowOpen) {
        sectorCustomStore.setState({ editWindowOpen: newEditWindowOpen })
      }
      updateSchedulerToggles()
    }
  })

  // 초기 데이터 로드
  loadInitialData()
}

/* ── 8.8: unmount ── */

function unmount(): void {
  if (unsubCustom) { unsubCustom(); unsubCustom = null }
  if (unsubSse) { unsubSse(); unsubSse = null }
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (settingsMgr) { settingsMgr.destroy(); settingsMgr = null }
  closeContextPopup()

  // Null all DOM refs
  indicatorDot = null
  indicatorLabel = null
  schedulerToggle1 = null
  schedulerToggle2 = null
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
  allStocks = new Map()
  stockNameIndex = new Map()

  // Clear shell triple panels
  shell.tripleHeader.innerHTML = ''
  shell.tripleLeft.innerHTML = ''
  shell.tripleCenter.innerHTML = ''
  shell.tripleRight.innerHTML = ''
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
  if (opts.allStocks !== undefined) allStocks = opts.allStocks
  if (opts.stockNameIndex !== undefined) stockNameIndex = opts.stockNameIndex
  if (opts.stagingSet !== undefined) stagingSet = opts.stagingSet
  if (opts.selectedStocks !== undefined) selectedStocks = opts.selectedStocks
}
