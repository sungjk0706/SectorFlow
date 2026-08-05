// frontend/src/pages/profit-overview-sector-pnl.ts
// 수익현황 페이지 — 업종별 종목 수익 렌더 + 섹션 구성 (F-05 분할, P24 단순성)
// profit-overview.ts에서 이관. 순수 이동 + renderSectorStockPnl 함수 분할, 동작 변경 없음.

import { FONT_SIZE, FONT_WEIGHT, COLOR, RADIUS, pnlColor } from '../components/common/ui-styles'
import { createActionButton } from '../components/common/button'
import { sectionTitle } from '../components/common/settings-common'
import { buildSectorStockPnl, type SectorPnlGroup, type SectorStockPnl } from './profit-math'
import type { ProfitOverviewState } from './profit-overview'

/* ── 셀 헬퍼: 수익금/수익률 숫자+단위 분리 셀 (헤더/행 공통 — P23 일관성) ── */

interface AmountCellOpts {
  width: string
  unitWidth: string
  fontSize: string
  fontWeight?: string
  border?: string
  formatValue: (n: number) => string
}

function createAmountCell(value: number, unit: string, opts: AmountCellOpts): HTMLSpanElement {
  const cell = document.createElement('span')
  Object.assign(cell.style, {
    flex: 'none', width: opts.width,
    display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline',
    fontSize: opts.fontSize, fontWeight: opts.fontWeight,
    border: opts.border, borderRadius: opts.border ? RADIUS.xs : undefined,
    padding: opts.border ? '2px 4px' : undefined, boxSizing: opts.border ? 'border-box' : undefined,
  })
  const sign = value >= 0 ? '+' : ''
  const num = document.createElement('span')
  Object.assign(num.style, { fontVariantNumeric: 'tabular-nums', color: pnlColor(value) })
  num.textContent = `${sign}${opts.formatValue(value)}`
  const unitEl = document.createElement('span')
  Object.assign(unitEl.style, { flex: 'none', width: opts.unitWidth, textAlign: 'left', color: pnlColor(value) })
  unitEl.textContent = unit
  cell.appendChild(num)
  cell.appendChild(unitEl)
  return cell
}

/* ── 업종 헤더 — 5컬럼 그리드 (종목 행과 동일 구조 — P23 일관성) ── */
// 컬럼: 1:업종명  2:빈셀  3:총수익금  4:총수익률  5:빈셀

function createSectorHeader(
  group: SectorPnlGroup,
  onHeaderClick: () => void,
): HTMLDivElement {
  const header = document.createElement('div')
  Object.assign(header.style, {
    display: 'flex', alignItems: 'center',
    padding: '8px 4px 4px', borderBottom: '2px solid ' + COLOR.borderLight, marginTop: '8px',
    cursor: 'pointer', userSelect: 'none',
  })
  // 컬럼1: 업종명 (flex:1, 종목 행 컬럼2와 폭 공유)
  const sectorName = document.createElement('span')
  Object.assign(sectorName.style, { flex: '1', minWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.semibold, color: group.color })
  sectorName.textContent = group.sector
  // 컬럼2: 빈셀 (종목 행의 종목명 자리)
  const headerEmpty2 = document.createElement('span')
  Object.assign(headerEmpty2.style, { flex: '1' })
  // 컬럼3: 업종 총수익금 (90px, 굵게 + 업종색 테두리)
  const sectorPnl = createAmountCell(group.pnl, '원', {
    width: '90px', unitWidth: '14px', fontSize: FONT_SIZE.label,
    fontWeight: FONT_WEIGHT.semibold, border: '1px solid ' + group.color,
    formatValue: n => n.toLocaleString(),
  })
  // 컬럼4: 업종 수익률 (60px, 굵게 + 업종색 테두리)
  const sectorRate = createAmountCell(group.rate, '%', {
    width: '60px', unitWidth: '12px', fontSize: FONT_SIZE.label,
    fontWeight: FONT_WEIGHT.semibold, border: '1px solid ' + group.color,
    formatValue: n => n.toFixed(2),
  })
  // 컬럼5: 빈셀 (종목 행의 매도수량 자리)
  const headerEmpty5 = document.createElement('span')
  Object.assign(headerEmpty5.style, { flex: 'none', width: '55px' })
  header.appendChild(sectorName)
  header.appendChild(headerEmpty2)
  header.appendChild(sectorPnl)
  header.appendChild(sectorRate)
  header.appendChild(headerEmpty5)
  header.addEventListener('click', onHeaderClick)
  return header
}

/* ── 종목 행 — 5컬럼 (업종 헤더와 동일 구조 — P23 일관성) ── */

