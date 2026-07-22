/**
 * 공통 UI 스타일 — 한국 증권 HTS 표준 기반.
 * 색상 · 폰트 · 굵기 · 기호를 한 곳에서 관리.
 */

// 셀 컴포넌트 / 컬럼 팩토리는 분할 파일에서 re-export (F06-03, P24 단순성)
export * from './ui-styles-cells'
export * from './ui-styles-columns'

/* ── 폰트 ── */

/** 기본 폰트 — 숫자/영어: Tahoma, 한글: 굴림 */
export const FONT_FAMILY = "Tahoma, '굴림', Gulim, sans-serif"

/* ── 폰트 크기 ── */

export const FONT_SIZE = {
  header: '13px',    // 테이블 헤더 (전역과 동일)
  body: '13px',      // 테이블 본문
  code: '12px',      // 종목코드
  small: '11px',     // 순번·배지·보조 텍스트
  group: '18px',     // 업종 그룹 헤더
  title: '15px',     // 카드 제목 (h3)
  section: '14px',   // 섹션/팝업 제목
  tab: '13px',       // 탭 버튼
  label: '12px',     // 토글 라벨·서브패널 제목·검색·탭(소)
  settingsLabel: '14px', // 설정 페이지 라벨·버튼 (GS.label 대체)
  desc: '12px',      // 설정 페이지 설명 텍스트 (GS.desc 대체)
  badge: '11px',     // 한도배지·경고·빈상태 메시지
  chip: '10px',      // 헤더 칩
  spin: '8px',       // 스핀 버튼 화살표
} as const

/* ── 폰트 굵기 ── */

export const FONT_WEIGHT = {
  normal: '400',      // 일반 수치
  medium: '500',      // 종목명 · 가격
  semibold: '600',    // 헤더 · 강조
  bold: '700',        // 그룹 헤더
} as const

/* ── 전역 색상 상수 (단일 소스 진리) ── */

export const COLOR = {
  up:           '#f44336',  // 상승/양수/매수/위험/에러 (빨강)
  upLight:      '#ef9a9a',
  down:         '#1e88e5',  // 하락/음수/매도/정보/활성 (파랑)
  downLight:    '#90caf9',
  neutral:      '#333',     // 보합/기본 텍스트
  success:      '#2e7d32',  // 성공/통과/연결 (초록)
  successLight: '#a5d6a7',
  warning:      '#e65100',  // 경고/주의 (주황)
  warningLight: '#ffcc80',
  kosdaq:       '#d63384',  // 코스닥 종목명 (핑크)
  tertiary:     '#666',     // 라벨/설명문 (보조 텍스트)
  code:         '#555',     // 종목코드
  disabled:     '#9e9e9e',  // 빈 상태/비활성/오프
  muted:        '#adb5bd',  // 미달/흐림
  white:        '#fff',     // 흰색 텍스트/배경 (컬러 배경 위 텍스트)
  groupHeader:  '#1a237e',  // 업종 그룹 헤더 (다크 인디고)
  // ── 보더 ──
  border:       '#ccc',     // 기본 보더
  borderDark:   '#ddd',     // 진한 보더 (섹션/헤더 구분선)
  borderLight:  '#eee',     // 연한 보더
  borderGrid:   '#d0d0d0',  // 그리드 셀 보더
  borderRow:    '#e5e7eb',  // 행 보더
  // ── 배경 ──
  upBg:         '#ffebee',  // 빨강 배경
  downBg:       '#e3f2fd',  // 파랑 배경
  successBg:    '#e8f5e9',  // 초록 배경
  warningBg:    '#fff3e0',  // 주황 배경
  neutralBg:    '#f5f5f5',  // 회색 배경
  zebra:        '#f9f9f9',  // 제브라 스트라이핑
  surfaceLight: '#fafafa',  // 연한 서피스
  hoverBg:      '#f0f0f0',  // 호버/활성 배경
  surface:      '#f8f9fa',  // 서피스 (사이드바/버튼)
  inactiveBg:   '#e0e0e0',  // 비활성 배경
  toggleOff:    '#6c757d',  // 토글 OFF
  // ── 기간 구분 카드 전용 (수익상세 상단 4카드 + 하단 통계 연동) ──
  // 당일은 down/downBg 재사용. 직전/당월/누적은 기존 의미 색(success/warning/up/kosdaq)과 충돌 회피한 신규 색.
  periodPrev:     '#0097a7', // 청록 (직전 거래일)
  periodPrevBg:   '#e0f7fa',
  periodMonth:    '#7b1fa2', // 보라 (당월)
  periodMonthBg:  '#f3e5f5',
  periodTotal:    '#455a64', // 슬레이트 (누적)
  periodTotalBg:  '#eceff1',
} as const

/* ── 공통 색상 함수 ── */

/** 등락률 / 대비 / 현재가 색상: 양수 빨강, 음수 파랑, 0 기본 */
export function rateColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return COLOR.neutral
  return v > 0 ? COLOR.up : v < 0 ? COLOR.down : COLOR.neutral
}

/** 손익 색상: 양수=빨강, 음수=파랑, 0=기본 */
export function pnlColor(v: number): string {
  return v > 0 ? COLOR.up : v < 0 ? COLOR.down : COLOR.neutral
}

