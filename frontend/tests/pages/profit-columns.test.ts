import { describe, it, expect } from 'vitest'
import { BUY_COLS } from '../../src/pages/profit-columns'

/**
 * BUY_COLS — 매수 내역 테이블 컬럼 정의 회귀 테스트.
 *
 * 업종/매수순위 컬럼 제거 (P24 단순성 — 매수 후보 화면에서 이미 확인 가능).
 * 매수 근거 컬럼(r.reason 가산점 통합 문자열) 표시 검증.
 * 가산점 라벨은 매수 후보 화면(buy-target-columns.ts)과 동일 텍스트 (P23 일관성).
 *
 * P10(SSOT): reason 파싱 없이 백엔드가 보낸 그대로 표시.
 * P20(폴백 금지): null/undefined → 빈 문자열 그대로 (폴백 값 없음).
 * P21(사용자 투명성): 매수 근거(가산점 통합 문자열) 사용자 열람 가능.
 */

function findCol(key: string): { render: (row: Record<string, unknown>, index: number) => string | HTMLElement } {
  const col = BUY_COLS.find(c => c.key === key)
  if (!col) throw new Error(`컬럼 '${key}' 없음`)
  return col
}

describe('BUY_COLS — 매수 근거 컬럼 (r.reason 가산점 통합 문자열, P21)', () => {
  const col = findCol('reason')

  it('가산점 통합 문자열 그대로 표시', () => {
    expect(col.render({ reason: '5거래일 고가 · 📰뉴스' }, 0)).toBe('5거래일 고가 · 📰뉴스')
  })

  it('가산점 4개 모두 발생 시 전체 문자열 표시 (매수 후보 화면 라벨과 일치 — P23)', () => {
    expect(col.render({ reason: '5거래일 고가 · 호가잔량비 · 📰뉴스 · 프.순.매' }, 0))
      .toBe('5거래일 고가 · 호가잔량비 · 📰뉴스 · 프.순.매')
  })

  it('가산점 미발생 시 빈 문자열 (P20)', () => {
    expect(col.render({ reason: '' }, 0)).toBe('')
  })

  it('r.reason이 undefined일 때 빈 문자열 (P20)', () => {
    expect(col.render({}, 0)).toBe('')
  })

  it('r.reason이 null일 때 빈 문자열 (P20)', () => {
    expect(col.render({ reason: null }, 0)).toBe('')
  })
})

describe('BUY_COLS — 컬럼 구조 (P23 용어 통일, P24 단순성)', () => {
  it('컬럼 수는 9개 (업종/매수순위 2개 제거)', () => {
    expect(BUY_COLS).toHaveLength(9)
  })

  it('매수 근거 컬럼 라벨은 "매수 근거" (표준 용어 사전 부합)', () => {
    const col = BUY_COLS.find(c => c.key === 'reason')
    expect(col?.label).toBe('매수 근거')
  })

  it('매수 근거 컬럼 타입은 desc (표준 타입 재사용, P23/P24)', () => {
    const col = BUY_COLS.find(c => c.key === 'reason')
    expect(col?.type).toBe('desc')
  })

  it('업종 컬럼은 제거됨 (P24 단순성 — 매수 후보 화면에서 확인)', () => {
    const col = BUY_COLS.find(c => c.key === 'sector')
    expect(col).toBeUndefined()
  })

  it('매수순위 컬럼은 제거됨 (P24 단순성 — 매수 후보 화면에서 확인)', () => {
    const col = BUY_COLS.find(c => c.key === 'buy_rank')
    expect(col).toBeUndefined()
  })

  it('매수 근거 컬럼은 말줄임 스타일 적용 (긴 텍스트 안전 처리)', () => {
    const col = BUY_COLS.find(c => c.key === 'reason')
    expect(col?.cellStyle).toEqual({
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    })
  })
})
