/**
 * 공통 UI 스타일 — 한국 증권 HTS 표준 기반.
 * 색상 · 폰트 · 굵기 · 기호를 한 곳에서 관리.
 */

// 셀 컴포넌트 / 컬럼 팩토리는 분할 파일에서 re-export (F06-03, P24 단순성)
export * from './ui-styles-cells'
export * from './ui-styles-columns'

/* ── 폰트 ── */

/** 기본 폰트 — macOS 시스템 폰트 우선 스택 (SF Pro → 폴백) */
export const FONT_FAMILY =
  "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', " +
  "'Helvetica Neue', 'Segoe UI', system-ui, sans-serif"

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

/* ── 둥근 모서리 ── */

export const RADIUS = {
  xs:   '4px',     // 칩, 스핀 버튼, 슬라이더 핸들, 행 내부 요소
  sm:   '6px',     // 버튼, 입력란, 카드 내부 요소, 태그
  md:   '8px',     // 카드, 드롭다운, 팝업, 컨텍스트 메뉴
  lg:   '10px',    // 토스트, 브로커 배지, 헤더 칩
  xl:   '12px',    // 다이얼로그, 사이드바 활성 항, 큰 카드
  pill: '9999px',  // 원형 배지, 토글
} as const

/* ── 레이아웃 간격 ── */

/** 카드 제목(h3) 하단 margin — card-title.ts·card-header.ts 공통 참조 (P23 일관성) */
export const CARD_TITLE_MARGIN_BOTTOM = 8

/* ── 그림자 ── */

export const SHADOW = {
  card:         '0 1px 2px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.06)',  // 카드/패널 — 은은한 1층
  cardHover:    '0 2px 6px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06)',  // 호버/활성 카드
  popup:        '0 4px 16px rgba(0, 0, 0, 0.12), 0 1px 4px rgba(0, 0, 0, 0.06)', // 팝업/드롭다운
  modal:        '0 12px 36px rgba(0, 0, 0, 0.16), 0 2px 8px rgba(0, 0, 0, 0.08)', // 모달/다이얼로그
  sidebarActive:'2px 2px 8px rgba(0, 0, 0, 0.06)',  // 사이드바 활성 항 — 좌측 책갈피용
  none:         'none',
} as const

/* ── 반투명 블러 ── */

export const BLUR = {
  toolbar: 'blur(20px) saturate(180%)',  // 헤더/사이드바 툴바 — 강한 블러 (macOS 툴바 표준)
  panel:   'blur(16px) saturate(150%)',  // 카드/패널 — 중간 블러
  overlay: 'blur(8px) saturate(120%)',   // 모달 오버레이 — 약한 블러
  none:    'none',
} as const

/* ── 반투명 표면 배경 (블러와 함께 사용) ── */

export const SURFACE_ALPHA = {
  toolbar: 'rgba(255, 255, 255, 0.72)',  // 헤더/사이드바 툴바 배경 — 흰색 72%
  panel:   'rgba(255, 255, 255, 0.80)',  // 카드/패널 배경 — 흰색 80%
  overlay: 'rgba(0, 0, 0, 0.40)',        // 모달 오버레이 — 검정 40%
} as const

/* ── 전역 색상 상수 (단일 소스 진리) ── */

