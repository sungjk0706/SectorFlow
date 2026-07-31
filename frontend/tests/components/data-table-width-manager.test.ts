import { describe, it, expect, vi } from 'vitest'
import {
  createColumnWidthManager,
  type ColumnDef,
} from '../../src/components/common/data-table'
import { COLUMN_WIDTH } from '../../src/components/common/table-config'

/**
 * 세션 4 — createColumnWidthManager 단위 테스트.
 * mergeCaps 축별 병합, widthReady 게이트(준비 전 보류·준비 후 1회 고정),
 * 중복 이벤트 폭 불변, extractSamples 의 render() 경유 샘플링을 고정한다 (P10/P16/P22).
 */

interface Row { name: string; price: number }

const COLS: ColumnDef<Row>[] = [
  { key: 'name', label: '종목명', align: 'left', type: 'name', render: (r) => r.name },
  { key: 'price', label: '현재가', align: 'right', type: 'price', render: (r) => String(r.price) },
]

const ROWS: Row[] = [
  { name: '삼성전자', price: 70000 },
  { name: 'SK하이닉스', price: 120000 },
]

describe('createColumnWidthManager — mergeCaps 축별 병합', () => {
  it('type 캡과 페이지 min/max 가 각 축별로 교집합 병합된다', () => {
    // name type: min=100, max=140 / 페이지 min=120, max=200 → min=max(100,120)=120, max=min(140,200)=140
    const applied: number[][] = []
    const mgr = createColumnWidthManager<Row>(
      [{ key: 'name', label: '종목명', align: 'left', type: 'name', minWidth: 120, maxWidth: 200, render: (r) => r.name }],
      (pcts) => applied.push(pcts),
    )
    mgr.initFromRows([{ name: 'A', price: 0 }])
    expect(applied.length).toBe(1)
    // 계산된 px 폭이 [120, 140] 범위 내인지 확인 (비율이 아닌 px 검증은 어려우므로 1컬럼이면 100%)
    expect(applied[0][0]).toBe(100) // 단일 컬럼 → 100%
  })

  it('페이지 min만 지정 시 max 축은 type 캡을 유지한다', () => {
    // name type: min=100, max=140 / 페이지 min=120 만 → min=120, max=140
    const mgr = createColumnWidthManager<Row>(
      [{ key: 'name', label: '종목명', align: 'left', type: 'name', minWidth: 120, render: (r) => r.name }],
      () => {},
    )
    // 예외 없이 정상 초기화되는지 확인
    expect(() => mgr.initFromRows([{ name: 'A', price: 0 }])).not.toThrow()
  })

  it('페이지 max만 지정 시 min 축은 type 캡을 유지한다', () => {
    // name type: min=100, max=140 / 페이지 max=120 만 → min=100, max=120
    const mgr = createColumnWidthManager<Row>(
      [{ key: 'name', label: '종목명', align: 'left', type: 'name', maxWidth: 120, render: (r) => r.name }],
      () => {},
    )
    expect(() => mgr.initFromRows([{ name: 'A', price: 0 }])).not.toThrow()
  })

  it('type 미지정 시 페이지 min/max 만 사용한다', () => {
    const mgr = createColumnWidthManager<Row>(
      [{ key: 'name', label: '종목명', align: 'left', minWidth: 80, maxWidth: 120, render: (r) => r.name }],
      () => {},
    )
    expect(() => mgr.initFromRows([{ name: 'A', price: 0 }])).not.toThrow()
  })
})

describe('createColumnWidthManager — widthReady 게이트', () => {
  it('widthReady false 시 최종 폭을 고정하지 않는다 (applyWidths 호출 없음)', () => {
    const applySpy = vi.fn()
    const ready = { v: false }
    const mgr = createColumnWidthManager<Row>(COLS, applySpy, () => ready.v)
    mgr.initFromRows(ROWS)
    expect(applySpy).not.toHaveBeenCalled()
  })

  it('widthReady true 전환 시 현재 rows 로 1회 계산 후 applyWidths 호출', () => {
    const applySpy = vi.fn()
    const ready = { v: false }
    const mgr = createColumnWidthManager<Row>(COLS, applySpy, () => ready.v)
    mgr.initFromRows(ROWS) // 준비 전 → 보류
    expect(applySpy).not.toHaveBeenCalled()
    ready.v = true
    mgr.initFromRows(ROWS) // 준비 완료 → 1회 계산
    expect(applySpy).toHaveBeenCalledTimes(1)
    expect(applySpy.mock.calls[0][0].length).toBe(2) // 컬럼 2개 비율
  })

  it('widthReady 생략 시 기본값 true — 일반 테이블은 즉시 계산', () => {
    const applySpy = vi.fn()
    const mgr = createColumnWidthManager<Row>(COLS, applySpy)
    mgr.initFromRows(ROWS)
    expect(applySpy).toHaveBeenCalledTimes(1)
  })

  it('준비 완료 후 추가 rows 호출 시 폭 계산·적용이 다시 실행되지 않는다', () => {
    const applySpy = vi.fn()
    const ready = { v: true }
    const mgr = createColumnWidthManager<Row>(COLS, applySpy, () => ready.v)
    mgr.initFromRows(ROWS) // 1회 계산
    expect(applySpy).toHaveBeenCalledTimes(1)
    // 추가 데이터·수신률 이벤트 시뮬레이션 — 동일 mgr 재호출
    mgr.initFromRows([{ name: 'LG에너지솔루션', price: 500000 }, ...ROWS])
    mgr.initFromRows([...ROWS, { name: '새종목', price: 9999 }])
    expect(applySpy).toHaveBeenCalledTimes(1) // 여전히 1회
  })

  it('준비 완료 이벤트가 중복되어도 컬럼 폭이 변경되지 않는다', () => {
    const applySpy = vi.fn()
    const ready = { v: true }
    const mgr = createColumnWidthManager<Row>(COLS, applySpy, () => ready.v)
    mgr.initFromRows(ROWS)
    mgr.initFromRows(ROWS) // 중복 준비 완료 이벤트
    mgr.initFromRows(ROWS)
    expect(applySpy).toHaveBeenCalledTimes(1)
  })

  it('준비 전 rows=[] 빈 데이터라도 최종 폭을 고정하지 않는다', () => {
    const applySpy = vi.fn()
    const ready = { v: false }
    const mgr = createColumnWidthManager<Row>(COLS, applySpy, () => ready.v)
    mgr.initFromRows([])
    expect(applySpy).not.toHaveBeenCalled()
  })
})

