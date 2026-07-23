// frontend/src/pages/profit-overview-mount.ts
// 수익현황 페이지 — mount 헬퍼 함수들 (F-05 분할, P24 단순성)
// profit-overview.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createProfitChart } from '../components/canvas-profit-chart'
import { createSectorDonut } from '../components/canvas-sector-donut'
import { globalSettingsManager } from '../settings'
import { FONT_SIZE, FONT_WEIGHT, COLOR } from '../components/common/ui-styles'
import { createActionButton } from '../components/common/button'
import { sectionTitle } from '../components/common/settings-common'
import { ACCOUNT_LABELS_REAL, ACCOUNT_LABELS_TEST } from '../components/common/account-labels'
import { hotStore, getPositionIndex } from '../stores/hotStore'
import { api } from '../api/client'
import {
  buildChartFromDailySummary,
  renderAccountVals as renderAccountValsShared,
  buildSectorDonutRows,
  filterTradeRows,
  getLocalToday,
  type AccountValsParams,
} from './profit-shared'
import { saveProfitDateRange, type ProfitDateRange } from './profit-overview-date'
import { renderSectorStockPnl, updateExpandToggleBtn, buildStockListSection } from './profit-overview-sector-pnl'
import type { ProfitOverviewState } from './profit-overview'

/* ── 헬퍼 ── */

const ROW_CSS = `display:flex;justify-content:space-between;padding:10px 4px;border-bottom:1px solid ${COLOR.hoverBg};font-size:${FONT_SIZE.body};`

/* ── 계좌 현황 렌더 (shared 순수 함수 래핑) ── */

export function renderAccountVals(state: ProfitOverviewState): void {
  const hotState = hotStore.getState()
  const settings = globalSettingsManager.getSettings()
  const params: AccountValsParams = {
    account: hotState.account,
    positions: hotState.positions,
    sectorStocks: hotState.sectorStocks,
    positionCount: hotState.positionCount ?? 0,
    isTestMode: settings?.trade_mode === 'test',
    buyHistory: state.buyHistory,
    sellHistory: state.sellHistory,
    realAccountContainer: state.realAccountContainer,
    testAccountContainer: state.testAccountContainer,
    accountValRefs: state.accountValRefs,
    testAccountValRefs: state.testAccountValRefs,
    holdingCountSpan: state.holdingCountSpan,
    holdingCountSpanTest: state.holdingCountSpanTest,
  }
  renderAccountValsShared(params)
}

/* ── 필터된 뷰 데이터 갱신: 도넛 차트 + 업종별 종목 수익 동시 업데이트 ── */

export function refreshFilteredViews(state: ProfitOverviewState): void {
  const { profitDateFrom, profitDateTo } = hotStore.getState()
  state.filteredSellHistory = filterTradeRows(state.sellHistory, profitDateFrom, profitDateTo)
  state.donutChart?.updateData(buildSectorDonutRows(state.filteredSellHistory))
  renderSectorStockPnl(state)
}

/* ── mount 헬퍼: 좌측 컬럼 (일별 수익률 차트 + 업종별 수익 도넛) ── */

export function buildLeftColumn(): { leftColumn: HTMLDivElement; chartContainer: HTMLDivElement; donutChartContainer: HTMLDivElement } {
  const leftColumn = document.createElement('div')
  Object.assign(leftColumn.style, { flex: '5', minWidth: '0', display: 'flex', flexDirection: 'column', gap: '4px' })

  // 좌측 상단: 일별 수익률 차트
  const chartPanel = document.createElement('div')
  Object.assign(chartPanel.style, { flex: '1', minWidth: '0', overflow: 'hidden', padding: '0 4px' })
  const chartTitle = document.createElement('div')
  Object.assign(chartTitle.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.normal, color: COLOR.down, padding: '10px 0 6px', borderBottom: '2px solid ' + COLOR.borderLight, marginBottom: '8px' })
  const chartTitleText = document.createElement('span')
  chartTitleText.textContent = '일별 수익률'
  chartTitle.appendChild(chartTitleText)
  chartPanel.appendChild(chartTitle)
  const chartContainer = document.createElement('div')
  Object.assign(chartContainer.style, { height: '100%' })
  chartPanel.appendChild(chartContainer)

  // 좌측 하단: 업종별 수익 도넛 차트
  const donutPanel = document.createElement('div')
  Object.assign(donutPanel.style, { flex: '1', minWidth: '0', overflow: 'hidden', padding: '0 4px', display: 'flex', flexDirection: 'column' })
  const donutTitle = document.createElement('div')
  Object.assign(donutTitle.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.normal, color: COLOR.down, padding: '10px 0 6px', borderBottom: '2px solid ' + COLOR.borderLight, marginBottom: '8px' })
  const donutTitleText = document.createElement('span')
  donutTitleText.textContent = '업종별 수익 분포'
  donutTitle.appendChild(donutTitleText)
  donutPanel.appendChild(donutTitle)
  const donutChartContainer = document.createElement('div')
  Object.assign(donutChartContainer.style, { flex: '1', minHeight: '0' })
  donutPanel.appendChild(donutChartContainer)

  leftColumn.appendChild(chartPanel)
  leftColumn.appendChild(donutPanel)
  return { leftColumn, chartContainer, donutChartContainer }
}

