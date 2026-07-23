// frontend/src/pages/profit-detail-mount.ts
// 수익 상세 페이지 — mount 헬퍼 함수들 + 초기화 + rAF/구독 (F-05 분할, P24 단순성)
// profit-detail.ts에서 이관. 순수 이동, 동작 변경 없음.

import { FONT_SIZE, COLOR } from '../components/common/ui-styles'
import { createSearchInput } from '../components/common/search-input'
import { createTabBar, createToggleSelectBtn } from '../components/common/button'
import { createDateRangeInput, type DateRangeInputApi } from '../components/common/date-range-input'
import { api } from '../api/client'
import { hotStore } from '../stores/hotStore'
import { globalSettingsManager } from '../settings'
import {
  type SummaryCardEls,
  createSummaryCards,
  updateSummaryCards,
} from './profit-shared'
import { loadProfitDetailView } from './profit-detail-view'
import {
  showTable,
  showDrilldown,
  filterByDate,
  filterByDateRange,
  updateCardSelection,
  updateDrilldownBtnStyle,
  updateTabLabels,
  persistViewState,
} from './profit-detail-display'
import type { ProfitDetailState } from './profit-detail'

/* ── mount 헬퍼: 요약 카드 행 (당일/직전/당월/누적 손익) ── */
export function buildSummaryRow(state: ProfitDetailState, todayStr: string, monthStart: string, monthEnd: string): HTMLDivElement {
  const summaryRow = document.createElement('div')
  Object.assign(summaryRow.style, { display: 'flex', gap: '8px', padding: '8px 4px', flex: 'none', borderBottom: '1px solid ' + COLOR.borderDark })

  state.summaryCardEls = createSummaryCards(summaryRow, {
    onTodayClick: () => {
      state.selectedView = 'today'
      updateCardSelection(state)
      updateDrilldownBtnStyle(state, false)
      filterByDate(state, todayStr)
      persistViewState(state)
    },
    onPrevClick: async () => {
      state.selectedView = 'prev'
      updateCardSelection(state)
      updateDrilldownBtnStyle(state, false)
      try {
        const prev = await api.getPrevTradingDay()
        // await 중 다른 카드/필터 클릭 시 덮어쓰기 방지
        if (state.selectedView !== 'prev') return
        filterByDate(state, prev.date)
        persistViewState(state)
      } catch (err) {
        console.error('[profit-detail] prev-trading-day fetch failed:', err)
      }
    },
    onMonthClick: () => {
      state.selectedView = 'month'
      updateCardSelection(state)
      updateDrilldownBtnStyle(state, false)
      filterByDateRange(state, monthStart, monthEnd)
      persistViewState(state)
    },
    onTotalClick: () => {
      state.selectedView = 'total'
      updateCardSelection(state)
      updateDrilldownBtnStyle(state, false)
      if (state.dateRangeInput) state.dateRangeInput.setValue('', '')
      state.drilldownActive = false
      showTable(state)
      updateTabLabels(state)
      persistViewState(state)
    },
  })

  return summaryRow
}

/* ── mount 헬퍼: 드릴다운 토글 버튼 클릭 콜백 ── */
function onDrilldownToggle(state: ProfitDetailState): void {
  state.drilldownActive = !state.drilldownActive
  if (state.drilldownActive) {
    state.selectedView = 'drilldown'
    updateCardSelection(state)
    updateDrilldownBtnStyle(state, true)
    showDrilldown(state)
    persistViewState(state)
  } else {
    state.selectedView = null
    updateCardSelection(state)
    updateDrilldownBtnStyle(state, false)
    showTable(state)
    updateTabLabels(state)
    persistViewState(state)
  }
}

