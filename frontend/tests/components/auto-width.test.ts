import { describe, it, expect, vi } from 'vitest'
import {
  computeColWidths,
  clampColWidth,
  estimateTextWidth,
  type ColumnWidthInput,
} from '../../src/components/common/auto-width'
import { CELL_PADDING, COLUMN_WIDTH } from '../../src/components/common/table-config'

/**
 * 세션 4 — 데이터 분포 기반 컬럼 자동 폭 산출 단위 테스트.
 * computeColWidths 의 샘플 수별 전략(0/1~19/max, ≥20/P95), 라벨 우선, 캡 교집합,
 * 유효 샘플 필터링, 간헐 컬럼(type 캡 재사용)을 고정한다 (P10/P24).
 * percentile 은 export 되지 않으므로 computeColWidths 결과를 통해 검증.
 */

const FONT_SIZE = 13
const CELL_HORIZONTAL_PADDING = CELL_PADDING * 2 // 8

/** 컬럼 폭 계산 편의 — 단일 컬럼 래핑 */
function widthOf(col: ColumnWidthInput): number {
  return computeColWidths([col], FONT_SIZE)[0]
}

/** 캡 없는 순수 텍스트 폭 → clamp 통과값 */
function rawToClamped(textWidth: number): number {
  const raw = textWidth + CELL_HORIZONTAL_PADDING
  // ABSOLUTE_MIN=36, ABSOLUTE_MAX=240, 캡 미전달
  return Math.max(36, Math.min(raw, 240))
}

describe('computeColWidths — 샘플 수별 대표 폭 전략', () => {
  it('샘플 0개는 데이터 폭 0 → 라벨 폭만 사용한다', () => {
    const label = '종목명' // 3 한글
    const w = widthOf({ label, samples: [] })
    expect(w).toBe(rawToClamped(estimateTextWidth(label, FONT_SIZE)))
  })

  it('샘플 10개에서는 max 방식을 사용한다 (1~19개 → max, P95=max 허용 특성)', () => {
    // 10개 샘플, 가장 긴 값이 대표
    const samples = Array.from({ length: 10 }, (_, i) => 'A'.repeat(i + 1)) // 1~10자
    const longest = 'A'.repeat(10)
    const w = widthOf({ label: 'X', samples })
    expect(w).toBe(rawToClamped(Math.max(estimateTextWidth('X', FONT_SIZE), estimateTextWidth(longest, FONT_SIZE))))
  })

  it('샘플 19개는 max 방식을 사용한다 (P95_MIN_SAMPLES=20 미만 경계)', () => {
    const samples = Array.from({ length: 19 }, (_, i) => 'A'.repeat(i + 1)) // 1~19자
    const longest = 'A'.repeat(19)
    const w = widthOf({ label: 'X', samples })
    expect(w).toBe(rawToClamped(Math.max(estimateTextWidth('X', FONT_SIZE), estimateTextWidth(longest, FONT_SIZE))))
  })

  it('샘플 20개 + 긴 이상치 1개에서 P95 대표 폭을 사용해 이상치를 완화한다', () => {
    // 20개: 19개는 짧은 값, 1개는 극단적으로 긴 이상치
    const short = 'AB' // 2자
    const outlier = 'A'.repeat(200) // 극단 이상치
    const samples = [outlier, ...Array.from({ length: 19 }, () => short)]
    expect(samples.length).toBe(20)
    const w = widthOf({ label: 'X', samples })
    // Nearest Rank P95: rank = ceil(0.95 * 20) = 19 → 정렬 후 19번째(1-based) = short (이상치는 20번째)
    // 따라서 대표 데이터 폭 = short 폭, 이상치는 폭에 반영되지 않음
    const expectedDataWidth = estimateTextWidth(short, FONT_SIZE)
    const expected = rawToClamped(Math.max(estimateTextWidth('X', FONT_SIZE), expectedDataWidth))
    expect(w).toBe(expected)
    // 이상치가 반영되었다면 폭이 훨씬 컸을 것 — P95 적용으로 완화됨을 확인
    const ifMaxUsed = rawToClamped(Math.max(estimateTextWidth('X', FONT_SIZE), estimateTextWidth(outlier, FONT_SIZE)))
    expect(w).toBeLessThan(ifMaxUsed)
  })

  it('라벨 폭이 대표 데이터 폭보다 길면 라벨 폭을 우선한다', () => {
    const longLabel = '거래대금금액표시' // 8 한글
    const shortSamples = ['A', 'B', 'C'] // 1자 영문
    const w = widthOf({ label: longLabel, samples: shortSamples })
    expect(w).toBe(rawToClamped(estimateTextWidth(longLabel, FONT_SIZE)))
  })
})