/* ── mount 헬퍼: 계좌 현황 행 (실전/테스트 공통 — P23 중복 제거) ── */

function buildAccountRows(
  labels: readonly string[],
  isTestMode: boolean,
  valRefs: HTMLSpanElement[],
  holdingCountTarget: (el: HTMLSpanElement) => void,
): HTMLDivElement {
  const container = document.createElement('div')
  container.style.display = isTestMode ? 'none' : ''
  for (let i = 0; i < labels.length; i++) {
    // P25: 행 단위 격리 — 한 행 생성 throw 시 다음 행 계속 렌더링.
    // valRefs.push(val)은 인덱스 기반(accountValRefs/testAccountValRefs)이므로
    // 실패 시 더미 push로 인덱스 정합성 유지 (P22).
    try {
      const row = document.createElement('div')
      row.style.cssText = ROW_CSS
      if (i % 2 === 1) row.style.backgroundColor = COLOR.zebra
      const label = document.createElement('span')
      if (i === 4) {
        label.appendChild(document.createTextNode('보유 종목 평가금액 ('))
        const cntSpan = document.createElement('span')
        cntSpan.style.color = COLOR.down
        cntSpan.style.fontWeight = 'bold'
        label.appendChild(cntSpan)
        label.appendChild(document.createTextNode('종목)'))
        holdingCountTarget(cntSpan)
      } else {
        label.textContent = labels[i]
      }
      const val = document.createElement('span')
      Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: FONT_SIZE.body })
      row.appendChild(label)
      row.appendChild(val)
      container.appendChild(row)
      valRefs.push(val)
    } catch (e) {
      console.error('[profit-overview] account row build error', e)
      const dummyVal = document.createElement('span')
      dummyVal.textContent = '-'
      valRefs.push(dummyVal)
    }
  }
  return container
}

/* ── mount 헬퍼: 우측 계좌 현황 패널 (실전 + 테스트 + 업종별 종목 수익) ── */

export function buildAccountPanel(state: ProfitOverviewState, isTestMode: boolean): HTMLDivElement {
  const accountPanel = document.createElement('div')
  Object.assign(accountPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px', display: 'flex', flexDirection: 'column' })

  const accountHeader = sectionTitle('계좌 현황')
  accountHeader.style.color = COLOR.down
  accountPanel.appendChild(accountHeader)

  // 실전모드 컨테이너
  state.realAccountContainer = buildAccountRows(
    ACCOUNT_LABELS_REAL, isTestMode, state.accountValRefs,
    (el) => { state.holdingCountSpan = el },
  )
  accountPanel.appendChild(state.realAccountContainer)

  // 테스트모드 컨테이너
  state.testAccountContainer = buildAccountRows(
    ACCOUNT_LABELS_TEST, !isTestMode, state.testAccountValRefs,
    (el) => { state.holdingCountSpanTest = el },
  )
  accountPanel.appendChild(state.testAccountContainer)

  // 업종별 종목 수익 섹션 — 타이틀 + 전체보기 버튼 + 컨테이너
  accountPanel.appendChild(buildStockListSection(state))

  return accountPanel
}

/* ── mount 헬퍼: 하단 상세 분석 보기 버튼 ── */

export function buildLowerSection(): HTMLDivElement {
  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '8px 0' })
  const detailBtn = createActionButton({
    label: '상세 분석 보기 →',
    variant: 'secondary',
    padding: '10px 24px',
    borderRadius: '6px',
    onClick: () => { location.hash = '#/profit-detail' },
  })
  Object.assign(detailBtn.style, {
    fontWeight: FONT_WEIGHT.semibold,
    border: '1px solid ' + COLOR.borderDark,
    background: COLOR.surfaceLight,
    color: COLOR.down,
  })
  lower.appendChild(detailBtn)
  return lower
}

