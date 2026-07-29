import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { getTradingToday, getTradingMonthStart, getLocalToday } from '../../src/utils/date'
import { uiStore } from '../../src/stores/uiStore'

/**
 * 개장 전 거래일 판정 로직 — getTradingToday/getTradingMonthStart phase 기반 분기 테스트.
 * 사용자 모델: "20:00~익일 08:00 = 당일(N일) 유지, 익일 08:00+ = 새 거래일(N+1일)".
 * P10 SSOT — uiStore.marketPhase 기반 판정. P16 살아있는 경로 — 실제 함수 호출 검증.
 */

function setMarketPhase(krx: string, nxt: string): void {
  uiStore.setState({
    marketPhase: { krx, nxt, krx_alert: null, is_nxt_only: false },
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  // 초기값 복원
  uiStore.setState({
    marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false },
  })
})

describe('getTradingToday — phase 기준 거래일 판정', () => {
  it('개장 전(장개시전, 07:00) → 전일 반환', () => {
    vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00')) // 목요일 07:00
    setMarketPhase('장개시전', '장개시전')
    expect(getTradingToday()).toBe('2026-07-29') // 수요일
  })

  it('휴장일(토요일) → 금요일 반환 (주말 건너뛰기)', () => {
    vi.setSystemTime(new Date('2026-08-01T14:00:00+09:00')) // 토요일 14:00
    setMarketPhase('휴장일', '휴장일')
    expect(getTradingToday()).toBe('2026-07-31') // 금요일
  })

  it('장중(정규장, 10:00) → 오늘 반환', () => {
    vi.setSystemTime(new Date('2026-07-30T10:00:00+09:00')) // 목요일 10:00
    setMarketPhase('정규장', '메인마켓')
    expect(getTradingToday()).toBe('2026-07-30')
  })

  it('장마감 후(장마감, 21:00) → 오늘 반환 (당일 성과 유지)', () => {
    vi.setSystemTime(new Date('2026-07-30T21:00:00+09:00')) // 목요일 21:00
    setMarketPhase('장마감', '장마감')
    expect(getTradingToday()).toBe('2026-07-30') // 당일 유지 (다음 거래일 전환 아님)
  })

  it('프리마켓(08:00~08:50, PRE_OPEN_PHASES 외) → 오늘 반환', () => {
    vi.setSystemTime(new Date('2026-07-30T08:30:00+09:00')) // 목요일 08:30
    setMarketPhase('장전 대기', '프리마켓')
    expect(getTradingToday()).toBe('2026-07-30')
  })

  it('초기값(WS 수신 전, 장마감) → 오늘 반환 (합리적 기본값)', () => {
    vi.setSystemTime(new Date('2026-07-30T21:00:00+09:00')) // 목요일 21:00
    // 초기값 복원 (setMarketPhase 호출 안 함 — uiStore 초기값 사용)
    uiStore.setState({
      marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false },
    })
    expect(getTradingToday()).toBe('2026-07-30')
  })

  it('월요일 아침(장개시전, 07:00) → 금요일 반환 (주말 건너뛰기)', () => {
    vi.setSystemTime(new Date('2026-08-03T07:00:00+09:00')) // 월요일 07:00
    setMarketPhase('장개시전', '장개시전')
    expect(getTradingToday()).toBe('2026-07-31') // 금요일
  })

  it('일요일(휴장일) → 금요일 반환 (주말 건너뛰기)', () => {
    vi.setSystemTime(new Date('2026-08-02T12:00:00+09:00')) // 일요일 12:00
    setMarketPhase('휴장일', '휴장일')
    expect(getTradingToday()).toBe('2026-07-31') // 금요일
  })
})

describe('getTradingMonthStart — 거래일 기준 월 시작', () => {
  it('월 경계일 개장 전(7/1 07:00, 장개시전) → 전월 1일 반환', () => {
    vi.setSystemTime(new Date('2026-07-01T07:00:00+09:00')) // 수요일 07:00
    setMarketPhase('장개시전', '장개시전')
    expect(getTradingToday()).toBe('2026-06-30') // 화요일
    expect(getTradingMonthStart()).toBe('2026-06-01')
  })

  it('장중(7/15 10:00, 정규장) → 당월 1일 반환', () => {
    vi.setSystemTime(new Date('2026-07-15T10:00:00+09:00')) // 수요일 10:00
    setMarketPhase('정규장', '메인마켓')
    expect(getTradingMonthStart()).toBe('2026-07-01')
  })

  it('월 경계일 장마감 후(7/1 21:00, 장마감) → 당월 1일 반환 (당일 유지)', () => {
    vi.setSystemTime(new Date('2026-07-01T21:00:00+09:00')) // 수요일 21:00
    setMarketPhase('장마감', '장마감')
    expect(getTradingToday()).toBe('2026-07-01') // 당일 유지
    expect(getTradingMonthStart()).toBe('2026-07-01')
  })
})

describe('getLocalToday — 캘린더 날짜 (시간 무관, 유지)', () => {
  it('개장 전에도 캘린더 오늘 반환 (표시 전용)', () => {
    vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00')) // 목요일 07:00
    setMarketPhase('장개시전', '장개시전')
    expect(getLocalToday()).toBe('2026-07-30') // 거래일 기준 아님 — 캘린더 날짜
  })
})
