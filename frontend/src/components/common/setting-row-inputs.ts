/**
 * 공통 설정 행 컴포넌트 — 입력란 그룹.
 * setting-row.ts에서 분할 (F06-02, P24 단순성).
 *
 * 포함: createNumInput, createMoneyInput, createTextInput, createSelect
 */

import { COLOR } from './ui-styles'
import { TEXT_INPUT_WIDTH, SELECT_WIDTH, focusNext, applyInputBase, createSpinButtons, createSuffix } from './setting-row'
import { showToast } from './toast'

/* ── 숫자 입력 문자열 검증 (P22 데이터 정합성) ────────────────
 * 유효 형식: 선택적 맨 앞 "-", 숫자, 소수점 1개, 숫자
 * 허용 중간 상태: "", "-", "-.", ".5", "1.", "1.5"
 * 차단: "0-7", "--7", "1.2.3", "abc" 등
 * 반환: true=유효(계속 처리), false=무효(이전 값 복원 + 토스트)
 */
function _isValidNumericInput(s: string): boolean {
  return s === '' || /^-?\d*\.?\d*$/.test(s)
}

function createInputGroup(input: HTMLInputElement, spinBtns: HTMLElement): HTMLSpanElement {
  const group = document.createElement('span')
  Object.assign(group.style, {
    display: 'inline-flex',
    alignItems: 'stretch',
  })
  group.appendChild(input)
  group.appendChild(spinBtns)
  return group
}

