/**
 * 공통 설정 행 컴포넌트 — 메인.
 *
 * 설정 화면(일반/업종/매수/매도)에서 사용하는 입력란·토글·라디오 등
 * 공통 컨트롤을 제공한다.
 *
 * 입력란 그룹과 컨트롤 그룹은 분할됨 (F06-02, P24 단순성):
 * - 입력란: setting-row-inputs.ts (createNumInput, createMoneyInput, createTextInput, createSelect)
 * - 컨트롤: setting-row-controls.ts (createToggleBtn, createRadioGroup, createToggleLabelControlsRow)
 */

import { COLOR } from './ui-styles'

// 분할된 모듈 re-export — 외부 import 경로 유지 (4개 설정 페이지)
export * from './setting-row-inputs'
export * from './setting-row-controls'

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
export function applyInputBase(el: HTMLInputElement, extraStyle?: Partial<CSSStyleDeclaration>) {
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

export function createSpinButtons(input: HTMLInputElement, onUp: () => void, onDown: () => void) {
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

/* ── 고정 텍스트 값 (시장가 등) ────────────────────────────── */
export function createFixedValue(text: string): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { color: `${COLOR.code}`, fontWeight: 'normal' })
  span.textContent = text
  return span
}
