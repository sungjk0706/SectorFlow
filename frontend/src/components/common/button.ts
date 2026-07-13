/**
 * 공통 버튼 컴포넌트 — SectorFlow 디자인 시스템.
 * 액션 버튼, solid 컬러 버튼, 탭 바, 토글 선택 버튼을 한 곳에서 관리.
 */

import { FONT_SIZE, FONT_WEIGHT, COLOR, FONT_FAMILY } from './ui-styles'

/* ── 액션 버튼 variant ── */

export type ActionVariant = 'primary' | 'danger' | 'secondary' | 'warning'

export interface ActionButtonOptions {
  label: string
  onClick: () => void
  variant?: ActionVariant
  /** 폰트 크기 오버라이드 (기본 FONT_SIZE.label) */
  fontSize?: string
  /** 패딩 오버라이드 (기본 7px 18px) */
  padding?: string
  /** borderRadius 오버라이드 (기본 6px) */
  borderRadius?: string
  /** disabled 상태 */
  disabled?: boolean
  /** data 속성 — 커스텀 식별자 */
  dataAttr?: { key: string; value: string }
  /** 커스텀 배경 컬러 — variant 대신 단일 컬러로 solid 버튼 생성 (white 텍스트) */
  customColor?: string
}

/**
 * 액션 버튼 — 저장/확인/취소/삭제/초기화 등 범용 버튼.
 * variant별 통일된 스타일: padding 7px 18px, borderRadius 6px, fontWeight 500.
 *
 * - primary: 파랑 solid (확인/저장)
 * - danger: 빨강 solid (삭제/초기화)
 * - secondary: 흰색 보더 (취소/일반)
 * - warning: 주황 아웃라인 (API 저장 등 경고)
 */
export function createActionButton(options: ActionButtonOptions): HTMLButtonElement {
  const {
    label, onClick,
    variant = 'secondary',
    fontSize = FONT_SIZE.label,
    padding = '7px 18px',
    borderRadius = '6px',
    disabled = false,
    dataAttr,
    customColor,
  } = options

  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = label

  const isPrimary = variant === 'primary'
  const isDanger = variant === 'danger'
  const isWarning = variant === 'warning'
  const isCustom = customColor !== undefined

  Object.assign(btn.style, {
    padding,
    borderRadius,
    border: isCustom ? 'none'
      : (isPrimary || isDanger) ? 'none'
      : isWarning ? `1px solid ${COLOR.warning}`
      : `1px solid ${COLOR.border}`,
    background: isCustom ? customColor!
      : isPrimary ? COLOR.down
      : isDanger ? COLOR.up
      : isWarning ? 'transparent'
      : COLOR.white,
    color: (isCustom || isPrimary || isDanger) ? COLOR.white
      : isWarning ? COLOR.warning
      : COLOR.neutral,
    cursor: 'pointer',
    fontSize,
    fontFamily: FONT_FAMILY,
    fontWeight: FONT_WEIGHT.medium,
  })

  if (dataAttr) btn.setAttribute(`data-${dataAttr.key}`, dataAttr.value)

  // 항상 click 리스너를 추가 — disabled는 속성으로 클릭을 차단하고,
  // 이후 disabled=false 변경 시 클릭이 동작하도록 보장
  btn.addEventListener('click', onClick)

  if (disabled) {
    btn.disabled = true
    btn.style.opacity = '0.4'
    btn.style.cursor = 'not-allowed'
  }

  return btn
}

/* ── Solid 컬러 버튼 ── */

export type SolidBtnSize = 'sm' | 'md'

export interface SolidButtonOptions {
  label: string
  onClick: (e: MouseEvent) => void
  /** 배경 컬러 (기본 COLOR.success) */
  color?: string
  /** 크기 — sm: 4px 10px / small, md: 6px 12px / label */
  size?: SolidBtnSize
  /** disabled 상태 */
  disabled?: boolean
  /** data-edit-control 속성 여부 (종목분류 편집 컨트롤 식별) */
  editControl?: boolean
  /** 호버 시 어둡게 할 컬러 (미지정 시 자동 계산 불가하므로 명시 필요) */
  hoverColor?: string
}

/**
 * Solid 컬러 버튼 — 추가/이동/다운로드/전체선택 등 작은 액션 버튼.
 * 배경색이 채워진 형태, 호버 시 약간 어두워짐.
 */
export function createSolidBtn(options: SolidButtonOptions): HTMLButtonElement {
  const {
    label, onClick,
    color = COLOR.success,
    size = 'sm',
    disabled = false,
    editControl = false,
    hoverColor,
  } = options

  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = label

  const isSm = size === 'sm'
  const padding = isSm ? '4px 10px' : '6px 12px'
  const fontSize = isSm ? FONT_SIZE.small : FONT_SIZE.label

  Object.assign(btn.style, {
    padding,
    border: 'none',
    borderRadius: '4px',
    background: color,
    color: COLOR.white,
    cursor: 'pointer',
    fontSize,
    fontFamily: FONT_FAMILY,
    fontWeight: FONT_WEIGHT.normal,
    flexShrink: '0',
    whiteSpace: 'nowrap',
    transition: 'background-color 0.2s',
  })

  if (editControl) btn.setAttribute('data-edit-control', '')

  // 항상 click 리스너를 추가 — disabled는 속성으로 클릭을 차단하고,
  // 이후 disabled=false 변경 시 클릭이 동작하도록 보장
  if (hoverColor) {
    btn.addEventListener('mouseenter', () => { btn.style.background = hoverColor })
    btn.addEventListener('mouseleave', () => { btn.style.background = color })
  }
  btn.addEventListener('click', onClick)

  if (disabled) {
    btn.disabled = true
    btn.style.opacity = '0.4'
    btn.style.pointerEvents = 'none'
  }

  return btn
}