function createStockRow(stock: SectorStockPnl): HTMLDivElement {
  const row = document.createElement('div')
  Object.assign(row.style, {
    display: 'flex', alignItems: 'center',
    padding: '6px 4px 6px', borderBottom: '1px solid ' + COLOR.neutralBg,
  })
  // 컬럼1: 빈셀 (업종 헤더의 업종명 자리 — 들여쓰기 효과)
  const empty1 = document.createElement('span')
  Object.assign(empty1.style, { flex: '1' })
  // 컬럼2: 종목명 (flex:1, 업종 헤더 컬럼2와 폭 공유)
  const nameEl = document.createElement('span')
  Object.assign(nameEl.style, { flex: '1', minWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: FONT_SIZE.body, fontWeight: FONT_WEIGHT.medium })
  nameEl.textContent = stock.stk_nm
  // 컬럼3: 수익금 — 숫자와 '원' 단위 분리 (digit 세로 정렬 + tabular-nums)
  const pnlEl = createAmountCell(stock.realized_pnl, '원', {
    width: '90px', unitWidth: '14px', fontSize: FONT_SIZE.body,
    formatValue: n => n.toLocaleString(),
  })
  // 컬럼4: 수익률 — 숫자와 '%' 단위 분리 (동일 패턴, P23 일관성)
  const rateEl = createAmountCell(stock.pnl_rate, '%', {
    width: '60px', unitWidth: '12px', fontSize: FONT_SIZE.body,
    formatValue: n => n.toFixed(2),
  })
  // 컬럼5: 매도수량
  const qtyEl = document.createElement('span')
  Object.assign(qtyEl.style, { flex: 'none', width: '55px', textAlign: 'right', fontSize: FONT_SIZE.small, color: COLOR.tertiary })
  qtyEl.textContent = `매도 ${stock.qty}주`
  row.appendChild(empty1)
  row.appendChild(nameEl)
  row.appendChild(pnlEl)
  row.appendChild(rateEl)
  row.appendChild(qtyEl)
  return row
}

/* ── 업종별 종목 수익 렌더 (orchestrator — 분할 후 50줄 이하) ── */

// H-03: key 기반 diff — 업종명 키로 그룹 요소 맵, 종목코드 키로 종목 행 맵 유지.
// 전체 재생성(innerHTML='') 대신 기존 요소 재사용, 변경된 텍스트만 갱신.
// 페이지 싱글톤 구조 — 모듈 레벨 캐시 1세트. 컨테이너 변경(재마운트) 시 초기화.
interface SectorGroupCache {
  groupEl: HTMLDivElement
  headerEl: HTMLDivElement
  stockRowsWrap: HTMLDivElement
  stockRowMap: Map<string, HTMLDivElement>
}
const sectorGroupCache = new Map<string, SectorGroupCache>()
let lastContainer: HTMLDivElement | null = null

/** 금액 셀 갱신 — 자식(num + unitEl)의 텍스트·색상만 갱신 (요소 재생성 없음) */
function updateAmountCell(cell: HTMLSpanElement, value: number, formatValue: (n: number) => string): void {
  const num = cell.children[0] as HTMLSpanElement
  const unitEl = cell.children[1] as HTMLSpanElement
  const sign = value >= 0 ? '+' : ''
  const newText = `${sign}${formatValue(value)}`
  if (num.textContent !== newText) {
    num.textContent = newText
    const color = pnlColor(value)
    num.style.color = color
    unitEl.style.color = color
  }
}

/** 업종 헤더 갱신 — 자식 요소 인덱스로 접근하여 텍스트·색상만 갱신 */
function updateSectorHeader(header: HTMLDivElement, group: SectorPnlGroup): void {
  const sectorName = header.children[0] as HTMLSpanElement
  if (sectorName.textContent !== group.sector) {
    sectorName.textContent = group.sector
    sectorName.style.color = group.color
  }
  updateAmountCell(header.children[2] as HTMLSpanElement, group.pnl, n => n.toLocaleString())
  updateAmountCell(header.children[3] as HTMLSpanElement, group.rate, n => n.toFixed(2))
}

/** 종목 행 갱신 — 자식 요소 인덱스로 접근하여 텍스트만 갱신 */
function updateStockRow(row: HTMLDivElement, stock: SectorStockPnl): void {
  const nameEl = row.children[1] as HTMLSpanElement
  if (nameEl.textContent !== stock.stk_nm) nameEl.textContent = stock.stk_nm
  updateAmountCell(row.children[2] as HTMLSpanElement, stock.realized_pnl, n => n.toLocaleString())
  updateAmountCell(row.children[3] as HTMLSpanElement, stock.pnl_rate, n => n.toFixed(2))
  const qtyEl = row.children[4] as HTMLSpanElement
  const newQty = `매도 ${stock.qty}주`
  if (qtyEl.textContent !== newQty) qtyEl.textContent = newQty
}

