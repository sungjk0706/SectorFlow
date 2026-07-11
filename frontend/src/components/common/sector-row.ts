// 공통 업종 행 컴포넌트 — [업종명] [이동 버튼(우측 정렬)]

import { FONT_SIZE, COLOR } from './ui-styles'
import { createSolidBtn } from './button'

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
    borderBottom: '1px solid ' + COLOR.borderLight,
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
    color: COLOR.neutral,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    marginRight: '8px',
  })
  nameSpan.textContent = sectorName

  const btn = createSolidBtn({
    label: btnText,
    color: COLOR.success,
    editControl: true,
    disabled: btnDisabled,
    onClick: (e: MouseEvent) => {
      e.stopPropagation()
      onBtnClick(e)
    },
  })
  btn.style.marginLeft = 'auto'

  if (onRowClick) {
    row.addEventListener('click', onRowClick)
  }

  row.appendChild(nameSpan)
  row.appendChild(btn)

  return row
}
