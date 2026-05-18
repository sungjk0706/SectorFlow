// frontend/src/pages/buy-settings.ui.test.ts
// buy-settings.ui.ts 목업 데이터 렌더링 검증

import { createBuySettingsCard, type BuySettingsProps } from './buy-settings.ui'

// 목업 데이터
const mockProps: BuySettingsProps = {
  autoBuyOn: true,
  buyTimeStart: '09:00',
  buyTimeEnd: '15:00',
  buyIndexGuardKospiOn: true,
  buyIndexKospiDrop: 5,
  buyIndexGuardKosdaqOn: true,
  buyIndexKosdaqDrop: 3,
  buyBlockRisePct: 10,
  buyBlockFallPct: 10,
  buyMinStrength: 50,
  boostHighBreakoutOn: true,
  boostHighBreakoutScore: 2.5,
  boostOrderRatioOn: true,
  boostOrderRatioPct: 20,
  boostOrderRatioScore: 1.5,
  maxDailyTotalBuyAmt: 10000000,
  maxStockCnt: 5,
  buyAmt: 5000000,
  wsSubscribed: true,
  onAutoBuyToggle: () => {},
  onTimePairChange: () => {},
  onKospiGuardToggle: () => {},
  onKospiDropChange: () => {},
  onKosdaqGuardToggle: () => {},
  onKosdaqDropChange: () => {},
  onRiseChange: () => {},
  onFallChange: () => {},
  onStrengthChange: () => {},
  onBoostHighToggle: () => {},
  onBoostHighScoreChange: () => {},
  onBoostOrderToggle: () => {},
  onBoostOrderRatioChange: () => {},
  onBoostOrderScoreChange: () => {},
  onMaxDailyChange: () => {},
  onMaxStockCntChange: () => {},
  onBuyAmtChange: () => {},
}

// 테스트 실행
function testBuySettingsCard(): void {
  console.log('[테스트] buy-settings.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createBuySettingsCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: BuySettingsProps = {
    ...mockProps,
    autoBuyOn: false,
    boostHighBreakoutOn: false,
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] buy-settings.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testBuySettingsCard()
}
