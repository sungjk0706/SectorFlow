/**
 * 공통 ⓘ 툴팁 컴포넌트 — 설정 페이지 입력란 안내 통일 (P23 일관성, P21 투명성).
 *
 * 범위·단위·OFF 동작·수수료 포함 등 부가 안내를 라벨 옆 ⓘ 아이콘 클릭/hover 시 말풍선으로 표시.
 * 라벨은 입력란 이름만 간결하게 유지 (1인 사용자 프로젝트 — P24 단순성).
 *
 * 재사용: clampPosition (context-popup.ts) — 뷰포트 경계 클램핑.
 *         outside-click 닫기 패턴 (createTimeDropdown) — 마우스 외부 클릭 시 닫기.
 */

import { COLOR, FONT_SIZE, RADIUS, SHADOW } from './ui-styles'
import { clampPosition } from './context-popup'

export function createInfoTooltip(text: string): HTMLElement {
  const icon = document.createElement('span')
  icon.setAttribute('role', 'button')
  icon.setAttribute('aria-label', '안내 정보')
  icon.setAttribute('tabindex', '0')
  icon.textContent = 'ⓘ'
  Object.assign(icon.style, {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '16px',
    height: '16px',
    fontSize: FONT_SIZE.small,
    color: COLOR.neutral,
    cursor: 'pointer',
    userSelect: 'none',
    flexShrink: '0',
  })

  let popup: HTMLElement | null = null

  function open(): void {
    if (popup) return
    try {
      popup = document.createElement('div')
      Object.assign(popup.style, {
        position: 'fixed',
        zIndex: '10001',
        maxWidth: '280px',
        padding: '8px 10px',
        borderRadius: RADIUS.sm,
        background: COLOR.white,
        border: '1px solid ' + COLOR.borderDark,
        boxShadow: SHADOW.popup,
        fontSize: '14px', // 설명 가독성 위해 desc(12px) + 2px
        color: COLOR.code,
        lineHeight: '1.4',
        whiteSpace: 'pre-wrap',
        fontFamily: 'inherit',
      })
      popup.textContent = text
      document.body.appendChild(popup)
      // 위치 계산 (렌더 후 실제 크기 기반) — 아이콘 상단에 표시 (마우스 포인터 위)
      const rect = icon.getBoundingClientRect()
      const pr = popup.getBoundingClientRect()
      const cx = rect.left
      const cy = rect.top - pr.height - 4
      const pos = clampPosition(cx, cy, pr.width, pr.height, window.innerWidth, window.innerHeight)
      popup.style.left = `${pos.left}px`
      popup.style.top = `${pos.top}px`
      // outside-click 닫기
      setTimeout(() => {
        document.addEventListener('mousedown', onOutside, true)
      }, 0)
    } catch (e) {
      console.error('[InfoTooltip] open error', e)
      if (popup) { popup.remove(); popup = null }
    }
  }

  function close(): void {
    if (popup) {
      popup.remove()
      popup = null
      document.removeEventListener('mousedown', onOutside, true)
    }
  }

  function onOutside(e: MouseEvent): void {
    if (popup && !popup.contains(e.target as Node) && e.target !== icon) {
      close()
    }
  }

  // 데스크탑: hover 표시, 모바일: click 토글
  icon.addEventListener('mouseenter', open)
  icon.addEventListener('mouseleave', close)
  icon.addEventListener('click', (e) => {
    e.stopPropagation()
    if (popup) close()
    else open()
  })
  // 키보드 접근성 — Enter/Space 로 토글, Escape 닫기
  icon.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (popup) close()
      else open()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      close()
    }
  })

  return icon
}
