// frontend/src/layout/sidebar.ui.ts
// 사이드바 네비게이션 — 6개 메뉴 항목, 활성 경로 시각적 강조, 숫자 배지
// 비즈니스 로직 제거, Props로 데이터 수신

import { FONT_SIZE } from '../components/common/ui-styles'

const MENU = [
  { path: '#/sector-ranking', label: '업종순위', icon: '📊' },
  { path: '#/buy-settings', label: '매수설정', icon: '💰' },
  { path: '#/sell-settings', label: '매도설정', icon: '📉' },
  { path: '#/profit-overview', label: '수익현황', icon: '📈' },
  { path: '#/stock-classification', label: '업종분류', icon: '🏷️', separator: true },
  { path: '#/general-settings', label: '일반설정', icon: '⚙️' },
] as const

const ACTIVE_COLOR = '#2563eb'
const ACTIVE_BG = '#e8f0fe'

/* ── Props 타입 ── */

export interface SidebarUiProps {
  activePath?: string
  badges?: Record<string, number>
  onNavigate?: (path: string) => void
}

/* ── UI 참조 ── */

const items = new Map<string, HTMLAnchorElement>()
const badges = new Map<string, HTMLSpanElement>()

/* ── createSidebar ── */

export function createSidebar(container: HTMLElement, props: SidebarUiProps): {
  el: HTMLElement
  setActive(path: string): void
  setBadge(path: string, count: number): void
  update(props: SidebarUiProps): void
} {
  const nav = document.createElement('nav')
  nav.style.cssText =
    'width:160px;min-width:160px;background:#f8f9fa;border-right:1px solid #ddd;display:flex;flex-direction:column;padding:12px 0;'

  // 메뉴 헤더
  const title = document.createElement('div')
  title.style.cssText = 'padding:0 12px 12px;font-weight:700;font-size:11px;color:#888;'
  title.textContent = '메뉴'
  nav.appendChild(title)

  // 메뉴 항목 생성
  for (const m of MENU) {
    // separator가 있으면 hr 삽입
    if ('separator' in m && m.separator) {
      const hr = document.createElement('hr')
      hr.style.cssText = 'margin:8px 12px;border:none;border-top:1px solid #ddd;'
      nav.appendChild(hr)
    }

    const a = document.createElement('a')
    a.href = m.path
    a.style.cssText =
      'display:block;padding:10px 12px;text-decoration:none;font-size:12px;color:#333;background:transparent;border-left:3px solid transparent;cursor:pointer;'
    a.textContent = `${m.icon} ${m.label}`
    a.addEventListener('click', (e) => {
      e.preventDefault()
      if (props.onNavigate) {
        props.onNavigate(m.path)
      }
    })
    items.set(m.path, a)
    nav.appendChild(a)
  }

  container.appendChild(nav)

  // 초기 렌더링
  updateSidebar(props)

  return { el: nav, setActive: setActiveRoute, setBadge: setBadgeCount, update: updateSidebar }
}

/* ── setActiveRoute ── */

function setActiveRoute(path: string): void {
  for (const [p, a] of items) {
    const isActive = p === path
    a.style.color = isActive ? ACTIVE_COLOR : '#333'
    a.style.background = isActive ? ACTIVE_BG : 'transparent'
    a.style.borderLeft = isActive
      ? `3px solid ${ACTIVE_COLOR}`
      : '3px solid transparent'
  }
}

/* ── setBadgeCount ── */

function setBadgeCount(path: string, count: number): void {
  const a = items.get(path)
  if (!a) return
  let badge = badges.get(path)
  if (count > 0) {
    if (!badge) {
      badge = document.createElement('span')
      Object.assign(badge.style, {
        background: '#dc3545',
        color: '#fff',
        borderRadius: '50%',
        fontSize: FONT_SIZE.chip,
        minWidth: '18px',
        height: '18px',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginLeft: '6px',
        fontWeight: '600',
      })
      a.appendChild(badge)
      badges.set(path, badge)
    }
    badge.textContent = String(count)
    badge.style.display = 'inline-flex'
  } else {
    if (badge) badge.style.display = 'none'
  }
}

/* ── updateSidebar ── */

export function updateSidebar(props: SidebarUiProps): void {
  if (props.activePath) {
    setActiveRoute(props.activePath)
  }
  if (props.badges) {
    for (const [path, count] of Object.entries(props.badges)) {
      setBadgeCount(path, count)
    }
  }
}
