// frontend/src/pages/profit-detail.ts
// 수익 상세 페이지 — Vanilla TS PageModule
// 차트(크게) + 드릴다운 + 날짜/종목 필터 + 전체 거래내역(가상 스크롤) + 통계 정보
//
// 파일 분할 (F-05, P24 단순성):
// - profit-detail.ts (메인): 상태 객체 + mount/unmount + export default
// - profit-detail-view.ts: 뷰 상태 localStorage 영속화
// - profit-detail-display.ts: 카드/탭/드릴다운/테이블 표시
// - profit-detail-mount.ts: mount 헬퍼 함수들 + 초기화 + rAF/구독

import { createCardTitle } from '../components/common/card-title'
import { createTabBar, createToggleSelectBtn } from '../components/common/button'
import { createSearchInput } from '../components/common/search-input'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import type { DataTableApi } from '../components/common/data-table'
import type { DateRangeInputApi } from '../components/common/date-range-input'
import { type DailyDrilldownRow, type SummaryCardEls, getLocalToday } from './profit-shared'
import {
  buildSummaryRow,
  buildFilterRow,
  buildTabRow,
  buildTableContainer,
  buildStatRow,
  restoreInitialView,
  ensureMonthlyDailySummary,
  subscribeProfitDetailStore,
} from './profit-detail-mount'

/* ── 모듈 변수 ── */
export type LowerTab = 'buy' | 'sell'
export type SelectedView = 'today' | 'prev' | 'month' | 'total' | 'drilldown' | null

/* ── 상태 객체 (P10 SSOT — 모든 가변 상태를 단일 소스로 관리) ── */

export interface ProfitDetailState {
  // 이력
  buyHistory: Record<string, unknown>[]
  sellHistory: Record<string, unknown>[]
  // 탭
  activeTab: LowerTab
  // 테이블 refs
  sellTable: DataTableApi<Record<string, unknown>> | null
  buyTable: DataTableApi<Record<string, unknown>> | null
  sellTabBtn: HTMLButtonElement | null
  buyTabBtn: HTMLButtonElement | null
  tabBarHandle: ReturnType<typeof createTabBar> | null
  tableContainer: HTMLDivElement | null
  tableViewContainer: HTMLDivElement | null
  drilldownViewContainer: HTMLDivElement | null
  // 필터 refs
  dateRangeInput: DateRangeInputApi | null
  stockFilterInput: ReturnType<typeof createSearchInput> | null
  unsubStore: (() => void) | null
  // 드릴다운 상태
  drilldownActive: boolean
  drilldownTable: DataTableApi<DailyDrilldownRow> | null
  tabRow: HTMLDivElement | null
  drilldownBtnHandle: ReturnType<typeof createToggleSelectBtn> | null
  // 뷰 선택
  selectedView: SelectedView
  // 요약 카드 refs
  summaryCardEls: SummaryCardEls | null
  // 통계 정보 DOM 참조
  statCountEl: HTMLSpanElement | null
  statBuyAmtEl: HTMLSpanElement | null
  statSellAmtEl: HTMLSpanElement | null
  statPnlEl: HTMLSpanElement | null
  statWinRateEl: HTMLSpanElement | null
  statAvgRateEl: HTMLSpanElement | null
  // 하단 통계 카드 색상 연동
  statCardEls: HTMLDivElement[]
  // rAF 배칭 상태
  rafId: number | null
  mounted: boolean
  dirtyHistory: boolean
  dirtySummary: boolean
  dirtySectorStocks: boolean
}

function createState(): ProfitDetailState {
  return {
    buyHistory: [],
    sellHistory: [],
    activeTab: 'sell',
    sellTable: null,
    buyTable: null,
    sellTabBtn: null,
    buyTabBtn: null,
    tabBarHandle: null,
    tableContainer: null,
    tableViewContainer: null,
    drilldownViewContainer: null,
    dateRangeInput: null,
    stockFilterInput: null,
    unsubStore: null,
    drilldownActive: true,
    drilldownTable: null,
    tabRow: null,
    drilldownBtnHandle: null,
    selectedView: null,
    summaryCardEls: null,
    statCountEl: null,
    statBuyAmtEl: null,
    statSellAmtEl: null,
    statPnlEl: null,
    statWinRateEl: null,
    statAvgRateEl: null,
    statCardEls: [],
    rafId: null,
    mounted: false,
    dirtyHistory: false,
    dirtySummary: false,
    dirtySectorStocks: false,
  }
}

const state: ProfitDetailState = createState()

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-detail')
  state.buyHistory = []
  state.sellHistory = []
  state.activeTab = 'sell'
  state.drilldownActive = true

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  root.appendChild(createCardTitle('수익 상세'))

  const todayStr = getLocalToday()
  const monthStart = todayStr.slice(0, 8) + '01'
  const monthEnd = todayStr.slice(0, 8) + '31'

  root.appendChild(buildSummaryRow(state, todayStr, monthStart, monthEnd))

  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', overflow: 'auto', display: 'flex', flexDirection: 'column' })
  lower.appendChild(buildFilterRow(state, monthStart, todayStr))
  lower.appendChild(buildTabRow(state))
  lower.appendChild(buildTableContainer(state))
  lower.appendChild(buildStatRow(state))
  root.appendChild(lower)
  container.appendChild(root)

  const initState = hotStore.getState()
  restoreInitialView(state, todayStr, initState)
  ensureMonthlyDailySummary(state, todayStr)
  subscribeProfitDetailStore(state, initState)
}

/* ── unmount ── */
function unmount(): void {
  state.mounted = false
  notifyPageInactive('profit-detail')
  if (state.rafId !== null) { cancelAnimationFrame(state.rafId); state.rafId = null }
  state.dirtyHistory = false
  state.dirtySummary = false
  state.dirtySectorStocks = false
  if (state.unsubStore) { state.unsubStore(); state.unsubStore = null }
  if (state.sellTable) { state.sellTable.destroy(); state.sellTable = null }
  if (state.buyTable) { state.buyTable.destroy(); state.buyTable = null }
  if (state.drilldownTable) { state.drilldownTable.destroy(); state.drilldownTable = null }
  Object.assign(state, createState())
}

export default { mount, unmount }
