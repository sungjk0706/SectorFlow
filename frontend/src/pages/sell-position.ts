// frontend/src/pages/sell-position.ts
// 보유종목(매도 포지션) 페이지

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { fixedTableOptions } from '../components/common/table-options'
import { hotStore, normalizeStockCode, getPositionIndex, type HotState } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { api } from '../api/client'
import { applyAccountSnapshot, applyPositionsSnapshot } from '../stores/hotStore'
import { refreshPageData, createPageRefreshStatus } from '../utils/page-refresh'
import { createCardHeaderWithMargin } from '../components/common/card-header'
import { globalSettingsManager } from '../settings'
import { rateColor, pnlColor, fmtComma, fmtRate, createCodeCell, createStockNameColumn, createNumberCell, createPriceCell, COLOR } from '../components/common/ui-styles'
import { createBadgeRow, createBadge, updateBadge, type BadgeHandle } from '../components/common/badge'
import { computeOrderBlockStatus } from '../utils/order-block-status'
import { getLocalToday } from '../utils/date'
import { createFrameScheduler, type FrameScheduler } from '../components/common/frame-scheduler'
import type { Position } from '../types'

const COLUMNS: ColumnDef<Position>[] = [
  {
    key: 'no', label: '순번', align: 'center', type: 'seq',
    render: (_p, index) => String(index + 1),
  },
  {
    key: 'stk_cd', label: '종목코드', align: 'center', type: 'code',
    render: (p) => createCodeCell(p.stk_cd),
  },
  createStockNameColumn<Position>(
    (p: Position) => {
      const state = hotStore.getState()
      const masterStock = state.masterStocks[normalizeStockCode(p.stk_cd)]
      return {
        name: p.stk_nm,
        market_type: masterStock?.market_type,
        nxt_enable: masterStock?.nxt_enable
      }
    }
  ),
  {
    // 표시 소스: masterStocks(백엔드 master_stocks_cache 프론트 사본) — 매수후보·업종별 종목과 동일 소스 (P23 일관성).
    // 현재가 표시만 masterStocks 기반. 평가손익/수익률은 백엔드(증권사/가상 시뮬레이터) 계산값을 그대로 표시 (P10 SSOT).
    // masterStocks에 종목이 없거나 cur_price가 null/undefined → '-' (P20 폴백 금지 — p.cur_price 참조 안 함).
    key: 'cur_price', label: '현재가', align: 'right', type: 'price', flash: true,
    render: (p) => {
      const state = hotStore.getState()
      const masterStock = state.masterStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = masterStock?.cur_price
      const changeRate = masterStock?.change_rate
      if (curPrice == null) return createPriceCell(null, null)
      return createPriceCell(Number(curPrice), changeRate != null ? Number(changeRate) : null)
    },
  },
  {
    key: 'buy_price', label: '매수가', align: 'right', type: 'buy_price',
    render: (p) => createNumberCell(p.avg_price),
  },
  {
    key: 'buy_amt', label: '매수금액(수수료 포함)', align: 'right', type: 'total_amt',
    render: (p) => createNumberCell(p.buy_amt),
  },
  {
    // 평가손익 — 백엔드(증권사/가상 시뮬레이터) 계산값 그대로 표시 (P10 SSOT). 화면 자체 계산 금지.
    // null = 시세 미수신 → '-' 표시 (P20 폴백 금지, P21 투명성).
    key: 'pnl', label: '평가손익', align: 'right', type: 'pnl',
    render: (p) => {
      const span = document.createElement('span')
      if (p.pnl_amount == null) {
        span.textContent = '-'
        return span
      }
      span.style.color = rateColor(p.pnl_amount)
      span.textContent = fmtComma(p.pnl_amount)
      return span
    },
  },
  {
    // 수익률 — 백엔드 계산값 그대로 표시 (P10 SSOT). null = 시세 미수신 → '-' 표시.
    key: 'rate', label: '수익률', align: 'right', type: 'pnl_rate',
    render: (p) => {
      const span = document.createElement('span')
      if (p.pnl_rate == null) {
        span.textContent = '-'
        return span
      }
      span.style.color = rateColor(p.pnl_rate)
      span.textContent = fmtRate(p.pnl_rate) + '%'
      return span
    },
  },
  {
    key: 'qty', label: '수량', align: 'right', type: 'qty',
    render: (p) => createNumberCell(p.qty),
  },
  {
    key: 'buy_date', label: '매수일자', align: 'center', type: 'date',
    render: (p) => {
      const span = document.createElement('span')
      span.textContent = p.buy_date
      const todayStr = getLocalToday()
      span.style.color = p.buy_date === todayStr ? COLOR.neutral : COLOR.disabled
      return span
    },
  },
]

