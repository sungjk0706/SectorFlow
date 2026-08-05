// frontend/src/pages/profit-detail-mount.ts
// 수익 상세 페이지 — mount 헬퍼 함수들 + 초기화 + rAF/구독 (F-05 분할).
// 카드 클릭 시 테이블 필터링 + 선택 강조 표시 (팝업/드릴다운 모달 없음 — P24 단순성).

import { FONT_SIZE, COLOR, RADIUS, SHADOW } from '../components/common/ui-styles'
import { createSearchInput } from '../components/common/search-input'
import { createTabBar } from '../components/common/button'
import { createDateRangeInput, type DateRangeInputApi } from '../components/common/date-range-input'
import { hotStore } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { globalSettingsManager } from '../settings'
import {
  type SummaryCardEls,
  createSummaryCards,
  updateSummaryCards,
} from './profit-shared'
import { getRecent5TradingDays } from './profit-math'
import { getTradingToday } from '../utils/date'
import { loadProfitDetailView } from './profit-detail-view'
import {
  showTable,
  filterByDate,
  filterByDateRange,
  updateCardSelection,
  updateTabLabels,
  persistViewState,
} from './profit-detail-display'
import type { ProfitDetailState, SelectedView } from './profit-detail'

/* ── mount 헬퍼: 요약 카드 행 (당일/5거래일/당월/누적 손익 — 클릭 시 테이블 필터 + 강조, 팝업 없음) ── */
export function buildSummaryRow(state: ProfitDetailState): HTMLDivElement {
  const summaryRow = document.createElement('div')
  Object.assign(summaryRow.style, { display: 'flex', gap: '8px', padding: '8px 4px', flex: 'none', borderBottom: '1px solid ' + COLOR.borderDark })

  state.summaryCardEls = createSummaryCards(summaryRow, {
    onTodayClick: () => {
      state.selectedView = 'today'
      updateCardSelection(state)
      filterByDate(state, getTradingToday())
      persistViewState(state)
    },
    onFivedayClick: () => {
      state.selectedView = 'fiveday'
      updateCardSelection(state)
      // 최근 5거래일 날짜 범위로 테이블 필터링 (P10 SSOT — getRecent5TradingDays 공유)
      const recent5 = getRecent5TradingDays(hotStore.getState().dailySummary)
      if (recent5.length > 0) {
        const from = recent5[recent5.length - 1]
        const to = recent5[0]
        filterByDateRange(state, from, to)
      } else {
        // 5거래일 데이터가 없으면 빈 범위로 테이블 표시
        filterByDateRange(state, '', '')
      }
      persistViewState(state)
    },
    onMonthClick: () => {
      state.selectedView = 'month'
      updateCardSelection(state)
      const today = getTradingToday()
      const currentMonthStart = today ? `${today.slice(0, 7)}-01` : ''
      const currentMonthEnd = today ? `${today.slice(0, 7)}-31` : ''
      filterByDateRange(state, currentMonthStart, currentMonthEnd)
      persistViewState(state)
    },
    onTotalClick: () => {
      state.selectedView = 'total'
      updateCardSelection(state)
      if (state.dateRangeInput) state.dateRangeInput.setValue('', '')
      showTable(state)
      updateTabLabels(state)
      persistViewState(state)
    },
  })

  return summaryRow
}

/* ── mount 헬퍼: 필터 행 (날짜 범위 + 종목 검색 — 드릴다운 토글 제거, 다단계 1세션 결정 2) ── */
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
      showTable(state)
      updateTabLabels(state)
      persistViewState(state)
    },
  })
  filterRow.appendChild(state.dateRangeInput.el)

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

/* ── mount 헬퍼: 테이블 컨테이너 (단일 상자 — 2단 겹침 단순화, 결정 5) ── */
export function buildTableContainer(state: ProfitDetailState): HTMLDivElement {
  // 이전: tableContainer → tableViewContainer 2단 겹침.
  // 단순화: tableViewContainer만 단일 상자로 사용 (높이 전파 체인 짧게).
  state.tableViewContainer = document.createElement('div')
  Object.assign(state.tableViewContainer.style, {
    display: 'flex',
    flexDirection: 'column',
    flex: '1',
    minHeight: '0',
    padding: '0 4px',
    overflow: 'hidden',
  })
  state.tableContainer = state.tableViewContainer
  return state.tableViewContainer
}

