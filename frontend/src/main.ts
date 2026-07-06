// frontend/src/main.ts — 앱 진입점 (순수 TS, React 없음)
// 기존 main.tsx + App.tsx의 초기화 로직을 통합

import { uiStore } from './stores/uiStore'
import { wsClient, wsSettingsClient, wsOrdersClient } from './api/ws'
import { bindWSToStore } from './binding'
import { createLayoutShell } from './layout/shell'
import { createRouter } from './router'
import type { RouteConfig, PageModule } from './router'
import { initToastContainer } from './components/common/toast'
import { stockClassificationStore } from './stores/stockClassificationStore'
import { api } from './api/client'
import { COLOR } from './components/common/ui-styles'
// Import sector-stock Web Component to register custom element
import './pages/sector-stock'

// ── FPS 모니터링 (1초 윈도우) ──
function startFpsMonitor(): void {
  let frameCount = 0
  let lastTime = performance.now()
  let lowFpsStreak = 0

  function tick(): void {
    frameCount++
    const now = performance.now()
    const elapsed = now - lastTime
    if (elapsed >= 1000) {
      const fps = Math.round((frameCount * 1000) / elapsed)
      if (fps < 50) {
        lowFpsStreak++
        if (lowFpsStreak >= 3) {
          console.warn(`[통계] FPS 저하 지속 — ${fps}fps (3초+)`)
        }
      } else {
        lowFpsStreak = 0
      }
      frameCount = 0
      lastTime = now
    }
    requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

// ── Layout Shell (모듈 레벨 export — stock-classification.ts 등에서 import) ──
export const shell = createLayoutShell()

// ── 라우트 설정 ──

const routes: RouteConfig[] = [
  {
    path: '#/sector-ranking',
    layout: 'triple',
    load: () => import('./pages/sector-ranking-page').then(m => m.default),
  },
  {
    path: '#/buy-settings',
    layout: 'dual',
    load: () => import('./pages/buy-target').then(m => m.default),
    settingsCard: () => import('./pages/buy-settings').then(m => m.default),
  },
  {
    path: '#/sell-settings',
    layout: 'dual',
    load: () => import('./pages/sell-position').then(m => m.default),
    settingsCard: () => import('./pages/sell-settings').then(m => m.default),
  },
  {
    path: '#/profit-overview',
    layout: 'full',
    load: () => import('./pages/profit-overview').then(m => m.default),
  },
  {
    path: '#/stock-classification',
    layout: 'triple',
    load: () => import('./pages/stock-classification').then(m => m.default),
  },
  {
    path: '#/general-settings',
    layout: 'single',
    load: () => import('./pages/general-settings').then(m => m.default),
  },
]

// ── 앱 초기화 ──

declare global {
  interface Window { uiStore: typeof uiStore }
}

function main(): void {
  window.uiStore = uiStore
  // 0. 전역 스타일 적용 (HTS 금융 표준 - ui-styles.ts 표준 준수)
  Object.assign(document.body.style, {
    fontFamily: "Tahoma, '굴림', Gulim, sans-serif",
    fontSize: '13px',
    fontWeight: 'normal',
    color: '#1a1a1a',
    backgroundColor: '#ffffff',
    lineHeight: '1.4',
  })

  // HTS 숫자/기호 스타일 (고정폭, 우측 정렬 느낌)
  const htsStyle = document.createElement('style')
  htsStyle.textContent = `
    /* HTS 스타일 테이블 숫자 - 고정폭 + 우측 정렬감 */
    td, th {
      font-family: Tahoma, '굴림', Gulim, sans-serif;
      font-size: 13px;
      letter-spacing: 0.5px;
    }
    
    /* 가격/거래대금 컬럼 (HTS처럼 깔끔하게) */
    .price, .amount, .avg-amount {
      text-align: right;
      font-family: Tahoma, '굴림', Gulim, sans-serif;
    }
    
    /* 상승/하락 색상 (HTS 전통) */
    .up, .positive {
      color: ${COLOR.up};
    }
    .down, .negative {
      color: ${COLOR.down};
    }
    .same, .even {
      color: #1a1a1a;
    }
    
    /* 등락률 기호 (HTS 스타일) */
    .rate-up::before {
      content: "▲";
      color: ${COLOR.up};
      margin-right: 2px;
    }
    .rate-down::before {
      content: "▼";
      color: ${COLOR.down};
      margin-right: 2px;
    }
    
    /* 음수/양수 구분 */
    .minus {
      color: ${COLOR.down};
    }
    .plus {
      color: ${COLOR.up};
    }
  `
  document.head.appendChild(htsStyle)

  // table 요소도 body 폰트 상속
  const globalStyle = document.createElement('style')
  globalStyle.textContent = 'table, th, td, input, button, select { font-family: inherit; font-size: inherit; }'
  document.head.appendChild(globalStyle)

  // 1. WS → Store 바인딩
  bindWSToStore(wsClient, wsSettingsClient, wsOrdersClient)

  // 2. Layout Shell 마운트
  const rootEl = document.getElementById('root')!
  rootEl.appendChild(shell.el)

  // 3. 토스트 컨테이너 초기화
  initToastContainer(shell.el)

  // 4. Router 초기화
  const router = createRouter(routes)

  // 라우트 변경 시 레이아웃 전환 + 사이드바 활성 메뉴 갱신
  router.onRouteChange((path) => {
    shell.setActiveRoute(path)
    const route = routes.find(r => r.path === path)
    if (route) {
      shell.setLayout(route.layout)
    }
  })

  // Router가 페이지를 마운트할 때 dual 레이아웃 처리:
  // - settingsCard → leftPanel, load → rightPanel
  // Router의 handleRouteChange를 확장하여 패널 분리 마운트 처리
  patchRouterForDualLayout(router, shell)

  // Router 초기화 — 메인 콘텐츠는 rightPanel에 마운트
  router.init(shell.rightPanel)

  // 5. 오버레이 제어 (settings가 없어서 기본 렌더링이 불가능할 때만 로딩 표시)
  uiStore.subscribe((state) => {
    if (state.settings === null) {
      shell.setOverlay(true, '로딩 중…')
    } else {
      shell.setOverlay(false, '')
    }
  })

  // 초기 오버레이 상태 설정
  const initState = uiStore.getState()
  if (initState.settings === null) {
    shell.setOverlay(true, '로딩 중…')
  } else {
    shell.setOverlay(false, '')
  }

  // 6. 업종명없음 배지 — stockClassificationStore 구독
  stockClassificationStore.subscribe((state) => {
    shell.setBadge('#/stock-classification', state.noSectorCount)
  })

  // 6. Health Check 후 WS 연결 시작 (현대적 안정성 패턴)
  const token = localStorage.getItem('token') || 'dev-bypass'
  
  // Health Check — localhost 고정 간격 폴링 (지수 백오프 불필요)
  async function waitForServerReady(): Promise<void> {
    const maxRetries = 100
    const retryDelay = 300 // 0.3초 고정 (localhost)
    let retryCount = 0

    while (retryCount < maxRetries) {
      try {
        const health = await api.healthCheck()

        // 서버가 응답하면 즉시 WS 연결 (initializing 상태도 허용)
        // WS 핸들러가 data_ready_event / bootstrap_event 대기 후 스냅샷 전송
        if (health.status === 'ready' || health.status === 'initializing' || health.status === 'error') {
          shell.setOverlay(false, '')
          return
        }

        // downloading 등 기타 상태: 재시도
        retryCount++
        shell.setOverlay(true, `서버 준비 중... (${retryCount}/${maxRetries})`)
        await new Promise(resolve => setTimeout(resolve, retryDelay))
      } catch {
        retryCount++
        console.log(`[Health] 서버 대기 중... ${retryCount}/${maxRetries}`)
        shell.setOverlay(true, `서버 연결 중... (${retryCount}/${maxRetries})`)
        await new Promise(resolve => setTimeout(resolve, retryDelay))
      }
    }

    console.error('[Health] 최대 재시도 횟수 초과 - WS 연결 시도')
    shell.setOverlay(true, '서버 준비 시간 초과 - 연결 시도 중')
  }
  
  // Health Check 시작 후 WS 연결
  waitForServerReady().then(() => {
    wsClient.connect(token)
    wsSettingsClient.connect(token)
    wsOrdersClient.connect(token)
  }).catch(error => {
    console.error('[Health] 초기화 실패:', error)
    shell.setOverlay(true, '초기화 실패')
  })

  // 브라우저 종료/새로고침 시 WS graceful close — TCP RST (ECONNRESET) 방지
  window.addEventListener('beforeunload', () => {
    wsClient.disconnect()
    wsSettingsClient.disconnect()
    wsOrdersClient.disconnect()
  })

  // FPS 모니터링 시작
  startFpsMonitor()
}

/**
 * Router의 handleRouteChange를 확장하여 dual 레이아웃 시
 * settingsCard → leftPanel, load → rightPanel 분리 마운트를 처리한다.
 *
 * 기존 Router는 contentEl(= rightPanel) 하나에 모든 것을 마운트하므로,
 * onRouteChange 콜백에서 settingsCard를 leftPanel에 별도 마운트한다.
 */
function patchRouterForDualLayout(
  router: ReturnType<typeof createRouter>,
  shell: ReturnType<typeof createLayoutShell>,
): void {
  let currentSettingsModule: PageModule | null = null

  router.onRouteChange(async (path) => {
    // 이전 settingsCard unmount
    if (currentSettingsModule) {
      currentSettingsModule.unmount()
      currentSettingsModule = null
    }
    while (shell.leftPanel.firstChild) shell.leftPanel.removeChild(shell.leftPanel.firstChild)

    const route = routes.find(r => r.path === path)
    if (!route || !route.settingsCard) return

    try {
      /*
      let settingsMod = settingsModuleCache.get(path)
      if (!settingsMod) {
        settingsMod = await route.settingsCard()
        settingsModuleCache.set(path, settingsMod)
      }
      */
      const settingsMod = await route.settingsCard()
      
      // 비동기 로딩이 완료된 시점에 사용자가 이미 다른 페이지로 이동했다면 마운트를 스킵한다.
      if (location.hash !== path) {
        console.log(`[Router] 라우트 전환 감지로 비동기 마운트 취소: ${path}`)
        return
      }

      currentSettingsModule = settingsMod
      settingsMod.mount(shell.leftPanel)
    } catch (err) {
      console.error('[Main] settingsCard 로딩 실패:', err)
      shell.leftPanel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;color:${COLOR.up};font-size:12px;">
          설정 카드를 불러올 수 없습니다
        </div>
      `
    }
  })
}

// ── 실행 ──
main()