let dataTable: DataTableApi<Position> | null = null
let unsubStore: (() => void) | null = null
let unsubUiStore: (() => void) | null = null
let unsubSettings: (() => void) | null = null
let _rowScheduler: FrameScheduler | null = null
let _summaryScheduler: FrameScheduler | null = null
let _statusScheduler: FrameScheduler | null = null
let onRealDataTick: ((e: Event) => void) | null = null
let _mounted = false
let pageDataReady = false
let refreshStatus: ReturnType<typeof createPageRefreshStatus> | null = null

async function refreshSellPositionPage(): Promise<void> {
  const isActive = () => _mounted
  refreshStatus?.set('최신 데이터 확인 중')
  pageDataReady = false
  dataTable?.updateRows([])
  renderSummary()
  const results = await Promise.all([
    refreshPageData({
      key: 'sell-position:account', policy: 'always-fresh', isActive,
      fetcher: async () => api.getAccountSnapshot('sell-position'),
      apply: (response) => applyAccountSnapshot(response.data, response.freshness!),
    }),
    refreshPageData({
      key: 'sell-position:positions', policy: 'always-fresh', isActive,
      fetcher: async () => api.getAccountPositions('sell-position'),
      apply: (response) => applyPositionsSnapshot(response.data, response.freshness!),
    }),
  ])
  if (!_mounted) return
  if (results.some(result => result.status === 'error')) {
    refreshStatus?.set('최신 데이터를 확인하지 못했습니다')
    return
  }
  pageDataReady = true
  refreshStatus?.set('', false)
  renderSummary()
  const positions = hotStore.getState().positions
  dataTable?.updateRows(positions)
}

/* ── hotStore 구독 참조 상태 — onHotStoreChange 참조 비교용 (mount 시 초기화, unmount 시 reset) ── */
let _prevPositions: HotState['positions'] = []
let _prevMasterStocks: HotState['masterStocks'] = {}
let _prevAccount: HotState['account'] = null

/* ── 보유 종목 요약 행 참조 ── */
let summaryEvalBadge: BadgeHandle | null = null
let summaryPnlBadge: BadgeHandle | null = null
let summaryRateBadge: BadgeHandle | null = null
let summaryStatusBadge: BadgeHandle | null = null

/** 보유 종목 요약 행 렌더 — account snapshot의 백엔드 계산값 그대로 표시 (P10 SSOT).
 *  개별 행과 동일하게 백엔드(증권사/가상 시뮬레이터)가 계산한 총평가·총손익·총수익률을 사용.
 *  P21/P23: account 값이 없으면 '-' 표시 (개별 행과 동일 null 패턴). */
function renderSummary(): void {
  if (!pageDataReady) {
    if (summaryEvalBadge) updateBadge(summaryEvalBadge, '—')
    if (summaryPnlBadge) updateBadge(summaryPnlBadge, '—')
    if (summaryRateBadge) updateBadge(summaryRateBadge, '—')
    return
  }
  const state = hotStore.getState()
  const count = state.positionCount
  const account = state.account
  const evalTotal = account?.total_eval_amount ?? null
  const evalPnl = account?.total_pnl ?? null
  const evalRate = account?.total_pnl_rate ?? null

  if (summaryEvalBadge) {
    updateBadge(summaryEvalBadge, evalTotal == null ? '-' : fmtComma(evalTotal), {
      statusNumber: String(count),
      statusLabel: '종목',
    })
  }

  const color = evalPnl == null ? '' : pnlColor(evalPnl)
  const pnlText = evalPnl == null ? '-' : `${evalPnl > 0 ? '+' : ''}${fmtComma(evalPnl)}`
  const rateText = evalRate == null ? '-' : `${evalRate > 0 ? '+' : ''}${evalRate.toFixed(2)}`

  if (summaryPnlBadge) {
    updateBadge(summaryPnlBadge, pnlText, { valueColor: color })
  }
  if (summaryRateBadge) {
    updateBadge(summaryRateBadge, rateText, { valueColor: color })
  }
}

/** 매도상태 배지 업데이트 — 전체 차단 게이트 집계 (P21 사용자 투명성)
 *  판정 로직은 computeOrderBlockStatus()로 추출 (P10 SSOT, P23 일관성 — buy-target.ts와 동일 패턴).
 *  표시 포맷도 buy-target.ts와 동일 — "차단" 값 + " · {사유}" 상태 텍스트 (P23 일관성). */