/* ── 탭 바 ── */

export interface TabItem {
  id: string
  label: string
}

export interface TabBarOptions {
  tabs: TabItem[]
  activeId: string
  onChange: (id: string) => void
  /** 폰트 크기 (기본 FONT_SIZE.tab) */
  fontSize?: string
  /** 패딩 (기본 8px 16px) */
  padding?: string
  /** flex:1 로 균등 분할 여부 (기본 false) */
  equalWidth?: boolean
  /** 활성 색상 (기본 COLOR.down) */
  activeColor?: string
  /** 사각 테두리 패턴 여부 (기본 false) — 활성: 파랑 보더+배경, 비활성: 회색 보더 */
  boxed?: boolean
}

/**
 * 탭 바 — 하단 보더 활성 패턴.
 * general-settings 메인 탭, profit-detail 매도/매수 탭, settings-common 시/분 탭 등.
 */
export function createTabBar(options: TabBarOptions): { el: HTMLElement; buttons: Map<string, HTMLButtonElement>; setActive(id: string): void } {
  const {
    tabs, activeId, onChange,
    fontSize = FONT_SIZE.tab,
    padding = '8px 16px',
    equalWidth = false,
    activeColor = COLOR.down,
    boxed = false,
  } = options

  const bar = document.createElement('div')
  bar.style.display = 'flex'

  const buttons = new Map<string, HTMLButtonElement>()

  function applyStyle(btn: HTMLButtonElement, active: boolean): void {
    Object.assign(btn.style, {
      padding,
      cursor: 'pointer',
      border: boxed
        ? `1px solid ${active ? activeColor : COLOR.border}`
        : 'none',
      borderRadius: boxed ? '4px' : '0',
      background: boxed
        ? (active ? COLOR.downBg : 'transparent')
        : 'transparent',
      borderBottom: boxed
        ? `1px solid ${active ? activeColor : COLOR.border}`
        : (active ? `2px solid ${activeColor}` : '2px solid transparent'),
      fontWeight: FONT_WEIGHT.normal,
      color: active ? activeColor : COLOR.tertiary,
      fontSize,
      textAlign: 'center',
      whiteSpace: 'nowrap',
      ...(equalWidth ? { flex: '1' } : {}),
    })
  }

  for (const tab of tabs) {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.textContent = tab.label
    const isActive = tab.id === activeId
    applyStyle(btn, isActive)
    btn.addEventListener('click', () => {
      if (tab.id !== currentActive) {
        currentActive = tab.id
        updateActive()
        onChange(tab.id)
      }
    })
    buttons.set(tab.id, btn)
    bar.appendChild(btn)
  }

  let currentActive = activeId

  function updateActive(): void {
    for (const [id, btn] of buttons) {
      applyStyle(btn, id === currentActive)
    }
  }

  function setActive(id: string): void {
    currentActive = id
    updateActive()
  }

  return { el: bar, buttons, setActive }
}

/* ── 토글 선택 버튼 ── */

export interface ToggleSelectButtonOptions {
  label: string
  active: boolean
  onClick: () => void
  /** 활성 색상 (기본 COLOR.down) */
  activeColor?: string
  /** 활성 배경색 (기본 COLOR.downBg) */
  activeBg?: string
  /** 폰트 크기 (기본 FONT_SIZE.label) */
  fontSize?: string
  /** 패딩 (기본 2px 8px) */
  padding?: string
  /** 비활성 시 border 두께 (기본 1px) */
  inactiveBorderWidth?: string
}

/**
 * 토글 선택 버튼 — border + background 토글 패턴.
 * canvas-profit-chart 빠른 선택, profit-detail 드릴다운, profit-overview 전체보기 등.
 */
export function createToggleSelectBtn(options: ToggleSelectButtonOptions): { el: HTMLButtonElement; setActive(active: boolean): void; updateLabel(label: string): void } {
  const {
    label, active, onClick,
    activeColor = COLOR.down,
    activeBg = COLOR.downBg,
    fontSize = FONT_SIZE.label,
    padding = '2px 8px',
    inactiveBorderWidth = '1px',
  } = options

  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = label

  let isActive = active

  function render(): void {
    Object.assign(btn.style, {
      padding,
      fontSize,
      borderRadius: '4px',
      cursor: 'pointer',
      border: isActive ? `2px solid ${activeColor}` : `${inactiveBorderWidth} solid ${activeColor}`,
      background: isActive ? activeBg : COLOR.white,
      color: isActive ? activeColor : COLOR.tertiary,
    })
  }

  render()

  btn.addEventListener('click', (e) => {
    onClick()
    ;(e.target as HTMLElement).blur()
  })

  function setActive(value: boolean): void {
    isActive = value
    render()
  }

  function updateLabel(text: string): void {
    btn.textContent = text
  }

  return { el: btn, setActive, updateLabel }
}
