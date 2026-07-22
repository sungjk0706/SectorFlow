// frontend/src/pages/profit-overview.ts
// 수익현황 페이지 — Vanilla TS PageModule
// 요약 대시보드: 일별 수익률 차트(좌상) + 업종별 수익 도넛 차트(좌하) + 계좌 현황(우) + 상세 분석 보기 버튼
//
// 파일 분할 (F-05, P24 단순성):
// - profit-overview.ts (메인): 상태 객체 + mount/unmount + export default
// - profit-overview-date.ts: 날짜 범위 localStorage 영속화
// - profit-overview-sector-pnl.ts: 업종별 종목 수익 렌더 + 섹션 구성
// - profit-overview-mount.ts: mount 헬퍼 함수들 (차트/계좌/구독)

import { createCardTitle } from '../components/common/card-title'
import { COLOR } from '../components/common/ui-styles'
import { globalSettingsManager } from '../settings'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import type { ProfitChartApi } from '../components/canvas-profit-chart'
import type { SectorDonutApi } from '../components/canvas-sector-donut'
import type { AccountSnapshot } from '../types'
import { filterTradeRows } from './profit-shared'
import { initDateRange } from './profit-overview-date'
import {
  renderAccountVals,
  refreshFilteredViews,
  buildLeftColumn,
  buildAccountPanel,
  buildLowerSection,
  buildProfitChart,
  buildDonutChart,
  subscribeProfitOverviewStore,
} from './profit-overview-mount'

/* ── 상태 객체 (P10 SSOT — 모든 가변 상태를 단일 소스로 관리) ── */

export interface ProfitOverviewState {
  // 차트
  chart: ProfitChartApi | null
  donutChart: SectorDonutApi | null
  // 계좌 현황 refs
  accountValRefs: HTMLSpanElement[]
  testAccountValRefs: HTMLSpanElement[]
  holdingCountSpan: HTMLSpanElement | null
  holdingCountSpanTest: HTMLSpanElement | null
  realAccountContainer: HTMLDivElement | null
  testAccountContainer: HTMLDivElement | null
  // 업종별 종목 수익
  sectorStockListContainer: HTMLDivElement | null
  expandToggleBtn: HTMLButtonElement | null
  allExpanded: boolean
  activeSector: string | null
  // 이력
  buyHistory: Record<string, unknown>[]
  sellHistory: Record<string, unknown>[]
  filteredSellHistory: Record<string, unknown>[]
  // rAF 배칭
  rafId: number | null
  mounted: boolean
  dirtyAccount: boolean
  dirtyHistory: boolean
  dirtyChart: boolean
  // applyDateRange 레이스 가드 시퀀스 (P19)
  applyDateRangeSeq: number
  // hotStore 구독
  unsubStore: (() => void) | null
  onRealDataTick: ((e: Event) => void) | null
  // hotStore 구독용 이전 상태 참조 (변경 감지)
  prevSellRef: Record<string, unknown>[]
  prevBuyRef: Record<string, unknown>[]
  prevDailySummaryRef: Record<string, unknown>[]
  prevAccountRef: AccountSnapshot | null
  prevPositionsRef: unknown[]
  prevTradeMode: string | undefined
}

function createState(): ProfitOverviewState {
  return {
    chart: null,
    donutChart: null,
    accountValRefs: [],
    testAccountValRefs: [],
    holdingCountSpan: null,
    holdingCountSpanTest: null,
    realAccountContainer: null,
    testAccountContainer: null,
    sectorStockListContainer: null,
    expandToggleBtn: null,
    allExpanded: true,
    activeSector: null,
    buyHistory: [],
    sellHistory: [],
    filteredSellHistory: [],
    rafId: null,
    mounted: false,
    dirtyAccount: false,
    dirtyHistory: false,
    dirtyChart: false,
    applyDateRangeSeq: 0,
    unsubStore: null,
    onRealDataTick: null,
    prevSellRef: [],
    prevBuyRef: [],
    prevDailySummaryRef: [],
    prevAccountRef: null,
    prevPositionsRef: [],
    prevTradeMode: undefined,
  }
}

const state: ProfitOverviewState = createState()

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-overview')
  state.buyHistory = []
  state.sellHistory = []
  state.accountValRefs = []

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  root.appendChild(createCardTitle('수익현황'))

  const settings = globalSettingsManager.getSettings()
  const isTestMode = settings?.trade_mode === 'test'

  // 상단: 좌측 차트 2개 + 우측 계좌 현황
  const upper = document.createElement('div')
  Object.assign(upper.style, { flex: '1', borderBottom: '1px solid ' + COLOR.borderDark, overflow: 'hidden', display: 'flex', gap: '8px' })
  const { leftColumn, chartContainer, donutChartContainer } = buildLeftColumn()
  const accountPanel = buildAccountPanel(state, isTestMode)
  upper.appendChild(leftColumn)
  upper.appendChild(accountPanel)
  root.appendChild(upper)

  // 하단: 상세 분석 보기 버튼
  root.appendChild(buildLowerSection())
  container.appendChild(root)

  // 날짜 범위 초기화 — localStorage 로드 후 hotStore에 보장 (차트 생성 전 실행)
  const saved = initDateRange()

  // 일별 수익률 차트 생성 + 초기 데이터 조회
  const { profitDateFrom: storedFrom, profitDateTo: storedTo } = hotStore.getState()
  buildProfitChart(state, chartContainer, storedFrom, storedTo, saved)

  // 초기 데이터 반영 — 도넛 차트 생성 전 filteredSellHistory 선할당
  const initState = hotStore.getState()
  state.sellHistory = initState.sellHistory
  state.buyHistory = initState.buyHistory
  state.filteredSellHistory = filterTradeRows(state.sellHistory, initState.profitDateFrom, initState.profitDateTo)

  // 업종별 수익 도넛 차트 생성
  buildDonutChart(state, donutChartContainer)
  refreshFilteredViews(state)

  // hotStore 구독 + 실시간 틱 핸들러
  subscribeProfitOverviewStore(state, initState)

  renderAccountVals(state)
}

/* ── unmount ── */
function unmount(): void {
  state.mounted = false
  notifyPageInactive('profit-overview')
  if (state.rafId !== null) { cancelAnimationFrame(state.rafId); state.rafId = null }
  state.dirtyAccount = false
  state.dirtyHistory = false
  state.dirtyChart = false
  if (state.unsubStore) { state.unsubStore(); state.unsubStore = null }
  if (state.onRealDataTick) { window.removeEventListener('real-data-tick', state.onRealDataTick); state.onRealDataTick = null }
  if (state.chart) { state.chart.destroy(); state.chart = null }
  if (state.donutChart) { state.donutChart.destroy(); state.donutChart = null }
  Object.assign(state, createState())
}

export default { mount, unmount }