function updateSellStatusBadge(): void {
  if (!summaryStatusBadge) return
  try {
    const uiState = uiStore.getState()
    const settings = globalSettingsManager.getSettings()
    const { text: statusText, blocked: statusBlocked, partial: statusPartial, holiday } = computeOrderBlockStatus('sell', uiState, settings)
    if (holiday) {
      // 휴장일 — 헤더 휴장일 칩과 동일 회색 (P21/P23). 값 자리에 휴장일 문구, 상태 텍스트 없음.
      updateBadge(summaryStatusBadge, statusText, {
        status: 'normal',
        statusColor: COLOR.disabled,
        valueColor: COLOR.disabled,
      })
      summaryStatusBadge.unitEl.textContent = ''
      return
    }
    if (statusBlocked) {
      // 강제 차단 — "차단" 값 + " · {사유}" 상태 텍스트 (buy-target.ts와 동일 포맷, P23 일관성).
      const value = statusPartial ? '부분 차단' : '차단'
      updateBadge(summaryStatusBadge, value, {
        status: 'warn',
        statusColor: COLOR.up,
        statusText: ` · ${statusText.replace(/^차단: /, '')}`,
      })
      summaryStatusBadge.unitEl.textContent = ''
      return
    }
    if (statusText !== '매도 가능') {
      // 정보 상태 (NXT만 가능 / 거래 시간 외) — 파랑 정보색, 값 자리에 정보 텍스트 (P21 투명성).
      updateBadge(summaryStatusBadge, statusText, {
        status: 'normal',
        statusColor: COLOR.down,
        valueColor: COLOR.down,
      })
      summaryStatusBadge.unitEl.textContent = ''
      return
    }
    // 정상 — "매도 가능" 초록 (헤더 칩 거래 가능 색과 동일, P23 일관성).
    updateBadge(summaryStatusBadge, statusText, {
      status: 'normal',
      statusColor: COLOR.success,
    })
    summaryStatusBadge.unitEl.textContent = ''
  } catch (err) {
    console.error('[sell-position] updateSellStatusBadge error', err)
  }
}

/* ── DOM 빌더 — mount에서 호출 (P24 책임 분할, buy-target.ts/sector-stock.ts 동일 패턴 P23) ── */

/** 헤더 + 보유 종목 요약 배지 행 빌드 */
function buildSummary(root: HTMLElement): void {
  // 헤더: 제목
  const headerRow = createCardHeaderWithMargin('보유종목')
  root.appendChild(headerRow)

  // 보유 종목 요약 배지 행 — 공통 컴포넌트 (flex 자동 균등 분할)
  const summaryRow = createBadgeRow()
  summaryEvalBadge = createBadge('평가금액 합계', '원', 'bar-chart')
  summaryPnlBadge = createBadge('평가손익 합계', '원', 'trending-down')
  summaryRateBadge = createBadge('평가수익률', '%', 'trending-up')
  summaryStatusBadge = createBadge('매도상태', '', 'activity')
  summaryRow.appendChild(summaryEvalBadge.el)
  summaryRow.appendChild(summaryPnlBadge.el)
  summaryRow.appendChild(summaryRateBadge.el)
  summaryRow.appendChild(summaryStatusBadge.el)
  root.appendChild(summaryRow)
}

/** 테이블 영역 + DataTable 빌드 (단일 상자 — 이중 스크롤 제거, 결정 2) */
function buildTableArea(root: HTMLElement): void {
  // 단일 레이아웃 상자 — overflowY:auto 제거 (비가상 모드도 동일 규칙)
  const tableWrap = document.createElement('div')
  Object.assign(tableWrap.style, {
    flex: '1',
    minHeight: '0',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden'
  })

  dataTable = createDataTable<Position>(
    fixedTableOptions<Position>({
      columns: COLUMNS,
      keyFn: (p) => p.stk_cd || String(p.stk_nm),
      emptyText: '보유종목이 없습니다.',
    }),
  )

  tableWrap.appendChild(dataTable.el)
  root.appendChild(tableWrap)
}

/* ── 구독 콜백 — mount에서 등록 (P24 책임 분할) ── */

/** hotStore 구독 콜백 — reference equality guard + rAF 배칭
 *  account 변경 시 요약 행 즉시 갱신 (요약은 account snapshot 기반 — P10 SSOT),
 *  positions/masterStocks 변경 시 rAF로 updateRows (개별 행 현재가·배지는 masterStocks 기반) */
