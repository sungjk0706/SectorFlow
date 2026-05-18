// frontend/src/pages/general-settings.ui.test.ts
// general-settings.ui.ts 목업 데이터 렌더링 검증

import { createGeneralSettingsCard, type GeneralSettingsProps } from './general-settings.ui'

// 목업 데이터
const mockSettings: Record<string, unknown> = {
  time_scheduler_on: true,
  holiday_guard_on: true,
  ws_subscribe_on: true,
  ws_subscribe_start: '09:00',
  ws_subscribe_end: '15:00',
  tele_on: false,
  telegram_chat_id: '',
  telegram_bot_token: '',
  trade_mode: 'test',
  test_virtual_deposit: 10000000,
  kiwoom_app_key_real: '',
  kiwoom_app_secret_real: '',
  kiwoom_account_no_real: '',
}

const mockProps: GeneralSettingsProps = {
  settings: mockSettings,
  isTradingDay: true,
  tradingDayLoading: false,
  wsSubscribed: true,
  onMasterToggle: () => {},
  onHolidayToggle: () => {},
  onWsToggle: () => {},
  onWsTimeChange: () => {},
  onTeleToggle: () => {},
  onTeleSave: () => {},
  onTradeModeChange: () => {},
  onDepositCharge: () => {},
  onDepositChange: () => {},
  onTestDataReset: () => {},
  onApiSave: () => {},
}

// 테스트 실행
function testGeneralSettingsCard(): void {
  console.log('[테스트] general-settings.ui.ts 렌더링 검증 시작')
  
  // 컨테이너 생성
  const container = document.createElement('div')
  document.body.appendChild(container)
  
  // 컴포넌트 마운트
  const card = createGeneralSettingsCard(mockProps)
  container.appendChild(card.el)
  
  console.log('[테스트] 컴포넌트 마운트 완료')
  console.log('[테스트] DOM 요소 수:', container.children.length)
  
  // Props 업데이트 테스트
  const updatedProps: GeneralSettingsProps = {
    ...mockProps,
    settings: { ...mockSettings, time_scheduler_on: false },
  }
  card.update(updatedProps)
  console.log('[테스트] Props 업데이트 완료')
  
  // 파괴 테스트
  card.destroy()
  container.remove()
  console.log('[테스트] 컴포넌트 파괴 완료')
  
  console.log('[테스트] general-settings.ui.ts 렌더링 검증 완료')
}

// 브라우저 환경에서 실행
if (typeof window !== 'undefined') {
  testGeneralSettingsCard()
}
