// frontend/src/pages/profit-overview.ts
// 수익현황 페이지 — Vanilla TS PageModule
// 요약 대시보드: 차트(작게) + 요약 카드 3개 + 계좌 현황 + 상세 분석 보기 버튼

import { createProfitChart, type ProfitChartApi } from '../components/canvas-profit-chart'
import { globalSettingsManager } from '../settings'
import { FONT_SIZE, FONT_WEIGHT, pnlColor, fmtWon, COLOR } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import { sectionTitle } from '../components/common/settings-common'
import { ACCOUNT_LABELS_REAL, ACCOUNT_LABELS_TEST } from '../components/common/account-labels'
import { hotStore } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import {
  getLocalToday,
  aggregatePnl,
  buildChartFromDailySummary,
  renderAccountVals as renderAccountValsShared,
  type AccountValsParams,
} from './profit-shared'

/* ── 헬퍼 ── */

const ROW_CSS = `display:flex;justify-content:space-between;padding:7px 4px;border-bottom:1px solid #f0f0f0;font-size:${FONT_SIZE.label};`

/* ── 모듈 변수 ── */
let chart: ProfitChartApi | null = null
let accountValRefs: HTMLSpanElement[] = []
let testAccountValRefs: HTMLSpanElement[] = []
let holdingCountSpan: HTMLSpanElement | null = null
let holdingCountSpanTest: HTMLSpanElement | null = null
let realAccountContainer: HTMLDivElement | null = null
let testAccountContainer: HTMLDivElement | null = null
let buyHistory: Record<string, unknown>[] = []
let sellHistory: Record<string, unknown>[] = []
let unsubStore: (() => void) | null = null

/* ── rAF 배칭 상태 ── */
let _rafId: number | null = null
let _mounted = false
let _dirtyAccount = false
let _dirtyHistory = false
let _dirtyChart = false

/* ── 요약 카드 DOM 참조 ── */
let todayPnlEl: HTMLSpanElement | null = null
let todayRateEl: HTMLSpanElement | null = null
let monthPnlEl: HTMLSpanElement | null = null
let monthRateEl: HTMLSpanElement | null = null
let totalPnlEl: HTMLSpanElement | null = null
let totalRateEl: HTMLSpanElement | null = null

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

