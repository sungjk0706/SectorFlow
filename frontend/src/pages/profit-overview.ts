// frontend/src/pages/profit-overview.ts
// 수익현황 페이지 — Vanilla TS PageModule
// 요약 대시보드: 일별 수익률 차트(좌상) + 업종별 수익 도넛 차트(좌하) + 계좌 현황(우) + 상세 분석 보기 버튼

import { createProfitChart, type ProfitChartApi } from '../components/canvas-profit-chart'
import { createSectorDonut, type SectorDonutApi, type SectorDonutRow } from '../components/canvas-sector-donut'
import { globalSettingsManager } from '../settings'
import { FONT_SIZE, FONT_WEIGHT, COLOR, pnlColor, fmtWon } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { sectionTitle } from '../components/common/settings-common'
import { ACCOUNT_LABELS_REAL, ACCOUNT_LABELS_TEST } from '../components/common/account-labels'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import {
  buildChartFromDailySummary,
  renderAccountVals as renderAccountValsShared,
  buildSectorStockPnl,
  type AccountValsParams,
} from './profit-shared'

/* ── 헬퍼 ── */

const ROW_CSS = `display:flex;justify-content:space-between;padding:10px 4px;border-bottom:1px solid #f0f0f0;font-size:${FONT_SIZE.body};`

/* ── 모듈 변수 ── */
let chart: ProfitChartApi | null = null
let donutChart: SectorDonutApi | null = null
let accountValRefs: HTMLSpanElement[] = []
let testAccountValRefs: HTMLSpanElement[] = []
let holdingCountSpan: HTMLSpanElement | null = null
let holdingCountSpanTest: HTMLSpanElement | null = null
let realAccountContainer: HTMLDivElement | null = null
let testAccountContainer: HTMLDivElement | null = null
let sectorStockListContainer: HTMLDivElement | null = null
let buyHistory: Record<string, unknown>[] = []
let sellHistory: Record<string, unknown>[] = []
let filteredSellHistory: Record<string, unknown>[] = []
let unsubStore: (() => void) | null = null

/* ── rAF 배칭 상태 ── */
let _rafId: number | null = null
let _mounted = false
let _dirtyAccount = false
let _dirtyHistory = false
let _dirtyChart = false

/* ── 계좌 현황 렌더 (shared 순수 함수 래핑) ── */
function renderAccountVals(): void {
  const state = hotStore.getState()
  const settings = globalSettingsManager.getSettings()
  const params: AccountValsParams = {
    account: state.account,
    positionCount: state.positionCount ?? 0,
    isTestMode: settings?.trade_mode === 'test',
    buyHistory,
    sellHistory,
    realAccountContainer,
    testAccountContainer,
    accountValRefs,
    testAccountValRefs,
    holdingCountSpan,
    holdingCountSpanTest,
  }
  renderAccountValsShared(params)
}

