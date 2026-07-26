// frontend/src/pages/sell-position.ts
// 보유종목 페이지 — 매수후보 코드 기반 최종본

// frontend/src/pages/sell-position.ts

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { hotStore, normalizeStockCode, getPositionIndex, type HotState } from '../stores/hotStore'
import { uiStore } from '../stores/uiStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createCardHeaderWithMargin } from '../components/common/card-header'
import { globalSettingsManager } from '../settings'
import { rateColor, pnlColor, fmtComma, fmtRate, createCodeCell, createStockNameColumn, createNumberCell, createPriceCell, COLOR } from '../components/common/ui-styles'
import { createBadgeRow, createBadge, updateBadge, type BadgeHandle } from '../components/common/badge'
import { computeOrderBlockStatus } from '../utils/order-block-status'
import { getLocalToday } from '../utils/date'
import { computeHoldingsSummary } from './profit-shared'
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
      const sectorStock = state.sectorStocks[normalizeStockCode(p.stk_cd)]
      return {
        name: p.stk_nm,
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
      }
    }
  ),
  {
    key: 'cur_price', label: '현재가', align: 'right', type: 'price', flash: true,
    render: (p) => {
      const sectorStock = hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = sectorStock?.cur_price
      if (curPrice == null) return createPriceCell(null, null)
      const buyPrice = p.avg_price
      const diff = Number(curPrice) - buyPrice
      const rate = buyPrice > 0 ? (diff / buyPrice) * 100 : 0
      return createPriceCell(Number(curPrice), rate)
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
    key: 'pnl', label: '평가손익', align: 'right', type: 'pnl',
    render: (p) => {
      const sectorStock = hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = sectorStock?.cur_price ?? null
      const span = document.createElement('span')
      if (curPrice == null) {
        span.textContent = '-'
        return span
      }
      const buyPrice = p.avg_price
      const qty = p.qty
      const pnl = (Number(curPrice) - buyPrice) * qty
      span.style.color = rateColor(pnl)
      span.textContent = fmtComma(pnl)
      return span
    },
  },
  {
    key: 'rate', label: '수익률', align: 'right', type: 'pnl_rate',
    render: (p) => {
      const sectorStock = hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = sectorStock?.cur_price ?? null
      const span = document.createElement('span')
      if (curPrice == null) {
        span.textContent = '-'
        return span
      }
      const buyPrice = p.avg_price
      const rate = buyPrice > 0 ? ((Number(curPrice) - buyPrice) / buyPrice) * 100 : 0
      span.style.color = rateColor(rate)
      span.textContent = fmtRate(rate) + '%'
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
let _rafId: number | null = null
let _summaryRafId: number | null = null
let _statusRafId: number | null = null
let onRealDataTick: ((e: Event) => void) | null = null
let _mounted = false

/* ── hotStore 구독 참조 상태 — onHotStoreChange 참조 비교용 (mount 시 초기화, unmount 시 reset) ── */
let _prevPositions: HotState['positions'] = []
let _prevSectorStocks: HotState['sectorStocks'] = {}
let _prevAccount: HotState['account'] = null

/* ── 보유 종목 요약 행 참조 ── */
let summaryEvalBadge: BadgeHandle | null = null
let summaryPnlBadge: BadgeHandle | null = null
let summaryRateBadge: BadgeHandle | null = null
let summaryStatusBadge: BadgeHandle | null = null

/** 보유 종목 요약 행 렌더 — positions + sectorStocks에서 직접 계산 (개별 종목 행과 동일 소스·공식)
 *  P21/P23: cur_price null인 보유종목 있으면 평가금액/평가손익/수익률 '-' 표시 (개별 행과 동일 null 패턴) */
function renderSummary(): void {
  const state = hotStore.getState()
  const count = state.positionCount
  const { evalTotal, evalPnl, evalRate, hasNullPrice } = computeHoldingsSummary(state.positions, state.sectorStocks)

  if (summaryEvalBadge) {
    updateBadge(summaryEvalBadge, hasNullPrice ? '-' : fmtComma(evalTotal), {
      statusNumber: String(count),
      statusLabel: '종목',
    })
  }

  const color = hasNullPrice ? '' : pnlColor(evalPnl)
  const pnlText = hasNullPrice ? '-' : `${evalPnl > 0 ? '+' : ''}${fmtComma(evalPnl)}`
  const rateText = hasNullPrice ? '-' : `${evalRate > 0 ? '+' : ''}${evalRate.toFixed(2)}`

  if (summaryPnlBadge) {
    updateBadge(summaryPnlBadge, pnlText, { valueColor: color })
  }
  if (summaryRateBadge) {
    updateBadge(summaryRateBadge, rateText, { valueColor: color })
  }
}

/** 매도상태 배지 업데이트 — 전체 차단 게이트 집계 (P21 사용자 투명성)
 *  판정 로직은 computeOrderBlockStatus()로 추출 (P10 SSOT, P23 일관성 — buy-target.ts와 동일 패턴) */
function updateSellStatusBadge(): void {
  if (!summaryStatusBadge) return
  try {
    const uiState = uiStore.getState()
    const settings = globalSettingsManager.getSettings()
    const { text: statusText, blocked: statusBlocked } = computeOrderBlockStatus('sell', uiState, settings)
    updateBadge(summaryStatusBadge, statusText, {
      status: statusBlocked ? 'warn' : 'normal',
      statusColor: statusBlocked ? COLOR.up : COLOR.down,
    })
  } catch (err) {
    console.error('[sell-position] updateSellStatusBadge error', err)
  }
}

/* ── DOM 빌더 — mount에서 호출 (P24 책임 분할, buy-target.ts/sector-stock.ts 동일 패턴 P23) ── */

/** 헤더 + 보유 종목 요약 배지 행 빌드 */
function buildSummary(root: HTMLElement): void {
  // 헤더: 제목
  const headerRow = createCardHeaderWithMargin('보유종목', undefined, '8px')
  root.appendChild(headerRow)

  // 보유 종목 요약 배지 행 — 공통 컴포넌트 (flex 자동 균등 분할)
  const summaryRow = createBadgeRow()
  summaryEvalBadge = createBadge('📊 평가금액 합계', '원')
  summaryPnlBadge = createBadge('📉 평가손익 합계', '원')
  summaryRateBadge = createBadge('📈 평가수익률', '%')
  summaryStatusBadge = createBadge('🚦 매도상태', '')
  summaryRow.appendChild(summaryEvalBadge.el)
  summaryRow.appendChild(summaryPnlBadge.el)
  summaryRow.appendChild(summaryRateBadge.el)
  summaryRow.appendChild(summaryStatusBadge.el)
  root.appendChild(summaryRow)
}

/** 스크롤 컨테이너 + DataTable 빌드 */
function buildTableArea(root: HTMLElement): void {
  const scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, {
    flex: '1',
    minHeight: '200px',
    display: 'flex',
    flexDirection: 'column',
    overflowY: 'auto'
  })

  dataTable = createDataTable<Position>({
    columns: COLUMNS,
    virtualScroll: false,
    keyFn: (p) => p.stk_cd || String(p.stk_nm),
    emptyText: '보유종목이 없습니다.',
    stickyHeader: true,
  })

  scrollContainer.appendChild(dataTable.el)
  root.appendChild(scrollContainer)
}

/* ── 구독 콜백 — mount에서 등록 (P24 책임 분할) ── */

/** hotStore 구독 콜백 — reference equality guard + rAF 배칭
 *  account 변경 시 요약 행 즉시 갱신, positions/sectorStocks 변경 시 rAF로 updateRows */
function onHotStoreChange(state: HotState): void {
  const positionsChanged = state.positions !== _prevPositions
  const sectorStocksChanged = state.sectorStocks !== _prevSectorStocks
  const accountChanged = state.account !== _prevAccount

  _prevPositions = state.positions
  _prevSectorStocks = state.sectorStocks
  _prevAccount = state.account

  // account 또는 sectorStocks 변경 시 요약 행 즉시 갱신 (rAF 배칭 불필요 — 텍스트 4개만 교체)
  // sectorStocks 변경 시 갱신 필수 — cur_price null → 실시간 틱 도달 후 정상 값 표시 (P21 투명성)
  if (accountChanged || sectorStocksChanged) {
    renderSummary()
  }

  // positions 또는 sectorStocks 변경 시 updateRows 실행
  // sectorStocks 변경 시에도 createStockNameColumn의 market_type/nxt_enable 배지가 갱신되어야 함
  if (!positionsChanged && !sectorStocksChanged) {
    return
  }

  // WS 상태 배지는 전역 싱글톤이 자동 업데이트하므로 수동 업데이트 제거

  // rAF 배칭 — 프레임당 1회만 갱신 예약
  if (_rafId === null) {
    _rafId = requestAnimationFrame(() => {
      _rafId = null
      if (!_mounted) return
      const latest = hotStore.getState()
      dataTable?.updateRows(latest.positions)
    })
  }
}

/** 매도상태 배지 rAF 배칭 갱신 — uiStore/settings 구독 공통 (P24 중복 제거) */
function scheduleStatusUpdate(): void {
  if (_statusRafId !== null) return
  _statusRafId = requestAnimationFrame(() => {
    _statusRafId = null
    if (!_mounted) return
    updateSellStatusBadge()
  })
}

/** O(1) 초저지연 DOM 갱신 이벤트 리스너 등록 */
function setupTickListener(): void {
  onRealDataTick = (e: Event) => {
    try {
      const code = (e as CustomEvent<string>).detail
      if (dataTable && dataTable.updateItemByKey) {
        dataTable.updateItemByKey(code)
      }
      // 보유종목 틱 시 요약 배지 갱신 (rAF 배칭 — 개별 행과 동일 소스로 실시간 일치)
      if (getPositionIndex(code) !== undefined && _summaryRafId === null) {
        _summaryRafId = requestAnimationFrame(() => {
          _summaryRafId = null
          if (!_mounted) return
          renderSummary()
        })
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
  buildTableArea(root)
  container.appendChild(root)

  // 초기 데이터
  const state = hotStore.getState()
  _prevPositions = state.positions
  _prevSectorStocks = state.sectorStocks
  _prevAccount = state.account
  dataTable?.updateRows(state.positions)
  renderSummary()
  updateSellStatusBadge()

  // Store 구독 — reference equality guard + rAF 배칭
  unsubStore = hotStore.subscribe(onHotStoreChange)

  // uiStore 구독 — 매도상태 배지 갱신 (서킷브레이커/리스크/시간대 차단)
  // rAF 배칭 — 프레임당 1회만 갱신 예약 (buy-target.ts 동일 패턴, P23 일관성)
  unsubUiStore = uiStore.subscribe(scheduleStatusUpdate)

  // globalSettingsManager 구독 — 자동매매/자동매도/매도 시간대 설정 변경 시 배지 갱신
  unsubSettings = globalSettingsManager.subscribe(scheduleStatusUpdate)

  // O(1) 초저지연 DOM 갱신 이벤트 리스너
  setupTickListener()
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
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  if (_summaryRafId !== null) { cancelAnimationFrame(_summaryRafId); _summaryRafId = null }
  if (_statusRafId !== null) { cancelAnimationFrame(_statusRafId); _statusRafId = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  summaryEvalBadge = null
  summaryPnlBadge = null
  summaryRateBadge = null
  summaryStatusBadge = null
  _prevPositions = []
  _prevSectorStocks = {}
  _prevAccount = null
}

export default { mount, unmount }