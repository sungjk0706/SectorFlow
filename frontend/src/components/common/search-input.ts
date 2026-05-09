// 공통 검색 입력 컴포넌트 — 이벤트 기반, 디바운스 없음 (워크룰 준수)

import { FONT_SIZE } from './ui-styles'

export interface SearchInputOptions {
  placeholder?: string
  onSearch: (query: string) => void
  width?: string
}

export function createSearchInput(options: SearchInputOptions): {
  el: HTMLElement
  getValue(): string
  clear(): void
} {
  const { placeholder = '종목명 또는 코드 검색', onSearch, width = '100%' } = options

  const wrapper = document.createElement('div')
  Object.assign(wrapper.style, {
    position: 'relative',
    width,
    marginBottom: '8px',
  })

  const input = document.createElement('input')
  input.type = 'text'
  input.placeholder = placeholder
  Object.assign(input.style, {
    width: '100%',
    boxSizing: 'border-box',
    padding: '4px 26px 4px 26px',
    fontSize: FONT_SIZE.body,
    border: '1px solid #ccc',
    borderRadius: '4px',
    outline: 'none',
  })

  // 🔍 아이콘
  const icon = document.createElement('span')
  Object.assign(icon.style, {
    position: 'absolute',
    left: '6px',
    top: '50%',
    transform: 'translateY(-50%)',
    fontSize: '13px',
    color: '#999',
    pointerEvents: 'none',
  })
  icon.textContent = '🔍'

  // ✕ 클리어 버튼
  const clearBtn = document.createElement('span')
  Object.assign(clearBtn.style, {
    position: 'absolute',
    right: '6px',
    top: '50%',
    transform: 'translateY(-50%)',
    fontSize: '14px',
    color: '#999',
    cursor: 'pointer',
    display: 'none',
    lineHeight: '1',
    userSelect: 'none',
  })
  clearBtn.textContent = '✕'
  clearBtn.addEventListener('click', () => {
    input.value = ''
    clearBtn.style.display = 'none'
    onSearch('')
    input.focus()
  })

  wrapper.appendChild(icon)
  wrapper.appendChild(input)
  wrapper.appendChild(clearBtn)

  // input 이벤트 — 즉시 콜백 (디바운스 없음) + 클리어 버튼 표시 토글
  input.addEventListener('input', () => {
    const val = input.value.trim()
    clearBtn.style.display = val ? '' : 'none'
    onSearch(val)
  })

  return {
    el: wrapper,
    getValue: () => input.value.trim(),
    clear() {
      input.value = ''
      clearBtn.style.display = 'none'
      onSearch('')
    },
  }
}
