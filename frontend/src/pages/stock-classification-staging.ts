// frontend/src/pages/stock-classification-staging.ts
// 종목분류 페이지 — Staging_Panel + 업종별 종목 집계 함수 (F-04 분할 2단계, P24 단순성)
// stock-classification.ts에서 이관. 순수 이동, 동작 변경 없음.
//
// 포함:
//   - getAllStocks(state): allStocks 파생 캐시 헬퍼 (main의 resolveToken/collectFuzzyResults 등도 사용)
//   - createChip / addToStaging / removeFromStaging / clearStaging / updateStagingPanel / updateStagingChipSectors
//   - countStocksBySector / getStocksForSector
//
// 순환 참조 해결: addToStaging/removeFromStaging/clearStaging이 main 잔류 함수
// (updateAllInlineMoveButtons, updateRightPanel)를 호출 → callback registration pattern.

import { stockClassificationStore } from '../stores/stockClassificationStore'
import { showSaveToast } from '../components/common/toast'
import { COLOR, FONT_SIZE, FONT_FAMILY } from '../components/common/ui-styles'
import type { StockClassificationPageState } from './stock-classification'

/* ── 순환 참조 해결: main 잔류 함수 callback ── */

export interface StagingPanelCallbacks {
  updateAllInlineMoveButtons: () => void
  updateRightPanel: () => void
}

let callbacks: StagingPanelCallbacks | null = null

/** mount 시 main에서 호출 — 순환 참조 함수 주입 */
export function initStagingCallbacks(cb: StagingPanelCallbacks): void {
  callbacks = cb
}

/** unmount 시 main에서 호출 — callback 해제 (P19 메모리 누수 방지) */
export function resetStagingCallbacks(): void {
  callbacks = null
}

/* ── allStocks 파생 헬퍼 (캐싱) ── */

/** store의 allStocks가 변경될 때만 재계산. main의 resolveToken/collectFuzzyResults/updateStockNameIndex 등도 사용. */
export function getAllStocks(state: StockClassificationPageState): Map<string, { code: string; name: string; sector: string; market_type?: string; nxt_enable?: boolean }> {
  const current = stockClassificationStore.getState().allStocks;
  if (current !== state.cachedSectorStocksRef) {
    state.cachedSectorStocksRef = current;
    state.cachedAllStocksMap = new Map();
    for (const s of current) {
      state.cachedAllStocksMap.set(s.code, {
        code: s.code,
        name: s.name,
        sector: s.sector || '',
        market_type: s.market_type,
        nxt_enable: s.nxt_enable
      });
    }
  }
  return state.cachedAllStocksMap;
}

/* ── Staging_Panel 함수 (Task 4) ── */

/** Task 4.4: Chip DOM 생성 — 종목명 + 업종명 + × 버튼 */
export function createChip(state: StockClassificationPageState, code: string): HTMLElement {
  const stock = getAllStocks(state).get(code)
  const stockName = stock?.name ?? code

  // 업종명 해석: stockMoves 우선, 없으면 getAllStocks().sector, sectors 리네임 적용
  const storeState = stockClassificationStore.getState()
  const { stockMoves, sectors } = storeState
  let sectorName = stockMoves[code] ?? stock?.sector ?? ''
  if (sectors[sectorName]) sectorName = sectors[sectorName]

  const chip = document.createElement('span')
  chip.className = 'staging-chip'
  chip.setAttribute('data-code', code)
  Object.assign(chip.style, {
    display: 'inline-flex', alignItems: 'center', gap: '4px',
    padding: '2px 8px', borderRadius: '12px',
    background: COLOR.downBg, fontSize: FONT_SIZE.small,
    fontFamily: FONT_FAMILY, cursor: 'default',
  })

  const nameSpan = document.createElement('span')
  nameSpan.className = 'chip-name'
  nameSpan.textContent = stockName

  const sectorSpan = document.createElement('span')
  sectorSpan.className = 'chip-sector'
  Object.assign(sectorSpan.style, { color: COLOR.disabled, fontSize: FONT_SIZE.chip })
  sectorSpan.textContent = sectorName

  const removeSpan = document.createElement('span')
  removeSpan.className = 'chip-remove'
  Object.assign(removeSpan.style, { cursor: 'pointer', marginLeft: '4px' })
  removeSpan.textContent = '×'
  removeSpan.addEventListener('click', () => removeFromStaging(state, code))

  chip.appendChild(nameSpan)
  chip.appendChild(sectorSpan)
  chip.appendChild(removeSpan)

  // Hover 강조
  chip.addEventListener('mouseenter', () => { chip.style.background = COLOR.downLight })
  chip.addEventListener('mouseleave', () => { chip.style.background = COLOR.downBg })

  return chip
}

