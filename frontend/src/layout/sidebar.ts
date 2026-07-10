// frontend/src/layout/sidebar.ts
// 사이드바 네비게이션 — 6개 메뉴 항목, 활성 경로 시각적 강조, 숫자 배지

import { FONT_SIZE, COLOR } from '../components/common/ui-styles'

const MENU = [
  { path: '#/sector-ranking', label: '업종순위', icon: '📊' },
  { path: '#/buy-settings', label: '매수설정', icon: '💰' },
  { path: '#/sell-settings', label: '매도설정', icon: '📉' },
  { path: '#/profit-overview', label: '수익현황', icon: '📈' },
  { path: '#/profit-detail', label: '수익상세', icon: '📋' },
  { path: '#/stock-classification', label: '종목분류', icon: '🏷️', separator: true },
  { path: '#/stock-detail', label: '종목상세', icon: '🔍', separator: true },
  { path: '#/general-settings', label: '일반설정', icon: '⚙️' },
] as const

const ACTIVE_COLOR = COLOR.down
const ACTIVE_BG = COLOR.downBg

export function createSidebar(onNavigate: (path: string) => void): {
  el: HTMLElement
  setActive(path: string): void
  setBadge(path: string, count: number): void
} {
  const nav = document.createElement('nav')
  nav.style.cssText =
    `width:120px;min-width:120px;background:${COLOR.surface};border-right:1px solid ${COLOR.borderDark};display:flex;flex-direction:column;padding:12px 0;`



  // 메뉴 항목 생성
  const items = new Map<string, HTMLAnchorElement>()

  for (const m of MENU) {
    // separator가 있으면 hr 삽입
    if ('separator' in m && m.separator) {
      const hr = document.createElement('hr')
      hr.style.cssText = `margin:8px 12px;border:none;border-top:1px solid ${COLOR.borderDark};`
      nav.appendChild(hr)
    }

    const a = document.createElement('a')
    a.href = m.path
    a.style.cssText =
      `display:block;padding:14px 0;margin-bottom:4px;text-align:center;text-decoration:none;font-size:13.5px;color:${COLOR.neutral};background:transparent;border-left:3px solid transparent;cursor:pointer;font-weight:500;`
    a.textContent = `${m.icon} ${m.label}`
    a.addEventListener('click', (e) => {
      e.preventDefault()
      onNavigate(m.path)
    })
    items.set(m.path, a)
    nav.appendChild(a)
  }

  function setActive(path: string): void {
    for (const [p, a] of items) {
      const isActive = p === path
      a.style.color = isActive ? ACTIVE_COLOR : COLOR.neutral
      a.style.background = isActive ? ACTIVE_BG : 'transparent'
      a.style.borderLeft = isActive
        ? `3px solid ${ACTIVE_COLOR}`
        : '3px solid transparent'
    }
  }

  const badges = new Map<string, HTMLSpanElement>()

  function setBadge(path: string, count: number): void {
    const a = items.get(path)
    if (!a) return
    let badge = badges.get(path)
    if (count > 0) {
      if (!badge) {
        badge = document.createElement('span')
        Object.assign(badge.style, {
          background: COLOR.up,
          color: COLOR.white,
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

  return { el: nav, setActive, setBadge }
}
