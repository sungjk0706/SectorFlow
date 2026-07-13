// frontend/src/pages/sell-position.ts
// 보유종목 페이지 — 매수후보 코드 기반 최종본

// frontend/src/pages/sell-position.ts

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { hotStore, normalizeStockCode, getPositionIndex } from '../stores/hotStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createCardHeaderWithMargin } from '../components/common/card-header'
import { rateColor, pnlColor, fmtComma, fmtRate, createCodeCell, createStockNameColumn, createNumberCell, createPriceCell, COLOR } from '../components/common/ui-styles'
import { createBadgeRow, createBadge, updateBadge, type BadgeHandle } from '../components/common/badge'
import { computeHoldingsSummary } from './profit-shared'
import type { Position } from '../types'

const COLUMNS: ColumnDef<Position>[] = [
  {
    key: 'no', label: '순번', align: 'center', minWidth: 36, maxWidth: 36,
    render: (_p, index) => String(index + 1),
  },
  {
    key: 'stk_cd', label: '종목코드', align: 'center', minWidth: 72, maxWidth: 72,
    render: (p) => createCodeCell(p.stk_cd || ''),
  },
  createStockNameColumn<Position>(
    (p: Position) => {
      const state = hotStore.getState()
      const sectorStock = state.sectorStocks[normalizeStockCode(p.stk_cd)]
      return {
        name: p.stk_nm || '',
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
      }
    }
  ),
  {
    key: 'cur_price', label: '현재가', align: 'right', flash: true, minWidth: 78, maxWidth: 90,
    render: (p) => {
      const sectorStock = hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = sectorStock?.cur_price
      if (curPrice == null) return createPriceCell(null, null)
      const buyPrice = p.buy_price ?? p.avg_price ?? 0
      const diff = Number(curPrice) - buyPrice
      const rate = buyPrice > 0 ? (diff / buyPrice) * 100 : 0
      return createPriceCell(Number(curPrice), rate)
    },
  },
  {
    key: 'buy_price', label: '매수가', align: 'right', minWidth: 60, maxWidth: 72,
    render: (p) => createNumberCell(p.buy_price ?? p.avg_price ?? 0),
  },
  {
    key: 'buy_amt', label: '매수금액', align: 'right', minWidth: 72, maxWidth: 85,
    render: (p) => createNumberCell(p.buy_amt ?? 0),
  },
  {
    key: 'pnl', label: '평가손익', align: 'right', minWidth: 72, maxWidth: 85,
    render: (p) => {
      const sectorStock = hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = sectorStock?.cur_price ?? p.cur_price
      const buyPrice = p.buy_price ?? p.avg_price ?? 0
      const qty = p.qty ?? 0
      const pnl = (Number(curPrice) - buyPrice) * qty
      const span = document.createElement('span')
      span.style.color = rateColor(pnl)
      span.textContent = fmtComma(pnl)
      return span
    },
  },
  {
    key: 'rate', label: '수익률', align: 'right', minWidth: 60, maxWidth: 72,
    render: (p) => {
      const sectorStock = hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]
      const curPrice = sectorStock?.cur_price ?? p.cur_price
      const buyPrice = p.buy_price ?? p.avg_price ?? 0
      const rate = buyPrice > 0 ? ((Number(curPrice) - buyPrice) / buyPrice) * 100 : 0
      const span = document.createElement('span')
      span.style.color = rateColor(rate)
      span.textContent = fmtRate(rate) + '%'
      return span
    },
  },
  {
    key: 'qty', label: '수량', align: 'right', minWidth: 48, maxWidth: 56,
    render: (p) => createNumberCell(p.qty ?? 0),
  },
  {
    key: 'buy_date', label: '매수일자', align: 'center', minWidth: 80, maxWidth: 80,
    render: (p) => {
      const span = document.createElement('span')
      span.textContent = p.buy_date || ''
      const today = new Date()
      const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
      span.style.color = p.buy_date === todayStr ? COLOR.neutral : COLOR.disabled
      return span
    },
  },
]