function onHotStoreChange(state: HotState): void {
  if (!pageDataReady) return
  const positionsChanged = state.positions !== _prevPositions
  const masterStocksChanged = state.masterStocks !== _prevMasterStocks
  const accountChanged = state.account !== _prevAccount

  _prevPositions = state.positions
  _prevMasterStocks = state.masterStocks
  _prevAccount = state.account

  // account 변경 시 요약 행 즉시 갱신 (rAF 배칭 불필요 — 텍스트 4개만 교체)
  // 요약의 평가손익·수익률은 account snapshot의 백엔드 계산값 기반 (P10 SSOT)
  if (accountChanged) {
    renderSummary()
  }

  // positions 또는 masterStocks 변경 시 updateRows 실행
  // masterStocks 변경 시에도 createStockNameColumn의 market_type/nxt_enable 배지가 갱신되어야 함
  if (!positionsChanged && !masterStocksChanged) {
    return
  }

  // positions 변경 시 재구독은 백엔드가 자동 갱신 — 프론트엔드가 코드를 보내지 않음.

  // WS 상태 배지는 전역 싱글톤이 자동 업데이트하므로 수동 업데이트 제거

  // 공통 화면주기 갱신 도구 — 프레임당 1회만 갱신 예약
  _rowScheduler?.schedule()
}

/** 매도상태 배지 화면주기 갱신 — uiStore/settings 구독 공통 (P24 중복 제거) */
function scheduleStatusUpdate(): void {
  _statusScheduler?.schedule()
}

/** O(1) 초저지연 DOM 갱신 이벤트 리스너 등록 */
function setupTickListener(): void {
  onRealDataTick = (e: Event) => {
    try {
      const code = (e as CustomEvent<string>).detail
      if (dataTable && dataTable.updateItemByKey) {
        dataTable.updateItemByKey(code)
      }
      // 보유종목 틱 시 요약 배지 갱신 (공통 도구 — 개별 행과 동일 소스로 실시간 일치)
      if (getPositionIndex(code) !== undefined) {
        _summaryScheduler?.schedule()
      }
    } catch (err) {
      console.error('[sell-position] real-data-tick error', err)
    }
  }
  window.addEventListener('real-data-tick', onRealDataTick)
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('sell-position')
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  buildSummary(root)
  refreshStatus = createPageRefreshStatus()
  root.appendChild(refreshStatus.el)
  buildTableArea(root)
  container.appendChild(root)

  // 초기 데이터
  const state = hotStore.getState()
  _prevPositions = state.positions
  _prevMasterStocks = state.masterStocks
  _prevAccount = state.account
  dataTable?.updateRows([])
  renderSummary()
  updateSellStatusBadge()

  // 공통 화면주기 갱신 도구 3종 — 테이블 행 / 요약 / 매도상태 배지
  _rowScheduler = createFrameScheduler(() => {
    if (!_mounted) return
    const latest = hotStore.getState()
    dataTable?.updateRows(latest.positions)
  })
  _summaryScheduler = createFrameScheduler(() => {
    if (!_mounted) return
    renderSummary()
  })
  _statusScheduler = createFrameScheduler(() => {
    if (!_mounted) return
    updateSellStatusBadge()
  })

  // Store 구독 — reference equality guard + 공통 도구 갱신
  unsubStore = hotStore.subscribe(onHotStoreChange)

  // uiStore 구독 — 매도상태 배지 갱신 (서킷브레이커/리스크/시간대 차단)
  // 공통 도구 — 프레임당 1회만 갱신 예약 (buy-target.ts 동일 패턴, P23 일관성)
  unsubUiStore = uiStore.subscribe(scheduleStatusUpdate)

  // globalSettingsManager 구독 — 자동매매/자동매도/매도 시간대 설정 변경 시 배지 갱신
  unsubSettings = globalSettingsManager.subscribe(scheduleStatusUpdate)

  // O(1) 초저지연 DOM 갱신 이벤트 리스너
  setupTickListener()
  void refreshSellPositionPage()
}

function unmount(): void {
  _mounted = false
  notifyPageInactive('sell-position')
  if (onRealDataTick) {
    window.removeEventListener('real-data-tick', onRealDataTick)
    onRealDataTick = null
  }
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (unsubUiStore) { unsubUiStore(); unsubUiStore = null }
  if (unsubSettings) { unsubSettings(); unsubSettings = null }
  if (_rowScheduler) { _rowScheduler.destroy(); _rowScheduler = null }
  if (_summaryScheduler) { _summaryScheduler.destroy(); _summaryScheduler = null }
  if (_statusScheduler) { _statusScheduler.destroy(); _statusScheduler = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  summaryEvalBadge = null
  summaryPnlBadge = null
  summaryRateBadge = null
  summaryStatusBadge = null
  _prevPositions = []
  _prevMasterStocks = {}
  _prevAccount = null
  pageDataReady = false
  refreshStatus = null
}

export default { mount, unmount }