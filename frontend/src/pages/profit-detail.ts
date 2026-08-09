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
import { createTabBar } from '../components/common/button'
import { createSearchInput } from '../components/common/search-input'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import type { DataTableApi } from '../components/common/data-table'
import type { DateRangeInputApi } from '../components/common/date-range-input'
import { type SummaryCardEls } from './profit-shared'
import { getTradingToday } from '../utils/date'
import {
  buildSummaryRow,
  buildFilterRow,
  buildTabRow,
  buildTableContainer,
  buildStatRow,
  restoreInitialView,
  subscribeProfitDetailStore,
} from './profit-detail-mount'

/* ── 모듈 변수 ── */
type LowerTab = 'buy' | 'sell'
export type SelectedView = 'today' | 'fiveday' | 'month' | 'total' | null

/* ── 1프레임 내 필터 결과 재사용 캐시 (P24 단순성 — filterTradeRows 중복 연산 방지) ── */
interface FilterCache {
  sellRef: Record<string, unknown>[]  // 캐시 유효성 검증용 sellHistory 참조
  buyRef: Record<string, unknown>[]   // 캐시 유효성 검증용 buyHistory 참조
  from: string
  to: string
  query: string
  view: SelectedView
  sells: Record<string, unknown>[]    // 필터링된 매도 내역
  buys: Record<string, unknown>[]     // 필터링된 매수 내역
}

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
  // 필터 refs
  dateRangeInput: DateRangeInputApi | null
  stockFilterInput: ReturnType<typeof createSearchInput> | null
  unsubStore: (() => void) | null
  unsubUiStore: (() => void) | null
  tabRow: HTMLDivElement | null
  // 뷰 선택
  selectedView: SelectedView
  // 요약 카드 refs
  summaryCardEls: SummaryCardEls | null
  // 통계 정보 DOM 참조
  statCountEl: HTMLSpanElement | null
  statBuyAmtEl: HTMLSpanElement | null
  statSellAmtEl: HTMLSpanElement | null
  statPnlEl: HTMLSpanElement | null
  statAvgRateEl: HTMLSpanElement | null
  // 하단 통계 카드 라벨 요소 (기간 접두사 동적 반영용)
  statLabelEls: HTMLSpanElement[]
  // 하단 통계 카드 색상 연동
  statCardEls: HTMLDivElement[]
  // rAF 배칭 상태
  rafId: number | null
  mounted: boolean
  dirtyHistory: boolean
  dirtySummary: boolean
  dirtyMasterStocks: boolean
  // 1프레임 내 필터 결과 재사용 (filterTradeRows 중복 연산 방지 — P24 단순성)
  filterCache: FilterCache | null
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
    dateRangeInput: null,
    stockFilterInput: null,
    unsubStore: null,
    unsubUiStore: null,
    tabRow: null,
    selectedView: null,
    summaryCardEls: null,
    statCountEl: null,
    statBuyAmtEl: null,
    statSellAmtEl: null,
    statPnlEl: null,
    statAvgRateEl: null,
    statLabelEls: [],
    statCardEls: [],
    rafId: null,
    mounted: false,
    dirtyHistory: false,
    dirtySummary: false,
    dirtyMasterStocks: false,
    filterCache: null,
  }
}

const state: ProfitDetailState = createState()

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-detail')
  state.buyHistory = []
  state.sellHistory = []
  state.activeTab = 'sell'

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  root.appendChild(createCardTitle('수익상세'))

  const todayStr = getTradingToday()
  const monthStart = todayStr ? `${todayStr.slice(0, 7)}-01` : ''

  root.appendChild(buildSummaryRow(state))

  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', minHeight: '0', overflow: 'hidden', display: 'flex', flexDirection: 'column' })
  lower.appendChild(buildFilterRow(state, monthStart, todayStr))
  lower.appendChild(buildTabRow(state))
  lower.appendChild(buildTableContainer(state))
  lower.appendChild(buildStatRow(state))
  root.appendChild(lower)
  container.appendChild(root)

  const initState = hotStore.getState()
  restoreInitialView(state, initState)
  subscribeProfitDetailStore(state, initState)
  // 초기 자료는 서버가 profit-detail-snapshot 이벤트로 전송 — binding.ts가 store에 적용.
  // 페이지 진입 시 별도 HTTP 조회를 하지 않고 store 구독으로 자동 갱신.
}

/* ── unmount ── */
function unmount(): void {
  state.mounted = false
  notifyPageInactive('profit-detail')
  if (state.rafId !== null) { cancelAnimationFrame(state.rafId); state.rafId = null }
  state.dirtyHistory = false
  state.dirtySummary = false
  state.dirtyMasterStocks = false
  if (state.unsubStore) { state.unsubStore(); state.unsubStore = null }
  if (state.unsubUiStore) { state.unsubUiStore(); state.unsubUiStore = null }
  if (state.sellTable) { state.sellTable.destroy(); state.sellTable = null }
  if (state.buyTable) { state.buyTable.destroy(); state.buyTable = null }
  Object.assign(state, createState())
}

export default { mount, unmount }
