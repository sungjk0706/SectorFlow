// frontend/src/router.ts
// hashchange 기반 경량 클라이언트 사이드 라우터
// react-router-dom 대체

// ── 타입 정의 ──

export interface PageModule {
  mount(container: HTMLElement): void
  unmount(): void
}

export interface RouteConfig {
  path: string
  load: () => Promise<PageModule>
  layout: 'dual' | 'single' | 'full' | 'triple'
  settingsCard?: () => Promise<PageModule>
}

export interface RouterApi {
  init(contentEl: HTMLElement): void
  navigate(hash: string): void
  getCurrentRoute(): string
  onRouteChange(cb: (route: string) => void): () => void
  destroy(): void
}

// ── 레거시 리다이렉트 매핑 ──

const LEGACY_REDIRECTS: Record<string, string> = {
  '#/sector': '#/sector-analysis',
  '#/buy': '#/buy-settings',
  '#/sell': '#/sell-settings',
  '#/account': '#/profit-overview',
  '#/profit': '#/profit-overview',
  '#/settings': '#/general-settings',
}

const DEFAULT_ROUTE = '#/sector-analysis'

// ── 순수 함수: 해시 → 정규 경로 해석 (테스트 가능) ──

export function resolveRoute(hash: string, validPaths: string[]): string {
  const normalized = hash || ''

  // 레거시 리다이렉트
  if (normalized in LEGACY_REDIRECTS) {
    return LEGACY_REDIRECTS[normalized]
  }

  // 정규 경로 매칭
  if (validPaths.includes(normalized)) {
    return normalized
  }

  // 알 수 없는 경로 또는 빈 해시 → 폴백
  return DEFAULT_ROUTE
}

// ── 로딩 스피너 ──

function showSpinner(container: HTMLElement): HTMLElement {
  const spinner = document.createElement('div')
  spinner.className = 'route-loading-spinner'
  spinner.style.cssText =
    'display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:16px;min-height:200px;'
  spinner.innerHTML = `
    <div style="width:40px;height:40px;border:4px solid #e0e0e0;border-top:4px solid #1a73e8;border-radius:50%;animation:spin 1s linear infinite"></div>
    <p style="color:#666;font-size:12px">로딩 중…</p>
    <style>@keyframes spin { to { transform: rotate(360deg) } }</style>
  `
  container.appendChild(spinner)
  return spinner
}

function removeSpinner(container: HTMLElement): void {
  const spinner = container.querySelector('.route-loading-spinner')
  if (spinner) spinner.remove()
}

// ── 라우터 팩토리 ──

export function createRouter(routes: RouteConfig[]): RouterApi {
  const validPaths = routes.map((r) => r.path)
  const routeMap = new Map<string, RouteConfig>(routes.map((r) => [r.path, r]))
  const moduleCache = new Map<string, PageModule>()

  let contentEl: HTMLElement | null = null
  let currentRoute = ''
  let currentModule: PageModule | null = null
  const routeChangeListeners = new Set<(route: string) => void>()
  let hashListener: (() => void) | null = null

  async function loadModule(config: RouteConfig): Promise<PageModule> {
    const cached = moduleCache.get(config.path)
    if (cached) return cached

    const mod = await config.load()
    moduleCache.set(config.path, mod)
    return mod
  }

  function notifyRouteChange(route: string): void {
    for (const cb of routeChangeListeners) {
      cb(route)
    }
  }

  async function handleRouteChange(): Promise<void> {
    if (!contentEl) return

    const hash = location.hash
    const resolved = resolveRoute(hash, validPaths)

    // 레거시/알 수 없는 경로 → 정규 경로로 리다이렉트
    if (hash !== resolved) {
      location.hash = resolved
      return // hashchange 이벤트가 다시 발생하므로 여기서 종료
    }

    // 동일 경로 재진입 방지
    if (resolved === currentRoute) return

    const config = routeMap.get(resolved)
    if (!config) return

    // 이전 페이지 unmount (unmount → mount 순서 보장)
    if (currentModule) {
      currentModule.unmount()
      currentModule = null
    }

    // 콘텐츠 영역 비우기
    while (contentEl.firstChild) contentEl.removeChild(contentEl.firstChild)

    currentRoute = resolved

    // 콜백 통지 (사이드바 활성 메뉴 갱신용 + settingsCard 마운트는 main.ts에서 처리)
    notifyRouteChange(resolved)

    // 캐시 히트: 스피너 없이 동기 마운트
    const cachedModule = moduleCache.get(config.path)
    if (cachedModule) {
      currentModule = cachedModule
      cachedModule.mount(contentEl)
      return
    }

    // 캐시 미스: 스피너 표시 → 비동기 로딩 → 스피너 제거 → 마운트
    showSpinner(contentEl)

    try {
      const pageModule = await loadModule(config)

      // destroy()가 호출되었으면 중단
      if (!contentEl) return

      // 스피너 제거
      removeSpinner(contentEl)

      // 새 페이지 mount (settingsCard는 main.ts의 patchRouterForDualLayout에서 leftPanel에 마운트)
      currentModule = pageModule
      pageModule.mount(contentEl)
    } catch (err) {
      // destroy()가 호출되었으면 중단
      if (!contentEl) return

      // 동적 import 에러 처리
      removeSpinner(contentEl)
      console.error('[Router] 페이지 로딩 실패:', err)

      contentEl.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:16px;min-height:200px;">
          <p style="color:#d32f2f;font-size:13px">페이지를 불러올 수 없습니다</p>
          <button style="padding:8px 16px;border:1px solid #ccc;border-radius:4px;background:#fff;cursor:pointer"
                  onclick="location.reload()">다시 시도</button>
        </div>
      `
    }
  }

  function init(el: HTMLElement): void {
    contentEl = el

    hashListener = () => { handleRouteChange() }
    window.addEventListener('hashchange', hashListener)

    // 초기 경로 처리
    handleRouteChange()
  }

  function navigate(hash: string): void {
    location.hash = hash
  }

  function getCurrentRoute(): string {
    return currentRoute
  }

  function onRouteChange(cb: (route: string) => void): () => void {
    routeChangeListeners.add(cb)
    return () => {
      routeChangeListeners.delete(cb)
    }
  }

  function destroy(): void {
    if (hashListener) {
      window.removeEventListener('hashchange', hashListener)
      hashListener = null
    }
    if (currentModule) {
      currentModule.unmount()
      currentModule = null
    }
    routeChangeListeners.clear()
    moduleCache.clear()
    currentRoute = ''
    contentEl = null
  }

  return { init, navigate, getCurrentRoute, onRouteChange, destroy }
}

// ── 기본 라우트 설정 ──
// 실제 페이지 모듈이 구현되면 main.ts 또는 routes.ts에서 동적 import 경로를 연결한다.
// 페이지 모듈이 아직 없으므로 여기서는 정의하지 않음.
