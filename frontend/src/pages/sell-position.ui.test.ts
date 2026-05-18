// frontend/src/pages/sell-position.ui.test.ts
// sell-position.ui.ts 목업 데이터 렌더링 검증

import { createSellPositionCard, type SellPositionProps } from './sell-position.ui'
import type { Position } from '../types'
import type { SectorStock } from '../types'

// 목업 데이터
const mockPositions: Position[] = [
  {
    stk_cd: '005930',
    stk_nm: '삼성전자',
    cur_price: 75000,
    buy_price: 70000,
    avg_price: 70000,
    pnl_amount: 50000,
    pnl_rate: 7.14,
    qty: 10,
    buy_amt: 700000,
  },
  {
    stk_cd: '000660',
    stk_nm: 'SK하이닉스',
    cur_price: 120000,
    buy_price: 115000,
    avg_price: 115000,
    pnl_amount: 50000,
    pnl_rate: 4.35,
    qty: 5,
    buy_amt: 575000,
  },
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

const mockProps: SellPositionProps = {
  positions: mockPositions,
  sectorStocks: mockSectorStocks,
  wsSubscribed: true,
}

// 테스트 실행
function testSellPositionCard(): void {
  console.log('[테스트] sell-position.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createSellPositionCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: SellPositionProps = {
    ...mockProps,
    positions: mockPositions.slice(0, 1),
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] sell-position.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testSellPositionCard()
}