/* ── mount 헬퍼: 통계 정보 행 (총 건수/매수금액/매도금액/실현손익/수익률/승률) ── */
export function buildStatRow(state: ProfitDetailState): HTMLDivElement {
  const statRow = document.createElement('div')
  Object.assign(statRow.style, { display: 'flex', gap: '8px', padding: '6px 4px', borderTop: '1px solid ' + COLOR.borderLight, flex: 'none' })

  const STAT_STYLE = `flex:1;background:${COLOR.surfaceLight};border:1px solid ${COLOR.borderLight};border-radius:${RADIUS.xs};box-shadow:${SHADOW.card};padding:4px 8px;display:flex;flex-direction:column;align-items:center;gap:2px;`
  // 기본 라벨(접두사 없음) — 기간 카드 선택 시 updateStatLabels가 접두사를 붙임.
  const STAT_LABELS = ['총 건수', '매수 지출(수수료 포함)', '매도 수령(실수령)', '실현손익', '실현 수익률', '승률']
  const statEls: HTMLSpanElement[] = []
  state.statCardEls = []
  state.statLabelEls = []

  for (let i = 0; i < 6; i++) {
    // P25: 카드 단위 격리 — 한 카드 생성 throw 시 다음 카드 계속 렌더링.
    // statEls/statCardEls/statLabelEls push는 인덱스 기반(state.statCountEl = statEls[0] 등)이므로
    // 더미 push로 인덱스 정합성 유지 (P22). buildSummaryCard 패턴과 일치 (P23).
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
      state.statLabelEls.push(labelEl)
    } catch (e) {
      console.error('[profit-detail] stat card build error', e)
      const dummyVal = document.createElement('span')
      dummyVal.textContent = '-'
      statEls.push(dummyVal)
      const dummyCard = document.createElement('div')
      state.statCardEls.push(dummyCard)
      const dummyLabel = document.createElement('span')
      state.statLabelEls.push(dummyLabel)
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

/* ── 자동 기간 선택의 현재 거래일 기준 범위 ── */
export function getAutomaticDateRange(
  selectedView: SelectedView,
  today: string,
  dailySummary: Record<string, unknown>[],
): { from: string; to: string } | null {
  if (selectedView === 'today') {
    return { from: today, to: today }
  }
  if (selectedView === 'month') {
    if (!today) return { from: '', to: '' }
    return { from: `${today.slice(0, 7)}-01`, to: `${today.slice(0, 7)}-31` }
  }
  if (selectedView === 'fiveday') {
    const recent5 = getRecent5TradingDays(dailySummary)
    return recent5.length > 0
      ? { from: recent5[recent5.length - 1], to: recent5[0] }
      : { from: '', to: '' }
  }
  if (selectedView === 'total') {
    return { from: '', to: '' }
  }
  return null
}

function getAutomaticRange(state: ProfitDetailState): { from: string; to: string } | null {
  return getAutomaticDateRange(state.selectedView, getTradingToday(), hotStore.getState().dailySummary)
}

function syncAutomaticRange(state: ProfitDetailState): boolean {
  const range = getAutomaticRange(state)
  if (!range || !state.dateRangeInput) return false
  const current = state.dateRangeInput.getValue()
  if (current.from === range.from && current.to === range.to) return false
  state.dateRangeInput.setValue(range.from, range.to)
  state.filterCache = null
  return true
}

/* ── mount 헬퍼: 초기 데이터 반영 + 저장된 뷰 상태 복원 ── */
export function restoreInitialView(state: ProfitDetailState, initState: ReturnType<typeof hotStore.getState>): void {
  state.sellHistory = initState.sellHistory
  state.buyHistory = initState.buyHistory
  updateTabLabels(state)

  // 저장된 빠른 선택은 날짜가 아니라 선택 의미를 복원하고 현재 거래일로 재계산.
  const savedView = loadProfitDetailView()
  if (savedView) {
    state.selectedView = savedView.selectedView
    if (state.selectedView === null) {
      if (state.dateRangeInput) state.dateRangeInput.setValue(savedView.from, savedView.to)
    } else {
      syncAutomaticRange(state)
      persistViewState(state)
    }
    updateCardSelection(state)
    showTable(state)
    updateTabLabels(state)
  } else {
    state.selectedView = 'today'
    syncAutomaticRange(state)
    updateCardSelection(state)
    showTable(state)
    updateTabLabels(state)
  }
  if (state.summaryCardEls) {
    updateSummaryCards(
      initState.dailySummary, state.summaryCardEls,
      state.sellHistory,
      globalSettingsManager.getSettings()?.trade_mode === 'test',
    )
  }
}

/* ── mount 헬퍼: rAF 배칭 렌더 (dirty 플래그 기반 selective update) ── */
function flushDirtyRender(state: ProfitDetailState): void {
  state.rafId = null
  if (!state.mounted) return

  // dirtyHistory 선소미: history 변경 시 summary도 함께 갱신되므로 dirtySummary를 선소미하여
  // updateSummaryCards 중복 호출 방지 (한 프레임당 1회 보장 — P24 단순성).
  const needSummary = state.dirtyHistory || state.dirtySummary

  if (state.dirtyHistory) {
    state.dirtyHistory = false
    state.dirtySummary = false  // history 변경이 summary 갱신을 내포 — 선소미
    showTable(state)
    updateTabLabels(state)
  }

  if (state.dirtySummary) {
    state.dirtySummary = false
  }

  if (needSummary && state.summaryCardEls) {
    const hotState = hotStore.getState()
    updateSummaryCards(
      hotState.dailySummary, state.summaryCardEls,
      state.sellHistory,
      globalSettingsManager.getSettings()?.trade_mode === 'test',
    )
  }

  if (state.dirtyMasterStocks) {
    state.dirtyMasterStocks = false
    showTable(state)
  }
}

/* ── mount 헬퍼: hotStore 구독 (rAF 배칭 + selective update) ── */
export function subscribeProfitDetailStore(state: ProfitDetailState, initState: ReturnType<typeof hotStore.getState>): void {
  let prevSellRef = initState.sellHistory
  let prevBuyRef = initState.buyHistory
  let prevDailySummaryRef = initState.dailySummary
  let prevMasterStocksRef = initState.masterStocks
  state.mounted = true

  state.unsubStore = hotStore.subscribe((curr) => {
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const summaryChanged = curr.dailySummary !== prevDailySummaryRef
    const masterStocksChanged = curr.masterStocks !== prevMasterStocksRef

    if (!historyChanged && !summaryChanged && !masterStocksChanged) return

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
      if (state.selectedView === 'fiveday') {
        syncAutomaticRange(state)
        state.dirtyHistory = true
      }
    }
    if (masterStocksChanged) {
      prevMasterStocksRef = curr.masterStocks
      state.dirtyMasterStocks = true
    }

    if (state.rafId !== null) return
    state.rafId = requestAnimationFrame(() => flushDirtyRender(state))
  })

  // marketPhase 구독 — chart_reference_trading_day 변화 시 요약 카드 재렌더링 (P16 살아있는 경로).
  // 08:00 KST 전환 시 백엔드가 새 거래일로 갱신 → 당일 카드 자동 반영 (페이지 새로고침 불필요).
  let prevRefDay = uiStore.getState().marketPhase.chart_reference_trading_day
  state.unsubUiStore = uiStore.subscribe((uiCurr) => {
    const refDayChanged = uiCurr.marketPhase.chart_reference_trading_day !== prevRefDay
    if (!refDayChanged) return
    prevRefDay = uiCurr.marketPhase.chart_reference_trading_day
    state.dirtySummary = true
    if (state.selectedView !== null && syncAutomaticRange(state)) {
      state.dirtyHistory = true
    }
    if (state.rafId !== null) return
    state.rafId = requestAnimationFrame(() => flushDirtyRender(state))
  })
}

/* ── SummaryCardEls / DateRangeInputApi 타입 re-export (사용처 호환) ── */
export type { SummaryCardEls, DateRangeInputApi }