/* ── 날짜 범위 적용 (레이스 가드 — P19: 빠른 연속 클릭 시 구식 응답 덮어쓰기 방지) ── */

export async function applyDateRange(state: ProfitOverviewState, from: string, to: string, days?: number, label?: string): Promise<void> {
  const seq = ++state.applyDateRangeSeq
  try {
    const settings = globalSettingsManager.getSettings()
    const tradeMode = settings?.trade_mode || 'test'
    let actualFrom = from
    let actualTo = to
    const needsRangeFill = !from || !to
    // 직전(days 없음) — 백엔드에서 단일 거래일 조회
    if (needsRangeFill && days === undefined) {
      const prev = await api.getPrevTradingDay()
      if (seq !== state.applyDateRangeSeq) return
      actualFrom = prev.date
      actualTo = prev.date
    }
    const data = await api.getDailySummary(actualFrom, actualTo, tradeMode, days)
    if (seq !== state.applyDateRangeSeq) return
    // days 기반(5일/전체) — 응답 데이터에서 실제 from/to 추출
    if (needsRangeFill && days !== undefined && data.length > 0) {
      actualFrom = String(data[0].date)
      actualTo = String(data[data.length - 1].date)
    }
    // from/to가 빈 문자열이었던 quickRange 버튼 — 입력란에 실제 범위 동기화
    if (needsRangeFill) {
      state.chart?.setDateRange(actualFrom, actualTo, label)
    }
    state.chart?.updateData(buildChartFromDailySummary(data))
    hotStore.setState({ profitDateFrom: actualFrom, profitDateTo: actualTo, dailySummary: data })
    saveProfitDateRange(actualFrom, actualTo, label)
    refreshFilteredViews(state)
  } catch (err) {
    console.error('[profit-overview] daily-summary fetch failed:', err)
  }
}

/* ── mount 헬퍼: 일별 수익률 차트 생성 + 초기 데이터 조회 ── */

export function buildProfitChart(
  state: ProfitOverviewState,
  chartContainer: HTMLDivElement,
  storedFrom: string,
  storedTo: string,
  saved: ProfitDateRange | null,
): void {
  const todayStr = getLocalToday()
  const monthStart = todayStr.slice(0, 8) + '01'
  const quickDateRangesConfig = [
    { label: '당일', from: todayStr, to: todayStr },
    { label: '직전' }, // from/to는 백엔드 조회 후 채움 (주말/공휴일 건너뜀)
    { label: '5일', days: 5 },
    { label: '당월', from: monthStart, to: todayStr },
    { label: '전체', days: 0 },
  ]

  state.chart = createProfitChart({
    container: chartContainer,
    data: buildChartFromDailySummary(hotStore.getState().dailySummary),
    dateFrom: storedFrom,
    dateTo: storedTo,
    quickDateRanges: quickDateRangesConfig,
    initialActiveQuickLabel: saved?.quickLabel,
    onDateRangeChange: (from, to, days, label) => { applyDateRange(state, from, to, days, label) },
  })

  // 초기 차트 데이터 — 저장된 quickLabel이 있으면 해당 버튼 기준 조회, 없으면 from/to로 조회
  if (saved?.quickLabel) {
    const savedQuick = quickDateRangesConfig.find(qr => qr.label === saved.quickLabel)
    if (savedQuick) {
      applyDateRange(state, savedQuick.from ?? '', savedQuick.to ?? '', savedQuick.days, savedQuick.label)
    }
  } else {
    applyDateRange(state, storedFrom, storedTo, undefined, undefined)
  }
}

/* ── mount 헬퍼: 업종별 수익 도넛 차트 생성 (필터링된 데이터로 초기 생성) ── */