/* ── 숫자 입력란 (커스텀 스핀 버튼) ────────────────────────── */
export function createNumInput(options: {
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number          // ▼ 버튼 하한 (기본 0 — 대부분 설정값은 음수 무의미)
  max?: number          // ▲ 버튼 상한 (기본 Infinity — 상한 없음)
  name?: string
  suffix?: string       // 입력란 우측 단위 표시 (예: "%", "점", "개", "초")
  style?: Partial<CSSStyleDeclaration>
}) {
  let currentValue = options.value
  const numStep = options.step ?? 1
  const minVal = options.min ?? 0
  const maxVal = options.max ?? Infinity

  const wrap = document.createElement('div')
  wrap.style.display = 'flex'
  wrap.style.alignItems = 'stretch'
  void wrap

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
    // 1. 형식 검증 — "-"는 맨 앞 1개만, 소수점 1개만 허용 (P22)
    if (!_isValidNumericInput(input.value)) {
      input.value = String(currentValue)
      showToast('warning', '올바른 값을 입력하세요 (숫자만 입력 가능)')
      return
    }
    const raw = input.value
    // 2. 빈 문자열 또는 "-", "-." 등 중간 상태는 저장하지 않고 대기
    if (raw === '' || raw === '-' || raw === '-.' || raw === '.') {
      return
    }
    const parsed = Number(raw)
    if (!isFinite(parsed)) {
      input.value = String(currentValue)
      showToast('warning', '올바른 값을 입력하세요')
      return
    }
    // 3. 실시간 clamp — 범위 밖 값 입력 즉시 보정 (슬라이더·▲▼ 버튼과 단일 범위, P10 SSOT)
    const clamped = Math.round(Math.min(maxVal, Math.max(minVal, parsed)) * 100) / 100
    currentValue = clamped
    // 보정된 경우에만 DOM 갱신 — 범위 내 타이핑 시 커서 위치 보존
    if (clamped !== parsed) {
      input.value = String(clamped)
    }
    try { options.onChange(clamped) } catch (e) { console.error('[NumInput] onChange error', e) }
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
  })

  const spinBtns = createSpinButtons(
    input,
    () => { currentValue = Math.round(Math.min(maxVal, currentValue + numStep) * 100) / 100; input.value = String(currentValue); try { options.onChange(currentValue) } catch (e) { console.error('[NumInput] spin up onChange error', e) } },
    () => { currentValue = Math.round(Math.max(minVal, currentValue - numStep) * 100) / 100; input.value = String(currentValue); try { options.onChange(currentValue) } catch (e) { console.error('[NumInput] spin down onChange error', e) } },
  )

  wrap.appendChild(createInputGroup(input, spinBtns))
  if (options.suffix) wrap.appendChild(createSuffix(options.suffix))

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
// unit: 'manwon' 지원 — 내부 currentValue·onChange·setValue는 원 단위 SSOT 유지(백엔드와 일관),
// 표시/편집만 만원 단위로 변환 (P10 SSOT, P21 투명성, P23 일관성).
export function createMoneyInput(options: {
  value: number                 // 원 단위 (백엔드 SSOT)
  onChange: (v: number) => void // 원 단위로 전달
  step?: number                 // 표시 단위 기준 스핀 증분 (won 기본 10000원, manwon 기본 1만원)
  min?: number                  // ▼ 버튼 하한 (원 단위, 기본 0 — 양수 전용 사용처 호환)
  max?: number                  // ▲ 버튼 상한 (원 단위, 기본 Infinity — 상한 없음)
  name?: string
  suffix?: string               // 입력란 우측 단위 표시 (won 기본 "원", manwon 기본 "만원")
  unit?: 'won' | 'manwon'       // 표시/편집 단위 (기본 'won')
  style?: Partial<CSSStyleDeclaration>
}) {
  const unit = options.unit ?? 'won'
  const isManwon = unit === 'manwon'
  let currentValue = options.value
  // 표시 단위 기준 step — manwon은 1만원 단위가 자연스러움 (사용처에서 원 단위 step 전달 시 *10000으로 환산)
  const step = isManwon ? (options.step ?? 1) * 10000 : (options.step ?? 10000)
  const minVal = options.min ?? 0
  const maxVal = options.max ?? Infinity

  // 금액 포맷: 0은 '0', 음수/양수 모두 천 단위 콤마 (음수 예: -500,000)
  function fmtMoney(v: number): string {
    return v === 0 ? '0' : v.toLocaleString()
  }
  // 원 단위 → 표시 단위 변환 (manwon: 10000배 축소)
  function toDisplay(v: number): number {
    return isManwon ? v / 10000 : v
  }
  // 표시 단위 입력 → 원 단위 변환 (manwon: 10000배 확대)
  function toValue(display: number): number {
    return isManwon ? display * 10000 : display
  }

  const wrap = document.createElement('div')
  wrap.style.display = 'flex'
  wrap.style.alignItems = 'stretch'
  void wrap

  const input = document.createElement('input')
  input.type = 'text'
  input.inputMode = 'numeric'
  if (options.name) input.setAttribute('data-name', options.name)
  input.value = fmtMoney(toDisplay(currentValue))
  applyInputBase(input, {
    borderRight: 'none',
    borderTopRightRadius: '0',
    borderBottomRightRadius: '0',
    ...(options.style || {}),
  } as Partial<CSSStyleDeclaration>)

  input.addEventListener('focus', () => {
    // 포커스 시 콤마 제거 → 순수 숫자로 편집 가능 (표시 단위 기준)
    const disp = toDisplay(currentValue)
    input.value = disp !== 0 ? String(disp) : ''
  })
  input.addEventListener('input', () => {
    // 콤마 제거 후 형식 검증 (createNumInput과 동일 패턴, P10/P23)
    const stripped = input.value.replace(/,/g, '')
    if (!_isValidNumericInput(stripped)) {
      input.value = fmtMoney(toDisplay(currentValue))
      showToast('warning', '올바른 값을 입력하세요 (숫자만 입력 가능)')
      return
    }
    if (stripped === '' || stripped === '-' || stripped === '-.' || stripped === '.') {
      return
    }
    const parsedDisplay = Number(stripped)
    if (!isFinite(parsedDisplay)) {
      input.value = fmtMoney(toDisplay(currentValue))
      showToast('warning', '올바른 값을 입력하세요')
      return
    }
    // 표시 단위 → 원 단위 변환 후 clamp (원 단위 SSOT 기준)
    const parsed = toValue(parsedDisplay)
    const clamped = Math.min(maxVal, Math.max(minVal, parsed))
    currentValue = clamped
    // 보정된 경우에만 DOM 갱신 — 범위 내 타이핑 시 커서 위치 보존 (표시 단위로 표시)
    if (clamped !== parsed) {
      input.value = String(toDisplay(clamped))
    }
    try { options.onChange(clamped) } catch (e) { console.error('[MoneyInput] onChange error', e) }
  })
  input.addEventListener('blur', () => {
    // 포커스 해제 시 콤마 포맷 복원 (표시 단위)
    input.value = fmtMoney(toDisplay(currentValue))
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
  })

  const spinBtns = createSpinButtons(
    input,
    () => { currentValue = Math.min(maxVal, currentValue + step); input.value = fmtMoney(toDisplay(currentValue)); try { options.onChange(currentValue) } catch (e) { console.error('[MoneyInput] spin up onChange error', e) } },
    () => { currentValue = Math.max(minVal, currentValue - step); input.value = fmtMoney(toDisplay(currentValue)); try { options.onChange(currentValue) } catch (e) { console.error('[MoneyInput] spin down onChange error', e) } },
  )

  wrap.appendChild(createInputGroup(input, spinBtns))
  const suffixText = options.suffix ?? (isManwon ? '만원' : undefined)
  if (suffixText) wrap.appendChild(createSuffix(suffixText))

  function setValue(v: number) {
    currentValue = v
    // 포커스 중이면 DOM 값 덮어쓰지 않음 (사용자 편집 보호)
    if (document.activeElement === input) return
    input.value = fmtMoney(toDisplay(v))
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
    input.addEventListener('input', () => {
      try { onChange(input.value) } catch (e) { console.error('[TextInput] onChange error', e) }
    })
  }
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (onEnter) {
        try { onEnter() } catch (err) { console.error('[TextInput] onEnter error', err) }
      } else focusNext(input)
    }
  })

  return input
}

/* ── 드롭다운 셀렉트 (공통 스타일) ─────────────────────────── */
// select는 NumInput/MoneyInput과 동일한 오른쪽 끝 정렬을 유지 (P23 일관성)
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
    width: options.width ?? `${SELECT_WIDTH}px`,
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
    try { options.onChange(select.value) } catch (e) { console.error('[Select] onChange error', e) }
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