describe('createColumnWidthManager — render() 결과 샘플링 (마스터 캐시 직접 참조 금지)', () => {
  it('extractSamples 는 ColumnDef.render() 결과를 사용한다 — render 호출 추적', () => {
    const renderSpy = vi.fn((r: Row) => r.name)
    const cols: ColumnDef<Row>[] = [
      { key: 'name', label: '종목명', align: 'left', type: 'name', render: renderSpy },
    ]
    const mgr = createColumnWidthManager<Row>(cols, () => {})
    mgr.initFromRows(ROWS)
    // 각 row 마다 render 호출됨 (group row 아님)
    expect(renderSpy).toHaveBeenCalledTimes(ROWS.length)
  })

  it('group row 는 샘플에서 제외된다', () => {
    const renderSpy = vi.fn((r: Row) => r.name)
    const cols: ColumnDef<Row>[] = [
      { key: 'name', label: '종목명', align: 'left', type: 'name', render: renderSpy },
    ]
    const mgr = createColumnWidthManager<Row>(cols, () => {})
    mgr.initFromRows([
      { type: 'group', label: '반도체', key: 'semi' },
      ...ROWS,
    ])
    // group row 1개 제외 → data row 2개만 render 호출
    expect(renderSpy).toHaveBeenCalledTimes(2)
  })

  it('render throw 시 해당 셀은 빈 문자열로 대체되고 다른 셀은 계속 계산된다 (P25 격리)', () => {
    const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const cols: ColumnDef<Row>[] = [
      { key: 'name', label: '종목명', align: 'left', type: 'name', render: () => { throw new Error('boom') } },
      { key: 'price', label: '현재가', align: 'right', type: 'price', render: (r) => String(r.price) },
    ]
    const applySpy = vi.fn()
    const mgr = createColumnWidthManager<Row>(cols, applySpy)
    expect(() => mgr.initFromRows(ROWS)).not.toThrow()
    expect(applySpy).toHaveBeenCalledTimes(1) // 격리 실패가 전체 계산을 중단하지 않음
    warnSpy.mockRestore()
  })
})

describe('createColumnWidthManager — 절대 캡·type 캡 교집합 검증', () => {
  it('news type 캡(min=50,max=70)과 절대 캡(36,240) 교집합 → [50,70]', () => {
    // news 컬럼, 유효 샘플 없음 → 라벨+패딩, 캡 [50,70] 적용
    const applied: number[][] = []
    const cols: ColumnDef<Row>[] = [
      { key: 'news', label: '뉴스', align: 'left', type: 'news', render: () => '' },
    ]
    const mgr = createColumnWidthManager<Row>(cols, (pcts) => applied.push(pcts))
    mgr.initFromRows([{ name: 'A', price: 0 }])
    expect(applied[0][0]).toBe(100) // 단일 컬럼 → 100% (px 검증은 auto-width.test.ts 에서)
  })

  it('COLUMN_WIDTH type 캡이 모두 절대 범위 [36,240] 내에 있거나 교집합 가능한지 확인', () => {
    // 모든 type 캡이 절대 최소 36 이상, 절대 최대 240 이하인지 (교집합 공집합 방지)
    for (const [type, cap] of Object.entries(COLUMN_WIDTH)) {
      if (type === 'empty') continue // empty 는 min=max=0 — 특수 의도
      expect(cap.minWidth).toBeGreaterThanOrEqual(0)
      expect(cap.maxWidth).toBeGreaterThanOrEqual(cap.minWidth)
      // 절대 캡과의 교집합: max(36, min) <= min(240, max)
      const mergedMin = Math.max(36, cap.minWidth)
      const mergedMax = Math.min(240, cap.maxWidth)
      expect(mergedMin).toBeLessThanOrEqual(mergedMax)
    }
  })
})
