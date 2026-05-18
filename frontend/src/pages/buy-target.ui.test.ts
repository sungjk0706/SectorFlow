// frontend/src/pages/buy-target.ui.test.ts
// buy-target.ui.ts 목업 데이터 렌더링 검증

import { createBuyTargetCard, type BuyTargetProps } from './buy-target.ui'
import type { BuyTarget } from '../types'

// 목업 데이터
const mockBuyTargets: BuyTarget[] = [
  {
    code: '005930',
    name: '삼성전자',
    market_type: 'KOSPI',
    nxt_enable: true,
    cur_price: 75000,
    change: 1500,
    change_rate: 2.04,
    strength: 85,
    order_ratio: [120, 80],
    high_5d: 78000,
    boost_score: 2.5,
    guard_pass: true,
    reason: '',
    rank: 1,
  },
  {
    code: '000660',
    name: 'SK하이닉스',
    market_type: 'KOSPI',
    nxt_enable: true,
    cur_price: 120000,
    change: 3000,
    change_rate: 2.56,
    strength: 78,
    order_ratio: [100, 100],
    high_5d: 125000,
    boost_score: 1.8,
    guard_pass: true,
    reason: '',
    rank: 2,
  },
  {
    code: '035420',
    name: 'NAVER',
    market_type: 'KOSPI',
    nxt_enable: true,
    cur_price: 180000,
    change: -2000,
    change_rate: -1.10,
    strength: 62,
    order_ratio: [80, 120],
    high_5d: 185000,
    boost_score: 0,
    guard_pass: false,
    reason: '보유중',
    rank: 3,
  },
]

const mockProps: BuyTargetProps = {
  buyTargets: mockBuyTargets,
  dailyBuySpent: 5000000,
  maxDailyTotalBuyAmt: 10000000,
  holdingCnt: 2,
  maxStockCnt: 5,
  buyAmtPerStock: 5000000,
  topTarget: mockBuyTargets[0],
  wsSubscribed: true,
}

// 테스트 실행
function testBuyTargetCard(): void {
  console.log('[테스트] buy-target.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createBuyTargetCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: BuyTargetProps = {
    ...mockProps,
    dailyBuySpent: 8000000,
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] buy-target.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testBuyTargetCard()
}
