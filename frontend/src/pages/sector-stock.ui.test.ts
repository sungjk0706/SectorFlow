// frontend/src/pages/sector-stock.ui.test.ts
// sector-stock.ui.ts 목업 데이터 렌더링 검증

import { createSectorStockCard, type SectorStockProps, type SectorScoreRow } from './sector-stock.ui'
import type { SectorStock } from '../types'

// 목업 데이터
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
  '035420': {
    code: '035420',
    name: 'NAVER',
    sector: 'IT소프트웨어',
    cur_price: 180000,
    change: -2000,
    change_rate: -1.10,
    trade_amount: 300000000000,
    avg_amt_5d: 350000000000,
    market_type: 'KOSPI',
    nxt_enable: true,
    strength: 62,
  },
}

const mockSectorScores: SectorScoreRow[] = [
  { rank: 1, sector: '반도체', total: 45, final_score: 85.5, rise_ratio: 65.2, total_trade_amount: 125000000000 },
  { rank: 2, sector: 'IT소프트웨어', total: 24, final_score: 68.9, rise_ratio: 49.8, total_trade_amount: 65000000000 },
]

const mockProps: SectorStockProps = {
  sectorStocks: mockSectorStocks,
  sectorScores: mockSectorScores,
  sectorOrder: ['반도체', 'IT소프트웨어'],
  selectedSector: null,
  maxTargets: 3,
  minTradeAmt: 660,
  wsSubscribed: true,
  onSearch: () => {},
  onClearSectorFilter: () => {},
}

// 테스트 실행
function testSectorStockCard(): void {
  console.log('[테스트] sector-stock.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createSectorStockCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: SectorStockProps = {
    ...mockProps,
    selectedSector: '반도체',
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] sector-stock.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testSectorStockCard()
}
