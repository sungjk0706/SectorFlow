// frontend/src/pages/profit-columns.ts
// 수익 페이지 테이블 컬럼 정의 — profit-detail.ts가 사용하는 매수/매도/드릴다운 컬럼

import type { ColumnDef } from '../components/common/data-table'
import { pnlColor, fmtWon, fmtComma, createStockNameColumn, createCodeCell, createNumberCell, COLOR } from '../components/common/ui-styles'
import { hotStore, normalizeStockCode } from '../stores/hotStore'
import type { DailyDrilldownRow } from './profit-shared'

/* ── 매수 컬럼 (7개) ── */
export const BUY_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', type: 'seq', render: (_, i) => String(i + 1) },
  { key: 'datetime', label: '일시', align: 'center', type: 'datetime', render: r => { const d = String(r.date ?? ''); const t = String(r.time ?? ''); const dd = d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d; return dd + (t ? ' ' + t : '') } },
  { key: 'stk_cd', label: '종목코드', align: 'center', type: 'code', render: r => createCodeCell(String(r.stk_cd ?? '')) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      const state = hotStore.getState()
      const sectorStock = state.sectorStocks[normalizeStockCode(String(r.stk_cd ?? ''))]
      return {
        name: String(r.stk_nm ?? ''),
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
      }
    }
  ),
  { key: 'price', label: '매수가', align: 'right', type: 'buy_price', render: r => createNumberCell(Number(r.price ?? 0)) },
  { key: 'qty', label: '수량', align: 'right', type: 'qty', render: r => createNumberCell(Number(r.qty ?? 0)) },
  { key: 'total_amt', label: '매수 지출(수수료 포함)', align: 'right', type: 'total_amt', render: r => fmtWon(Number(r.total_amt ?? 0)) },
  { key: 'fee', label: '수수료', align: 'right', type: 'fee', render: r => fmtWon(Number(r.fee ?? 0)) },
]

/* ── 매도 컬럼 (12개) ── */
export const SELL_COLS: ColumnDef<Record<string, unknown>>[] = [
  { key: 'no', label: '순번', align: 'center', type: 'seq', render: (_, i) => String(i + 1) },
  { key: 'datetime', label: '일시', align: 'center', type: 'datetime', render: r => { const d = String(r.date ?? ''); const t = String(r.time ?? ''); const dd = d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d; return dd + (t ? ' ' + t : '') } },
  { key: 'stk_cd', label: '종목코드', align: 'center', type: 'code', render: r => createCodeCell(String(r.stk_cd ?? '')) },
  createStockNameColumn<Record<string, unknown>>(
    (r: Record<string, unknown>) => {
      const state = hotStore.getState()
      const sectorStock = state.sectorStocks[normalizeStockCode(String(r.stk_cd ?? ''))]
      return {
        name: String(r.stk_nm ?? ''),
        market_type: sectorStock?.market_type,
        nxt_enable: sectorStock?.nxt_enable
      }
    }
  ),
  { key: 'buy_date', label: '매수일시', align: 'center', type: 'date_short', render: r => { const d = String(r.buy_date ?? ''); return d.length >= 10 ? d.slice(5, 7) + '/' + d.slice(8, 10) : d } },
  { key: 'avg_buy_price', label: '매수가', align: 'right', type: 'avg_buy_price', render: r => createNumberCell(Number(r.avg_buy_price ?? 0)) },
  { key: 'price', label: '매도가', align: 'right', type: 'sell_price', render: r => {
    const sell = Number(r.price ?? 0)
    const pnl = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(pnl)
    span.textContent = fmtComma(sell)
    return span
  }},
  { key: 'qty', label: '수량', align: 'right', type: 'qty', render: r => createNumberCell(Number(r.qty ?? 0)) },
  { key: 'buy_total_amt', label: '매수 지출(수수료 포함)', align: 'right', type: 'total_amt', render: r => fmtWon(Number(r.buy_total_amt ?? 0)) },
  { key: 'total_amt', label: '매도 수령(실수령)', align: 'right', type: 'total_amt', render: r => {
    const v = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = fmtWon(Number(r.total_amt ?? 0))
    return span
  }},
  { key: 'realized_pnl', label: '실현손익', align: 'right', type: 'pnl_won', render: r => {
    const v = Number(r.realized_pnl ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = `${v > 0 ? '+' : ''}${v.toLocaleString()}원`
    return span
  }},
  { key: 'pnl_rate', label: '수익률', align: 'right', type: 'pnl_rate', render: r => {
    const v = Number(r.pnl_rate ?? 0)
    const span = document.createElement('span')
    span.style.color = pnlColor(v)
    span.textContent = `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
    return span
  }},
  { key: 'fee', label: '수수료', align: 'right', type: 'fee', render: r => fmtWon(Number(r.fee ?? 0)) },
  { key: 'tax', label: '세금', align: 'right', type: 'tax', render: r => fmtWon(Number(r.tax ?? 0)) },
]

/* ── 드릴다운 컬럼 (팩토리 — onDateClick 콜백 주입) ── */
export function createDrilldownCols(onDateClick: (date: string) => void): ColumnDef<DailyDrilldownRow>[] {
  return [
    { key: 'date', label: '날짜', align: 'center', type: 'date_short', render: r => {
      const span = document.createElement('span')
      span.style.cursor = 'pointer'
      span.style.color = COLOR.down
      span.style.textDecoration = 'underline'
      span.textContent = r.date.slice(5) // MM-DD
      span.addEventListener('click', () => onDateClick(r.date))
      return span
    }},
    { key: 'sellCount', label: '매도건수', align: 'right', type: 'sell_count', render: r => String(r.sellCount) },
    { key: 'buyCount', label: '매수건수', align: 'right', type: 'buy_count', render: r => String(r.buyCount) },
    { key: 'pnl', label: '당일손익', align: 'right', type: 'pnl_won', render: r => {
      const span = document.createElement('span')
      span.style.color = pnlColor(r.pnl)
      span.textContent = fmtWon(r.pnl)
      return span
    }},
    { key: 'rate', label: '당일수익률', align: 'right', type: 'pnl_rate', render: r => {
      const span = document.createElement('span')
      span.style.color = pnlColor(r.rate)
      span.textContent = `${r.rate > 0 ? '+' : ''}${r.rate.toFixed(2)}%`
      return span
    }},
  ]
}