export function buildDonutChart(state: ProfitOverviewState, donutChartContainer: HTMLDivElement): void {
  state.donutChart = createSectorDonut({
    container: donutChartContainer,
    data: buildSectorDonutRows(state.filteredSellHistory),
    onSectorClick: (sector: string) => {
      // 좌측 도넛 범례 업종 클릭 → 우측 종목수익 해당 업종으로 스크롤 + 하이라이트
      state.activeSector = sector
      state.allExpanded = false
      updateExpandToggleBtn(state)
      renderSectorStockPnl(state)
      // 렌더 후 해당 업종 요소 찾아 스크롤
      requestAnimationFrame(() => {
        if (!state.sectorStockListContainer) return
        const target = state.sectorStockListContainer.querySelector(`[data-sector="${CSS.escape(sector)}"]`) as HTMLElement | null
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      })
    },
  })
}

/* ── mount 헬퍼: rAF 배칭 렌더 (dirty 플래그 기반 selective update) ── */

export function flushRender(state: ProfitOverviewState): void {
  state.rafId = requestAnimationFrame(() => {
    state.rafId = null
    if (!state.mounted) return

    if (state.dirtyAccount) {
      state.dirtyAccount = false
      renderAccountVals(state)
    }

    if (state.dirtyHistory) {
      state.dirtyHistory = false
      renderAccountVals(state)
      refreshFilteredViews(state)
    }

    if (state.dirtyChart) {
      state.dirtyChart = false
      const latest = hotStore.getState()
      const settings = globalSettingsManager.getSettings()
      const tradeModeChanged = settings?.trade_mode !== state.prevTradeMode
      if (tradeModeChanged) {
        state.chart?.updateData(buildChartFromDailySummary(latest.dailySummary))
      }
      refreshFilteredViews(state)
      if (tradeModeChanged) {
        state.prevTradeMode = settings?.trade_mode
        const isTest = settings?.trade_mode === 'test'
        if (state.realAccountContainer && state.testAccountContainer) {
          state.realAccountContainer.style.display = isTest ? 'none' : ''
          state.testAccountContainer.style.display = isTest ? '' : 'none'
        }
        renderAccountVals(state)
      }
    }
  })
}

/* ── mount 헬퍼: hotStore 구독 + 실시간 틱 핸들러 ── */

export function subscribeProfitOverviewStore(state: ProfitOverviewState, initState: ReturnType<typeof hotStore.getState>): void {
  state.prevSellRef = initState.sellHistory
  state.prevBuyRef = initState.buyHistory
  state.prevDailySummaryRef = initState.dailySummary
  state.prevAccountRef = initState.account
  state.prevTradeMode = globalSettingsManager.getSettings()?.trade_mode
  state.prevPositionsRef = initState.positions
  state.mounted = true

  state.unsubStore = hotStore.subscribe((curr) => {
    const accountChanged = curr.account !== state.prevAccountRef || curr.positions !== state.prevPositionsRef
    const historyChanged = curr.sellHistory !== state.prevSellRef || curr.buyHistory !== state.prevBuyRef
    const chartChanged = curr.dailySummary !== state.prevDailySummaryRef || globalSettingsManager.getSettings()?.trade_mode !== state.prevTradeMode

    if (!accountChanged && !historyChanged && !chartChanged) return

    if (accountChanged) {
      state.prevAccountRef = curr.account
      state.prevPositionsRef = curr.positions
      state.dirtyAccount = true
    }
    if (historyChanged) {
      state.prevSellRef = curr.sellHistory
      state.prevBuyRef = curr.buyHistory
      state.sellHistory = curr.sellHistory
      state.buyHistory = curr.buyHistory
      state.dirtyHistory = true
    }
    if (chartChanged) {
      state.prevDailySummaryRef = curr.dailySummary
      state.prevTradeMode = globalSettingsManager.getSettings()?.trade_mode
      state.dirtyChart = true
    }

    if (state.rafId !== null) return
    flushRender(state)
  })

  // 보유종목 실시간 틱 시 계좌현황 평가손익/수익률 갱신 (개별 종목 행과 동일 소스 — P22 데이터 정합성)
  state.onRealDataTick = (e: Event) => {
    try {
      const code = (e as CustomEvent<string>).detail
      if (getPositionIndex(code) !== undefined) {
        state.dirtyAccount = true
        if (state.rafId === null) flushRender(state)
      }
    } catch (err) {
      console.error('[profit-overview] real-data-tick error', err)
    }
  }
  window.addEventListener('real-data-tick', state.onRealDataTick)
}
