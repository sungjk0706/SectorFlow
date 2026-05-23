/**
 * 카드 헤더 행 컴포넌트 — 제목 + WS 상태 배지
 * 여러 페이지에서 반복되는 패턴을 모듈화
 */

import { createCardTitle } from './card-title'

export function createCardHeader(title: string, wsBadge?: HTMLElement): HTMLElement {
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '12px',
  })
  
  headerRow.appendChild(createCardTitle(title))
  
  if (wsBadge) {
    headerRow.appendChild(wsBadge)
  }
  
  return headerRow
}

export function createCardHeaderWithMargin(title: string, wsBadge?: HTMLElement, marginBottom: string = '4px'): HTMLElement {
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom,
  })
  
  headerRow.appendChild(createCardTitle(title))
  
  if (wsBadge) {
    headerRow.appendChild(wsBadge)
  }
  
  return headerRow
}
