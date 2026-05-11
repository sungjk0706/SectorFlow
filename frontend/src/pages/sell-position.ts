// frontend/src/pages/sell-position.ts
// 보유종목 페이지 — 매수후보 코드 기반 최종본

// frontend/src/pages/sell-position.ts

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { appStore } from '../stores/appStore'
import { notifyPageActive, notifyPageInactive } from '../api/ws'
import { createCardTitle } from '../components/common/card-title'
import { createWsStatusBadge } from '../components/common/setting-row'
import { rateColor, fmtComma, fmtRate, createCodeCell, createStockNameColumn, createNumberCell, createPriceCell } from '../components/common/ui-styles'
import type { Position } from '../types'

const COLUMNS: ColumnDef<Position>[] = [
  {
    key: 'no', label: '순번', align: 'center',
    render: (_p, index) => String(index + 1),
  },
  {
    key: 'stk_cd', label: '종목코드', align: 'center',
    render: (p) => createCodeCell(p.stk_cd || ''),
  },
  createStockNameColumn<Position>(
    (p: Position) => {
      const state = appStore.getState()
      const sectorStock = state.sectorStocks[p.stk_cd || '']
      return {
        name: p.stk_nm || '',
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
      }
    }
  ),
  {
    key: 'cur_price', label: '현재가', align: 'right',
    render: (p) => {
      const buyPrice = p.buy_price ?? p.avg_price ?? 0
      const curPrice = p.cur_price ?? 0
      const diff = curPrice - buyPrice
      const rate = buyPrice > 0 ? (diff / buyPrice) * 100 : 0
      return createPriceCell(curPrice, rate)
    },
  },
  {
    key: 'pnl', label: '평가손익', align: 'right',
    render: (p) => {
      const pnl = p.pnl_amount ?? 0
      const span = document.createElement('span')
      span.style.color = rateColor(pnl)
      span.textContent = fmtComma(pnl)
      return span
    },
  },
  {
    key: 'rate', label: '수익률', align: 'right',
    render: (p) => {
      const rate = p.pnl_rate ?? 0
      const span = document.createElement('span')
      span.style.color = rateColor(rate)
      span.textContent = fmtRate(rate) + '%'
      return span
    },
  },
  {
    key: 'buy_price', label: '매수가', align: 'right',
    render: (p) => createNumberCell(p.buy_price ?? p.avg_price ?? 0),
  },
  {
    key: 'qty', label: '수량', align: 'right',
    render: (p) => createNumberCell(p.qty ?? 0),
  },
  {
    key: 'buy_amt', label: '매수금액', align: 'right',
    render: (p) => createNumberCell(p.buy_amt ?? 0),
  },
]

let dataTable: DataTableApi<Position> | null = null
let unsubStore: (() => void) | null = null
let wsBadge: ReturnType<typeof createWsStatusBadge> | null = null
let _rafId: number | null = null
let _mounted = false

function mount(container: HTMLElement): void {
  _mounted = true
  notifyPageActive('sell-position')
  const root = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  // 헤더: 제목 + WS 상태 배지
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' })
  headerRow.appendChild(createCardTitle('보유종목'))

  const initState = appStore.getState()
  const isTestMode = initState.settings?.trade_mode === 'test'
  wsBadge = createWsStatusBadge({
    subscribed: !isTestMode,
    broker: isTestMode ? undefined : 'kiwoom',
    label: isTestMode ? '테스트모드' : undefined,
  })
  headerRow.appendChild(wsBadge.el)
  root.appendChild(headerRow)

  const scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, { 
    flex: '1', 
    minHeight: '200px', 
    display: 'flex', 
    flexDirection: 'column'
  })

  dataTable = createDataTable<Position>({
    columns: COLUMNS,
    virtualScroll: true,
    keyFn: (p) => p.stk_cd || String(p.stk_nm),
    emptyText: '보유종목이 없습니다.',
    stickyHeader: true,
    zebraStriping: true,
    priceFn: (p) => p.cur_price ?? 0,
  })

  scrollContainer.appendChild(dataTable.el)
  root.appendChild(scrollContainer)
  container.appendChild(root)

  const state = appStore.getState()

  const initialPositions = state.positions
  dataTable.updateRows(initialPositions)

  // Store 구독 — reference equality guard + rAF coalescing
  {
    let prevPositions = state.positions
    let prevSectorStocks = state.sectorStocks

    unsubStore = appStore.subscribe((state) => {
      const positionsChanged = state.positions !== prevPositions
      const sectorStocksChanged = state.sectorStocks !== prevSectorStocks

      prevPositions = state.positions
      prevSectorStocks = state.sectorStocks

      // positions 참조 미변경 시 updateRows 생략
      if (!positionsChanged) {
        // sectorStocks만 변경 시 WS 뱃지만 업데이트
        if (sectorStocksChanged) {
          const isTest = state.settings?.trade_mode === 'test'
          wsBadge?.update(!isTest, isTest ? undefined : 'kiwoom', isTest ? '테스트모드' : undefined)
        }
        return
      }

      // rAF coalescing — 프레임당 1회만 갱신 예약
      if (_rafId === null) {
        _rafId = requestAnimationFrame(() => {
          _rafId = null
          if (!_mounted) return
          const latest = appStore.getState()
          dataTable?.updateRows(latest.positions)
        })
      }

      // WS 상태 뱃지 업데이트
      const isTest = state.settings?.trade_mode === 'test'
      wsBadge?.update(!isTest, isTest ? undefined : 'kiwoom', isTest ? '테스트모드' : undefined)
    })
  }
}

function unmount(): void {
  _mounted = false
  notifyPageInactive('sell-position')
  if (unsubStore) { unsubStore(); unsubStore = null }
  if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null }
  if (dataTable) { dataTable.destroy(); dataTable = null }
  wsBadge = null
}

export default { mount, unmount }