// 공통 업종 행 컴포넌트 — [업종명] [이동 버튼(우측 정렬)]

import { FONT_SIZE, FONT_FAMILY } from './ui-styles'

export interface SectorRowOptions {
  sectorName: string
  btnText: string
  btnDisabled?: boolean
  onBtnClick: (e: MouseEvent) => void
  onRowClick?: () => void
}

export function createSectorRowEl(options: SectorRowOptions): HTMLElement {
  const { sectorName, btnText, btnDisabled = false, onBtnClick, onRowClick } = options

  const row = document.createElement('div')
  Object.assign(row.style, {
    display: 'flex',
    alignItems: 'center',
    padding: '6px 8px',
    borderBottom: '1px solid #eee',
    cursor: 'pointer',
    width: '100%',
    boxSizing: 'border-box',
  })

  const nameSpan = document.createElement('span')
  Object.assign(nameSpan.style, {
    flex: '1',
    minWidth: '0',
    fontWeight: 'normal',
    fontSize: FONT_SIZE.body,
    color: '#111',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    marginRight: '8px',
  })
  nameSpan.textContent = sectorName

  const btn = document.createElement('button')
  btn.setAttribute('data-edit-control', '')
  btn.textContent = btnText
  Object.assign(btn.style, {
    marginLeft: 'auto',
    flexShrink: '0',
    whiteSpace: 'nowrap',
    padding: '4px 10px',
    border: 'none',
    borderRadius: '4px',
    background: '#198754',
    color: '#fff',
    cursor: 'pointer',
    fontSize: FONT_SIZE.small,
    fontFamily: FONT_FAMILY,
  })
  if (btnDisabled) {
    btn.disabled = true
    btn.style.opacity = '0.4'
    btn.style.pointerEvents = 'none'
  }
  btn.addEventListener('click', (e: MouseEvent) => {
    e.stopPropagation()
    onBtnClick(e)
  })

  if (onRowClick) {
    row.addEventListener('click', onRowClick)
  }

  row.appendChild(nameSpan)
  row.appendChild(btn)

  return row
}
