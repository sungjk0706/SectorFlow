/** 카드 제목 — h3 태그 */
import { FONT_SIZE } from './ui-styles'

export function createCardTitle(text: string): HTMLElement {
  const h3 = document.createElement('h3')
  Object.assign(h3.style, { fontSize: FONT_SIZE.title, margin: '0 0 8px', color: '#333' })
  h3.textContent = text
  return h3
}

/** 카드 제목 — 문자열 또는 HTMLElement 지원 */
export function createCardTitleWithContent(content: string | HTMLElement): HTMLElement {
  const h3 = document.createElement('h3')
  Object.assign(h3.style, { fontSize: FONT_SIZE.title, margin: '0 0 8px', color: '#333' })
  if (typeof content === 'string') {
    h3.textContent = content
  } else {
    h3.appendChild(content)
  }
  return h3
}