/* ── 업종별 종목 수익 렌더 ── */
function renderSectorStockPnl(): void {
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
    // 업종 헤더
    const header = document.createElement('div')
    Object.assign(header.style, {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '8px 4px 4px', borderBottom: '2px solid #eee', marginTop: '8px',
    })
    const sectorName = document.createElement('span')
    Object.assign(sectorName.style, { fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.semibold, color: group.color })
    sectorName.textContent = group.sector
    const sectorPnl = document.createElement('span')
    Object.assign(sectorPnl.style, { fontSize: FONT_SIZE.label, fontWeight: FONT_WEIGHT.normal, color: pnlColor(group.pnl) })
    const sign = group.pnl >= 0 ? '+' : ''
    sectorPnl.textContent = `${sign}${fmtWon(group.pnl)}`
    const sectorRate = document.createElement('span')
    Object.assign(sectorRate.style, { fontSize: FONT_SIZE.label, fontWeight: FONT_WEIGHT.normal, color: pnlColor(group.rate), marginLeft: '8px' })
    const rateSign = group.rate >= 0 ? '+' : ''
    sectorRate.textContent = `${rateSign}${group.rate.toFixed(2)}%`
    header.appendChild(sectorName)
    header.appendChild(sectorPnl)
    header.appendChild(sectorRate)
    sectorStockListContainer.appendChild(header)

    // 종목 행
    for (const stock of group.stocks) {
      const row = document.createElement('div')
      Object.assign(row.style, {
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 4px 6px 12px', borderBottom: '1px solid #f5f5f5',
      })
      // 종목명
      const nameEl = document.createElement('span')
      Object.assign(nameEl.style, { flex: '1', minWidth: '0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: FONT_SIZE.body, fontWeight: FONT_WEIGHT.medium })
      nameEl.textContent = stock.stk_nm

      // 수익금
      const pnlEl = document.createElement('span')
      Object.assign(pnlEl.style, { flex: 'none', width: '90px', textAlign: 'right', fontSize: FONT_SIZE.body, color: pnlColor(stock.realized_pnl) })
      const pnlSign = stock.realized_pnl >= 0 ? '+' : ''
      pnlEl.textContent = `${pnlSign}${stock.realized_pnl.toLocaleString()}원`

      // 수익률
      const rateEl = document.createElement('span')
      Object.assign(rateEl.style, { flex: 'none', width: '60px', textAlign: 'right', fontSize: FONT_SIZE.body, color: pnlColor(stock.pnl_rate) })
      const rateSign = stock.pnl_rate >= 0 ? '+' : ''
      rateEl.textContent = `${rateSign}${stock.pnl_rate.toFixed(2)}%`

      // 매도수량
      const qtyEl = document.createElement('span')
      Object.assign(qtyEl.style, { flex: 'none', width: '55px', textAlign: 'right', fontSize: FONT_SIZE.small, color: COLOR.secondary })
      qtyEl.textContent = `매도 ${stock.qty}주`

      row.appendChild(nameEl)
      row.appendChild(pnlEl)
      row.appendChild(rateEl)
      row.appendChild(qtyEl)
      sectorStockListContainer.appendChild(row)
    }
  }
}

/* ── 도넛 차트 데이터 빌드 (sellHistory → 업종별 손익 + 수익률 집계) ── */
function buildSectorDonutData(sells: Record<string, unknown>[]): SectorDonutRow[] {
  const pnlMap = new Map<string, number>()
  const buyTotalMap = new Map<string, number>()
  for (const r of sells) {
    const sector = String(r.sector ?? '미분류')
    const pnl = Number(r.realized_pnl ?? 0)
    const buyTotal = Number(r.buy_total_amt ?? 0)
    pnlMap.set(sector, (pnlMap.get(sector) ?? 0) + pnl)
    buyTotalMap.set(sector, (buyTotalMap.get(sector) ?? 0) + buyTotal)
  }
  return Array.from(pnlMap.entries()).map(([sector, pnl]) => {
    const buyTotal = buyTotalMap.get(sector) ?? 0
    const rate = buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0
    return { sector, pnl, rate, buyTotal }
  })
}

/* ── 날짜 범위로 sellHistory 필터링 (profit-detail.ts filterRows와 동일 패턴) ── */
function filterSellHistoryByDate(rows: Record<string, unknown>[], from: string, to: string): Record<string, unknown>[] {
  return rows.filter(r => {
    const d = String(r.date ?? '')
    if (from && d < from) return false
    if (to && d > to) return false
    return true
  })
}

/* ── 필터된 뷰 데이터 갱신: 도넛 차트 + 업종별 종목 수익 동시 업데이트 ── */
function refreshFilteredViews(): void {
  const { profitDateFrom, profitDateTo } = hotStore.getState()
  filteredSellHistory = filterSellHistoryByDate(sellHistory, profitDateFrom, profitDateTo)
  donutChart?.updateData(buildSectorDonutData(filteredSellHistory))
  renderSectorStockPnl()
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  notifyPageActive('profit-overview')
  buyHistory = []
  sellHistory = []
  accountValRefs = []

  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  root.appendChild(createCardTitle('수익현황'))

  const settings = globalSettingsManager.getSettings()
  const isTestMode = settings?.trade_mode === 'test'

  /* ── 상단 (남은 공간 채우기) ── */
  const upper = document.createElement('div')
  Object.assign(upper.style, {
    flex: '1',
    borderBottom: '1px solid #ddd',
    overflow: 'hidden',
    display: 'flex',
    gap: '8px',
  })

  // 좌측 컬럼: 차트 2개 세로 배치
  const leftColumn = document.createElement('div')
  Object.assign(leftColumn.style, { flex: '5', minWidth: '0', display: 'flex', flexDirection: 'column', gap: '4px' })

  // 좌측 상단: 일별 수익률 차트
  const chartPanel = document.createElement('div')
  Object.assign(chartPanel.style, { flex: '1', minWidth: '0', overflow: 'hidden', padding: '0 4px' })
  const chartTitle = document.createElement('div')
  Object.assign(chartTitle.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.normal, color: COLOR.down, padding: '10px 0 6px', borderBottom: '2px solid #eee', marginBottom: '8px' })
  const chartTitleText = document.createElement('span')
  chartTitleText.textContent = '일별 수익률'
  const retentionLabel = document.createElement('span')
  Object.assign(retentionLabel.style, { fontSize: '11px', color: COLOR.disabled, fontWeight: 'normal' })
  retentionLabel.textContent = isTestMode ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
  chartTitle.appendChild(chartTitleText)
  chartTitle.appendChild(retentionLabel)
  chartPanel.appendChild(chartTitle)

  const chartContainer = document.createElement('div')
  Object.assign(chartContainer.style, { height: '100%' })
  chartPanel.appendChild(chartContainer)

  // 좌측 하단: 업종별 수익 도넛 차트
  const donutPanel = document.createElement('div')
  Object.assign(donutPanel.style, { flex: '1', minWidth: '0', overflow: 'hidden', padding: '0 4px', display: 'flex', flexDirection: 'column' })
  const donutTitle = document.createElement('div')
  Object.assign(donutTitle.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: FONT_SIZE.section, fontWeight: FONT_WEIGHT.normal, color: COLOR.down, padding: '10px 0 6px', borderBottom: '2px solid #eee', marginBottom: '8px' })
  const donutTitleText = document.createElement('span')
  donutTitleText.textContent = '업종별 수익 분포'
  donutTitle.appendChild(donutTitleText)
  donutPanel.appendChild(donutTitle)
  const donutChartContainer = document.createElement('div')
  Object.assign(donutChartContainer.style, { flex: '1', minHeight: '0' })
  donutPanel.appendChild(donutChartContainer)

  leftColumn.appendChild(chartPanel)
  leftColumn.appendChild(donutPanel)

  // 우측: 계좌 현황 테이블
  const accountPanel = document.createElement('div')
  Object.assign(accountPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px', display: 'flex', flexDirection: 'column' })

  const accountHeader = sectionTitle('계좌 현황')
  accountHeader.style.color = COLOR.down
  accountPanel.appendChild(accountHeader)

  // 실전모드 컨테이너
  realAccountContainer = document.createElement('div')
  realAccountContainer.style.display = isTestMode ? 'none' : ''
  for (let i = 0; i < ACCOUNT_LABELS_REAL.length; i++) {
    const row = document.createElement('div')
    row.style.cssText = ROW_CSS
    if (i % 2 === 1) row.style.backgroundColor = '#f9f9f9'
    const label = document.createElement('span')
    if (i === 4) {
      label.appendChild(document.createTextNode('보유주식 평가금액 ('))
      const cntSpan = document.createElement('span')
      cntSpan.style.color = COLOR.down
      cntSpan.style.fontWeight = 'bold'
      label.appendChild(cntSpan)
      label.appendChild(document.createTextNode('종목)'))
      holdingCountSpan = cntSpan
    } else {
      label.textContent = ACCOUNT_LABELS_REAL[i]
    }
    const val = document.createElement('span')
    Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: FONT_SIZE.body })
    row.appendChild(label)
    row.appendChild(val)
    realAccountContainer.appendChild(row)
    accountValRefs.push(val)
  }
  accountPanel.appendChild(realAccountContainer)

  // 테스트모드 컨테이너
  testAccountContainer = document.createElement('div')
  testAccountContainer.style.display = isTestMode ? '' : 'none'
  for (let i = 0; i < ACCOUNT_LABELS_TEST.length; i++) {
    const row = document.createElement('div')
    row.style.cssText = ROW_CSS
    if (i % 2 === 1) row.style.backgroundColor = '#f9f9f9'
    const label = document.createElement('span')
    if (i === 4) {
      label.appendChild(document.createTextNode('보유주식 평가금액 ('))
      const cntSpan = document.createElement('span')
      cntSpan.style.color = COLOR.down
      cntSpan.style.fontWeight = 'bold'
      label.appendChild(cntSpan)
      label.appendChild(document.createTextNode('종목)'))
      holdingCountSpanTest = cntSpan
    } else {
      label.textContent = ACCOUNT_LABELS_TEST[i]
    }
    const val = document.createElement('span')
    Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: FONT_SIZE.body })
    row.appendChild(label)
    row.appendChild(val)
    testAccountContainer.appendChild(row)
    testAccountValRefs.push(val)
  }
  accountPanel.appendChild(testAccountContainer)

  // 업종별 종목 수익 섹션
  const stockListHeader = sectionTitle('업종별 종목 수익')
  stockListHeader.style.color = COLOR.down
  stockListHeader.style.marginTop = '12px'
  accountPanel.appendChild(stockListHeader)

  sectorStockListContainer = document.createElement('div')
  Object.assign(sectorStockListContainer.style, { flex: '1', minHeight: '0' })
  accountPanel.appendChild(sectorStockListContainer)

  upper.appendChild(leftColumn)
  upper.appendChild(accountPanel)
  root.appendChild(upper)

  /* ── 하단: 상세 분석 보기 버튼 ── */
  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '8px 0' })

  const detailBtn = document.createElement('button')
  Object.assign(detailBtn.style, {
    padding: '10px 24px',
    fontSize: FONT_SIZE.label,
    fontWeight: FONT_WEIGHT.semibold,
    border: '1px solid #ddd',
    borderRadius: '6px',
    background: '#fafafa',
    cursor: 'pointer',
    color: COLOR.down,
  })
  detailBtn.textContent = '상세 분석 보기 →'
  detailBtn.addEventListener('click', () => {
    location.hash = '#/profit-detail'
  })
  lower.appendChild(detailBtn)

  root.appendChild(lower)
  container.appendChild(root)

  // 차트 생성 — 일별 수익률
  const { profitDateFrom: storedFrom, profitDateTo: storedTo } = hotStore.getState()
  chart = createProfitChart({
    container: chartContainer,
    data: buildChartFromDailySummary(hotStore.getState().dailySummary),
    dateFrom: storedFrom,
    dateTo: storedTo,
    onDateRangeChange: async (from: string, to: string) => {
      try {
        const settings = globalSettingsManager.getSettings()
        const tradeMode = settings?.trade_mode || 'test'
        const data = await api.getDailySummary(from, to, tradeMode)
        chart?.updateData(buildChartFromDailySummary(data))
        hotStore.setState({ profitDateFrom: from, profitDateTo: to, dailySummary: data })
        refreshFilteredViews()
      } catch (err) {
        console.error('[profit-overview] daily-summary fetch failed:', err)
      }
    },
  })

  // 차트 생성 — 업종별 수익 도넛
  donutChart = createSectorDonut({
    container: donutChartContainer,
    data: buildSectorDonutData(hotStore.getState().sellHistory),
  })

  // 초기 데이터 반영
  const initState = hotStore.getState()
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  const storedDates = hotStore.getState()
  if (!storedDates.profitDateFrom || !storedDates.profitDateTo) {
    const now = new Date()
    const from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
    const to = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    hotStore.setState({ profitDateFrom: from, profitDateTo: to })
  }
  filteredSellHistory = filterSellHistoryByDate(sellHistory, hotStore.getState().profitDateFrom, hotStore.getState().profitDateTo)

  // hotStore 구독 — rAF 배칭 + selective update
  let prevSellRef = initState.sellHistory
  let prevBuyRef = initState.buyHistory
  let prevDailySummaryRef = initState.dailySummary
  let prevAccountRef = initState.account
  let prevTradeMode = globalSettingsManager.getSettings()?.trade_mode
  let prevPositionsRef = initState.positions
  _mounted = true

  unsubStore = hotStore.subscribe((curr) => {
    const accountChanged = curr.account !== prevAccountRef || curr.positions !== prevPositionsRef
    const historyChanged = curr.sellHistory !== prevSellRef || curr.buyHistory !== prevBuyRef
    const chartChanged = curr.dailySummary !== prevDailySummaryRef || globalSettingsManager.getSettings()?.trade_mode !== prevTradeMode

    if (!accountChanged && !historyChanged && !chartChanged) return

    if (accountChanged) {
      prevAccountRef = curr.account
      prevPositionsRef = curr.positions
      _dirtyAccount = true
    }
    if (historyChanged) {
      prevSellRef = curr.sellHistory
      prevBuyRef = curr.buyHistory
      sellHistory = curr.sellHistory
      buyHistory = curr.buyHistory
      _dirtyHistory = true
    }
    if (chartChanged) {
      prevDailySummaryRef = curr.dailySummary
      prevTradeMode = globalSettingsManager.getSettings()?.trade_mode
      _dirtyChart = true
    }

    if (_rafId !== null) return

    _rafId = requestAnimationFrame(() => {
      _rafId = null
      if (!_mounted) return

      if (_dirtyAccount) {
        _dirtyAccount = false
        renderAccountVals()
      }

      if (_dirtyHistory) {
        _dirtyHistory = false
        renderAccountVals()
        refreshFilteredViews()
      }

      if (_dirtyChart) {
        _dirtyChart = false
        const latest = hotStore.getState()
        const settings = globalSettingsManager.getSettings()
        const tradeModeChanged = settings?.trade_mode !== prevTradeMode
        if (tradeModeChanged) {
          chart?.updateData(buildChartFromDailySummary(latest.dailySummary))
        }
        refreshFilteredViews()
        if (tradeModeChanged) {
          prevTradeMode = settings?.trade_mode
          const isTest = settings?.trade_mode === 'test'
          retentionLabel.textContent = isTest ? '최근 60거래일 데이터' : '최근 5거래일 데이터'
          if (realAccountContainer && testAccountContainer) {
            realAccountContainer.style.display = isTest ? 'none' : ''
            testAccountContainer.style.display = isTest ? '' : 'none'
          }
          renderAccountVals()
        }
      }
    })
  })

  renderAccountVals()
  renderSectorStockPnl()
}

/* ── unmount ── */
function unmount(): void {
  _mounted = false
  notifyPageInactive('profit-overview')
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  _dirtyAccount = false
  _dirtyHistory = false
  _dirtyChart = false
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (chart) { chart.destroy(); chart = null }
  if (donutChart) { donutChart.destroy(); donutChart = null }
  accountValRefs = []
  testAccountValRefs = []
  holdingCountSpan = null
  holdingCountSpanTest = null
  realAccountContainer = null
  testAccountContainer = null
  sectorStockListContainer = null
  buyHistory = []
  sellHistory = []
  filteredSellHistory = []
}

export default { mount, unmount }
