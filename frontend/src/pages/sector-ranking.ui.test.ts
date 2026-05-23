// frontend/src/pages/sector-ranking.ui.test.ts
// sector-ranking.ui.ts 목업 데이터 렌더링 검증

import { createSectorAnalysisCard, type SectorAnalysisProps, type SectorScoreRow } from './sector-ranking.ui'

// 목업 데이터
const mockSectorScores: SectorScoreRow[] = [
  { rank: 1, sector: '반도체', total: 45, final_score: 85.5, rise_ratio: 65.2, total_trade_amount: 125000000000 },
  { rank: 2, sector: '자동차', total: 32, final_score: 78.3, rise_ratio: 58.7, total_trade_amount: 98000000000 },
  { rank: 3, sector: '바이오', total: 28, final_score: 72.1, rise_ratio: 52.4, total_trade_amount: 76000000000 },
  { rank: 4, sector: 'IT소프트웨어', total: 24, final_score: 68.9, rise_ratio: 49.8, total_trade_amount: 65000000000 },
  { rank: 5, sector: '통신', total: 18, final_score: 61.2, rise_ratio: 45.3, total_trade_amount: 52000000000 },
]

const mockProps: SectorAnalysisProps = {
  minTradeAmt: 660,
  minRiseRatio: 50,
  trimChangeRate: 10,
  trimTradeAmt: 15,
  maxTargets: 3,
  riseRatioWeight: 50,
  sectorScores: mockSectorScores,
  selectedSector: null,
  wsSubscribed: true,
  onMinTradeAmtChange: () => {},
  onMinRiseRatioChange: () => {},
  onTrimChangeRateChange: () => {},
  onTrimTradeAmtChange: () => {},
  onMaxTargetsChange: () => {},
  onRiseRatioWeightChange: () => {},
  onSectorClick: () => {},
}

// 테스트 실행
function testSectorAnalysisCard(): void {
  console.log('[테스트] sector-ranking.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createSectorAnalysisCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: SectorAnalysisProps = {
    ...mockProps,
    selectedSector: '반도체',
    maxTargets: 2,
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] sector-ranking.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testSectorAnalysisCard()
}
