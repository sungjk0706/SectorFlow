// frontend/src/pages/stock-classification-right.ts
// 종목분류 페이지 — tripleRight(Target_Sector_List + onMoveStock) 분할 (F-04 분할 6단계)
// P10 SSOT/P16 살아있는 경로/P24 단순성 — state 첫 인자 전달 패턴

import { shell } from '../main'
import { stockClassificationStore } from '../stores/stockClassificationStore'
import { api } from '../api/client'
import { toastResult } from '../components/common/toast'
import { showContextPopup } from '../components/common/context-popup'
import { createSearchInput } from '../components/common/search-input'
import { createSectorRowEl } from '../components/common/sector-row'
import { FONT_SIZE, FONT_FAMILY, COLOR } from '../components/common/ui-styles'
import type { StockClassificationMutationResponse } from '../types'
import {
  handleMutationResult,
  buildMoveMessage,
} from './stock-classification-shared'
import {
  getAllStocks,
  clearStaging,
} from './stock-classification-staging'
import { getActiveSectors } from './stock-classification-master'
import type { StockClassificationPageState } from './stock-classification'

/* ── Right_Panel Callbacks (순환 참조 회피 — main 잔류 함수 연결) ── */

interface RightPanelCallbacks {
  setControlsDisabled: (disabled: boolean) => void
}

let callbacks: RightPanelCallbacks | null = null

export function initRightCallbacks(cb: RightPanelCallbacks): void {
  callbacks = cb
}

export function resetRightCallbacks(): void {
  callbacks = null
}

/* ── 8.5: tripleRight — Target_Sector_List ── */

/** Move_Source 결정 — state.stagingSet 우선, 비어있으면 state.selectedStocks, 둘 다 비면 null */
function getMoveSource(state: StockClassificationPageState): { source: 'staging' | 'checked'; codes: string[] } | null {
  if (state.stagingSet.size > 0) return { source: 'staging', codes: [...state.stagingSet] }
  if (state.selectedStocks.size > 0) return { source: 'checked', codes: [...state.selectedStocks] }
  return null
}

/** 이동 가능 종목 수 (버튼 텍스트용) */
function getMovableCount(state: StockClassificationPageState): number {
  if (state.stagingSet.size > 0) return state.stagingSet.size
  return state.selectedStocks.size
}

/** 대상 업종 목록 반환: activeSectors에서 state.selectedSector 제외 */
function getTargetSectors(state: StockClassificationPageState): string[] {
  const activeSectors = getActiveSectors(state)
  // 배치 입력: state.selectedSector 없어도 staging에 종목이 있으면 전체 업종 표시
  if (state.selectedSector === null && state.stagingSet.size > 0) {
    return activeSectors
  }
  if (state.selectedSector === null) return []
  return activeSectors.filter(s => s !== state.selectedSector)
}

/** 업종 행 하나 생성: [업종명 span (flex:1)] + [이동 버튼] */
function createSectorRow(state: StockClassificationPageState, sectorName: string): HTMLElement {
  const count = getMovableCount(state)
  const row = createSectorRowEl({
    sectorName,
    btnText: count > 0 ? `${count}개 이동` : '이동',
    btnDisabled: count === 0,
    onBtnClick: (e) => onMoveStock(state, e, sectorName),
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

export function buildTripleRight(state: StockClassificationPageState): void {
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
  updateTargetSectorList(state)

  // 초기 상태
  updateRightPanel(state)
}

/** Target_Sector_List 델타 갱신 */
function updateTargetSectorList(state: StockClassificationPageState): void {
  if (!state.targetSectorListRef) return
  const newTargets = getTargetSectors(state)
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
      const row = createSectorRow(state, s)
      state.sectorRowMap.set(s, row)
      state.targetSectorListRef.appendChild(row)
    }
  }

  state.prevTargetSectors = newSet
}

/** 모든 인라인 이동 버튼의 텍스트 + disabled 상태 갱신 (Task 8.1, 8.3) */
export function updateAllInlineMoveButtons(state: StockClassificationPageState): void {
  const count = getMovableCount(state)
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

export function updateRightPanel(state: StockClassificationPageState): void {
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
    buildTripleRight(state)
    return
  }

  updateTargetSectorList(state)
  updateAllInlineMoveButtons(state)
  const storeState = stockClassificationStore.getState()
  callbacks!.setControlsDisabled(!storeState.editWindowOpen)
}

async function onMoveStock(state: StockClassificationPageState, e: MouseEvent, targetSector: string): Promise<void> {
  const moveSource = getMoveSource(state)
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
