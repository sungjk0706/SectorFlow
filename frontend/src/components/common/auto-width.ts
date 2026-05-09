/**
 * Auto_Width_Engine — 데이터 기반 컬럼 폭 자동 계산 (순수 함수, DOM 접근 없음).
 *
 * 한글 문자는 영문 대비 약 1.8배 폭으로 취급하여
 * 긴 한글 종목명("LIG디펜스앤에어로스페이스")이 잘리지 않도록 보장한다.
 */

/** 기본 폰트 크기 — FONT_SIZE.body (13px) */
const DEFAULT_FONT_SIZE = 13

/** 셀 수평 패딩 합계 — padding: 4px 6px → 좌우 6px × 2 = 12px */
const CELL_HORIZONTAL_PADDING = 12

/** 기본 최소 폭 (px) */
const DEFAULT_MIN_WIDTH = 40

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
 * - 한글: fontSize × 0.75 × 1.8
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
      width += fontSize * 0.75 * 1.8
    } else {
      // 영문/숫자/기호
      width += fontSize * 0.75 * 1.0
    }
  }
  return width
}

/** computeColumnWidths 입력 */
export interface ColumnWidthInput {
  label: string
  minWidth?: number
  maxWidth?: number
  /** 해당 컬럼의 데이터 텍스트 샘플 (render 결과의 textContent) */
  samples: string[]
}

/** computeColumnWidths 출력 */
export interface ColumnWidthResult {
  /** 각 컬럼의 계산된 폭 (px) */
  widths: number[]
  /** 각 컬럼의 비율 (%) — 합계 100 */
  percentages: number[]
}

/**
 * 컬럼 폭 계산.
 * 1. 각 컬럼의 rawWidth = max(헤더 텍스트 폭, 데이터 샘플 최대 폭) + 셀 패딩
 * 2. minWidth/maxWidth 클램핑
 * 3. 컨테이너 너비에 비례 배분하여 합계 100%
 */
export function computeColumnWidths(
  columns: ColumnWidthInput[],
  containerWidth: number,
  fontSize: number = DEFAULT_FONT_SIZE,
): ColumnWidthResult {
  if (columns.length === 0) {
    return { widths: [], percentages: [] }
  }

  // containerWidth ≤ 0이면 기본값 800px
  const cw = containerWidth > 0 ? containerWidth : 800

  const clampedWidths: number[] = new Array(columns.length)

  for (let i = 0; i < columns.length; i++) {
    const col = columns[i]

    // rawWidth = max(헤더 폭, 샘플 최대 폭) + 패딩
    let maxTextWidth = estimateTextWidth(col.label, fontSize)
    const samples = col.samples
    for (let j = 0; j < samples.length; j++) {
      const w = estimateTextWidth(samples[j], fontSize)
      if (w > maxTextWidth) maxTextWidth = w
    }
    const rawWidth = maxTextWidth + CELL_HORIZONTAL_PADDING

    // minWidth/maxWidth 클램핑
    let minW = col.minWidth ?? DEFAULT_MIN_WIDTH
    let maxW = col.maxWidth ?? Infinity

    if (minW > maxW) {
      console.warn(
        `[auto-width] Column "${col.label}": minWidth(${minW}) > maxWidth(${maxW}), clamping minWidth to maxWidth`,
      )
      minW = maxW
    }

    clampedWidths[i] = Math.max(minW, Math.min(rawWidth, maxW))
  }

  // 비례 배분: percentage[i] = clampedWidth[i] / totalClamped * 100
  let totalClamped = 0
  for (let i = 0; i < clampedWidths.length; i++) {
    totalClamped += clampedWidths[i]
  }

  const percentages: number[] = new Array(columns.length)
  const widths: number[] = new Array(columns.length)

  for (let i = 0; i < columns.length; i++) {
    percentages[i] = (clampedWidths[i] / totalClamped) * 100
    widths[i] = (percentages[i] / 100) * cw
  }

  return { widths, percentages }
}
