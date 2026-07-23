/**
 * DataTable 컬럼 유형 및 표준 너비 상수.
 *
 * 모든 페이지와 공통 컬럼 팩토리는 이 상수를 참조하여 컬럼 너비를 통일한다.
 */

export type ColumnType =
  | 'seq'
  | 'code'
  | 'name'
  | 'sector'
  | 'price'
  | 'buy_price'
  | 'sell_price'
  | 'avg_buy_price'
  | 'change'
  | 'rate'
  | 'strength'
  | 'amount'
  | 'avg_amount'
  | 'high'
  | 'qty'
  | 'date'
  | 'date_short'
  | 'datetime'
  | 'total_amt'
  | 'fee'
  | 'tax'
  | 'pnl'
  | 'pnl_won'
  | 'pnl_rate'
  | 'order_ratio'
  | 'program_net'
  | 'boost'
  | 'news'
  | 'guard'
  | 'reason'
  | 'actions'
  | 'cmd'
  | 'desc'
  | 'count'
  | 'rank'
  | 'score'
  | 'sell_count'
  | 'buy_count'
  | 'trade_short'
  | 'rise_ratio'
  | 'qty_desc'
  | 'empty'

export interface ColumnWidth {
  minWidth: number
  maxWidth: number
}

export const COLUMN_WIDTH: Record<ColumnType, ColumnWidth> = {
  seq: { minWidth: 36, maxWidth: 36 },
  code: { minWidth: 72, maxWidth: 85 },
  name: { minWidth: 100, maxWidth: 140 },
  sector: { minWidth: 80, maxWidth: 180 },
  price: { minWidth: 80, maxWidth: 100 },
  buy_price: { minWidth: 80, maxWidth: 100 },
  sell_price: { minWidth: 80, maxWidth: 100 },
  avg_buy_price: { minWidth: 80, maxWidth: 100 },
  change: { minWidth: 70, maxWidth: 110 },
  rate: { minWidth: 60, maxWidth: 75 },
  strength: { minWidth: 60, maxWidth: 85 },
  amount: { minWidth: 80, maxWidth: 140 },
  avg_amount: { minWidth: 80, maxWidth: 120 },
  high: { minWidth: 60, maxWidth: 100 },
  qty: { minWidth: 36, maxWidth: 50 },
  date: { minWidth: 80, maxWidth: 115 },
  date_short: { minWidth: 40, maxWidth: 65 },
  datetime: { minWidth: 80, maxWidth: 150 },
  total_amt: { minWidth: 80, maxWidth: 120 },
  fee: { minWidth: 50, maxWidth: 60 },
  tax: { minWidth: 50, maxWidth: 90 },
  pnl: { minWidth: 80, maxWidth: 100 },
  pnl_won: { minWidth: 80, maxWidth: 120 },
  pnl_rate: { minWidth: 60, maxWidth: 85 },
  order_ratio: { minWidth: 80, maxWidth: 140 },
  program_net: { minWidth: 60, maxWidth: 85 },
  boost: { minWidth: 36, maxWidth: 60 },
  news: { minWidth: 50, maxWidth: 70 },
  guard: { minWidth: 36, maxWidth: 50 },
  reason: { minWidth: 50, maxWidth: 85 },
  actions: { minWidth: 50, maxWidth: 120 },
  cmd: { minWidth: 50, maxWidth: 70 },
  desc: { minWidth: 80, maxWidth: 160 },
  count: { minWidth: 36, maxWidth: 60 },
  rank: { minWidth: 24, maxWidth: 45 },
  score: { minWidth: 36, maxWidth: 60 },
  sell_count: { minWidth: 40, maxWidth: 70 },
  buy_count: { minWidth: 40, maxWidth: 70 },
  trade_short: { minWidth: 80, maxWidth: 120 },
  rise_ratio: { minWidth: 60, maxWidth: 85 },
  qty_desc: { minWidth: 50, maxWidth: 120 },
  empty: { minWidth: 0, maxWidth: 0 },
}