let dataTable: DataTableApi<Position> | null = null
let unsubStore: (() => void) | null = null
let _rafId: number | null = null
let _summaryRafId: number | null = null
let onRealDataTick: ((e: Event) => void) | null = null
let _mounted = false

/* ── 보유주식 요약 행 참조 ── */
let summaryEvalBadge: BadgeHandle | null = null
let summaryPnlBadge: BadgeHandle | null = null
let summaryRateBadge: BadgeHandle | null = null

/** 보유주식 요약 행 렌더 — positions + sectorStocks에서 직접 계산 (개별 종목 행과 동일 소스·공식) */
function renderSummary(): void {
  const state = hotStore.getState()
  const count = state.positionCount ?? state.positions.length
  const { evalTotal, evalPnl, evalRate } = computeHoldingsSummary(state.positions, state.sectorStocks)

  if (summaryEvalBadge) {
    updateBadge(summaryEvalBadge, fmtComma(evalTotal), {
      statusText: `(${count}종목) `,
      statusColor: COLOR.code,
    })
  }

  const color = pnlColor(evalPnl)
  const pnlSign = evalPnl > 0 ? '+' : ''
  const rateSign = evalRate > 0 ? '+' : ''

  if (summaryPnlBadge) {
    updateBadge(summaryPnlBadge, `${pnlSign}${fmtComma(evalPnl)}`, { valueColor: color })
  }
  if (summaryRateBadge) {
    updateBadge(summaryRateBadge, `${rateSign}${evalRate.toFixed(2)}`, { valueColor: color })
  }
}

function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('sell-position')
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  // 헤더: 제목
  const headerRow = createCardHeaderWithMargin('보유종목', undefined, '4px')
  root.appendChild(headerRow)

  // 보유주식 요약 배지 행 — 공통 컴포넌트 (flex 3등분 고정)
  const summaryRow = createBadgeRow()
  summaryEvalBadge = createBadge('📊 보유주식 평가금액', '원')
  summaryPnlBadge = createBadge('📉 평가손익', '원')
  summaryRateBadge = createBadge('📈 수익률', '%')
  summaryRow.appendChild(summaryEvalBadge.el)
  summaryRow.appendChild(summaryPnlBadge.el)
  summaryRow.appendChild(summaryRateBadge.el)
  root.appendChild(summaryRow)

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
  container.appendChild(root)

  const state = hotStore.getState()

  const initialPositions = state.positions
  dataTable.updateRows(initialPositions)
  renderSummary()

  // Store 구독 — reference equality guard + rAF 배칭
  {
    let prevPositions = state.positions
    let prevSectorStocks = state.sectorStocks
    let prevAccount = state.account

    unsubStore = hotStore.subscribe((state) => {
      const positionsChanged = state.positions !== prevPositions
      const sectorStocksChanged = state.sectorStocks !== prevSectorStocks
      const accountChanged = state.account !== prevAccount

      prevPositions = state.positions
      prevSectorStocks = state.sectorStocks
      prevAccount = state.account

      // account 변경 시 요약 행 즉시 갱신 (rAF 배칭 불필요 — 텍스트 4개만 교체)
      if (accountChanged) {
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
      } else {
        // 보유 종목 없음
      }
    })
  }

  // O(1) 초저지연 DOM 갱신 이벤트 리스너
  onRealDataTick = (e: Event) => {
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
  }
  window.addEventListener('real-data-tick', onRealDataTick)
}

function unmount(): void {
  _mounted = false
  notifyPageInactive('sell-position')
  if (onRealDataTick) {
    window.removeEventListener('real-data-tick', onRealDataTick)
    onRealDataTick = null
  }
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  if (_summaryRafId !== null) { cancelAnimationFrame(_summaryRafId); _summaryRafId = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  summaryEvalBadge = null
  summaryPnlBadge = null
  summaryRateBadge = null
}

export default { mount, unmount }