describe('computeColWidths — 유효 샘플 필터링 (간헐·동적 컬럼)', () => {
  it('빈 문자열·공백 샘플은 유효 샘플 수에서 제외한다', () => {
    // 전부 빈/공백 → 유효 샘플 0개 → 라벨 폭만 사용
    const label = '뉴스'
    const w = widthOf({ label, samples: ['', '   ', '\t', '\n'] })
    expect(w).toBe(rawToClamped(estimateTextWidth(label, FONT_SIZE)))
  })

  it('null/undefined 샘플은 제외되고 유효값만 분포에 들어간다', () => {
    const label = 'X'
    const valid = 'ABCDEFGH' // 8자
    const samples: (string | null | undefined)[] = [null, undefined, '', valid, '   ']
    const w = widthOf({ label, samples: samples as string[] })
    // 유효 샘플 1개(valid) → max 방식
    expect(w).toBe(rawToClamped(Math.max(estimateTextWidth('X', FONT_SIZE), estimateTextWidth(valid, FONT_SIZE))))
  })

  it('유효 샘플이 없는 뉴스 컬럼은 라벨 + 공통 패딩 + news type 캡으로 계산된다', () => {
    // news type 캡: minWidth=50, maxWidth=70
    const label = '뉴스'
    const labelWidth = estimateTextWidth(label, FONT_SIZE)
    const w = widthOf({ label, samples: [], minWidth: COLUMN_WIDTH.news.minWidth, maxWidth: COLUMN_WIDTH.news.maxWidth })
    // rawWidth = labelWidth + 8, 캡 [50, 70] 교집합 → max(36,50)=50, min(240,70)=70
    const raw = labelWidth + CELL_HORIZONTAL_PADDING
    const expected = Math.max(50, Math.min(raw, 70))
    expect(w).toBe(expected)
    // 라벨 폭이 작아도 news type 최소 50 보장
    expect(w).toBeGreaterThanOrEqual(50)
    expect(w).toBeLessThanOrEqual(70)
  })

  it('유효 샘플이 부족한 프.순.매(program_net)는 기존 페이지 캡을 유지한다', () => {
    // program_net type 캡: minWidth=60, maxWidth=85
    // 페이지 안전 캡(76 고정, 88 최대) 가정 — 축별 교집합:
    //   min = max(60, 76) = 76, max = min(85, 88) = 85
    const label = '프.순.매'
    const longValue = 'A'.repeat(100) // 긴 값이어도 캡이 제한
    const w = widthOf({
      label,
      samples: [longValue], // 1개 → max 방식이지만 캡이 제한
      minWidth: 76,
      maxWidth: 88,
    })
    // type 캡과 페이지 캡은 data-table mergeCaps 에서 병합됨 — 여기서는 페이지 캡만 전달 시뮬레이션
    // 전달된 캡 [76, 88] + 절대 [36, 240] → min=max(36,76)=76, max=min(240,88)=88
    const raw = Math.max(estimateTextWidth(label, FONT_SIZE), estimateTextWidth(longValue, FONT_SIZE)) + CELL_HORIZONTAL_PADDING
    const expected = Math.max(76, Math.min(raw, 88))
    expect(w).toBe(expected)
    expect(w).toBeLessThanOrEqual(88)
  })

  it('호가잔량비(order_ratio) 유효 샘플 부족 시 페이지 캡을 유지한다', () => {
    // order_ratio type 캡: minWidth=80, maxWidth=140
    // 페이지 안전 캡(76 고정, 88 최대) 가정 — 축별 교집합:
    //   min = max(80, 76) = 80, max = min(140, 88) = 88
    const label = '호가잔량비'
    const w = widthOf({
      label,
      samples: [], // 유효 샘플 0 → 라벨만
      minWidth: 76,
      maxWidth: 88,
    })
    const raw = estimateTextWidth(label, FONT_SIZE) + CELL_HORIZONTAL_PADDING
    const expected = Math.max(76, Math.min(raw, 88))
    expect(w).toBe(expected)
    expect(w).toBeLessThanOrEqual(88)
  })
})