export const COLOR = {
  up:           '#d64545',  // 상승/양수/매수/위험/에러 (빨강) — macOS 시스템 레드 톤
  upLight:      '#eba0a0',
  down:         '#0a6cff',  // 하락/음수/매도/정보/활성 (파랑) — macOS 시스템 블루
  downLight:    '#a5c8ff',
  neutral:      '#1d1d1f',  // 보합/기본 텍스트 — macOS 라벨 컬러
  success:      '#248a3d',  // 성공/통과/연결 (초록) — macOS 시스템 그린 톤
  successLight: '#a8d8b0',
  successHover: '#157347',  // success 버튼 호버 (진한 초록)
  warning:      '#d97706',  // 경고/주의 (주황) — macOS 시스템 오렌지 톤
  warningLight: '#f0c080',
  kosdaq:       '#d63384',  // 코스닥 종목명 (핑크)
  // ── 업종 종합점수 단계 색 (scoreColor 전용) ──
  scoreHigh:    '#e67e22',  // 고득점 (80+) — 주황
  scoreMid:     '#2c3e50',  // 중간 (60+) — 다크 네이비
  scoreLow:     '#7f8c8d',  // 저득점 (60 미만) — 회색
  tertiary:     '#6e6e73',  // 라벨/설명문 (보조 텍스트) — macOS 세컨더리 라벨
  code:         '#515154',  // 종목코드 — macOS 터셔너리 라벨
  disabled:     '#a1a1a6',  // 빈 상태/비활성/오프 — macOS 쿼터너리 라벨
  muted:        '#c7c7cc',  // 미달/흐림 — macOS 플레이스홀더
  white:        '#fff',     // 흰색 텍스트/배경 (컬러 배경 위 텍스트)
  groupHeader:  '#1a237e',  // 업종 그룹 헤더 (다크 인디고)
  // ── 보더 ──
  border:       '#d2d2d7',  // 기본 보더 — macOS 세퍼레이터
  borderDark:   '#e5e5ea',  // 진한 보더 (섹션/헤더 구분선) — macOS 세퍼레이터 (연함)
  borderLight:  '#f2f2f7',  // 연한 보더 — macOS 그룹 배경 경계
  borderGrid:   '#e5e5ea',  // 그리드 셀 보더 — 더 연하게
  borderRow:    '#f2f2f7',  // 행 보더 — 거의 안 보이게
  // ── 배경 ──
  upBg:         '#faeaea',  // 빨강 배경 — macOS 톤 pastel (채도 낮춤)
  downBg:       '#eaf0fa',  // 파랑 배경 — macOS 톤 pastel
  successBg:    '#eaf5ec',  // 초록 배경 — macOS 톤 pastel
  warningBg:    '#f7eede',  // 주황 배경 — macOS 톤 pastel
  neutralBg:    '#f2f2f7',  // 회색 배경 — macOS 비활성 배경
  zebra:        '#fafafa',  // 제브라 스트라이핑 — 매우 연함
  surfaceLight: '#fbfbfd',  // 연한 서피스 — macOS secondary 백그라운드
  hoverBg:      '#ececef',  // 호버/활성 배경 — macOS 호버 하이라이트
  surface:      '#f5f5f7',  // 서피스 (사이드바/버튼) — macOS 그룹 배경 백그라운드
  inactiveBg:   '#e5e5ea',  // 비활성 배경 — macOS 비활성 토글 배경
  eliminatedBg: 'rgba(0,0,0,0.06)', // 탈락 업종 행 — 어두운 틴트 유리 (글자는 선명, 배경만 살짝 어둡게)
  toggleOff:    '#8e8e93',  // 토글 OFF — macOS 토글 OFF
  // ── 기간 구분 카드 전용 (수읉상세 상단 4카드 + 하단 통계 연동) ──
  // 당일은 down/downBg 재사용. 5거래일/당월/누적은 기존 의미 색(success/warning/up/kosdaq)과 충돌 회피한 신규 색.
  period5day:     '#c2185b', // 마젠타 (최근 5거래일)
  period5dayBg:   '#fce4ec',
  periodMonth:    '#7b1fa2', // 보라 (당월)
  periodMonthBg:  '#f3e5f5',
  periodTotal:    '#455a64', // 슬레이트 (누적)
  periodTotalBg:  '#eceff1',
  // ── 종목 거래소 라벨 (createStockNameCell) ──
  krxLabel:       '#0288d1', // K 라벨 글자 — 진한 하늘 (KRX 전용)
  krxLabelBg:     '#e1f5fe', // K 라벨 배경 — 약한 하늘
  nxtLabel:       '#7b1fa2', // 통 라벨 글자 — 진한 보라 (KRX+NXT 통합)
  nxtLabelBg:     '#f3e5f5', // 통 라벨 배경 — 약한 보라
} as const

/* ── 공통 색상 함수 ── */

/** 가중 수익률 = pnl / buyTotal × 100 (소수 2자리 반올림, buyTotal 0이면 0).
 *  실현손익/평가손익 수익률의 단일 공식 — P22/P23 일관성. */
export function computeWeightedRate(pnl: number, buyTotal: number): number {
  return buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0
}

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

/** 백만원 단위 → 억 단위 문자열 (ko-KR, 소수점 1자리, 콤마).
 *  순수 변환만 담당 — null/0/음수 등 빈 값 처리는 호출부에서 담당 (P20 폴백 금지). */
export function fmtMillionsToBillion(v: number): string {
  return (v / 100).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
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

/* ── 설정 행 수직 padding (행간 간격 SSOT) ── */
// 모든 설정 페이지 행간 간격의 단일 소스 (P10 SSOT, P23 일관성).
// 토글 행: createSettingToggleRow / 일반 행: createSettingRow / 섹션 제목: sectionTitle
// 조밀 행: sector-settings krx·nxt 행 (별도 컨텍스트, 조밀 의도 보존)
export const ROW_PADDING = {
  toggle:  '8px 0',      // 토글 행 (이전 10px 0 → 8px 0)
  plain:   '4px 0',      // 일반 설정 행 (이전 6px 0 → 4px 0)
  section: '8px 0 4px',  // 섹션 제목 (이전 10px 0 6px → 8px 0 4px)
  compact: '2px 0',      // 조밀 행 (sector krx/nxt — 그대로 유지)
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

/* ── 스타일 헬퍼 ── */

/** 요소 비활성화/활성화 설정 (opacity + pointerEvents) */
export function setDisabled(el: HTMLElement, disabled: boolean): void {
  el.style.opacity = disabled ? '0.4' : '1'
  el.style.pointerEvents = disabled ? 'none' : 'auto'
}