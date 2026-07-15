/**
 * Auto_Width_Engine — 데이터 기반 컬럼 폭 자동 계산 (순수 함수, DOM 접근 없음).
 *
 * 한글 문자는 영문 대비 약 1.4배 폭으로 취급하여
 * 9자 이내 종목명까지 표시하면서 공간 낭비를 줄인다.
 */

/** 기본 폰트 크기 — FONT_SIZE.body (13px) */
const DEFAULT_FONT_SIZE = 13

/** 셀 수평 패딩 합계 — padding: 4px 6px → 좌우 6px × 2 = 12px */
const CELL_HORIZONTAL_PADDING = 12

/** 기본 최소 폭 (px) */
const DEFAULT_MIN_WIDTH = 40

/** 한글 문자 폭 대비 영문/숫자 배율. Tahoma/굴림 13px 기준 실측에 가까운 1.4 사용. */
const KOREAN_SCALE = 1.4

/**
 * 한글 유니코드 범위 판별.
 * - AC00-D7AF: 한글 음절
 * - 3130-318F: 한글 호환 자모
 * - 1100-11FF: 한글 자모
 */
function isKorean(code: number): boolean {
  return (
    (code >= 0xac00 && code <= 0xd7af) ||
    (code >= 0x3130 && code <= 0x318f) ||
    (code >= 0x1100 && code <= 0x11ff)
  )
}

/**
 * 텍스트 폭 추정 (px).
 * - 한글: fontSize × 0.75 × KOREAN_SCALE
 * - 영문/숫자/기호: fontSize × 0.75 × 1.0
 * - 공백: fontSize × 0.3
 */
export function estimateTextWidth(text: string, fontSize: number): number {
  let width = 0
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i)
    if (code === 0x20) {
      // 공백
      width += fontSize * 0.3
    } else if (isKorean(code)) {
      // 한글
      width += fontSize * 0.75 * KOREAN_SCALE
    } else {
      // 영문/숫자/기호
      width += fontSize * 0.75 * 1.0
    }
  }
  return width
}

/** 컬럼 폭 계산 입력 */
export interface ColumnWidthInput {
  label: string
  minWidth?: number
  maxWidth?: number
  /** 해당 컬럼의 데이터 텍스트 샘플 (render 결과의 textContent) */
  samples: string[]
}

/**
 * 단일 텍스트 폭을 클램프된 px 폭으로 변환.
 * rawWidth = textWidth + 셀 패딩, minWidth/maxWidth 클램핑.
 */
export function clampColWidth(
  textWidth: number,
  minWidth?: number,
  maxWidth?: number,
): number {
  const rawWidth = textWidth + CELL_HORIZONTAL_PADDING
  let minW = minWidth ?? DEFAULT_MIN_WIDTH
  let maxW = maxWidth ?? Infinity
  if (minW > maxW) {
    console.warn(
      `[auto-width] minWidth(${minW}) > maxWidth(${maxW}), clamping minWidth to maxWidth`,
    )
    minW = maxW
  }
  return Math.max(minW, Math.min(rawWidth, maxW))
}

/**
 * 각 컬럼의 클램프된 px 폭 계산 (컨테이너 너비 무관).
 * 1. 각 컬럼의 maxTextWidth = max(헤더 텍스트 폭, 데이터 샘플 최대 폭)
 * 2. clampColWidth로 px 폭 산출
 */
export function computeColWidths(
  columns: ColumnWidthInput[],
  fontSize: number = DEFAULT_FONT_SIZE,
): number[] {
  if (columns.length === 0) return []

  const widths: number[] = new Array(columns.length)

  for (let i = 0; i < columns.length; i++) {
    const col = columns[i]
    let maxTextWidth = estimateTextWidth(col.label, fontSize)
    const samples = col.samples
    for (let j = 0; j < samples.length; j++) {
      const w = estimateTextWidth(samples[j], fontSize)
      if (w > maxTextWidth) maxTextWidth = w
    }
    widths[i] = clampColWidth(maxTextWidth, col.minWidth, col.maxWidth)
  }

  return widths
}

/**
 * px 폭 배열을 비율(%) 배열로 변환 — 합계 100.
 */
export function widthsToPercentages(widths: number[]): number[] {
  if (widths.length === 0) return []
  let total = 0
  for (let i = 0; i < widths.length; i++) total += widths[i]
  if (total <= 0) return widths.map(() => 100 / widths.length)
  const percentages = new Array(widths.length)
  for (let i = 0; i < widths.length; i++) {
    percentages[i] = (widths[i] / total) * 100
  }
  return percentages
}
