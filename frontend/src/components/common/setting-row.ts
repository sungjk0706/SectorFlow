import { COLOR, FONT_SIZE, setDisabled } from './ui-styles'

/* ── 공통 너비 상수 ────────────────────────────────────────── */
export const INPUT_WIDTH = 80
export const TEXT_INPUT_WIDTH = 220

/* ── Enter → 다음 포커스 이동 헬퍼 ─────────────────────────── */
export function focusNext(el: HTMLElement) {
  const form = el.closest('form, section, div[role="group"], header, main, [data-settings]')
  const root = form || document.body
  const inputs = Array.from(root.querySelectorAll<HTMLElement>(
    'input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]):not([tabindex="-1"])'
  )).filter(e => e.offsetParent !== null || e === document.activeElement)
  const idx = inputs.indexOf(el)
  if (idx >= 0 && idx < inputs.length - 1) inputs[idx + 1].focus()
}

/* ── 공통 스핀 버튼 스타일 적용 ─────────────────────────────── */
function applyInputBase(el: HTMLInputElement, extraStyle?: Partial<CSSStyleDeclaration>) {
  el.autocomplete = 'off'
  el.setAttribute('autocomplete', 'new-password')
  el.setAttribute('autocorrect', 'off')
  el.setAttribute('data-form-type', 'other')
  el.setAttribute('data-lpignore', 'true')
  el.spellcheck = false
  Object.assign(el.style, {
    width: `${INPUT_WIDTH}px`,
    padding: '4px 8px',
    borderRadius: '4px',
    border: '1px solid ' + COLOR.border,
    textAlign: 'right',
    fontSize: '13px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  })
  if (extraStyle) Object.assign(el.style, extraStyle)
}

function applySpinBtn(btn: HTMLButtonElement) {
  Object.assign(btn.style, {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '22px',
    height: '50%',
    border: '1px solid ' + COLOR.border,
    background: COLOR.surface,
    cursor: 'pointer',
    fontSize: '8px',
    lineHeight: '1',
    padding: '0',
    userSelect: 'none',
  })
  btn.type = 'button'
  btn.tabIndex = -1
}

function createSpinButtons(input: HTMLInputElement, onUp: () => void, onDown: () => void) {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, {
    display: 'flex',
    flexDirection: 'column',
    borderRadius: '0 4px 4px 0',
    overflow: 'hidden',
  })
  // mousedown 시 버튼 포커스 및 INPUT blur 방지 + INPUT 포커스 보장
  // (macOS에서 버튼 클릭 시 INPUT이 blur되어 syncFromSettings 가드가 무력화되는 문제 방지)
  wrap.addEventListener('mousedown', (e) => {
    e.preventDefault()
    input.focus()
  })
  const upBtn = document.createElement('button')
  applySpinBtn(upBtn)
  upBtn.style.borderBottom = 'none'
  upBtn.style.borderTopRightRadius = '4px'
  upBtn.textContent = '▲'
  upBtn.addEventListener('click', onUp)

  const downBtn = document.createElement('button')
  applySpinBtn(downBtn)
  downBtn.style.borderBottomRightRadius = '4px'
  downBtn.textContent = '▼'
  downBtn.addEventListener('click', onDown)

  wrap.appendChild(upBtn)
  wrap.appendChild(downBtn)
  return wrap
}


/* ── 설정 행: 레이블 왼쪽 — 입력란 오른쪽 (한 줄) ──────────── */
export function createSettingRow(label: string | HTMLElement, child: HTMLElement, opts?: { disabled?: boolean; style?: Partial<CSSStyleDeclaration> }): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 0',
    borderBottom: '1px solid ' + COLOR.borderLight,
  })
  if (opts?.disabled) {
    div.style.opacity = '0.4'
    div.style.pointerEvents = 'none'
  }
  if (opts?.style) Object.assign(div.style, opts.style)

  const labelSpan = document.createElement('span')
  if (typeof label === 'string') {
    labelSpan.textContent = label
  } else {
    labelSpan.appendChild(label)
  }
  div.appendChild(labelSpan)
  div.appendChild(child)
  return div
}

/* ── 토글 + 라벨 + 컨트롤 컴포지션 행 ─────────────────────── */
export function createToggleLabelControlsRow(options: {
  labelText: string
  labelSubText?: string
  toggleOn: boolean
  onToggle: (next: boolean) => void
  controlsChild: HTMLElement
  initialDisabled?: boolean
  extraDisableTargets?: HTMLElement[]
  rowStyle?: Partial<CSSStyleDeclaration>
}): {
  el: HTMLElement
  toggle: ReturnType<typeof createToggleBtn>
  controls: HTMLElement
} {
  const controls = document.createElement('span')
  controls.style.cssText = 'display:flex;align-items:center;gap:6px;'

  let toggle: ReturnType<typeof createToggleBtn>
  toggle = createToggleBtn({ on: options.toggleOn, onClick: () => {
    const next = !toggle.isOn()
    toggle.setOn(next)
    setDisabled(controls, !next)
    if (options.extraDisableTargets) {
      for (const t of options.extraDisableTargets) setDisabled(t, !next)
    }
    options.onToggle(next)
  }})

  const labelWrap = document.createElement('span')
  labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
  labelWrap.appendChild(toggle.el)
  const labelBox = document.createElement('span')
  labelBox.style.cssText = 'display:flex;flex-direction:column;line-height:1.2;'
  const label = document.createElement('span')
  label.textContent = options.labelText
  labelBox.appendChild(label)
  if (options.labelSubText) {
    const sub = document.createElement('span')
    sub.style.cssText = `font-size:${FONT_SIZE.small};color:${COLOR.tertiary};`
    sub.textContent = options.labelSubText
    labelBox.appendChild(sub)
  }
  labelWrap.appendChild(labelBox)

  controls.appendChild(options.controlsChild)
  const initDisabled = options.initialDisabled ?? !options.toggleOn
  setDisabled(controls, initDisabled)
  if (options.extraDisableTargets) {
    for (const t of options.extraDisableTargets) setDisabled(t, initDisabled)
  }

  const el = createSettingRow(labelWrap, controls, options.rowStyle ? { style: options.rowStyle } : undefined)
  return { el, toggle, controls }
}

