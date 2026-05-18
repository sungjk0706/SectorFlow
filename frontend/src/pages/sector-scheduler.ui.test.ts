// frontend/src/pages/sector-scheduler.ui.test.ts
// sector-scheduler.ui.ts 테스트

import { renderSectorSchedulerUi, updateSectorSchedulerUi, type SectorSchedulerUiProps } from './sector-scheduler.ui'

/* ── 테스트 유틸리티 ── */

function createMockContainer(): HTMLElement {
  const div = document.createElement('div')
  document.body.appendChild(div)
  return div
}

/* ── 테스트 케이스 ── */

export function testSectorSchedulerUi(): void {
  console.log('[sector-scheduler.ui.test] 테스트 시작')

  const container = createMockContainer()

  const mockProps: SectorSchedulerUiProps = {
    schedulerMarketCloseOn: true,
    scheduler5dDownloadOn: true,
    onToggleScheduler: (key, value) => console.log(`[TEST] onToggleScheduler: ${key} = ${value}`),
    onDeleteCache: (type) => console.log(`[TEST] onDeleteCache: ${type}`),
  }

  // 렌더링 테스트
  renderSectorSchedulerUi(container, mockProps)
  console.log('[sector-scheduler.ui.test] 렌더링 완료')

  // 스케줄러 카드 검증
  const schedulerCard = container.children[0] as HTMLElement
  if (schedulerCard.querySelector('.sf-card-title')?.textContent?.includes('장마감 후 데이터 갱신')) {
    console.log('[sector-scheduler.ui.test] ✓ 스케줄러 카드 타이틀 검증 성공')
  } else {
    console.error('[sector-scheduler.ui.test] ✗ 스케줄러 카드 타이틀 검증 실패')
  }

  // 토글 버튼 검증
  const toggles = schedulerCard.querySelectorAll('.sf-toggle-btn')
  if (toggles.length === 2) {
    console.log('[sector-scheduler.ui.test] ✓ 토글 버튼 수 검증 성공 (2개)')
  } else {
    console.error(`[sector-scheduler.ui.test] ✗ 토글 버튼 수 검증 실패 (기대: 2, 실제: ${toggles.length})`)
  }

  // 데이터 관리 카드 검증
  const dataManageCard = container.children[1] as HTMLElement
  if (dataManageCard.querySelector('.sf-card-title')?.textContent?.includes('데이터 관리')) {
    console.log('[sector-scheduler.ui.test] ✓ 데이터 관리 카드 타이틀 검증 성공')
  } else {
    console.error('[sector-scheduler.ui.test] ✗ 데이터 관리 카드 타이틀 검증 실패')
  }

  // 삭제 버튼 검증
  const deleteBtns = dataManageCard.querySelectorAll('button')
  if (deleteBtns.length === 2) {
    console.log('[sector-scheduler.ui.test] ✓ 삭제 버튼 수 검증 성공 (2개)')
  } else {
    console.error(`[sector-scheduler.ui.test] ✗ 삭제 버튼 수 검증 실패 (기대: 2, 실제: ${deleteBtns.length})`)
  }

  // Props 갱신 테스트
  mockProps.schedulerMarketCloseOn = false
  mockProps.scheduler5dDownloadOn = false
  updateSectorSchedulerUi(mockProps)
  console.log('[sector-scheduler.ui.test] Props 갱신 완료')

  // 정리
  document.body.removeChild(container)
  console.log('[sector-scheduler.ui.test] 테스트 완료')
}

// 자동 실행 (브라우저 환경)
if (typeof window !== 'undefined') {
  (window as any).testSectorSchedulerUi = testSectorSchedulerUi
}