/** 종목 행 key diff — 새 종목 추가, 제거된 종목 삭제, 기존 종목 텍스트 갱신, 순서 재배치 */
function updateStockRows(
  wrap: HTMLDivElement,
  rowMap: Map<string, HTMLDivElement>,
  stocks: SectorStockPnl[],
): void {
  const newKeySet = new Set(stocks.map(s => s.stk_cd))
  // 제거된 종목 행 삭제
  for (const [stkCd, rowEl] of rowMap) {
    if (!newKeySet.has(stkCd)) {
      rowEl.remove()
      rowMap.delete(stkCd)
    }
  }
  // 추가·갱신·순서 재배치
  for (let i = 0; i < stocks.length; i++) {
    const stock = stocks[i]
    let rowEl = rowMap.get(stock.stk_cd)
    if (!rowEl) {
      // P25: 종목 행 단위 격리 — 한 종목 행 throw 시 다음 종목 계속 렌더링
      try {
        rowEl = createStockRow(stock)
        rowMap.set(stock.stk_cd, rowEl)
      } catch (e) {
        console.error('[profit-overview-sector-pnl] stock row render error', e)
        continue
      }
    } else {
      updateStockRow(rowEl, stock)
    }
    const refChild = wrap.children[i]
    if (refChild !== rowEl) {
      if (refChild) wrap.insertBefore(rowEl, refChild)
      else wrap.appendChild(rowEl)
    }
  }
}

/** 펼침/접힘 상태만 갱신 — 요소 재생성 없이 display·배경 토글 (헤더 클릭 시 사용) */
function applyExpandState(state: ProfitOverviewState): void {
  for (const [sector, cache] of sectorGroupCache) {
    const isActive = state.activeSector === sector
    if (isActive) {
      Object.assign(cache.groupEl.style, { background: COLOR.hoverBg, borderRadius: RADIUS.sm })
    } else {
      cache.groupEl.style.background = ''
      cache.groupEl.style.borderRadius = ''
    }
    const shouldShow = state.allExpanded || isActive
    cache.stockRowsWrap.style.display = shouldShow ? 'block' : 'none'
  }
}

export function renderSectorStockPnl(state: ProfitOverviewState): void {
  const { sectorStockListContainer, filteredSellHistory, allExpanded, activeSector } = state
  if (!sectorStockListContainer) return
  // 컨테이너 변경(재마운트) 시 캐시 초기화
  if (lastContainer !== sectorStockListContainer) {
    sectorGroupCache.clear()
    lastContainer = sectorStockListContainer
  }
  const groups = buildSectorStockPnl(filteredSellHistory)

  // 빈 데이터 — 기존 그룹 전부 제거 + 빈 메시지 표시
  if (groups.length === 0) {
    for (const [, cache] of sectorGroupCache) cache.groupEl.remove()
    sectorGroupCache.clear()
    // 캐시 외 잔재(빈 메시지 등) 제거
    sectorStockListContainer.innerHTML = ''
    const empty = document.createElement('div')
    Object.assign(empty.style, { padding: '20px 4px', textAlign: 'center', color: COLOR.disabled, fontSize: FONT_SIZE.label })
    empty.textContent = '매도 체결 내역이 없습니다'
    sectorStockListContainer.appendChild(empty)
    return
  }

  // 캐시 외 잔재(빈 메시지 등) 제거 — dataset.sector 없는 자식 제거
  for (let i = sectorStockListContainer.children.length - 1; i >= 0; i--) {
    const child = sectorStockListContainer.children[i] as HTMLElement
    if (!child.dataset.sector) child.remove()
  }

  const newSectorSet = new Set(groups.map(g => g.sector))
  // 제거된 업종 그룹 삭제
  for (const [sector, cache] of sectorGroupCache) {
    if (!newSectorSet.has(sector)) {
      cache.groupEl.remove()
      sectorGroupCache.delete(sector)
    }
  }

  for (let gi = 0; gi < groups.length; gi++) {
    const group = groups[gi]
    // P25: 업종 그룹 단위 격리 — 한 그룹 처리 throw 시 다음 업종 계속 렌더링
    try {
      let cache = sectorGroupCache.get(group.sector)
      if (!cache) {
        // 신규 업종 그룹 생성
        const sectorGroup = document.createElement('div')
        sectorGroup.dataset.sector = group.sector
        const header = createSectorHeader(group, () => {
          // H-03: 재호출 대신 display 토글만 수행 (깜빡임 없음)
          if (state.activeSector === group.sector && !state.allExpanded) {
            state.activeSector = null
          } else {
            state.activeSector = group.sector
            state.allExpanded = false
          }
          updateExpandToggleBtn(state)
          applyExpandState(state)
        })
        const stockRowsWrap = document.createElement('div')
        sectorGroup.appendChild(header)
        sectorGroup.appendChild(stockRowsWrap)
        sectorStockListContainer.appendChild(sectorGroup)
        cache = { groupEl: sectorGroup, headerEl: header, stockRowsWrap, stockRowMap: new Map() }
        sectorGroupCache.set(group.sector, cache)
      } else {
        // 기존 헤더 텍스트 갱신
        updateSectorHeader(cache.headerEl, group)
      }

      // 활성 업종 배경 갱신
      const isActive = activeSector === group.sector
      if (isActive) {
        Object.assign(cache.groupEl.style, { background: COLOR.hoverBg, borderRadius: RADIUS.sm })
      } else {
        cache.groupEl.style.background = ''
        cache.groupEl.style.borderRadius = ''
      }

      // 펼침/접힘 — display 토글 (행 삭제 없음)
      const shouldShow = allExpanded || isActive
      cache.stockRowsWrap.style.display = shouldShow ? 'block' : 'none'

      // 종목 행 key diff
      updateStockRows(cache.stockRowsWrap, cache.stockRowMap, group.stocks)

      // 업종 순서 재배치
      const refChild = sectorStockListContainer.children[gi]
      if (refChild !== cache.groupEl) {
        if (refChild) sectorStockListContainer.insertBefore(cache.groupEl, refChild)
        else sectorStockListContainer.appendChild(cache.groupEl)
      }
    } catch (e) {
      console.error('[profit-overview-sector-pnl] sector group render error', e)
    }
  }
}

