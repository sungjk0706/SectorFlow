/**
 * 공통 설정 행 컴포넌트 — 토글/라디오/컴포지션 컨트롤 그룹.
 * setting-row.ts에서 분할 (F06-02, P24 단순성).
 *
 * 포함: createToggleBtn, createRadioGroup, createToggleLabelControlsRow
 */

import { COLOR, FONT_SIZE, setDisabled } from './ui-styles'
import { createSettingRow } from './setting-row'

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
