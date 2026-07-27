/**
 * 공통 설정 행 컴포넌트 — 메인.
 *
 * 설정 화면(일반/업종/매수/매도)에서 사용하는 입력란·토글·라디오 등
 * 공통 컨트롤을 제공한다.
 *
 * 입력란 그룹과 컨트롤 그룹은 분할됨 (F06-02, P24 단순성):
 * - 입력란: setting-row-inputs.ts (createNumInput, createMoneyInput, createTextInput, createSelect)
 * - 컨트롤: setting-row-controls.ts (createToggleBtn, createRadioGroup, createSettingToggleRow)
 */

import { COLOR, FONT_SIZE } from './ui-styles'
import { createInfoTooltip } from './info-tooltip'

// 분할된 모듈 re-export — 외부 import 경로 유지 (4개 설정 페이지)
export * from './setting-row-inputs'
export * from './setting-row-controls'

/* ── 공통 너비 상수 ────────────────────────────────────────── */
export const INPUT_WIDTH = 70
export const TEXT_INPUT_WIDTH = 220
export const SPIN_BUTTON_WIDTH = 22
export const SUFFIX_GAP = 4
// suffix 고정폭 — 모든 단위("%", "점", "개", "초", "회", "원", "만원", "억원")가 동일 너비 차지 → 정렬 통일 (P23 일관성)
export const SUFFIX_WIDTH = 24
// 입력 그룹 공통 너비 — 숫자/금액 입력란과 select가 동일한 오른쪽 기준 사용 (P23 일관성)
export const CONTROL_WIDTH = INPUT_WIDTH + SPIN_BUTTON_WIDTH + SUFFIX_GAP + SUFFIX_WIDTH
// select는 NumInput/MoneyInput과 동일한 오른쪽 끝 정렬을 유지 (P23 일관성)
export const SELECT_WIDTH = CONTROL_WIDTH
// rightWrap 간격 — ⓘ↔입력란↔suffix 그룹 내 통일 간격 (P23 일관성, P24 단순성)
export const RIGHT_WRAP_GAP = 2
// rightWrap 우측 여백 — 패널 padding이 그룹 우측 여백을 제공 (P23 일관성)
export const RIGHT_WRAP_MARGIN = 0

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
    boxSizing: 'border-box',
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
    width: `${SPIN_BUTTON_WIDTH}px`,
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
  upBtn.addEventListener('click', () => {
    try { onUp() } catch (e) { console.error('[SpinBtn] up error', e) }
  })

  const downBtn = document.createElement('button')
  applySpinBtn(downBtn)
  downBtn.style.borderBottomRightRadius = '4px'
  downBtn.textContent = '▼'
  downBtn.addEventListener('click', () => {
    try { onDown() } catch (e) { console.error('[SpinBtn] down error', e) }
  })

  wrap.appendChild(upBtn)
  wrap.appendChild(downBtn)
  return wrap
}

/* ── 입력란 우측 단위 표시 (suffix) ─────────────────────────── */
// createNumInput/createMoneyInput에서 호출. 스핀 버튼 우측에 단위 텍스트 배치.
// 색상/폰트는 rangeText와 동일 패턴 (P23 일관성).
// SUFFIX_WIDTH 고정폭 적용 — 모든 단위가 동일 너비 차지하여 입력란 정렬 통일 (P23 일관성, P24 단순성).
export function createSuffix(text: string): HTMLSpanElement {
  const span = document.createElement('span')
  Object.assign(span.style, {
    marginLeft: `${SUFFIX_GAP}px`,
    color: COLOR.tertiary,
    fontSize: FONT_SIZE.small,
    whiteSpace: 'nowrap',
    textAlign: 'right',
    alignSelf: 'center',
    flexShrink: '0',
    width: `${SUFFIX_WIDTH}px`,
  })
  span.textContent = text
  return span
}


/* ── 설정 행: 레이블 왼쪽 — 입력란 오른쪽 (한 줄) ──────────── */
// rangeText(입력란 좌측 안내) + infoText(입력란 좌측 ⓘ 툴팁) 옵션.
// 전부 툴팁 통일 방식에서는 infoText 사용, rangeText는 점진적 마이그레이션 위해 유지.
export function createSettingRow(label: string | HTMLElement, child: HTMLElement, opts?: { disabled?: boolean; style?: Partial<CSSStyleDeclaration>; rangeText?: string; infoText?: string }): HTMLElement {
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

  // infoText: 입력란 좌측에 ⓘ 툴팁 배치 — 그룹(ⓘ+입력란+suffix)을 우측 정렬 + 우측 여백 통일 (P23 일관성)
  const rightWrap = document.createElement('span')
  if (opts?.infoText) {
    Object.assign(rightWrap.style, {
      display: 'inline-flex',
      alignItems: 'center',
      gap: `${RIGHT_WRAP_GAP}px`,
      flexShrink: '0',
      marginLeft: 'auto',
      marginRight: `${RIGHT_WRAP_MARGIN}px`,
    })
    rightWrap.appendChild(createInfoTooltip(opts.infoText))
    if (opts?.rangeText) {
      const rangeSpan = document.createElement('span')
      Object.assign(rangeSpan.style, { fontSize: FONT_SIZE.small, color: COLOR.tertiary, whiteSpace: 'nowrap' })
      rangeSpan.textContent = opts.rangeText
      rightWrap.appendChild(rangeSpan)
    }
    rightWrap.appendChild(child)
    div.appendChild(rightWrap)
  } else if (opts?.rangeText) {
    Object.assign(rightWrap.style, { display: 'flex', alignItems: 'center', gap: `${RIGHT_WRAP_GAP}px`, marginLeft: 'auto', marginRight: `${RIGHT_WRAP_MARGIN}px` })
    const rangeSpan = document.createElement('span')
    Object.assign(rangeSpan.style, { fontSize: FONT_SIZE.small, color: COLOR.tertiary, whiteSpace: 'nowrap' })
    rangeSpan.textContent = opts.rangeText
    rightWrap.appendChild(rangeSpan)
    rightWrap.appendChild(child)
    div.appendChild(rightWrap)
  } else {
    Object.assign(child.style, { marginLeft: 'auto', marginRight: `${RIGHT_WRAP_MARGIN}px` })
    div.appendChild(child)
  }
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