describe('computeColWidths — 배열 순서·길이 유지', () => {
  it('컬럼 간 계산 결과가 섞이지 않고 입력 순서·길이를 유지한다', () => {
    const cols: ColumnWidthInput[] = [
      { label: '종목명', samples: ['삼성전자'] },
      { label: '현재가', samples: ['70,000'] },
      { label: '등락률', samples: ['+2.5%'] },
    ]
    const widths = computeColWidths(cols, FONT_SIZE)
    expect(widths.length).toBe(3)
    // 각각 독립 계산값과 일치
    expect(widths[0]).toBe(widthOf(cols[0]))
    expect(widths[1]).toBe(widthOf(cols[1]))
    expect(widths[2]).toBe(widthOf(cols[2]))
  })

  it('빈 columns 배열은 빈 배열을 반환한다', () => {
    expect(computeColWidths([], FONT_SIZE)).toEqual([])
  })
})

describe('computeColWidths — P95 계산이 입력 배열을 변경하지 않는다', () => {
  it('20개 샘플 전달 후 원본 samples 배열이 변경되지 않는다', () => {
    const samples = Array.from({ length: 20 }, (_, i) => 'A'.repeat(i + 1))
    const snapshot = [...samples]
    widthOf({ label: 'X', samples })
    expect(samples).toEqual(snapshot)
  })
})

describe('clampColWidth — 3계층 캡 교집합', () => {
  it('전달값 없으면 절대 캡만 사용 (36~240)', () => {
    expect(clampColWidth(10)).toBe(36) // 10+8=18 → 최소 36
    expect(clampColWidth(300)).toBe(240) // 300+8=308 → 최대 240
    expect(clampColWidth(100)).toBe(108) // 100+8=108 → 범위 내
  })

  it('minWidth/maxWidth 전달 시 절대 캡과 교집합', () => {
    // minWidth=50, maxWidth=200 → 절대와 교집합 → [50, 200]
    expect(clampColWidth(10, 50, 200)).toBe(50)
    expect(clampColWidth(300, 50, 200)).toBe(200)
    expect(clampColWidth(100, 50, 200)).toBe(108)
  })

  it('minWidth가 절대 최소(36)보다 작아도 절대 최소가 하한', () => {
    expect(clampColWidth(10, 20, 100)).toBe(36) // max(36,20)=36
  })

  it('maxWidth가 절대 최대(240)보다 커도 절대 최대가 상한', () => {
    expect(clampColWidth(500, 36, 500)).toBe(240) // min(240,500)=240
  })

  it('minWidth > maxWidth 시 경고 후 maxWidth로 보정한다', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    // min=100, max=50 → 보정 후 min=50, max=50 → 항상 50
    const w = clampColWidth(200, 100, 50)
    expect(warnSpy).toHaveBeenCalled()
    expect(w).toBe(50)
    warnSpy.mockRestore()
  })

  it('절대 최소(36)가 절대 최대(240)보다 작으므로 정상 동작', () => {
    // 캡 전달 없고 텍스트 폭이 0이어도 절대 최소 36
    expect(clampColWidth(0)).toBe(36)
  })
})
