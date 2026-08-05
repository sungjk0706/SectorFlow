// frontend/src/pages/profit-overview.ts
// 수익현황 페이지 — Vanilla TS PageModule
// 요약 대시보드: 거래일별 수익률 차트(좌상) + 업종별 수익 도넛 차트(좌하) + 계좌 현황(우) + 상세 분석 보기 버튼
//
// 파일 분할 (F-05, P24 단순성):
// - profit-overview.ts (메인): 상태 객체 + mount/unmount + export default
// - profit-overview-date.ts: 날짜 범위 localStorage 영속화
// - profit-overview-sector-pnl.ts: 업종별 종목 수익 렌더 + 섹션 구성
// - profit-overview-mount.ts: mount 헬퍼 함수들 (차트/계좌/구독)

import { createCardTitle } from '../components/common/card-title'
import { COLOR } from '../components/common/ui-styles'
import { globalSettingsManager } from '../settings'
import { hotStore, applyAccountSnapshot, applyPositionsSnapshot } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import { refreshPageData, createPageRefreshStatus } from '../utils/page-refresh'
import type { ProfitChartApi } from '../components/canvas-profit-chart'
import type { SectorDonutApi } from '../components/canvas-sector-donut'
import type { AccountSnapshot } from '../types'
import { filterTradeRows } from './profit-math'
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
  // 업종별 종목 수익 섹션 타이틀 중앙 요약 refs (기간 라벨 + 총손익 + 수익률 — 도넛 중앙과 동일 SSOT, P10/P21)
  sectorSummaryLabelRef: HTMLSpanElement | null
  sectorSummaryPnlRef: HTMLSpanElement | null
  sectorSummaryRateRef: HTMLSpanElement | null
  // 이력
  buyHistory: Record<string, unknown>[]
  sellHistory: Record<string, unknown>[]
  filteredSellHistory: Record<string, unknown>[]
  // dailySummary 명시적 분리 (3단계 — 차트 범위 이슈 방지):
  // - chartDailySummary: 차트 데이터 전용 (사용자 선택 날짜 범위의 dailySummary)
  // - analysisDailySummary: 분석(도넛 중앙 손익·계좌 현황 분모)용 — hotStore 동기화
  //   기존 localDailySummary가 두 용도에 공용되어 차트 범위와 분석 범위가 혼재될 위험 제거
  chartDailySummary: Record<string, unknown>[]
  analysisDailySummary: Record<string, unknown>[]
  // 페이지 로컬 날짜 범위 (P10 SSOT — 공유 store 오염 방지)
  localDateFrom: string
  localDateTo: string
  localQuickLabel: string | undefined
  localRangeMode: import('./profit-overview-date').ProfitDateRangeMode
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
  unsubUiStore: (() => void) | null
  onRealDataTick: ((e: Event) => void) | null
  // hotStore 구독용 이전 상태 참조 (변경 감지)
  prevSellRef: Record<string, unknown>[]
  prevBuyRef: Record<string, unknown>[]
  prevDailySummaryRef: Record<string, unknown>[]
  prevAccountRef: AccountSnapshot | null
  prevPositionsRef: unknown[]
  prevMasterStocksRef: Record<string, unknown>
  prevTradeMode: string | undefined
  dataReady: boolean
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
    allExpanded: false,
    activeSector: null,
    sectorSummaryLabelRef: null,
    sectorSummaryPnlRef: null,
    sectorSummaryRateRef: null,
    buyHistory: [],
    sellHistory: [],
    filteredSellHistory: [],
    chartDailySummary: [],
    analysisDailySummary: [],
    localDateFrom: '',
    localDateTo: '',
    localQuickLabel: undefined,
    localRangeMode: 'default',
    rafId: null,
    mounted: false,
    dirtyAccount: false,
    dirtyHistory: false,
    dirtyChart: false,
    applyDateRangeSeq: 0,
    unsubStore: null,
    unsubUiStore: null,
    onRealDataTick: null,
    prevSellRef: [],
    prevBuyRef: [],
    prevDailySummaryRef: [],
    prevAccountRef: null,
    prevPositionsRef: [],
    prevMasterStocksRef: {},
    prevTradeMode: undefined,
    dataReady: false,
  }
}

const state: ProfitOverviewState = createState()
let refreshStatus: ReturnType<typeof createPageRefreshStatus> | null = null

async function refreshProfitOverviewPage(): Promise<void> {
  refreshStatus?.set('최신 데이터 확인 중')
  state.dataReady = false
  const isActive = () => state.mounted
  const results = await Promise.all([
    refreshPageData({
      key: 'profit-overview:account', policy: 'always-fresh', isActive,
      fetcher: async () => api.getAccountSnapshot('profit-overview'),
      apply: (response) => applyAccountSnapshot(response.data, response.freshness!),
    }),
    refreshPageData({
      key: 'profit-overview:positions', policy: 'always-fresh', isActive,
      fetcher: async () => api.getAccountPositions('profit-overview'),
      apply: (response) => applyPositionsSnapshot(response.data, response.freshness!),
    }),
  ])
  if (!state.mounted) return
  if (results.some(result => result.status === 'error')) {
    refreshStatus?.set('최신 데이터를 확인하지 못했습니다')
    return
  }
  state.dataReady = true
  notifyPageActive('profit-overview')
  refreshStatus?.set('', false)
  renderAccountVals(state)
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-overview')
  state.buyHistory = []
  state.sellHistory = []
  state.accountValRefs = []

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })
  root.appendChild(createCardTitle('수익현황'))
  refreshStatus = createPageRefreshStatus()
  root.appendChild(refreshStatus.el)

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

  // 날짜 범위 초기화 — localStorage 로드 → 페이지 로컬 상태에 저장 (차트 생성 전 실행)
  const { saved, from: initFrom, to: initTo } = initDateRange()
  state.localDateFrom = initFrom
  state.localDateTo = initTo
  state.localQuickLabel = saved?.quickLabel
  state.localRangeMode = saved?.mode ?? 'default'

  // 거래일별 수익률 차트 생성 + 초기 데이터 조회
  // chartDailySummary/analysisDailySummary는 WS push 데이터로 초기화 (P10 SSOT — 공유 store = 최근 N거래일)
  const initState = hotStore.getState()
  state.chartDailySummary = initState.dailySummary
  state.analysisDailySummary = initState.dailySummary
  buildProfitChart(state, chartContainer, initFrom, initTo, saved)

  // 초기 데이터 반영 — 도넛 차트 생성 전 filteredSellHistory 선할당
  state.sellHistory = initState.sellHistory
  state.buyHistory = initState.buyHistory
  state.filteredSellHistory = filterTradeRows(state.sellHistory, state.localDateFrom, state.localDateTo)

  // 업종별 수익 도넛 차트 생성
  buildDonutChart(state, donutChartContainer)
  refreshFilteredViews(state)

  // hotStore 구독 + 실시간 틱 핸들러
  subscribeProfitOverviewStore(state, initState)

  // 계좌·보유 스냅샷 확인 전에는 기존 hotStore 값을 계좌 패널에 표시하지 않는다.
  void refreshProfitOverviewPage()
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
  if (state.unsubUiStore) { state.unsubUiStore(); state.unsubUiStore = null }
  if (state.onRealDataTick) { window.removeEventListener('real-data-tick', state.onRealDataTick); state.onRealDataTick = null }
  if (state.chart) { state.chart.destroy(); state.chart = null }
  if (state.donutChart) { state.donutChart.destroy(); state.donutChart = null }
  Object.assign(state, createState())
}

export default { mount, unmount }
