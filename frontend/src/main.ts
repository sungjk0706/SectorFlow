// frontend/src/main.ts — 앱 진입점 (순수 TS, React 없음)
// 기존 main.tsx + App.tsx의 초기화 로직을 통합

import { appStore } from './stores/appStore'
import { wsClient } from './api/ws'
import { bindWSToStore } from './binding'
import { createLayoutShell } from './layout/shell'
import { createRouter } from './router'
import type { RouteConfig, PageModule } from './router'
import { initToastContainer } from './components/common/save-toast'
import { sectorCustomStore } from './stores/sectorCustomStore'
import { api } from './api/client'

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
      // 5초마다 한 번씩 INFO 수준으로 출력 (콘솔 과부하 방지)
      if (Math.round(now / 1000) % 5 === 0) {
        console.log(`[통계] FPS=${fps}`)
      }
      frameCount = 0
      lastTime = now
    }
    requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

// ── Layout Shell (모듈 레벨 export — sector-custom.ts 등에서 import) ──
export const shell = createLayoutShell()

// ── 라우트 설정 ──

const routes: RouteConfig[] = [
  {
    path: '#/sector-analysis',
    layout: 'dual',
    load: () => import('./pages/sector-stock').then(m => m.default),
    settingsCard: () => import('./pages/sector-analysis').then(m => m.default),
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
    path: '#/sector-custom',
    layout: 'triple',
    load: () => import('./pages/sector-custom').then(m => m.default),
  },
  {
    path: '#/general-settings',
    layout: 'single',
    load: () => import('./pages/general-settings').then(m => m.default),
  },
]

// ── 앱 초기화 ──

function main(): void {
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
      color: #d32f2f;
    }
    .down, .negative {
      color: #1976d2;
    }
    .same, .even {
      color: #1a1a1a;
    }
    
    /* 등락률 기호 (HTS 스타일) */
    .rate-up::before {
      content: "▲";
      color: #d32f2f;
      margin-right: 2px;
    }
    .rate-down::before {
      content: "▼";
      color: #1976d2;
      margin-right: 2px;
    }
    
    /* 음수/양수 구분 */
    .minus {
      color: #1976d2;
    }
    .plus {
      color: #d32f2f;
    }
  `
  document.head.appendChild(htsStyle)

  // table 요소도 body 폰트 상속
  const globalStyle = document.createElement('style')
  globalStyle.textContent = 'table, th, td, input, button, select { font-family: inherit; font-size: inherit; }'
  document.head.appendChild(globalStyle)

  // 1. WS → Store 바인딩
  bindWSToStore(wsClient, appStore)

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

  // 5. 오버레이 제어 (engineReady 구독)
  appStore.subscribe((state) => {
    if (state.settings === null) {
      shell.setOverlay(true, '로딩 중…')
    } else if (!state.engineReady) {
      shell.setOverlay(true, '엔진 초기화 중…')
    } else {
      shell.setOverlay(false, '')
    }
  })

  // 初期 오버레이 상태 설정
  const initState = appStore.getState()
  if (initState.settings === null) {
    shell.setOverlay(true, '로딩 중…')
  } else if (!initState.engineReady) {
    shell.setOverlay(true, '엔진 초기화 중…')
  }

  // 6. 업종명없음 배지 — sectorCustomStore 구독
  sectorCustomStore.subscribe((state) => {
    shell.setBadge('#/sector-custom', state.noSectorCount)
  })

  // 6. Health Check 후 WS 연결 시작 (현대적 안정성 패턴)
  const token = localStorage.getItem('token') || 'dev-bypass'
  
  // Health Check 및 재시도 로직
  async function waitForServerReady(): Promise<void> {
    const maxRetries = 20
    const baseDelay = 500 // 0.5초
    let retryCount = 0
    
    while (retryCount < maxRetries) {
      try {
        const health = await api.healthCheck()
        console.log('[Health] 상태:', health.status, health.message)
        
        if (health.status === 'ready') {
          console.log('[Health] 서버 준비 완료 - WS 연결 시작')
          return
        } else if (health.status === 'error') {
          console.error('[Health] 서버 오류 상태:', health.message)
          shell.setOverlay(true, `서버 오류: ${health.message}`)
          return
        }
        
        // initializing 상태이면 재시도
        retryCount++
        const delay = baseDelay * Math.pow(2, Math.min(retryCount - 1, 5)) // 지수 백오프, 최대 16초
        console.log(`[Health] 초기화 중... ${retryCount}/${maxRetries} (${delay}ms 후 재시도)`)
        shell.setOverlay(true, `서버 준비 중... (${retryCount}/${maxRetries})`)
        
        await new Promise(resolve => setTimeout(resolve, delay))
      } catch (error) {
        retryCount++
        const delay = baseDelay * Math.pow(2, Math.min(retryCount - 1, 5))
        console.error(`[Health] Health Check 실패: ${error}. ${retryCount}/${maxRetries} (${delay}ms 후 재시도)`)
        shell.setOverlay(true, `서버 연결 중... (${retryCount}/${maxRetries})`)
        
        await new Promise(resolve => setTimeout(resolve, delay))
      }
    }
    
    console.error('[Health] 최대 재시도 횟수 초과 - WS 연결 시도')
    shell.setOverlay(true, '서버 준비 시간 초과 - 연결 시도 중')
  }
  
  // Health Check 시작 후 WS 연결
  waitForServerReady().then(() => {
    wsClient.connect(token)
  }).catch(error => {
    console.error('[Health] 초기화 실패:', error)
    shell.setOverlay(true, '초기화 실패')
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
      currentSettingsModule = settingsMod
      settingsMod.mount(shell.leftPanel)
    } catch (err) {
      console.error('[Main] settingsCard 로딩 실패:', err)
      shell.leftPanel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;color:#d32f2f;font-size:12px;">
          설정 카드를 불러올 수 없습니다
        </div>
      `
    }
  })
}

// ── 실행 ──
main()