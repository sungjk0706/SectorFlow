/**
 * 공통 설정 행 컴포넌트 — 입력란 그룹.
 * setting-row.ts에서 분할 (F06-02, P24 단순성).
 *
 * 포함: createNumInput, createMoneyInput, createTextInput, createSelect
 */

import { COLOR } from './ui-styles'
import { TEXT_INPUT_WIDTH, focusNext, applyInputBase, createSpinButtons } from './setting-row'

/* ── 숫자 입력란 (커스텀 스핀 버튼) ────────────────────────── */
export function createNumInput(options: {
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number          // ▼ 버튼 하한 (기본 0 — 대부분 설정값은 음수 무의미)
  max?: number          // ▲ 버튼 상한 (기본 Infinity — 상한 없음)
  name?: string
  style?: Partial<CSSStyleDeclaration>
}) {
  let currentValue = options.value
  const numStep = options.step ?? 1
  const minVal = options.min ?? 0
  const maxVal = options.max ?? Infinity

  const wrap = document.createElement('div')
  wrap.style.display = 'flex'
  wrap.style.alignItems = 'stretch'

  const input = document.createElement('input')
  input.type = 'text'
  input.inputMode = 'decimal'
  input.value = String(currentValue)
  if (options.name) input.setAttribute('data-name', options.name)
  applyInputBase(input, {
    borderRight: 'none',
    borderTopRightRadius: '0',
    borderBottomRightRadius: '0',
    ...(options.style || {}),
  } as Partial<CSSStyleDeclaration>)

  input.addEventListener('input', () => {
    const raw = input.value.replace(/[^0-9.-]/g, '')
    const parsed = Number(raw) || 0
    // 실시간 clamp — 범위 밖 값 입력 즉시 보정 (슬라이더·▲▼ 버튼과 단일 범위, P10 SSOT)
    const clamped = Math.round(Math.min(maxVal, Math.max(minVal, parsed)) * 100) / 100
    currentValue = clamped
    // 보정된 경우에만 DOM 갱신 — 범위 내 타이핑 시 커서 위치 보존
    if (clamped !== parsed) {
      input.value = String(clamped)
    }
    options.onChange(clamped)
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
  })

  const spinBtns = createSpinButtons(
    input,
    () => { currentValue = Math.round(Math.min(maxVal, currentValue + numStep) * 100) / 100; input.value = String(currentValue); options.onChange(currentValue) },
    () => { currentValue = Math.round(Math.max(minVal, currentValue - numStep) * 100) / 100; input.value = String(currentValue); options.onChange(currentValue) },
  )

  wrap.appendChild(input)
  wrap.appendChild(spinBtns)

  function setValue(v: number) {
    currentValue = v
    // 포커스 중이면 DOM 값 덮어쓰지 않음 (사용자 편집 보호)
    if (document.activeElement === input) return
    input.value = String(v)
  }

  function getValue(): number {
    return currentValue
  }

  return { el: wrap as HTMLElement, setValue, getValue }
}

/* ── 금액 입력란 (콤마 포맷 + 커스텀 스핀 버튼, 음수 지원) ─── */
export function createMoneyInput(options: {
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number          // ▼ 버튼 하한 (기본 0 — 양수 전용 사용처 호환)
  max?: number          // ▲ 버튼 상한 (기본 Infinity — 상한 없음)
  name?: string
  style?: Partial<CSSStyleDeclaration>
}) {
  let currentValue = options.value
  const step = options.step ?? 10000
  const minVal = options.min ?? 0
  const maxVal = options.max ?? Infinity

  // 금액 포맷: 0은 '0', 음수/양수 모두 천 단위 콤마 (음수 예: -500,000)
  function fmtMoney(v: number): string {
    return v === 0 ? '0' : v.toLocaleString()
  }

  const wrap = document.createElement('div')
  wrap.style.display = 'flex'
  wrap.style.alignItems = 'stretch'

  const input = document.createElement('input')
  input.type = 'text'
  input.inputMode = 'numeric'
  if (options.name) input.setAttribute('data-name', options.name)
  input.value = fmtMoney(currentValue)
  applyInputBase(input, {
    borderRight: 'none',
    borderTopRightRadius: '0',
    borderBottomRightRadius: '0',
    ...(options.style || {}),
  } as Partial<CSSStyleDeclaration>)

  input.addEventListener('focus', () => {
    // 포커스 시 콤마 제거 → 순수 숫자로 편집 가능
    input.value = currentValue !== 0 ? String(currentValue) : ''
  })
  input.addEventListener('input', () => {
    currentValue = Number(input.value.replace(/,/g, '')) || 0
    options.onChange(currentValue)
  })
  input.addEventListener('blur', () => {
    // 포커스 해제 시 콤마 포맷 복원
    input.value = fmtMoney(currentValue)
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
  })

  const spinBtns = createSpinButtons(
    input,
    () => { currentValue = Math.min(maxVal, currentValue + step); input.value = fmtMoney(currentValue); options.onChange(currentValue) },
    () => { currentValue = Math.max(minVal, currentValue - step); input.value = fmtMoney(currentValue); options.onChange(currentValue) },
  )

  wrap.appendChild(input)
  wrap.appendChild(spinBtns)

  function setValue(v: number) {
    currentValue = v
    // 포커스 중이면 DOM 값 덮어쓰지 않음 (사용자 편집 보호)
    if (document.activeElement === input) return
    input.value = fmtMoney(v)
  }

  function getValue(): number {
    return currentValue
  }

  return { el: wrap as HTMLElement, setValue, getValue }
}

/* ── 텍스트/패스워드 입력란 ────────────────────────────────── */
export function createTextInput(options: {
  value?: string
  type?: 'text' | 'password'
  placeholder?: string
  name?: string
  width?: string
  onChange?: (v: string) => void
  onEnter?: () => void
  style?: Partial<CSSStyleDeclaration>
}): HTMLInputElement {
  const {
    value = '',
    type = 'text',
    placeholder,
    name,
    width = `${TEXT_INPUT_WIDTH}px`,
    onChange,
    onEnter,
    style,
  } = options

  const input = document.createElement('input')
  input.type = type
  input.value = value
  if (placeholder) input.placeholder = placeholder
  if (name) input.setAttribute('data-name', name)
  applyInputBase(input, {
    width,
    textAlign: 'left',
    ...(style || {}),
  } as Partial<CSSStyleDeclaration>)

  if (onChange) {
    input.addEventListener('input', () => onChange(input.value))
  }
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (onEnter) onEnter()
      else focusNext(input)
    }
  })

  return input
}

/* ── 드롭다운 셀렉트 (공통 스타일) ─────────────────────────── */
export function createSelect(options: {
  items: { value: string; label: string }[]
  value: string
  onChange: (v: string) => void
  name?: string
  width?: string
}) {
  const select = document.createElement('select')
  if (options.name) select.setAttribute('data-name', options.name)
  Object.assign(select.style, {
    width: options.width ?? '121px',
    padding: '4px 8px',
    borderRadius: '4px',
    border: '1px solid ' + COLOR.border,
    fontSize: '13px',
    boxSizing: 'border-box',
  })
  for (const item of options.items) {
    const opt = document.createElement('option')
    opt.value = item.value
    opt.textContent = item.label
    select.appendChild(opt)
  }
  select.value = options.value

  select.addEventListener('change', () => {
    options.onChange(select.value)
  })

  function setValue(v: string) {
    if (document.activeElement === select) return
    select.value = v
  }

  function getValue(): string {
    return select.value
  }

  return { el: select as HTMLSelectElement, setValue, getValue }
}
