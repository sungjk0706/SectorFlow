// frontend/src/pages/profit-overview-sector-pnl.ts
// 수익현황 페이지 — 업종별 종목 수익 렌더 + 섹션 구성 (F-05 분할, P24 단순성)
// profit-overview.ts에서 이관. 순수 이동 + renderSectorStockPnl 함수 분할, 동작 변경 없음.

import { FONT_SIZE, FONT_WEIGHT, COLOR, pnlColor } from '../components/common/ui-styles'
import { createActionButton } from '../components/common/button'
import { buildSectorStockPnl, type SectorPnlGroup, type SectorStockPnl } from './profit-shared'
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
    border: opts.border, borderRadius: opts.border ? '4px' : undefined,
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

export function renderSectorStockPnl(state: ProfitOverviewState): void {
  const { sectorStockListContainer, filteredSellHistory, allExpanded, activeSector } = state
  if (!sectorStockListContainer) return
  const groups = buildSectorStockPnl(filteredSellHistory)
  sectorStockListContainer.innerHTML = ''

  if (groups.length === 0) {
    const empty = document.createElement('div')
    Object.assign(empty.style, { padding: '20px 4px', textAlign: 'center', color: COLOR.disabled, fontSize: FONT_SIZE.label })
    empty.textContent = '매도 체결 내역이 없습니다'
    sectorStockListContainer.appendChild(empty)
    return
  }

  for (const group of groups) {
    // P25: 업종 그룹 단위 격리 — 한 그룹 처리 throw 시 다음 업종 계속 렌더링
    try {
      const sectorGroup = document.createElement('div')
      sectorGroup.dataset.sector = group.sector
      const isActive = activeSector === group.sector
      if (isActive) {
        Object.assign(sectorGroup.style, { background: COLOR.hoverBg, borderRadius: '6px' })
      }

      const header = createSectorHeader(group, () => {
        if (state.activeSector === group.sector && !state.allExpanded) {
          state.activeSector = null
        } else {
          state.activeSector = group.sector
          state.allExpanded = false
        }
        updateExpandToggleBtn(state)
        renderSectorStockPnl(state)
      })
      sectorGroup.appendChild(header)

      // 종목 행 컨테이너 — 펼침/접힘 토글 대상
      const stockRowsWrap = document.createElement('div')
      const shouldShow = allExpanded || isActive
      stockRowsWrap.style.display = shouldShow ? 'block' : 'none'
      for (const stock of group.stocks) {
        // P25: 종목 행 단위 격리 — 한 종목 행 throw 시 다음 종목 계속 렌더링
        try {
          stockRowsWrap.appendChild(createStockRow(stock))
        } catch (e) {
          console.error('[profit-overview-sector-pnl] stock row render error', e)
        }
      }
      sectorGroup.appendChild(stockRowsWrap)
      sectorStockListContainer.appendChild(sectorGroup)
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
  const stockListHeaderWrap = document.createElement('div')
  Object.assign(stockListHeaderWrap.style, {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    fontWeight: FONT_WEIGHT.normal, fontSize: FONT_SIZE.section, color: COLOR.down,
    padding: '10px 0 6px', borderBottom: '2px solid ' + COLOR.borderLight,
    marginBottom: '8px', marginTop: '12px',
  })
  const stockListTitle = document.createElement('span')
  stockListTitle.textContent = '업종별 종목 수익'
  stockListHeaderWrap.appendChild(stockListTitle)

  const toggleBtn = createActionButton({
    label: state.allExpanded ? '전체접기' : '전체보기',
    variant: 'secondary',
    padding: '2px 10px',
    fontSize: FONT_SIZE.small,
    borderRadius: '4px',
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
  stockListHeaderWrap.appendChild(toggleBtn)

  const container = document.createElement('div')
  Object.assign(container.style, { flex: '1', minHeight: '0' })
  state.sectorStockListContainer = container
  stockListHeaderWrap.appendChild(container)

  return stockListHeaderWrap
}
