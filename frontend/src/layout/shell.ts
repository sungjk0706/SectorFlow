// frontend/src/layout/shell.ts
// 앱 전체 레이아웃 셸 — 100vh flex column: 헤더(40px) + 본문(사이드바 160px + 콘텐츠)

import { createHeader } from './header'
import { createSidebar } from './sidebar'

export function createLayoutShell(): {
  el: HTMLElement
  contentArea: HTMLElement
  leftPanel: HTMLElement
  rightPanel: HTMLElement
  tripleHeader: HTMLElement
  tripleLeft: HTMLElement
  tripleCenter: HTMLElement
  tripleRight: HTMLElement
  setLayout(type: 'dual' | 'single' | 'full' | 'triple'): void
  setOverlay(visible: boolean, message: string): void
  setActiveRoute(path: string): void
  setBadge(path: string, count: number): void
} {
  // ── 루트 컨테이너 ──
  const root = document.createElement('div')
  root.style.cssText = 'height:100vh;display:flex;flex-direction:column;overflow:hidden;'

  // ── 헤더 ──
  const header = createHeader()
  root.appendChild(header.el)

  // ── 토스트 컨테이너 (SaveToast용) ──
  const toastContainer = document.createElement('div')
  toastContainer.id = 'toast-container'
  root.appendChild(toastContainer)

  // ── 본문 (사이드바 + 콘텐츠) ──
  const body = document.createElement('div')
  body.style.cssText = 'flex:1;display:flex;min-height:0;'

  // 사이드바
  const sidebar = createSidebar((path) => {
    location.hash = path
  })
  body.appendChild(sidebar.el)

  // ── 콘텐츠 래퍼 (오버레이 + 콘텐츠 영역) ──
  const contentWrapper = document.createElement('div')
  contentWrapper.style.cssText = 'flex:1;display:flex;position:relative;min-width:0;min-height:0;overflow:hidden;'

  // ── 로딩 오버레이 (DOM 유지, display 토글) ──
  const overlay = document.createElement('div')
  overlay.style.cssText =
    'position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(255,255,255,0.92);z-index:100;gap:16px;'
  overlay.style.display = 'none'

  const overlaySpinner = document.createElement('div')
  overlaySpinner.style.cssText =
    'width:40px;height:40px;border:4px solid #e0e0e0;border-top:4px solid #1a73e8;border-radius:50%;animation:spin 1s linear infinite;'
  overlay.appendChild(overlaySpinner)

  const overlayMsg = document.createElement('p')
  overlayMsg.style.cssText = 'color:#666;font-size:12px;'
  overlayMsg.textContent = '로딩 중…'
  overlay.appendChild(overlayMsg)

  // spin 키프레임 (shell용)
  const spinStyle = document.createElement('style')
  spinStyle.textContent = '@keyframes spin { to { transform: rotate(360deg) } }'
  overlay.appendChild(spinStyle)

  contentWrapper.appendChild(overlay)

  // ── 콘텐츠 영역 (라우터가 페이지를 마운트하는 곳) ──
  const contentArea = document.createElement('div')
  contentArea.style.cssText = 'display:flex;flex:1;min-height:0;min-width:0;overflow:hidden;'

  // ── 좌측 패널 (dual 레이아웃 시 설정 카드) ──
  const leftPanel = document.createElement('div')
  leftPanel.style.cssText =
    'width:380px;min-width:380px;border-right:1px solid #ddd;overflow-y:auto;scrollbar-gutter:stable;padding:16px;outline:none;display:none;'

  // ── 우측 패널 (dual 레이아웃 시 데이터 영역) ──
  const rightPanel = document.createElement('div')
  rightPanel.style.cssText =
    'flex:1;min-width:0;overflow-y:auto;padding:16px;display:flex;flex-direction:column;outline:none;'

  // ── Triple 레이아웃 요소 (3컬럼 모드) ──
  const tripleHeader = document.createElement('div')
  tripleHeader.style.cssText =
    'display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #ddd;display:none;'

  const tripleContainer = document.createElement('div')
  tripleContainer.style.cssText = 'display:flex;flex:1;min-height:0;display:none;'

  const tripleLeft = document.createElement('div')
  tripleLeft.style.cssText = 'flex:4;overflow-y:auto;padding:16px;border-right:1px solid #ddd;'

  const tripleCenter = document.createElement('div')
  tripleCenter.style.cssText = 'flex:3;overflow-y:auto;padding:16px;border-right:1px solid #ddd;'

  const tripleRight = document.createElement('div')
  tripleRight.style.cssText = 'flex:3;overflow-y:auto;padding:16px;'

  tripleContainer.appendChild(tripleLeft)
  tripleContainer.appendChild(tripleCenter)
  tripleContainer.appendChild(tripleRight)

  contentArea.appendChild(leftPanel)
  contentArea.appendChild(rightPanel)
  contentArea.appendChild(tripleHeader)
  contentArea.appendChild(tripleContainer)
  contentWrapper.appendChild(contentArea)
  body.appendChild(contentWrapper)
  root.appendChild(body)

  // ── setLayout ──
  function setLayout(type: 'dual' | 'single' | 'full' | 'triple'): void {
    // triple 요소 기본 숨김
    tripleHeader.style.display = 'none'
    tripleContainer.style.display = 'none'

    switch (type) {
      case 'dual':
        contentArea.style.flexDirection = ''
        leftPanel.style.display = ''
        rightPanel.style.display = ''
        rightPanel.style.maxWidth = ''
        break
      case 'single':
        contentArea.style.flexDirection = ''
        leftPanel.style.display = 'none'
        rightPanel.style.display = ''
        rightPanel.style.maxWidth = '720px'
        break
      case 'full':
        contentArea.style.flexDirection = ''
        leftPanel.style.display = 'none'
        rightPanel.style.display = ''
        rightPanel.style.maxWidth = ''
        break
      case 'triple':
        contentArea.style.flexDirection = 'column'
        leftPanel.style.display = 'none'
        rightPanel.style.display = 'none'
        tripleHeader.style.display = 'flex'
        tripleContainer.style.display = 'flex'
        break
    }
  }

  // ── setOverlay ──
  function setOverlay(visible: boolean, message: string): void {
    overlay.style.display = visible ? 'flex' : 'none'
    overlayMsg.textContent = message
  }

  // ── setActiveRoute ──
  function setActiveRoute(path: string): void {
    sidebar.setActive(path)
  }

  // ── setBadge (사이드바 배지 위임) ──
  function setBadge(path: string, count: number): void {
    sidebar.setBadge(path, count)
  }

  return { el: root, contentArea, leftPanel, rightPanel, tripleHeader, tripleLeft, tripleCenter, tripleRight, setLayout, setOverlay, setActiveRoute, setBadge }
}