/** 체결강도 색상: 100 미만 파랑, 100 이상 빨강 */
export function strengthColor(v: number): string {
  return v >= 100 ? COLOR.up : COLOR.down
}

/**
 * hex 색상 → rgba 문자열 변환.
 * @param hex  '#rgb' 또는 '#rrggbb' 형식
 * @param alpha  0~1 투명도
 */
export function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const full = h.length === 3
    ? h.split('').map((c) => c + c).join('')
    : h
  const r = parseInt(full.slice(0, 2), 16)
  const g = parseInt(full.slice(2, 4), 16)
  const b = parseInt(full.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/* ── 기호 ── */

/** 대비 화살표: 상승 ▲, 하락 ▼, 보합 빈 문자열 */
export function changeArrow(v: number): string {
  return v > 0 ? '▲' : v < 0 ? '▼' : ''
}

/** 등락률 포맷: +3.70 / -2.15 / 0.00 (부호 포함, 색상으로도 구분) */
export function fmtRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  if (v > 0) return '+' + v.toFixed(2)
  if (v < 0) return v.toFixed(2)
  return '0.00'
}

/** 금액 천 단위 콤마 */
export function fmtComma(v: number): string {
  return v.toLocaleString()
}

/** 금액 포맷: 천 단위 콤마 + '원' */
export function fmtWon(v: number): string {
  return `${v.toLocaleString()}원`
}

/**
 * Canvas 차트 툴팁 위치 보정 — overflow:hidden 컨테이너 내에서
 * 툴팁이 완전히 보이도록 양축(X/Y) 경계 클램핑.
 *
 * X축: 마우스 우측 우선 → 우측 넘침 시 좌측 → 좌측 넘침 시 경계 정렬
 * Y축: 마우스 상단 우선 → 하단 넘침 시 상단 이동 → 상단 넘침 시 경계 정렬
 *
 * @param tooltip 툴팁 요소 (display:block 상태에서 호출해야 offsetWidth/Height 유효)
 * @param mx      마우스 X (컨테이너 기준)
 * @param my      마우스 Y (컨테이너 기준)
 * @param cw      컨테이너 너비
 * @param ch      컨테이너 높이
 */
export function positionTooltip(
  tooltip: HTMLElement,
  mx: number, my: number,
  cw: number, ch: number,
): void {
  const tw = tooltip.offsetWidth
  const th = tooltip.offsetHeight
  const MARGIN = 4

  // X축: 우측 우선, 넘침 시 좌측, 좌측도 넘침 시 좌측 경계
  let tx = mx + 15
  if (tx + tw > cw) tx = mx - tw - 15
  if (tx < 0) tx = MARGIN

  // Y축: 상단 우선, 하단 넘침 시 상단으로, 상단 넘침 시 상단 경계
  let ty = my - 40
  if (ty + th > ch) ty = ch - th - MARGIN
  if (ty < 0) ty = MARGIN

  tooltip.style.left = `${tx}px`
  tooltip.style.top = `${ty}px`
}

/* ── 공통 셀 border ── */

export const CELL_BORDER = `1px solid ${COLOR.border}`

/* ── 행 높이 ── */

export const ROW_HEIGHT = {
  data: '32px',       // 데이터 행
  header: '32px',     // 헤더 행
  group: '48px',      // 업종 그룹 행
} as const

/** 행 높이 숫자값 (가상 스크롤러용) */
export const ROW_HEIGHT_PX = {
  data: 32,
  header: 32,
  group: 48,
} as const

/* ── 다크테마 폼 컨트롤 ── */

const DARK_FIELD_STYLE = {
  width: '200px',
  flexShrink: '0',
  padding: '6px 10px',
  borderRadius: '6px',
  border: '1px solid #555',
  background: '#1e1e1e',
  color: '#ddd',
  fontSize: '14px',
  boxSizing: 'border-box' as const,
}

/** 다크테마 텍스트/패스워드 input */
export function createDarkInput(type: 'text' | 'password' = 'text'): HTMLInputElement {
  const el = document.createElement('input')
  el.type = type
  el.autocomplete = 'off'
  Object.assign(el.style, DARK_FIELD_STYLE)
  return el
}

/** 다크테마 select (options: { value, label }[]) */
export function createDarkSelect(options: { value: string; label: string; disabled?: boolean }[], value: string): HTMLSelectElement {
  const el = document.createElement('select')
  Object.assign(el.style, { ...DARK_FIELD_STYLE, cursor: 'pointer', appearance: 'none', backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23aaa'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' })
  for (const opt of options) {
    const o = document.createElement('option')
    o.value = opt.value
    o.textContent = opt.label
    if (opt.disabled) { o.disabled = true; o.style.color = COLOR.tertiary }
    el.appendChild(o)
  }
  el.value = value
  return el
}

/* ── 스타일 헬퍼 ── */

/** 요소 비활성화/활성화 설정 (opacity + pointerEvents) */
export function setDisabled(el: HTMLElement, disabled: boolean): void {
  el.style.opacity = disabled ? '0.4' : '1'
  el.style.pointerEvents = disabled ? 'none' : 'auto'
}

/** 요소 표시/숨김 설정 (display) */
export function setDisplay(el: HTMLElement, visible: boolean): void {
  el.style.display = visible ? '' : 'none'
}