import { describe, it, expect } from 'vitest'
import { BUY_COLS } from '../../src/pages/profit-columns'

/**
 * BUY_COLS — 매수 내역 테이블 컬럼 정의 회귀 테스트.
 *
 * 세션 5(프론트엔드) — reason 문자열 파싱 제거 → 구조화 컬럼(r.sector/r.buy_rank) 직접 표시,
 * 신규 "매수 근거" 컬럼(r.reason 가산점 통합 문자열) 추가 검증.
 *
 * P10(SSOT): reason 파싱 제거, 구조화 컬럼 단일 진실 소스.
 * P20(폴백 금지): null/undefined → 빈 문자열 그대로 (폴백 값 없음).
 * P21(사용자 투명성): 매수 근거(가산점 통합 문자열) 사용자 열람 가능.
 */

function findCol(key: string): { render: (row: Record<string, unknown>, index: number) => string | HTMLElement } {
  const col = BUY_COLS.find(c => c.key === key)
  if (!col) throw new Error(`컬럼 '${key}' 없음`)
  return col
}

describe('BUY_COLS — 업종 컬럼 (r.sector 직접 표시, P10)', () => {
  const col = findCol('sector')

  it('r.sector 값을 그대로 표시', () => {
    expect(col.render({ sector: '반도체' }, 0)).toBe('반도체')
  })

  it('r.sector가 undefined일 때 빈 문자열 (P20 — 폴백 없음)', () => {
    expect(col.render({}, 0)).toBe('')
  })

  it('r.sector가 null일 때 빈 문자열 (P20)', () => {
    expect(col.render({ sector: null }, 0)).toBe('')
  })

  it('r.sector가 빈 문자열일 때 빈 문자열', () => {
    expect(col.render({ sector: '' }, 0)).toBe('')
  })

  it('reason 문자열에 "업종=X"가 있어도 파싱하지 않고 r.sector만 사용 (P10)', () => {
    // 세션 4 이전 과거 레코드: reason="업종자동매수 업종=반도체 순위=1", sector=NULL
    // 파싱하지 않고 r.sector(NULL → 빈 문자열) 표시
    expect(col.render({ reason: '업종자동매수 업종=반도체 순위=1' }, 0)).toBe('')
  })
})

describe('BUY_COLS — 매수순위 컬럼 (r.buy_rank 직접 표시, P10)', () => {
  const col = findCol('buy_rank')

  it('r.buy_rank 숫자를 문자열로 표시', () => {
    expect(col.render({ buy_rank: 1 }, 0)).toBe('1')
    expect(col.render({ buy_rank: 12 }, 0)).toBe('12')
  })

  it('r.buy_rank가 0일 때 "0" 표시 (빈 문자열 아님)', () => {
    expect(col.render({ buy_rank: 0 }, 0)).toBe('0')
  })

  it('r.buy_rank가 undefined일 때 빈 문자열 (P20)', () => {
    expect(col.render({}, 0)).toBe('')
  })

  it('r.buy_rank가 null일 때 빈 문자열 (P20)', () => {
    expect(col.render({ buy_rank: null }, 0)).toBe('')
  })

  it('reason 문자열에 "순위=N"이 있어도 파싱하지 않고 r.buy_rank만 사용 (P10)', () => {
    // 세션 4 이전 과거 레코드: reason에 순위 정보 있으나 buy_rank=NULL
    expect(col.render({ reason: '업종자동매수 업종=반도체 순위=1' }, 0)).toBe('')
  })
})

describe('BUY_COLS — 매수 근거 컬럼 (r.reason 가산점 통합 문자열, P21)', () => {
  const col = findCol('reason')

  it('가산점 통합 문자열 그대로 표시', () => {
    expect(col.render({ reason: '📈고가돌파 · 📰뉴스' }, 0)).toBe('📈고가돌파 · 📰뉴스')
  })

  it('가산점 4개 모두 발생 시 전체 문자열 표시', () => {
    expect(col.render({ reason: '📈고가돌파 · 📊잔량비율 · 📰뉴스 · 💹프로그램순매수' }, 0))
      .toBe('📈고가돌파 · 📊잔량비율 · 📰뉴스 · 💹프로그램순매수')
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

  it('과거 레코드 reason 포맷("업종자동매수 업종=X 순위=N")도 그대로 표시 (변환하지 않음 — 설계서 §3.2)', () => {
    expect(col.render({ reason: '업종자동매수 업종=반도체 순위=1' }, 0))
      .toBe('업종자동매수 업종=반도체 순위=1')
  })
})

describe('BUY_COLS — 컬럼 구조 (P23 용어 통일)', () => {
  it('컬럼 수는 11개 (기존 10 + 매수 근거 1개 신규)', () => {
    expect(BUY_COLS).toHaveLength(11)
  })

  it('매수 근거 컬럼 라벨은 "매수 근거" (표준 용어 사전 부합)', () => {
    const col = BUY_COLS.find(c => c.key === 'reason')
    expect(col?.label).toBe('매수 근거')
  })

  it('매수 근거 컬럼 타입은 desc (표준 타입 재사용, P23/P24)', () => {
    const col = BUY_COLS.find(c => c.key === 'reason')
    expect(col?.type).toBe('desc')
  })

  it('업종 컬럼 라벨은 "업종" (표준 용어 — "섹터" 아님)', () => {
    const col = BUY_COLS.find(c => c.key === 'sector')
    expect(col?.label).toBe('업종')
  })

  it('매수순위 컬럼 라벨은 "매수순위" (표준 용어)', () => {
    const col = BUY_COLS.find(c => c.key === 'buy_rank')
    expect(col?.label).toBe('매수순위')
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
