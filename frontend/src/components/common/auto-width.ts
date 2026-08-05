/**
 * Auto_Width_Engine — 데이터 기반 컬럼 폭 자동 계산 (순수 함수, DOM 접근 없음).
 *
 * 한글 문자는 영문 대비 약 1.4배 폭으로 취급하여
 * 9자 이내 종목명까지 표시하면서 공간 낭비를 줄인다.
 */

import { CELL_PADDING } from './table-config'

/** 기본 폰트 크기 — FONT_SIZE.body (13px) */
const DEFAULT_FONT_SIZE = 13

/** 셀 수평 패딩 합계 — table-config.ts CELL_PADDING과 동기화 (좌우 합) */
const CELL_HORIZONTAL_PADDING = CELL_PADDING * 2

/** P95 백분위 적용 최소 샘플 수 (미만 시 max 사용 — Nearest Rank 특성 반영) */
const P95_MIN_SAMPLES = 20

/** 절대 최소 폭 (모든 컬럼 공통 하한 — 극단값 차단) */
const ABSOLUTE_MIN_WIDTH = 36

/** 절대 최대 폭 (모든 컬럼 공통 상한 — 폭 계산 가중치 상한, percentage 변환 전) */
const ABSOLUTE_MAX_WIDTH = 240

/** 한글 문자 폭 대비 영문/숫자 배율. Tahoma/굴림 13px 기준 실측에 가까운 1.4 사용. */
const KOREAN_SCALE = 1.4

/**
 * 배열의 p백분위 값 (Nearest Rank 방식 — 단순·결정론적, 보간 없음).
 * - 입력 배열을 복사한 뒤 오름차순 정렬하여 원본을 변경하지 않음.
 * - 빈 배열은 0 반환.
 * - Math.ceil((p / 100) * length) rank 사용 → 보수적 (더 큰 폭, 잘림 최소화).
 * - 마지막 인덱스 보호 적용.
 */
function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const rank = Math.ceil((p / 100) * sorted.length)
  return sorted[Math.min(rank - 1, sorted.length - 1)]
}

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
 * rawWidth = textWidth + 셀 패딩.
 * 3계층 캡 교집합 — 절대 캡(ABSOLUTE_MIN/MAX)과 전달된 minWidth/maxWidth(병합된 type/page 캡)의 교집합.
 * - 최소 폭: max(ABSOLUTE_MIN_WIDTH, minWidth) — 전달값 없으면 절대 최소값.
 * - 최대 폭: min(ABSOLUTE_MAX_WIDTH, maxWidth) — 전달값 없으면 절대 최대값.
 * - min > max 시 기존 경고 후 max로 보정.
 */
export function clampColWidth(
  textWidth: number,
  minWidth?: number,
  maxWidth?: number,
): number {
  const rawWidth = textWidth + CELL_HORIZONTAL_PADDING
  let minW = minWidth !== undefined ? Math.max(ABSOLUTE_MIN_WIDTH, minWidth) : ABSOLUTE_MIN_WIDTH
  const maxW = maxWidth !== undefined ? Math.min(ABSOLUTE_MAX_WIDTH, maxWidth) : ABSOLUTE_MAX_WIDTH
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
 * 1. 유효 데이터 샘플 폭 배열 계산 — null·undefined·빈 문자열·공백은 분포에서 제외.
 * 2. 대표 폭 선택 (유효 샘플 수에 따른 단계적 전략):
 *    - 0개: dataWidth=0 (라벨 폭만 사용)
 *    - 1~19개: max (Nearest Rank P95가 max와 같을 수 있어 기존 방식 유지)
 *    - ≥20개: P95 (Nearest Rank — 상위 5% 이상치 완화)
 * 3. maxTextWidth = max(라벨 폭, 대표 데이터 폭)
 * 4. clampColWidth로 px 폭 산출 (3계층 캡 교집합)
 */
export function computeColWidths(
  columns: ColumnWidthInput[],
  fontSize: number = DEFAULT_FONT_SIZE,
): number[] {
  if (columns.length === 0) return []

  const widths: number[] = new Array(columns.length)

  for (let i = 0; i < columns.length; i++) {
    const col = columns[i]
    const labelWidth = estimateTextWidth(col.label, fontSize)

    // 유효 데이터 샘플 폭 배열 — 빈 문자열·공백은 분포에서 제외 (간헐·동적 컬럼 처리)
    const sampleWidths: number[] = []
    const samples = col.samples
    for (let j = 0; j < samples.length; j++) {
      if (samples[j] == null) continue
      if (samples[j].trim().length === 0) continue
      sampleWidths.push(estimateTextWidth(samples[j], fontSize))
    }

    // 대표 폭 선택 (유효 샘플 수에 따른 단계적 전략)
    let dataWidth: number
    if (sampleWidths.length === 0) {
      dataWidth = 0                                    // 데이터 없음 → 라벨만 사용
    } else if (sampleWidths.length < P95_MIN_SAMPLES) {
      dataWidth = Math.max(...sampleWidths)            // 샘플 부족 → max (기존 방식)
    } else {
      dataWidth = percentile(sampleWidths, 95)         // 충분 → P95
    }

    const maxTextWidth = Math.max(labelWidth, dataWidth)
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
