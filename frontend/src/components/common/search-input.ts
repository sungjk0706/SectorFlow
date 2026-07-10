// 공통 검색 입력 컴포넌트 — 이벤트 기반, 디바운스 없음 (워크룰 준수)

import { COLOR, FONT_SIZE, FONT_WEIGHT } from './ui-styles'

export interface SearchInputOptions {
  placeholder?: string
  onSearch: (query: string) => void
  width?: string
  borderColor?: string
  /** 라벨 텍스트 — 제공 시 라벨 + 입력란 인라인 배치 (sector-stock 패턴) */
  label?: string
  /** 라벨 색상 (기본 = borderColor) */
  labelColor?: string
  /** compact 모드 — 아이콘/클리어버튼 off, 작은 padding (인라인 필터 행용) */
  compact?: boolean
}

export function createSearchInput(options: SearchInputOptions): {
  el: HTMLElement
  getValue(): string
  clear(): void
} {
  const {
    placeholder = '종목명/코드 검색',
    onSearch,
    width = '180px',
    borderColor = COLOR.border,
    label,
    labelColor,
    compact = false,
  } = options
  const lblColor = labelColor ?? borderColor

  // 입력란 래퍼 (relative — 아이콘/클리어버튼 절대위치 기준)
  const inputWrapper = document.createElement('div')
  Object.assign(inputWrapper.style, {
    position: 'relative',
    width,
    marginBottom: '0',
  })

  const input = document.createElement('input')
  input.type = 'text'
  input.placeholder = placeholder
  input.className = 'sf-search-input'
  Object.assign(input.style, {
    width: '100%',
    boxSizing: 'border-box',
    padding: compact ? '2px 4px' : '4px 26px 4px 26px',
    fontSize: compact ? FONT_SIZE.label : FONT_SIZE.body,
    border: `1px solid ${borderColor}`,
    borderRadius: '4px',
    outline: 'none',
    color: COLOR.code,
  })

  // 포커스 언더라인 강조 (HTS 스타일 — 레이아웃 시프트 없음)
  input.addEventListener('focus', () => {
    input.style.boxShadow = `inset 0 -2px 0 ${borderColor}`
  })
  input.addEventListener('blur', () => {
    input.style.boxShadow = ''
  })

  // 🔍 아이콘 (compact 모드에서는 미사용)
  let icon: HTMLSpanElement | null = null
  if (!compact) {
    icon = document.createElement('span')
    Object.assign(icon.style, {
      position: 'absolute',
      left: '6px',
      top: '50%',
      transform: 'translateY(-50%)',
      fontSize: '13px',
      color: COLOR.disabled,
      pointerEvents: 'none',
    })
    icon.textContent = '🔍'
  }

  // ✕ 클리어 버튼 (compact 모드에서는 미사용)
  let clearBtn: HTMLSpanElement | null = null
  if (!compact) {
    clearBtn = document.createElement('span')
    Object.assign(clearBtn.style, {
      position: 'absolute',
      right: '6px',
      top: '50%',
      transform: 'translateY(-50%)',
      fontSize: '14px',
      color: COLOR.disabled,
      cursor: 'pointer',
      display: 'none',
      lineHeight: '1',
      userSelect: 'none',
    })
    clearBtn.textContent = '✕'
    clearBtn.addEventListener('click', () => {
      input.value = ''
      clearBtn!.style.display = 'none'
      onSearch('')
      input.focus()
    })
  }

  if (icon) inputWrapper.appendChild(icon)
  inputWrapper.appendChild(input)
  if (clearBtn) inputWrapper.appendChild(clearBtn)

  // input 이벤트 — 즉시 콜백 (디바운스 없음) + 클리어 버튼 표시 토글
  input.addEventListener('input', () => {
    const val = input.value.trim()
    if (clearBtn) clearBtn.style.display = val ? '' : 'none'
    onSearch(val)
  })

  // 라벨 제공 시: 외부 flex 컨테이너에 라벨 + 입력란 인라인 배치
  let outer: HTMLElement
  if (label) {
    outer = document.createElement('div')
    Object.assign(outer.style, {
      display: 'flex',
      flexDirection: 'row',
      alignItems: 'center',
      gap: '4px',
    })
    const labelEl = document.createElement('span')
    Object.assign(labelEl.style, {
      fontSize: FONT_SIZE.section,
      color: lblColor,
      fontWeight: FONT_WEIGHT.normal,
      whiteSpace: 'nowrap',
    })
    labelEl.textContent = label
    outer.appendChild(labelEl)
    outer.appendChild(inputWrapper)
  } else {
    // 라벨 미사용 시: 기존 동작 유지 (래퍼 자체를 el로 반환)
    // 하위 호환 — 기존 코드에서 el.style.marginBottom 등 조작 가능
    inputWrapper.style.marginBottom = '8px'
    outer = inputWrapper
  }

  return {
    el: outer,
    getValue: () => input.value.trim(),
    clear() {
      input.value = ''
      if (clearBtn) clearBtn.style.display = 'none'
      onSearch('')
    },
  }
}