/* ── mount 헬퍼: 필터 행 (날짜 범위 + 드릴다운 토글 + 종목 검색) ── */
export function buildFilterRow(state: ProfitDetailState, monthStart: string, todayStr: string): HTMLDivElement {
  const filterRow = document.createElement('div')
  Object.assign(filterRow.style, { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 4px', borderBottom: '1px solid ' + COLOR.borderLight, flexWrap: 'wrap' })

  state.dateRangeInput = createDateRangeInput({
    from: monthStart,
    to: todayStr,
    label: '기간:',
    onChange: () => {
      state.selectedView = null
      updateCardSelection(state)
      updateDrilldownBtnStyle(state, false)
      showTable(state)
      updateTabLabels(state)
      persistViewState(state)
    },
  })
  filterRow.appendChild(state.dateRangeInput.el)

  state.drilldownBtnHandle = createToggleSelectBtn({
    label: '당월 일별 요약',
    active: false,
    onClick: () => onDrilldownToggle(state),
  })
  filterRow.appendChild(state.drilldownBtnHandle.el)

  const stockSep = document.createElement('span')
  stockSep.textContent = '|'
  stockSep.style.color = COLOR.border
  filterRow.appendChild(stockSep)

  state.stockFilterInput = createSearchInput({
    label: '종목명/코드',
    labelColor: COLOR.down,
    placeholder: '종목명/코드 검색',
    borderColor: COLOR.down,
    onSearch: () => { showTable(state); updateTabLabels(state) },
  })
  filterRow.appendChild(state.stockFilterInput.el)

  return filterRow
}

/* ── mount 헬퍼: 탭 헤더 (매도/매수 내역) ── */
export function buildTabRow(state: ProfitDetailState): HTMLDivElement {
  state.tabRow = document.createElement('div')
  Object.assign(state.tabRow.style, { display: 'flex', marginTop: '4px', padding: '0 4px', marginBottom: '12px' })

  state.tabBarHandle = createTabBar({
    tabs: [
      { id: 'sell', label: '매도 내역' },
      { id: 'buy', label: '매수 내역' },
    ],
    activeId: state.activeTab,
    onChange: (id) => {
      state.activeTab = id as 'buy' | 'sell'
      state.drilldownActive = false
      showTable(state)
      updateTabLabels(state)
    },
    fontSize: FONT_SIZE.tab,
    padding: '8px 16px',
    equalWidth: true,
    boxed: true,
  })
  state.sellTabBtn = state.tabBarHandle.buttons.get('sell') ?? null
  state.buyTabBtn = state.tabBarHandle.buttons.get('buy') ?? null
  state.tabRow.appendChild(state.tabBarHandle.el)
  return state.tabRow
}

/* ── mount 헬퍼: 테이블 컨테이너 (테이블 뷰 + 드릴다운 뷰) ── */
export function buildTableContainer(state: ProfitDetailState): HTMLDivElement {
  state.tableContainer = document.createElement('div')
  Object.assign(state.tableContainer.style, { flex: '1', padding: '0 4px', overflow: 'auto' })

  state.tableViewContainer = document.createElement('div')
  state.drilldownViewContainer = document.createElement('div')
  state.drilldownViewContainer.style.display = 'none'

  state.tableContainer.appendChild(state.tableViewContainer)
  state.tableContainer.appendChild(state.drilldownViewContainer)
  return state.tableContainer
}

/* ── mount 헬퍼: 통계 정보 행 (총 건수/매수금액/매도금액/실현손익/승률/수익률) ── */
export function buildStatRow(state: ProfitDetailState): HTMLDivElement {
  const statRow = document.createElement('div')
  Object.assign(statRow.style, { display: 'flex', gap: '8px', padding: '6px 4px', borderTop: '1px solid ' + COLOR.borderLight, flex: 'none' })

  const STAT_STYLE = `flex:1;background:${COLOR.surfaceLight};border:1px solid ${COLOR.borderLight};border-radius:4px;padding:4px 8px;display:flex;flex-direction:column;align-items:center;gap:2px;`
  const STAT_LABELS = ['총 건수', '당일 매수 지출(수수료 포함)', '당일 매도 수령(실수령)', '실현손익', '수익률', '승률']
  const statEls: HTMLSpanElement[] = []
  state.statCardEls = []

  for (let i = 0; i < 6; i++) {
    // P25: 카드 단위 격리 — 한 카드 생성 throw 시 다음 카드 계속 렌더링.
    // statEls/statCardEls push는 인덱스 기반(state.statCountEl = statEls[0] 등)이므로
    // 실패 시 더미 push로 인덱스 정합성 유지 (P22).
    try {
      const stat = document.createElement('div')
      stat.style.cssText = STAT_STYLE

      const labelEl = document.createElement('span')
      Object.assign(labelEl.style, { fontSize: FONT_SIZE.section, color: COLOR.tertiary })
      labelEl.textContent = STAT_LABELS[i]

      const valEl = document.createElement('span')
      Object.assign(valEl.style, { fontSize: FONT_SIZE.section, fontWeight: 'normal' })
      valEl.textContent = '-'

      stat.appendChild(labelEl)
      stat.appendChild(valEl)
      statRow.appendChild(stat)

      statEls.push(valEl)
      state.statCardEls.push(stat)
    } catch (e) {
      console.error('[profit-detail] stat card build error', e)
      const dummyVal = document.createElement('span')
      dummyVal.textContent = '-'
      statEls.push(dummyVal)
      const dummyCard = document.createElement('div')
      state.statCardEls.push(dummyCard)
    }
  }

  state.statCountEl = statEls[0]
  state.statBuyAmtEl = statEls[1]
  state.statSellAmtEl = statEls[2]
  state.statPnlEl = statEls[3]
  state.statAvgRateEl = statEls[4]
  state.statWinRateEl = statEls[5]

  return statRow
}

/* ── mount 헬퍼: 초기 데이터 반영 + 저장된 뷰 상태 복원 ── */
export function restoreInitialView(state: ProfitDetailState, todayStr: string, initState: ReturnType<typeof hotStore.getState>): void {
  state.sellHistory = initState.sellHistory
  state.buyHistory = initState.buyHistory
  updateTabLabels(state)

  // 저장된 뷰 상태 복원 — 없으면 기본값 'today'
  const savedView = loadProfitDetailView()
  if (savedView) {
    state.selectedView = savedView.selectedView
    state.drilldownActive = savedView.drilldownActive
    if (state.dateRangeInput) state.dateRangeInput.setValue(savedView.from, savedView.to)
    updateCardSelection(state)
    if (savedView.drilldownActive) {
      updateDrilldownBtnStyle(state, true)
      showDrilldown(state)
    } else {
      updateDrilldownBtnStyle(state, false)
      showTable(state)
      updateTabLabels(state)
    }
  } else {
    state.selectedView = 'today'
    updateCardSelection(state)
    filterByDate(state, todayStr)
  }
  if (state.summaryCardEls) {
    updateSummaryCards(state.sellHistory, initState.dailySummary, state.summaryCardEls)
  }
}

/* ── mount 헬퍼: 당월 dailySummary 조회 (드릴다운 당월 전체 날짜 보장 — P21 사용자 투명성)
 *  수익현황 페이지의 날짜 범위 선택(당일/5일 등)이 hotStore.dailySummary에 반영되어 있을 수 있으므로,
 *  수익상세 진입 시 당월 전체 범위로 재조회하여 드릴다운이 항상 당월 전체를 표시하도록 보장.
 *  applyDateRange(profit-overview-mount.ts)와 동일한 api.getDailySummary + hotStore.setState 패턴 (P23 일관성). */
export async function ensureMonthlyDailySummary(state: ProfitDetailState, todayStr: string): Promise<void> {
  if (!state.mounted) return
  const monthStart = todayStr.slice(0, 8) + '01'
  const tradeMode = globalSettingsManager.getSettings()?.trade_mode || 'test'
  try {
    const data = await api.getDailySummary(monthStart, todayStr, tradeMode)
    if (!state.mounted) return
    hotStore.setState({ dailySummary: data })
  } catch (err) {
    console.error('[profit-detail] 당월 daily-summary 조회 실패:', err)
  }
}

/* ── mount 헬퍼: rAF 배칭 렌더 (dirty 플래그 기반 selective update) ── */
export function flushDirtyRender(state: ProfitDetailState): void {
  state.rafId = null
  if (!state.mounted) return

  if (state.dirtyHistory) {
    state.dirtyHistory = false
    if (state.drilldownActive) {
      showDrilldown(state)
    } else {
      showTable(state)
    }
    updateTabLabels(state)
    if (state.summaryCardEls) {
      updateSummaryCards(state.sellHistory, hotStore.getState().dailySummary, state.summaryCardEls)
    }
  }

  if (state.dirtySummary) {
    state.dirtySummary = false
    if (state.summaryCardEls) {
      updateSummaryCards(state.sellHistory, hotStore.getState().dailySummary, state.summaryCardEls)
    }
    // 드릴다운이 dailySummary 기반이므로 summary 변경 시 드릴다운도 갱신 (P10 SSOT)
    if (state.drilldownActive) {
      showDrilldown(state)
    }
  }

  if (state.dirtySectorStocks) {
    state.dirtySectorStocks = false
    if (state.drilldownActive) {
      showDrilldown(state)
    } else {
      showTable(state)
    }
  }
}

/* ── mount 헬퍼: hotStore 구독 (rAF 배칭 + selective update) ── */
export function subscribeProfitDetailStore(state: ProfitDetailState, initState: ReturnType<typeof hotStore.getState>): void {
  let prevSellRef = initState.sellHistory
  let prevBuyRef = initState.buyHistory
  let prevDailySummaryRef = initState.dailySummary
  let prevSectorStocksRef = initState.sectorStocks
  state.mounted = true

  state.unsubStore = hotStore.subscribe((curr) => {
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const summaryChanged = curr.dailySummary !== prevDailySummaryRef
    const sectorStocksChanged = curr.sectorStocks !== prevSectorStocksRef

    if (!historyChanged && !summaryChanged && !sectorStocksChanged) return

    if (historyChanged) {
      prevSellRef = curr.sellHistory
      prevBuyRef = curr.buyHistory
      state.sellHistory = curr.sellHistory
      state.buyHistory = curr.buyHistory
      state.dirtyHistory = true
    }
    if (summaryChanged) {
      prevDailySummaryRef = curr.dailySummary
      state.dirtySummary = true
    }
    if (sectorStocksChanged) {
      prevSectorStocksRef = curr.sectorStocks
      state.dirtySectorStocks = true
    }

    if (state.rafId !== null) return
    state.rafId = requestAnimationFrame(() => flushDirtyRender(state))
  })
}

/* ── SummaryCardEls / DateRangeInputApi 타입 re-export (사용처 호환) ── */
export type { SummaryCardEls, DateRangeInputApi }
