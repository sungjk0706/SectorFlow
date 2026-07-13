/**
 * 공통 배지 컴포넌트 — 상단 요약 인디케이터 행.
 *
 * buy-target / sell-position 페이지 상단의 "한도 배지 행"을 통일.
 * - 행: display:flex + gap → 배지 열 위치 고정 (좌우 움직임 방지)
 * - 배지: inline-flex + flex:1 + min-width:0 + nowrap + ellipsis →
 *   값이 변해도 배지 폭이 변하지 않음
 * - 값 갱신: 매번 DOM 재구성하지 않고 valueEl.textContent만 교체
 *   (sector-stock.ts:341 "innerHTML 파괴 금지" 원칙과 일관)
 *
 * P23(일관된 통일성) + P24(단순성) + P10(SSOT) 준수.
 */

import { FONT_SIZE, FONT_WEIGHT, COLOR } from './ui-styles'

export type BadgeStatus = 'normal' | 'near' | 'hit' | 'warn'

const STATUS_BG: Record<BadgeStatus, string> = {
  normal: COLOR.neutralBg,
  near: COLOR.warningBg,
  hit: COLOR.upBg,
  warn: COLOR.upBg,
}

const STATUS_WEIGHT: Record<BadgeStatus, string> = {
  normal: FONT_WEIGHT.normal,
  near: FONT_WEIGHT.semibold,
  hit: FONT_WEIGHT.semibold,
  warn: FONT_WEIGHT.semibold,
}

export interface BadgeHandle {
  /** 배지 루트 요소 (createBadgeRow 에 appendChild) */
  el: HTMLSpanElement
  /** 값 텍스트 span (색상/내용만 갱신) */
  valueEl: HTMLSpanElement
  /** 단위 텍스트 span */
  unitEl: HTMLSpanElement
  /** 후위 상태 텍스트 span ("(한도)" 등) */
  statusEl: HTMLSpanElement
}

/**
 * 배지 행 컨테이너 생성.
 * display:flex + gap 으로 자식 배지들의 열 위치를 고정.
 */
export function createBadgeRow(): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '6px',
  })
  return row
}

/**
 * 단일 배지 생성.
 * 구조: [labelSpan 고정] [valueSpan 가변] [unitSpan 고정] [statusSpan 가변]
 * - label/unit은 생성 시 1회만 세팅
 * - value/status는 updateBadge()로 textContent만 갱신
 */
export function createBadge(label: string, unit: string): BadgeHandle {
  const el = document.createElement('span')
  Object.assign(el.style, {
    display: 'inline-flex',
    alignItems: 'center',
    flex: '1',
    minWidth: '0',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    fontSize: FONT_SIZE.body,
    padding: '4px 12px',
    borderRadius: '4px',
    background: COLOR.neutralBg,
  })

  const labelEl = document.createElement('span')
  labelEl.style.color = COLOR.code
  labelEl.textContent = `${label} `
  el.appendChild(labelEl)

  const valueEl = document.createElement('span')
  valueEl.style.color = COLOR.up
  el.appendChild(valueEl)

  const unitEl = document.createElement('span')
  unitEl.style.color = COLOR.code
  unitEl.textContent = unit
  el.appendChild(unitEl)

  const statusEl = document.createElement('span')
  statusEl.style.color = COLOR.code
  el.appendChild(statusEl)

  return { el, valueEl, unitEl, statusEl }
}

/**
 * 배지 값 갱신 — DOM 재구성 없이 textContent만 교체.
 * status 변경 시 배경색/굵기만 교체 (위치 변화 없음).
 */
export function updateBadge(
  badge: BadgeHandle,
  value: string,
  options?: {
    valueColor?: string
    status?: BadgeStatus
    statusText?: string
    statusColor?: string
  },
): void {
  badge.valueEl.textContent = value
  if (options?.valueColor) badge.valueEl.style.color = options.valueColor

  if (options?.status) {
    badge.el.style.background = STATUS_BG[options.status]
    badge.el.style.fontWeight = STATUS_WEIGHT[options.status]
  }

  if (options?.statusText !== undefined) {
    badge.statusEl.textContent = options.statusText
    badge.statusEl.style.color = options.statusColor ?? COLOR.code
  }
}
