import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { buildTableContainer, getAutomaticDateRange } from '../../src/pages/profit-detail-mount'
import type { ProfitDetailState } from '../../src/pages/profit-detail'
import { initDateRange, saveProfitDateRange } from '../../src/pages/profit-overview-date'
import { uiStore } from '../../src/stores/uiStore'

const OVERVIEW_DATE_KEY = 'sf_profit_date_range'
const storage = new Map<string, string>()
const localStorageMock = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value) },
  removeItem: (key: string) => { storage.delete(key) },
  clear: () => { storage.clear() },
}

function setReferenceDay(day: string): void {
  uiStore.setState({
    marketPhase: {
      krx: '정규장',
      nxt: '메인마켓',
      krx_alert: null,
      is_nxt_only: false,
      chart_reference_trading_day: day,
    },
  })
}

describe('거래일 변경 시 자동 기간 기준', () => {
  it('당일 선택은 화면을 다시 열지 않아도 현재 거래일을 사용한다', () => {
    expect(getAutomaticDateRange('today', '2026-08-03', [])).toEqual({
      from: '2026-08-03',
      to: '2026-08-03',
    })
  })

  it('5거래일 선택은 최신 일별 자료 기준으로 범위를 다시 계산한다', () => {
    const dailySummary = [
      { date: '2026-07-28' },
      { date: '2026-08-03' },
      { date: '2026-07-31' },
      { date: '2026-07-30' },
      { date: '2026-07-29' },
      { date: '2026-07-27' },
    ]
    expect(getAutomaticDateRange('fiveday', '2026-08-03', dailySummary)).toEqual({
      from: '2026-07-28',
      to: '2026-08-03',
    })
  })

  it('직접 지정 기간은 자동 기간 계산 대상이 아니다', () => {
    expect(getAutomaticDateRange(null, '2026-08-03', [])).toBeNull()
    expect(getAutomaticDateRange('total', '2026-08-03', [])).toEqual({ from: '', to: '' })
  })
})

describe('수익상세 표 영역 크기 제한', () => {
  it('표 컨테이너와 내부 보기 영역이 세로형 축소 가능 구조다', () => {
    const state = { tableContainer: null, tableViewContainer: null } as unknown as ProfitDetailState
    const container = buildTableContainer(state)
    const view = state.tableViewContainer!

    expect(container.style.display).toBe('flex')
    expect(container.style.flexDirection).toBe('column')
    expect(container.style.minHeight).toMatch(/^0(px)?$/)
    expect(view.style.display).toBe('flex')
    expect(view.style.flexDirection).toBe('column')
    expect(view.style.minHeight).toMatch(/^0(px)?$/)
  })
})

describe('수익현황 저장 기간의 의미 구분', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', localStorageMock)
    localStorageMock.removeItem(OVERVIEW_DATE_KEY)
    setReferenceDay('2026-08-03')
  })

  afterEach(() => {
    localStorageMock.removeItem(OVERVIEW_DATE_KEY)
    vi.unstubAllGlobals()
    uiStore.setState({
      marketPhase: {
        krx: '장마감',
        nxt: '장마감',
        krx_alert: null,
        is_nxt_only: false,
        chart_reference_trading_day: '',
      },
    })
  })

  it('기본 기간은 다시 열 때 현재 거래일 기준으로 갱신된다', () => {
    saveProfitDateRange('2026-07-01', '2026-07-31', undefined, 'default')
    const result = initDateRange()
    expect(result.from).toBe('2026-08-01')
    expect(result.to).toBe('2026-08-03')
  })

  it('직접 지정한 기간은 다시 열어도 유지된다', () => {
    saveProfitDateRange('2026-07-01', '2026-07-31', undefined, 'manual')
    const result = initDateRange()
    expect(result.from).toBe('2026-07-01')
    expect(result.to).toBe('2026-07-31')
  })
})
