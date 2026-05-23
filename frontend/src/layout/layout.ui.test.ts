// frontend/src/layout/layout.ui.test.ts
// layout UI 껍데기 테스트

import { createHeader, type HeaderUiProps } from './header.ui'
import { createSidebar, type SidebarUiProps } from './sidebar.ui'
import { createLayoutShell, type ShellUiProps } from './shell.ui'
import { createScrollPanel, type ScrollPanelUiProps } from './scroll-panel.ui'

/* ── 테스트 유틸리티 ── */

function createMockContainer(): HTMLElement {
  const div = document.createElement('div')
  document.body.appendChild(div)
  return div
}

/* ── 테스트 케이스 ── */

export function testLayoutUi(): void {
  console.log('[layout.ui.test] 테스트 시작')

  // Header 테스트
  const headerContainer = createMockContainer()
  const headerProps: HeaderUiProps = {
    marketPhase: { krx: '정규장', nxt: '메인마켓' },
    bootstrapStage: undefined,
    engineReady: true,
    avgAmtProgress: undefined,
    status: {
      is_test_mode: false,
      kiwoom_token_valid: true,
      kiwoom_connected: true,
      kospi: { price: 2500.5, rate: 1.5, change: 37.5 },
      kosdaq: { price: 800.3, rate: 0.8, change: 6.4 },
      index_polling: true,
    },
    settings: {
      ws_subscribe_on: true,
      time_scheduler_on: true,
      auto_buy_on: true,
      auto_sell_on: true,
      tele_on: true,
      buy_time_start: '09:00',
      buy_time_end: '15:20',
      sell_time_start: '09:00',
      sell_time_end: '15:20',
    },
  }
  const headerApi = createHeader(headerContainer, headerProps)
  console.log('[layout.ui.test] Header 렌더링 완료')

  if (headerContainer.querySelector('header')) {
    console.log('[layout.ui.test] ✓ Header 요소 렌더링 성공')
  } else {
    console.error('[layout.ui.test] ✗ Header 요소 렌더링 실패')
  }

  // Header Props 갱신 테스트
  headerProps.marketPhase = { krx: '휴장일', nxt: '휴식' }
  headerApi.update(headerProps)
  console.log('[layout.ui.test] Header Props 갱신 완료')

  document.body.removeChild(headerContainer)

  // Sidebar 테스트
  const sidebarContainer = createMockContainer()
  const sidebarProps: SidebarUiProps = {
    activePath: '#/sector-ranking',
    badges: { '#/buy-settings': 3 },
    onNavigate: (path) => console.log(`[TEST] onNavigate: ${path}`),
  }
  const sidebarApi = createSidebar(sidebarContainer, sidebarProps)
  console.log('[layout.ui.test] Sidebar 렌더링 완료')

  if (sidebarContainer.querySelector('nav')) {
    console.log('[layout.ui.test] ✓ Sidebar 요소 렌더링 성공')
  } else {
    console.error('[layout.ui.test] ✗ Sidebar 요소 렌더링 실패')
  }

  const menuItems = sidebarContainer.querySelectorAll('a')
  if (menuItems.length === 6) {
    console.log('[layout.ui.test] ✓ 메뉴 항목 수 검증 성공 (6개)')
  } else {
    console.error(`[layout.ui.test] ✗ 메뉴 항목 수 검증 실패 (기대: 6, 실제: ${menuItems.length})`)
  }

  // Sidebar Props 갱신 테스트
  sidebarProps.activePath = '#/buy-settings'
  sidebarApi.update(sidebarProps)
  console.log('[layout.ui.test] Sidebar Props 갱신 완료')

  document.body.removeChild(sidebarContainer)

  // Shell 테스트
  const shellContainer = createMockContainer()
  const shellProps: ShellUiProps = {
    headerProps,
    sidebarProps,
    layoutType: 'dual',
    overlayVisible: false,
  }
  const shellApi = createLayoutShell(shellContainer, shellProps)
  console.log('[layout.ui.test] Shell 렌더링 완료')

  if (shellContainer.querySelector('header') && shellContainer.querySelector('nav')) {
    console.log('[layout.ui.test] ✓ Shell Header + Sidebar 렌더링 성공')
  } else {
    console.error('[layout.ui.test] ✗ Shell Header + Sidebar 렌더링 실패')
  }

  // Shell 레이아웃 전환 테스트
  shellApi.setLayout('triple')
  console.log('[layout.ui.test] Shell 레이아웃 전환 완료 (dual -> triple)')

  // Shell Props 갱신 테스트
  shellProps.layoutType = 'full'
  shellApi.update(shellProps)
  console.log('[layout.ui.test] Shell Props 갱신 완료')

  document.body.removeChild(shellContainer)

  // ScrollPanel 테스트
  const scrollContainer = createMockContainer()
  const scrollProps: ScrollPanelUiProps = {
    cacheKey: 'test-key',
  }
  const scrollApi = createScrollPanel(scrollContainer, scrollProps)
  console.log('[layout.ui.test] ScrollPanel 렌더링 완료')

  if (scrollContainer.querySelector('div')) {
    console.log('[layout.ui.test] ✓ ScrollPanel 요소 렌더링 성공')
  } else {
    console.error('[layout.ui.test] ✗ ScrollPanel 요소 렌더링 실패')
  }

  // ScrollPanel 스크롤 테스트
  scrollApi.el.scrollTop = 100
  scrollApi.saveScroll()
  console.log('[layout.ui.test] ScrollPanel 스크롤 저장 완료')

  document.body.removeChild(scrollContainer)

  console.log('[layout.ui.test] 테스트 완료')
}

// 자동 실행 (브라우저 환경)
if (typeof window !== 'undefined') {
  (window as any).testLayoutUi = testLayoutUi
}
