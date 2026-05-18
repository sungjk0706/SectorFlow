// frontend/src/pages/sell-position.ui.ts
// 보유종목 페이지 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createDataTable, type DataTableApi, type ColumnDef } from '../components/common/data-table'
import { createGlobalWsBadge } from '../settings'
import { createCardTitle } from '../components/common/card-title'
import { rateColor, fmtComma, fmtRate, createCodeCell, createStockNameColumn, createNumberCell, createPriceCell } from '../components/common/ui-styles'
import type { Position } from '../types'
import type { SectorStock } from '../types'

// ── Props 타입 정의 ──

export interface SellPositionProps {
  // 보유종목 데이터
  positions: Position[]
  
  // 업종별 종목 데이터 (종목명 표시용)
  sectorStocks: Record<string, SectorStock>
  
  // 실시간 상태
  wsSubscribed: boolean
}

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
      const sectorStock = p.sectorStock
      return {
        name: p.stk_nm || '',
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
      }
    }
  ),
  {
    key: 'cur_price', label: '현재가', align: 'right',
    flash: true,
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

/* ── 컴포넌트 생성 함수 ── */

export function createSellPositionCard(props: SellPositionProps): { el: HTMLElement; update: (newProps: SellPositionProps) => void; destroy: () => void } {
  let root: HTMLElement | null = document.createElement('div')
  Object.assign(root.style, { display: 'flex', flexDirection: 'column', height: '100%' })

  let dataTable: DataTableApi<Position> | null = null
  let wsBadge: HTMLElement | null = null

  // 헤더: 제목 + WS 상태 배지
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' })
  headerRow.appendChild(createCardTitle('보유종목'))

  wsBadge = createGlobalWsBadge()
  headerRow.appendChild(wsBadge)
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
  })

  scrollContainer.appendChild(dataTable.el)
  root.appendChild(scrollContainer)

  // 초기 데이터 준비 - sectorStocks를 position에 주입
  const positionsWithSectorStock = props.positions.map(p => ({
    ...p,
    sectorStock: props.sectorStocks[p.stk_cd || '']
  }))

  dataTable.updateRows(positionsWithSectorStock)

  // Props 업데이트 함수
  function update(newProps: SellPositionProps): void {
    Object.assign(props, newProps)
    
    // sectorStocks를 position에 주입
    const positionsWithSectorStock = props.positions.map(p => ({
      ...p,
      sectorStock: props.sectorStocks[p.stk_cd || '']
    }))
    
    dataTable?.updateRows(positionsWithSectorStock)
  }

  // 파괴 함수
  function destroy(): void {
    if (dataTable) { dataTable.destroy(); dataTable = null }
    if (root && root.parentNode) root.parentNode.removeChild(root)
    root = null
    wsBadge = null
  }

  return { el: root, update, destroy }
}