/** Task 4.2: Staging_Set에 종목 추가. 중복 시 false + 토스트 */
export function addToStaging(state: StockClassificationPageState, code: string): boolean {
  if (state.stagingSet.has(code)) {
    showSaveToast('error', '이미 추가된 종목입니다')
    return false
  }
  state.stagingSet.add(code)
  const chip = createChip(state, code)
  state.stagingChipMap.set(code, chip)
  // Chip 목록 컨테이너에 삽입 (state.stagingPanelRef의 chip-list 영역)
  const chipList = state.stagingPanelRef?.querySelector('.staging-chip-list')
  if (chipList) chipList.appendChild(chip)
  updateStagingPanel(state)
  // P20 폴백 금지 — callback은 mount 시 주입됨, 미주입 시 프로그래밍 에러
  callbacks!.updateAllInlineMoveButtons()
  callbacks!.updateRightPanel()
  return true
}

/** Task 4.2: Staging_Set에서 종목 제거 + 해당 Chip DOM만 삭제 (전체 리렌더링 금지) */
export function removeFromStaging(state: StockClassificationPageState, code: string): void {
  state.stagingSet.delete(code)
  const chip = state.stagingChipMap.get(code)
  if (chip) chip.remove()
  state.stagingChipMap.delete(code)
  updateStagingPanel(state)
  callbacks!.updateAllInlineMoveButtons()
  callbacks!.updateRightPanel()
}

/** Task 4.2: Staging_Set 전체 비우기 + 모든 Chip DOM 삭제 */
export function clearStaging(state: StockClassificationPageState): void {
  state.stagingSet.clear()
  for (const [, chip] of state.stagingChipMap) chip.remove()
  state.stagingChipMap.clear()
  updateStagingPanel(state)
  callbacks!.updateAllInlineMoveButtons()
  callbacks!.updateRightPanel()
}

/** Task 4.5: Staging_Panel 카운트/빈 상태 갱신 */
export function updateStagingPanel(state: StockClassificationPageState): void {
  if (state.stagingCountRef) {
    state.stagingCountRef.textContent = state.stagingSet.size > 0 ? `${state.stagingSet.size}개 선택` : ''
  }
  if (state.stagingEmptyRef) {
    state.stagingEmptyRef.style.display = state.stagingSet.size === 0 ? '' : 'none'
  }
  // "전체 해제" 버튼 표시/숨김
  const clearBtn = state.stagingPanelRef?.querySelector('.staging-clear-btn') as HTMLElement | null
  if (clearBtn) {
    clearBtn.style.display = state.stagingSet.size > 0 ? '' : 'none'
  }
}

/** Task 9.1: SSE 수신 시 모든 Chip의 업종명 텍스트만 갱신 (전체 리렌더링 금지) */
export function updateStagingChipSectors(state: StockClassificationPageState): void {
  const storeState = stockClassificationStore.getState()
  const { stockMoves, sectors } = storeState
  for (const [code, chip] of state.stagingChipMap) {
    // P25: 칩 단위 격리 — 한 칩 갱신 throw 시 다음 칩 계속 갱신
    try {
      const stock = getAllStocks(state).get(code)
      let sectorName = stockMoves[code] ?? stock?.sector ?? ''
      if (sectors[sectorName]) sectorName = sectors[sectorName]
      const sectorSpan = chip.querySelector('.chip-sector')
      if (sectorSpan) sectorSpan.textContent = sectorName
    } catch (e) {
      console.error('[stock-classification] staging chip sector update error', e)
    }
  }
}

/* ── 8.6: countStocksBySector / getStocksForSector — getAllStocks() 기반 ── */

export function countStocksBySector(state: StockClassificationPageState): Record<string, number> {
  const counts: Record<string, number> = {}
  const storeState = stockClassificationStore.getState()
  const { stockMoves, sectors, mergedSectors } = storeState
  for (const s of mergedSectors) counts[s] = 0

  for (const [, stock] of getAllStocks(state)) {
    // P25: 종목 단위 격리 — 한 종목 처리 throw 시 다음 종목 계속 카운트
    try {
      let sector = stockMoves[stock.code] ?? stock.sector
      if (sector === undefined || sector === null) sector = '미분류'
      if (sectors[sector]) sector = sectors[sector]
      if (sector && counts[sector] !== undefined) counts[sector]++
      else if (sector) counts[sector] = 1
    } catch (e) {
      console.error('[stock-classification] count stock by sector error', e)
    }
  }
  return counts
}

export function getStocksForSector(state: StockClassificationPageState, sectorName: string): Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> {
  const storeState = stockClassificationStore.getState()
  const { stockMoves, sectors } = storeState
  const result: Array<{ code: string; name: string; market_type?: string; nxt_enable?: boolean }> = []

  for (const [, stock] of getAllStocks(state)) {
    // P25: 종목 단위 격리 — 한 종목 처리 throw 시 다음 종목 계속 수집
    try {
      let sector = stockMoves[stock.code] ?? stock.sector
      if (sector === undefined || sector === null) sector = '미분류'
      if (sectors[sector]) sector = sectors[sector]
      if (sector === sectorName) result.push({ code: stock.code, name: stock.name, market_type: stock.market_type, nxt_enable: stock.nxt_enable })
    } catch (e) {
      console.error('[stock-classification] get stocks for sector error', e)
    }
  }
  return result.sort((a, b) => a.name.localeCompare(b.name))
}
