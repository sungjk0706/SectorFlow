// 공통 기간 선택 입력 컴포넌트 — 시작/종료 날짜 한 쌍

import { COLOR, FONT_SIZE } from './ui-styles'

export interface DateRangeInputOptions {
  from?: string
  to?: string
  label?: string
  /** 인라인 필터 행용 작은 크기 */
  compact?: boolean
  onChange?: (from: string, to: string) => void
}

export interface DateRangeInputApi {
  el: HTMLElement
  getValue: () => { from: string; to: string }
  setValue: (from: string, to: string) => void
}

export function createDateRangeInput(options: DateRangeInputOptions): DateRangeInputApi {
  const {
    from = '',
    to = '',
    label,
    compact = false,
    onChange,
  } = options

  const root = document.createElement('div')
  Object.assign(root.style, {
    display: 'flex',
    alignItems: 'center',
    gap: compact ? '4px' : '6px',
  })

  if (label) {
    const labelEl = document.createElement('span')
    Object.assign(labelEl.style, {
      fontSize: compact ? FONT_SIZE.label : FONT_SIZE.body,
      color: COLOR.tertiary,
      whiteSpace: 'nowrap',
    })
    labelEl.textContent = label
    root.appendChild(labelEl)
  }

  const dateFromInput = document.createElement('input')
  dateFromInput.type = 'date'
  dateFromInput.value = from
  Object.assign(dateFromInput.style, {
    padding: compact ? '4px 6px' : '6px 8px',
    fontSize: compact ? FONT_SIZE.label : FONT_SIZE.body,
    border: `1px solid ${COLOR.borderLight}`,
    borderRadius: '4px',
    color: COLOR.code,
    minWidth: compact ? '100px' : '120px',
    boxSizing: 'border-box',
  })

  const dateSep = document.createElement('span')
  Object.assign(dateSep.style, { color: COLOR.border, fontSize: FONT_SIZE.label })
  dateSep.textContent = '~'

  const dateToInput = document.createElement('input')
  dateToInput.type = 'date'
  dateToInput.value = to
  Object.assign(dateToInput.style, {
    padding: compact ? '4px 6px' : '6px 8px',
    fontSize: compact ? FONT_SIZE.label : FONT_SIZE.body,
    border: `1px solid ${COLOR.borderLight}`,
    borderRadius: '4px',
    color: COLOR.code,
    minWidth: compact ? '100px' : '120px',
    boxSizing: 'border-box',
  })

  root.appendChild(dateFromInput)
  root.appendChild(dateSep)
  root.appendChild(dateToInput)

  const emitChange = () => {
    onChange?.(dateFromInput.value, dateToInput.value)
  }

  dateFromInput.addEventListener('change', emitChange)
  dateToInput.addEventListener('change', emitChange)

  return {
    el: root,
    getValue: () => ({ from: dateFromInput.value, to: dateToInput.value }),
    setValue: (fromValue: string, toValue: string) => {
      dateFromInput.value = fromValue
      dateToInput.value = toValue
    },
  }
}
