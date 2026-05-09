/* ── 공통 너비 상수 ────────────────────────────────────────── */
export const INPUT_WIDTH = 80
export const TEXT_INPUT_WIDTH = 220

/* ── Enter → 다음 포커스 이동 헬퍼 ─────────────────────────── */
function focusNext(el: HTMLElement) {
  const form = el.closest('form, section, div[role="group"], header, main, [data-settings]')
  const root = form || document.body
  const inputs = Array.from(root.querySelectorAll<HTMLElement>(
    'input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])'
  ))
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
    border: '1px solid #ccc',
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
    border: '1px solid #ccc',
    background: '#f8f8f8',
    cursor: 'pointer',
    fontSize: '8px',
    lineHeight: '1',
    padding: '0',
    userSelect: 'none',
  })
  btn.type = 'button'
  btn.tabIndex = -1
}

function createSpinButtons(onUp: () => void, onDown: () => void) {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, {
    display: 'flex',
    flexDirection: 'column',
    borderRadius: '0 4px 4px 0',
    overflow: 'hidden',
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
    borderBottom: '1px solid #eee',
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
  Object.assign(labelDiv.style, { color: '#555', marginBottom: '4px' })
  labelDiv.textContent = label
  div.appendChild(labelDiv)

  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '4px' })
  if (child) row.appendChild(child)
  if (unit) {
    const unitSpan = document.createElement('span')
    Object.assign(unitSpan.style, { color: '#888' })
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
  name?: string
  style?: Partial<CSSStyleDeclaration>
}) {
  let currentValue = options.value
  const numStep = options.step ?? 1

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
    const raw = input.value.replace(/[^0-9.\-]/g, '')
    currentValue = Number(raw) || 0
    options.onChange(currentValue)
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
  })

  const spinBtns = createSpinButtons(
    () => { currentValue = Math.round((currentValue + numStep) * 100) / 100; input.value = String(currentValue); options.onChange(currentValue) },
    () => { currentValue = Math.round(Math.max(0, currentValue - numStep) * 100) / 100; input.value = String(currentValue); options.onChange(currentValue) },
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

/* ── 금액 입력란 (콤마 포맷 + 커스텀 스핀 버튼) ────────────── */
export function createMoneyInput(options: {
  value: number
  onChange: (v: number) => void
  step?: number
  name?: string
  style?: Partial<CSSStyleDeclaration>
}) {
  let currentValue = options.value
  const step = options.step ?? 10000

  const wrap = document.createElement('div')
  wrap.style.display = 'flex'
  wrap.style.alignItems = 'stretch'

  const input = document.createElement('input')
  input.type = 'text'
  input.inputMode = 'numeric'
  if (options.name) input.setAttribute('data-name', options.name)
  input.value = currentValue > 0 ? currentValue.toLocaleString() : '0'
  applyInputBase(input, {
    borderRight: 'none',
    borderTopRightRadius: '0',
    borderBottomRightRadius: '0',
    ...(options.style || {}),
  } as Partial<CSSStyleDeclaration>)

  input.addEventListener('focus', () => {
    // 포커스 시 콤마 제거 → 순수 숫자로 편집 가능
    input.value = currentValue > 0 ? String(currentValue) : ''
  })
  input.addEventListener('input', () => {
    currentValue = Number(input.value.replace(/,/g, '')) || 0
    options.onChange(currentValue)
  })
  input.addEventListener('blur', () => {
    // 포커스 해제 시 콤마 포맷 복원
    input.value = currentValue > 0 ? currentValue.toLocaleString() : '0'
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
  })

  const spinBtns = createSpinButtons(
    () => { currentValue = currentValue + step; input.value = currentValue > 0 ? currentValue.toLocaleString() : '0'; options.onChange(currentValue) },
    () => { currentValue = Math.max(0, currentValue - step); input.value = currentValue > 0 ? currentValue.toLocaleString() : '0'; options.onChange(currentValue) },
  )

  wrap.appendChild(input)
  wrap.appendChild(spinBtns)

  function setValue(v: number) {
    currentValue = v
    // 포커스 중이면 DOM 값 덮어쓰지 않음 (사용자 편집 보호)
    if (document.activeElement === input) return
    input.value = v > 0 ? v.toLocaleString() : '0'
  }

  function getValue(): number {
    return currentValue
  }

  return { el: wrap as HTMLElement, setValue, getValue }
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
    background: '#fff',
    boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
    transition: 'left 0.2s',
  })
  btn.appendChild(knob)

  function render() {
    btn.style.background = isOn ? '#198754' : '#6c757d'
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

  return { el: btn as HTMLElement, setOn }
}

/* ── 고정 텍스트 값 (시장가 등) ────────────────────────────── */
export function createFixedValue(text: string): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { color: '#555', fontWeight: 'normal' })
  span.textContent = text
  return span
}

/* ── 실시간 연결 상태 뱃지 (공통) ──────────────────── */
export function createWsStatusBadge(options: {
  subscribed: boolean
  broker?: string  // 'kiwoom' | 'ls' | null
  label?: string
}) {
  const wrap = document.createElement('span')
  Object.assign(wrap.style, {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '12px',
  })

  const dot = document.createElement('span')
  Object.assign(dot.style, { display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%' })

  const labelSpan = document.createElement('span')

  wrap.appendChild(dot)
  wrap.appendChild(labelSpan)

  // 증권사별 색상
  const brokerColors: Record<string, string> = {
    kiwoom: '#FF8C00',
  }
  const brokerNames: Record<string, string> = {
    kiwoom: '키움',
  }

  function render(opts: { subscribed: boolean; broker?: string; label?: string }) {
    const hasBroker = opts.subscribed && opts.broker
    const color = hasBroker ? (brokerColors[opts.broker!] ?? '#198754') : '#adb5bd'

    dot.style.background = opts.subscribed ? color : '#adb5bd'
    labelSpan.style.color = opts.subscribed ? color : '#888'

    if (opts.subscribed && opts.broker) {
      labelSpan.textContent = opts.label || `[${brokerNames[opts.broker] ?? opts.broker}]실시간`
    } else {
      labelSpan.textContent = opts.label || '연결해제'
    }

    // 배경색은 연결 상태에만 따라 변경 (증권사 무관)
    wrap.style.background = opts.subscribed ? '#e8f5e9' : '#f5f5f5'
  }

  render(options)

  function update(subscribed: boolean, broker?: string, label?: string) {
    render({ ...options, subscribed, broker, label })
  }

  return { el: wrap as HTMLElement, update }
}

/* ── WsToggleGroup — 우측 밀착 배치 래퍼 ──────────────────── */
export function createWsToggleGroup(children: HTMLElement[]): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { display: 'inline-flex', alignItems: 'center', gap: '8px' })
  for (const child of children) span.appendChild(child)
  return span
}
