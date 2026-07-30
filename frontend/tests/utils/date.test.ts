import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { getTradingToday, getTradingMonthStart, getLocalToday, isPreOpenPhase } from '../../src/utils/date'
import { uiStore } from '../../src/stores/uiStore'

/**
 * 거래일 기준 오늘 판정 — 백엔드 chart_reference_trading_day 기반 (P10 SSOT).
 * 프론트 독자 로직(_prevWeekday/PRE_OPEN_PHASES) 제거 — 백엔드 get_chart_reference_trading_day() 단일 소스.
 * P20 폴백 금지 — 빈 문자열(WS 미연결) 그대로 전달. P25 격리 — 빈 문자열 시 안전한 기본값.
 */

function setMarketPhase(krx: string, nxt: string, chartRefDay: string = ''): void {
  uiStore.setState({
    marketPhase: { krx, nxt, krx_alert: null, is_nxt_only: false, chart_reference_trading_day: chartRefDay },
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  // 초기값 복원
  uiStore.setState({
    marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false, chart_reference_trading_day: '' },
  })
})

describe('getTradingToday — 백엔드 chart_reference_trading_day 직접 반환', () => {
  it('개장 전(07:00) + 백엔드 전일 → 백엔드 값 직접 반환', () => {
    vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00')) // 목요일 07:00
    setMarketPhase('장개시전', '장개시전', '2026-07-29')
    expect(getTradingToday()).toBe('2026-07-29') // 백엔드 값 직접 반환
  })

  it('장중(정규장, 10:00) + 백엔드 오늘 → 백엔드 값 직접 반환', () => {
    vi.setSystemTime(new Date('2026-07-30T10:00:00+09:00')) // 목요일 10:00
    setMarketPhase('정규장', '메인마켓', '2026-07-30')
    expect(getTradingToday()).toBe('2026-07-30')
  })

  it('장마감 후(21:00) + 백엔드 오늘 → 백엔드 값 직접 반환 (당일 성과 유지)', () => {
    vi.setSystemTime(new Date('2026-07-30T21:00:00+09:00')) // 목요일 21:00
    setMarketPhase('장마감', '장마감', '2026-07-30')
    expect(getTradingToday()).toBe('2026-07-30') // 당일 유지 (다음 거래일 전환 아님)
  })

  it('초기값(WS 수신 전, 빈 문자열) → 빈 문자열 반환 (P20 폴백 금지)', () => {
    vi.setSystemTime(new Date('2026-07-30T21:00:00+09:00')) // 목요일 21:00
    // 초기값 사용 (setMarketPhase 호출 안 함 — uiStore 초기값 chart_reference_trading_day='')
    uiStore.setState({
      marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false, chart_reference_trading_day: '' },
    })
    expect(getTradingToday()).toBe('') // 빈 문자열 — 폴백으로 getLocalToday() 덮지 않음 (P20)
  })

  it('평일 공휴일(금 06:47) + 백엔드 직전 거래일 → 백엔드 값 직접 반환 (핵심 시나리오)', () => {
    // 설계서 1.2 시나리오 A — 평일 공휴일에 프론트 독자 _prevWeekday는 금요일(오늘) 반환하지만
    // 백엔드 캘린더는 공휴일을 건너뛴 직전 거래일(수) 반환 → 본 작업이 해결하는 불일치
    vi.setSystemTime(new Date('2026-08-14T06:47:00+09:00')) // 금요일 06:47 (광복절 전날 가정)
    setMarketPhase('장개시전', '장개시전', '2026-08-13') // 수요일 (백엔드 캘린더 기반)
    expect(getTradingToday()).toBe('2026-08-13') // 백엔드 값 — 프론트 독자 로직이었으면 '2026-08-14' 반환
  })

  it('월요일 아침(07:00) + 백엔드 금요일 → 백엔드 값 직접 반환', () => {
    vi.setSystemTime(new Date('2026-08-03T07:00:00+09:00')) // 월요일 07:00
    setMarketPhase('장개시전', '장개시전', '2026-07-31') // 금요일 (백엔드)
    expect(getTradingToday()).toBe('2026-07-31')
  })
})

describe('getTradingMonthStart — 거래일 기준 월 시작 (getTradingToday 기반)', () => {
  it('월 경계일 개장 전(7/1 07:00) + 백엔드 전월 말일 → 전월 1일 반환', () => {
    vi.setSystemTime(new Date('2026-07-01T07:00:00+09:00')) // 수요일 07:00
    setMarketPhase('장개시전', '장개시전', '2026-06-30') // 화요일 (백엔드)
    expect(getTradingToday()).toBe('2026-06-30')
    expect(getTradingMonthStart()).toBe('2026-06-01')
  })

  it('장중(7/15 10:00) + 백엔드 당일 → 당월 1일 반환', () => {
    vi.setSystemTime(new Date('2026-07-15T10:00:00+09:00')) // 수요일 10:00
    setMarketPhase('정규장', '메인마켓', '2026-07-15')
    expect(getTradingMonthStart()).toBe('2026-07-01')
  })

  it('월 경계일 장마감 후(7/1 21:00) + 백엔드 당일 → 당월 1일 반환 (당일 유지)', () => {
    vi.setSystemTime(new Date('2026-07-01T21:00:00+09:00')) // 수요일 21:00
    setMarketPhase('장마감', '장마감', '2026-07-01')
    expect(getTradingToday()).toBe('2026-07-01') // 당일 유지
    expect(getTradingMonthStart()).toBe('2026-07-01')
  })
})

describe('getLocalToday — 캘린더 날짜 (시간 무관, 유지)', () => {
  it('개장 전에도 캘린더 오늘 반환 (표시 전용)', () => {
    vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00')) // 목요일 07:00
    setMarketPhase('장개시전', '장개시전', '2026-07-29')
    expect(getLocalToday()).toBe('2026-07-30') // 거래일 기준 아님 — 캘린더 날짜
  })
})

describe('isPreOpenPhase — 백엔드 chart_reference_trading_day 기반 개장 전 판정', () => {
  it('백엔드 전일 + 로컬 오늘과 다름 → true (개장 전)', () => {
    vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00')) // 목요일 07:00 (로컬 오늘=2026-07-30)
    setMarketPhase('장개시전', '장개시전', '2026-07-29') // 백엔드 전일
    expect(isPreOpenPhase()).toBe(true)
  })

  it('백엔드 오늘 + 로컬 오늘과 같음 → false (개장 후)', () => {
    vi.setSystemTime(new Date('2026-07-30T10:00:00+09:00')) // 목요일 10:00 (로컬 오늘=2026-07-30)
    setMarketPhase('정규장', '메인마켓', '2026-07-30') // 백엔드 오늘
    expect(isPreOpenPhase()).toBe(false)
  })

  it('빈 문자열(WS 미연결) → false (0.5 보완안 — P21 초기 화면 동작 유지, P25 격리)', () => {
    vi.setSystemTime(new Date('2026-07-30T07:00:00+09:00')) // 목요일 07:00
    setMarketPhase('장개시전', '장개시전', '') // 빈 문자열
    expect(isPreOpenPhase()).toBe(false) // !!'' = false → 현재 동작(초기 false) 유지
  })

  it('장마감 후 + 백엔드 오늘 → false', () => {
    vi.setSystemTime(new Date('2026-07-30T21:00:00+09:00')) // 목요일 21:00
    setMarketPhase('장마감', '장마감', '2026-07-30')
    expect(isPreOpenPhase()).toBe(false)
  })
})
