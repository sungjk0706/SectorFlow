/**
 * 공통 설정 행 컴포넌트 — 토글/라디오/컴포지션 컨트롤 그룹.
 * setting-row.ts에서 분할 (F06-02, P24 단순성).
 *
 * 포함: createToggleBtn, createRadioGroup, createSettingToggleRow
 */

import { COLOR, FONT_SIZE, FONT_WEIGHT, RADIUS, ROW_PADDING, SHADOW, setDisabled } from './ui-styles'
import { createInfoTooltip } from './info-tooltip'
import { RIGHT_WRAP_GAP, RIGHT_WRAP_MARGIN } from './setting-row'

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
    borderRadius: RADIUS.xl,
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
    borderRadius: RADIUS.pill,
    background: COLOR.white,
    boxShadow: SHADOW.card,
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
  btn.addEventListener('click', () => {
    if (!options.disabled) {
      try { options.onClick() } catch (e) { console.error('[ToggleBtn] onClick error', e) }
    }
  })

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
      try { onChange(item.value) } catch (e) { console.error('[RadioGroup] onChange error', e) }
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

/* ── 설정 행 — 라벨 + (컨트롤) + 토글 ───────────────────────── */
// 토글 위치/간격 통일용 (P23 일관성)
// togglePosition: 'left'  → [토글][라벨]      [info][controls][extras]
// togglePosition: 'right' → [라벨]      [info][controls][extras][토글]
export function createSettingToggleRow(options: {
  label: string | string[]
  toggleOn: boolean
  onToggle: (next: boolean) => void
  controls?: HTMLElement[]
  extras?: HTMLElement[]
  infoText?: string
  disableControlsOnToggle?: boolean
  initialDisabled?: boolean
  extraDisableTargets?: HTMLElement[]
  togglePosition?: 'left' | 'right'
  rowStyle?: Partial<CSSStyleDeclaration>
}): {
  el: HTMLElement
  toggle: ReturnType<typeof createToggleBtn>
  controls: HTMLElement
} {
  const togglePosition = options.togglePosition ?? 'left'

  const row = document.createElement('div')
  Object.assign(row.style, {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: ROW_PADDING.toggle,
    borderBottom: '1px solid ' + COLOR.borderLight,
  })
  if (options.rowStyle) Object.assign(row.style, options.rowStyle)

  const labelBox = document.createElement('span')
  Object.assign(labelBox.style, {
    display: 'flex',
    flexDirection: 'column',
    fontSize: FONT_SIZE.settingsLabel,
    fontWeight: FONT_WEIGHT.normal,
  })
  const labelLines = Array.isArray(options.label) ? options.label : [options.label]
  for (const t of labelLines) {
    const s = document.createElement('span')
    s.textContent = t
    labelBox.appendChild(s)
  }

  const controls = document.createElement('span')
  controls.style.cssText = 'display:inline-flex;align-items:center;gap:6px;'

  const extras = document.createElement('span')
  extras.style.cssText = 'display:inline-flex;align-items:center;gap:6px;'
  if (options.extras) {
    for (const c of options.extras) extras.appendChild(c)
  }

  const right = document.createElement('span')
  right.style.cssText = `display:inline-flex;align-items:center;gap:${RIGHT_WRAP_GAP}px;margin-left:auto;margin-right:${RIGHT_WRAP_MARGIN}px;`

  if (options.infoText) {
    right.appendChild(createInfoTooltip(options.infoText))
  }

  if (options.controls) {
    for (const c of options.controls) controls.appendChild(c)
    right.appendChild(controls)
  }

  if (options.extras && options.extras.length > 0) {
    right.appendChild(extras)
  }

  const toggle = createToggleBtn({ on: options.toggleOn, onClick: () => {
    const next = !toggle.isOn()
    toggle.setOn(next)
    if (options.disableControlsOnToggle) {
      setDisabled(controls, !next)
    }
    if (options.extraDisableTargets) {
      for (const t of options.extraDisableTargets) setDisabled(t, !next)
    }
    options.onToggle(next)
  }})

  const initDisabled = options.initialDisabled ?? (options.disableControlsOnToggle ? !options.toggleOn : false)
  if (options.disableControlsOnToggle) {
    setDisabled(controls, initDisabled)
  }
  if (options.extraDisableTargets) {
    for (const t of options.extraDisableTargets) setDisabled(t, initDisabled)
  }

  if (togglePosition === 'left') {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:inline-flex;align-items:center;gap:8px;'
    labelWrap.appendChild(toggle.el)
    labelWrap.appendChild(labelBox)
    row.appendChild(labelWrap)
  } else {
    row.appendChild(labelBox)
    right.appendChild(toggle.el)
  }

  row.appendChild(right)
  return { el: row, toggle, controls }
}
