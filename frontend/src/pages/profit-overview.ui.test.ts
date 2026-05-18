// frontend/src/pages/profit-overview.ui.test.ts
// profit-overview.ui.ts 목업 데이터 렌더링 검증

import { createProfitOverviewCard, type ProfitOverviewProps } from './profit-overview.ui'
import type { SectorStock } from '../types'

// 목업 데이터
const mockAccount = {
  deposit: 10000000,
  orderable: 5000000,
  total_eval_amount: 15000000,
  total_pnl: 500000,
  total_pnl_rate: 3.33,
  positionCount: 3,
  accumulated_investment: 10000000,
  initial_deposit: 10000000,
}

const mockBuyHistory: Record<string, unknown>[] = [
  { date: '2026-04-14', time: '09:15:00', stk_cd: '005930', stk_nm: '삼성전자', price: 70000, qty: 100, total_amt: 7001050, fee: 1050 },
  { date: '2026-04-14', time: '09:22:00', stk_cd: '000660', stk_nm: 'SK하이닉스', price: 185000, qty: 50, total_amt: 9251388, fee: 1388 },
]

const mockSellHistory: Record<string, unknown>[] = [
  { date: '2026-04-14', time: '10:05:00', stk_cd: '005930', stk_nm: '삼성전자', avg_buy_price: 70000, price: 71500, qty: 100, buy_total_amt: 7001050, total_amt: 7134627, realized_pnl: 133577, pnl_rate: 1.91, fee: 1073, tax: 14300 },
]

const mockDailySummary: Record<string, unknown>[] = [
  { date: '2026-04-14', sell_count: 2, realized_pnl: 133577, pnl_rate: 1.91 },
  { date: '2026-04-13', sell_count: 1, realized_pnl: -50000, pnl_rate: -0.5 },
]

const mockSectorStocks: Record<string, SectorStock> = {
  '005930': {
    code: '005930',
    name: '삼성전자',
    sector: '반도체',
    cur_price: 75000,
    change: 1500,
    change_rate: 2.04,
    trade_amount: 1500000000000,
    avg_amt_5d: 1200000000000,
    market_type: 'KOSPI',
    nxt_enable: true,
    strength: 85,
  },
  '000660': {
    code: '000660',
    name: 'SK하이닉스',
    sector: '반도체',
    cur_price: 120000,
    change: 3000,
    change_rate: 2.56,
    trade_amount: 800000000000,
    avg_amt_5d: 650000000000,
    market_type: 'KOSPI',
    nxt_enable: true,
    strength: 78,
  },
}

const mockProps: ProfitOverviewProps = {
  account: mockAccount,
  buyHistory: mockBuyHistory,
  sellHistory: mockSellHistory,
  dailySummary: mockDailySummary,
  tradeMode: 'real',
  todayBuyAmt: 7001050,
  todaySellAmt: 7134627,
  cumulativePnl: 133577,
  cumulativePnlRate: 1.91,
  todayPnl: 133577,
  todayRate: 1.91,
  monthPnl: 83577,
  monthRate: 0.83,
  totalPnl: 133577,
  totalRate: 1.91,
  wsSubscribed: true,
  sectorStocks: mockSectorStocks,
  onTabChange: () => {},
  onDateFilter: () => {},
  onDrilldownToggle: () => {},
  onChartBarClick: () => {},
  onChartDateRangeChange: () => {},
}

// 테스트 실행
function testProfitOverviewCard(): void {
  console.log('[테스트] profit-overview.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createProfitOverviewCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: ProfitOverviewProps = {
    ...mockProps,
    todayPnl: 200000,
    todayRate: 2.5,
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] profit-overview.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testProfitOverviewCard()
}
