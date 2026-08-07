// frontend/src/layout/sidebar.ts
// 사이드바 네비게이션 — 8개 메뉴 항목, 활성 경로 시각적 강조(책갈피 스타일), 숫자 배지

import { FONT_SIZE, FONT_WEIGHT, COLOR, RADIUS, SHADOW, BLUR, SURFACE_ALPHA } from '../components/common/ui-styles'
import { createIcon } from '../components/common/icon'
import type { IconName } from '../components/common/icon'

const MENU = [
  { path: '#/sector-ranking', label: '업종순위', icon: 'bar-chart' as IconName },
  { path: '#/buy-settings', label: '매수후보', icon: 'wallet' as IconName },
  { path: '#/sell-settings', label: '보유종목', icon: 'trending-down' as IconName },
  { path: '#/profit-overview', label: '수익현황', icon: 'trending-up' as IconName },
  { path: '#/profit-detail', label: '수익상세', icon: 'clipboard-list' as IconName },
  { path: '#/stock-classification', label: '종목분류', icon: 'tag' as IconName, separator: true },
  { path: '#/stock-detail', label: '종목상세', icon: 'search' as IconName, separator: true },
  { path: '#/general-settings', label: '일반설정', icon: 'settings' as IconName },
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
    `width:120px;min-width:120px;background:${SURFACE_ALPHA.toolbar};backdrop-filter:${BLUR.toolbar};-webkit-backdrop-filter:${BLUR.toolbar};border-right:1px solid ${COLOR.borderDark};display:flex;flex-direction:column;padding:12px 0;`



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
    const icon = createIcon(m.icon, { size: 15 })
    icon.style.verticalAlign = 'middle'
    icon.style.marginRight = '4px'
    a.appendChild(icon)
    a.appendChild(document.createTextNode(m.label))
    a.addEventListener('click', (e) => {
      e.preventDefault()
      onNavigate(m.path)
    })
    items.set(m.path, a)
    nav.appendChild(a)
  }

  // 하단 이니셜
  const footer = document.createElement('div')
  footer.style.cssText =
    `margin-top:auto;padding:16px 0 12px 0;text-align:center;`

  const footerText = document.createElement('span')
  footerText.style.cssText =
    `display:inline-block;font-size:${FONT_SIZE.section};font-family:'Georgia','Times New Roman',serif;color:${COLOR.muted};font-weight:${FONT_WEIGHT.semibold};`
  footerText.textContent = 'Built by J.K'

  footer.appendChild(footerText)
  nav.appendChild(footer)

  function setActive(path: string): void {
    for (const [p, a] of items) {
      const isActive = p === path
      a.style.color = isActive ? ACTIVE_COLOR : COLOR.neutral
      a.style.background = isActive ? ACTIVE_BG : 'transparent'
      a.style.borderLeft = isActive
        ? `3px solid ${ACTIVE_COLOR}`
        : '3px solid transparent'
      // 책갈피 스타일 — 선택 메뉴만 우측 모서리 둥글게 + 은은한 그림자 (비선택은 평평)
      a.style.borderTopRightRadius = isActive ? RADIUS.xl : '0'
      a.style.borderBottomRightRadius = isActive ? RADIUS.xl : '0'
      a.style.boxShadow = isActive ? SHADOW.sidebarActive : SHADOW.none
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