/* ── 요약 카드 갱신 ── */
function updateSummaryCards(): void {
  const today = getLocalToday()
  const yearMonth = today.slice(0, 7)

  const dailySummary = hotStore.getState().dailySummary
  const todayEntry = dailySummary.find(r => String(r.date ?? '') === today)
  const dayPnl = todayEntry ? Number(todayEntry.realized_pnl ?? 0) : 0
  const dayRate = todayEntry ? Number(todayEntry.pnl_rate ?? 0) : 0

  const monS = aggregatePnl(sellHistory, yearMonth + '-01', yearMonth + '-31')
  const allS = aggregatePnl(sellHistory)

  if (todayPnlEl) { todayPnlEl.textContent = fmtWon(dayPnl); todayPnlEl.style.color = pnlColor(dayPnl) }
  if (todayRateEl) { todayRateEl.textContent = `${dayRate.toFixed(2)}%`; todayRateEl.style.color = pnlColor(dayPnl) }
  if (monthPnlEl) { monthPnlEl.textContent = fmtWon(monS.pnl); monthPnlEl.style.color = pnlColor(monS.pnl) }
  if (monthRateEl) { monthRateEl.textContent = `${monS.rate.toFixed(2)}%`; monthRateEl.style.color = pnlColor(monS.pnl) }
  if (totalPnlEl) { totalPnlEl.textContent = fmtWon(allS.pnl); totalPnlEl.style.color = pnlColor(allS.pnl) }
  if (totalRateEl) { totalRateEl.textContent = `${allS.rate.toFixed(2)}%`; totalRateEl.style.color = pnlColor(allS.pnl) }
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

  /* ── 상단 (자연스러운 높이) ── */
  const upper = document.createElement('div')
  Object.assign(upper.style, {
    flex: 'none',
    borderBottom: '1px solid #ddd',
    overflow: 'hidden',
    display: 'flex',
    gap: '8px',
  })

  // 우 50%: 일별 수익률 차트
  const chartPanel = document.createElement('div')
  Object.assign(chartPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px' })
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
  chartPanel.appendChild(chartContainer)

  // 좌 50%: 계좌 현황 테이블
  const accountPanel = document.createElement('div')
  Object.assign(accountPanel.style, { flex: '5', minWidth: '0', overflow: 'auto', padding: '0 4px' })

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
    Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })
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
    Object.assign(val.style, { textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })
    row.appendChild(label)
    row.appendChild(val)
    testAccountContainer.appendChild(row)
    testAccountValRefs.push(val)
  }
  accountPanel.appendChild(testAccountContainer)

  upper.appendChild(chartPanel)
  upper.appendChild(accountPanel)
  root.appendChild(upper)

  /* ── 요약 카드 3개 ── */
  const summaryRow = document.createElement('div')
  Object.assign(summaryRow.style, { display: 'flex', gap: '8px', padding: '8px 4px' })

  const CARD_STYLE = `flex:1;background:#fafafa;border:1px solid #eee;border-radius:6px;padding:6px 12px;display:flex;justify-content:space-between;align-items:center;`
  const CARD_TITLES = ['당일 손익', '당월 손익', '누적 손익']

  const pnlEls: HTMLSpanElement[] = []
  const rateEls: HTMLSpanElement[] = []

  for (let i = 0; i < 3; i++) {
    const card = document.createElement('div')
    card.style.cssText = CARD_STYLE

    const titleEl = document.createElement('div')
    Object.assign(titleEl.style, { fontSize: FONT_SIZE.badge, color: COLOR.secondary, whiteSpace: 'nowrap' })
    titleEl.textContent = CARD_TITLES[i]

    const valRow = document.createElement('div')
    Object.assign(valRow.style, { display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', gap: '6px' })

    const pnlEl = document.createElement('span')
    Object.assign(pnlEl.style, { fontSize: FONT_SIZE.section, fontWeight: 'normal' })
    pnlEl.textContent = fmtWon(0)

    const rateEl = document.createElement('span')
    Object.assign(rateEl.style, { fontSize: FONT_SIZE.label, color: COLOR.neutral })
    rateEl.textContent = '0.00%'

    valRow.appendChild(pnlEl)
    valRow.appendChild(rateEl)
    card.appendChild(titleEl)
    card.appendChild(valRow)
    summaryRow.appendChild(card)

    pnlEls.push(pnlEl)
    rateEls.push(rateEl)
  }

  todayPnlEl = pnlEls[0]; todayRateEl = rateEls[0]
  monthPnlEl = pnlEls[1]; monthRateEl = rateEls[1]
  totalPnlEl = pnlEls[2]; totalRateEl = rateEls[2]

  root.appendChild(summaryRow)

  /* ── 하단: 상세 분석 보기 버튼 ── */
  const lower = document.createElement('div')
  Object.assign(lower.style, { flex: '1', overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' })

  const detailBtn = document.createElement('button')
  Object.assign(detailBtn.style, {
    padding: '10px 24px',
    fontSize: FONT_SIZE.label,
    border: '1px solid #ddd',
    borderRadius: '6px',
    background: '#fafafa',
    cursor: 'pointer',
    color: COLOR.secondary,
  })
  detailBtn.textContent = '상세 분석 보기 →'
  detailBtn.addEventListener('click', () => {
    location.hash = '#/profit-detail'
  })
  lower.appendChild(detailBtn)

  root.appendChild(lower)
  container.appendChild(root)

  // 차트 생성
  chart = createProfitChart({
    container: chartContainer,
    data: buildChartFromDailySummary(hotStore.getState().dailySummary),
    onBarClick: () => {
      location.hash = '#/profit-detail'
    },
    onDateRangeChange: async (from: string, to: string) => {
      try {
        const settings = globalSettingsManager.getSettings()
        const tradeMode = settings?.trade_mode || 'test'
        const data = await api.getDailySummary(from, to, tradeMode)
        chart?.updateData(buildChartFromDailySummary(data))
      } catch (err) {
        console.warn('[profit-overview] daily-summary fetch failed:', err)
      }
    },
  })

  // 초기 데이터 반영
  const initState = hotStore.getState()
  sellHistory = initState.sellHistory
  buyHistory = initState.buyHistory
  updateSummaryCards()

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
        updateSummaryCards()
        renderAccountVals()
      }

      if (_dirtyChart) {
        _dirtyChart = false
        updateSummaryCards()
        const latest = hotStore.getState()
        const settings = globalSettingsManager.getSettings()
        const tradeModeChanged = settings?.trade_mode !== prevTradeMode
        chart?.updateData(buildChartFromDailySummary(latest.dailySummary))
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
  accountValRefs = []
  testAccountValRefs = []
  holdingCountSpan = null
  holdingCountSpanTest = null
  realAccountContainer = null
  testAccountContainer = null
  buyHistory = []
  sellHistory = []
  todayPnlEl = null; todayRateEl = null
  monthPnlEl = null; monthRateEl = null
  totalPnlEl = null; totalRateEl = null
}

export default { mount, unmount }