/* ── 전체보기 버튼 텍스트 동기화 ── */
export function updateExpandToggleBtn(state: ProfitOverviewState): void {
  if (!state.expandToggleBtn) return
  state.expandToggleBtn.textContent = state.allExpanded ? '전체접기' : '전체보기'
}

/* ── mount 헬퍼: 업종별 종목 수익 섹션 (타이틀 + 전체보기 버튼 + 컨테이너) ── */

export function buildStockListSection(state: ProfitOverviewState): HTMLDivElement {
  // 형제 구조 — 타이틀 행(가로) 아래 컨테이너(세로)가 별도 블록.
  // 다른 섹션(차트/도넛/계좌 현황)과 동일 패턴 — P23 일관성.
  const wrapper = document.createElement('div')
  Object.assign(wrapper.style, { display: 'flex', flexDirection: 'column', marginTop: '12px' })

  const toggleBtn = createActionButton({
    label: state.allExpanded ? '전체접기' : '전체보기',
    variant: 'secondary',
    padding: '2px 10px',
    fontSize: FONT_SIZE.small,
    borderRadius: RADIUS.xs,
    onClick: () => {
      state.allExpanded = !state.allExpanded
      state.activeSector = null
      updateExpandToggleBtn(state)
      renderSectorStockPnl(state)
    },
  })
  Object.assign(toggleBtn.style, {
    border: '1px solid ' + COLOR.borderDark,
    background: COLOR.surfaceLight,
    color: COLOR.down,
    fontWeight: FONT_WEIGHT.normal,
  })
  state.expandToggleBtn = toggleBtn

  // 타이틀 행 중앙: 기간 라벨 + 총 실현손익 + 수익률 (도넛 중앙과 동일 SSOT — buildDonutCenter 결과로 갱신, P10/P21).
  // 초기값은 빈 문자열(placeholder 없음, P20) — refreshFilteredViews에서 첫 갱신.
  const centerSlot = document.createElement('span')
  Object.assign(centerSlot.style, { display: 'inline-flex', alignItems: 'baseline', gap: '8px' })
  const labelRef = document.createElement('span')
  Object.assign(labelRef.style, { fontSize: FONT_SIZE.label, color: COLOR.tertiary, fontWeight: FONT_WEIGHT.normal })
  const pnlRef = document.createElement('span')
  Object.assign(pnlRef.style, { fontVariantNumeric: 'tabular-nums', fontWeight: FONT_WEIGHT.semibold, fontSize: FONT_SIZE.body })
  const rateRef = document.createElement('span')
  Object.assign(rateRef.style, { fontVariantNumeric: 'tabular-nums', fontSize: FONT_SIZE.label })
  centerSlot.appendChild(labelRef)
  centerSlot.appendChild(pnlRef)
  centerSlot.appendChild(rateRef)
  state.sectorSummaryLabelRef = labelRef
  state.sectorSummaryPnlRef = pnlRef
  state.sectorSummaryRateRef = rateRef

  wrapper.appendChild(sectionTitle('업종별 종목 수익', toggleBtn, centerSlot))

  const container = document.createElement('div')
  Object.assign(container.style, { flex: '1', minHeight: '0' })
  state.sectorStockListContainer = container
  wrapper.appendChild(container)

  return wrapper
}