/* ── 설정 행: 레이블 위 — 입력란 아래 (2줄) ───────────────── */
export function createSettingField(label: string, unit?: string, child?: HTMLElement, opts?: { disabled?: boolean; style?: Partial<CSSStyleDeclaration> }): HTMLElement {
  const div = document.createElement('div')
  div.style.marginBottom = '10px'
  if (opts?.disabled) {
    div.style.opacity = '0.4'
    div.style.pointerEvents = 'none'
  }
  if (opts?.style) Object.assign(div.style, opts.style)

  const labelDiv = document.createElement('div')
  Object.assign(labelDiv.style, { color: `${COLOR.code}`, marginBottom: '4px' })
  labelDiv.textContent = label
  div.appendChild(labelDiv)

  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '4px' })
  if (child) row.appendChild(child)
  if (unit) {
    const unitSpan = document.createElement('span')
    Object.assign(unitSpan.style, { color: `${COLOR.tertiary}` })
    unitSpan.textContent = unit
    row.appendChild(unitSpan)
  }
  div.appendChild(row)
  return div
}

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

/* ── ON/OFF 토글 버튼 ──────────────────────────────────────── */
export function createToggleBtn(options: {
  on: boolean
  onClick: () => void
  disabled?: boolean
}) {
  let isOn = options.on

  const btn = document.createElement('button')
  btn.setAttribute('role', 'switch')
  btn.setAttribute('aria-pressed', String(isOn))
  Object.assign(btn.style, {
    position: 'relative',
    width: '44px',
    height: '24px',
    borderRadius: '12px',
    border: 'none',
    padding: '0',
    transition: 'background 0.2s',
  })

  const knob = document.createElement('span')
  Object.assign(knob.style, {
    position: 'absolute',
    top: '2px',
    width: '20px',
    height: '20px',
    borderRadius: '50%',
    background: COLOR.white,
    boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
    transition: 'left 0.2s',
  })
  btn.appendChild(knob)

  function render() {
    btn.style.background = isOn ? `${COLOR.success}` : COLOR.toggleOff
    btn.style.cursor = options.disabled ? 'not-allowed' : 'pointer'
    knob.style.left = isOn ? '22px' : '2px'
    btn.setAttribute('aria-pressed', String(isOn))
    if (options.disabled) {
      btn.style.opacity = '0.4'
      btn.style.pointerEvents = 'none'
      btn.setAttribute('aria-disabled', 'true')
    } else {
      btn.style.opacity = '1'
      btn.style.pointerEvents = 'auto'
      btn.removeAttribute('aria-disabled')
    }
  }

  render()
  btn.addEventListener('click', () => { if (!options.disabled) options.onClick() })

  function setOn(v: boolean) {
    isOn = v
    render()
  }

  function getOn() {
    return isOn
  }

  return { el: btn as HTMLElement, setOn, isOn: getOn }
}

/* ── 라디오 버튼 그룹 ─────────────────────────────────────── */
export function createRadioGroup(options: {
  items: { value: string; label: string }[]
  name: string
  value: string
  onChange: (v: string) => void
  fontSize?: string
  gap?: string
}): { el: HTMLElement; setValue: (v: string) => void; getValue: () => string; setDisabled: (disabled: boolean) => void } {
  const {
    items,
    name,
    value: initialValue,
    onChange,
    fontSize = FONT_SIZE.settingsLabel,
    gap = '24px',
  } = options

  const container = document.createElement('div')
  Object.assign(container.style, { display: 'flex', alignItems: 'center', gap })

  const radios: Record<string, HTMLInputElement> = {}
  let currentValue = initialValue

  for (const item of items) {
    const label = document.createElement('label')
    label.style.cssText = `cursor:pointer;display:flex;align-items:center;gap:6px;font-size:${fontSize}`
    const radio = document.createElement('input')
    radio.type = 'radio'
    radio.name = name
    radio.checked = item.value === initialValue
    radio.addEventListener('change', () => {
      currentValue = item.value
      onChange(item.value)
    })
    radios[item.value] = radio
    label.appendChild(radio)
    label.appendChild(document.createTextNode(item.label))
    container.appendChild(label)
  }

  function setValue(v: string): void {
    currentValue = v
    for (const [val, radio] of Object.entries(radios)) {
      radio.checked = val === v
    }
  }

  function getValue(): string {
    return currentValue
  }

  function setDisabled(disabled: boolean): void {
    for (const radio of Object.values(radios)) {
      radio.disabled = disabled
    }
  }

  return { el: container, setValue, getValue, setDisabled }
}

/* ── 고정 텍스트 값 (시장가 등) ────────────────────────────── */
export function createFixedValue(text: string): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { color: `${COLOR.code}`, fontWeight: 'normal' })
  span.textContent = text
  return span
}
