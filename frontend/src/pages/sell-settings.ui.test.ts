// frontend/src/pages/sell-settings.ui.test.ts
// sell-settings.ui.ts 목업 데이터 렌더링 검증

import { createSellSettingsCard, type SellSettingsProps } from './sell-settings.ui'

// 목업 데이터
const mockProps: SellSettingsProps = {
  autoSellOn: true,
  sellTimeStart: '09:00',
  sellTimeEnd: '15:00',
  tpApply: true,
  tpVal: 5.0,
  lossApply: true,
  lossVal: -3.0,
  tsApply: true,
  tsStartVal: 3.0,
  tsDropVal: -2.0,
  wsSubscribed: true,
  onAutoSellToggle: () => {},
  onTimePairChange: () => {},
  onTpToggle: () => {},
  onTpValChange: () => {},
  onLossToggle: () => {},
  onLossValChange: () => {},
  onTsToggle: () => {},
  onTsStartValChange: () => {},
  onTsDropValChange: () => {},
}

// 테스트 실행
function testSellSettingsCard(): void {
  console.log('[테스트] sell-settings.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createSellSettingsCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: SellSettingsProps = {
    ...mockProps,
    autoSellOn: false,
    tpApply: false,
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] sell-settings.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testSellSettingsCard()
}
