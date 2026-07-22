/**
 * 공통 UI 스타일 — 테이블 컬럼 팩토리.
 * ui-styles.ts에서 분할 (F06-03, P24 단순성).
 * 순수 이동 — 동작 변경 없음. 외부 import 경로는 메인에서 re-export 유지.
 */

import type { ColumnDef } from './data-table'
import { COLUMN_WIDTH } from './table-config'
import { COLOR } from './ui-styles'
import {
  createSeqCell,
  createCodeCell,
  createPriceCell,
  createChangeCell,
  createRateCell,
  createStrengthCell,
  createAmountCell,
  createAvgAmountCell,
  createStockNameCell,
} from './ui-styles-cells'

/* ── 공통 컬럼 팩토리 ── */
/**
 * 데이터 접근 getter를 받아 ColumnDef를 반환하는 팩토리 함수.
 * buy-target(flat) / sector-stock(중첩) 등 구조가 다른 페이지에서 동일하게 사용.
 */

/** 순번 컬럼 */
export function makeSeqColumn<T>(get: (t: T) => number): ColumnDef<T> {
  return {
    key: 'seq',
    label: '순번',
    align: 'center',
    type: 'seq',
    ...COLUMN_WIDTH.seq,
    render: (t) => createSeqCell(get(t)),
  }
}

/** 종목코드 컬럼 */
export function makeCodeColumn<T>(get: (t: T) => string): ColumnDef<T> {
  return {
    key: 'code',
    label: '종목코드',
    align: 'center',
    type: 'code',
    ...COLUMN_WIDTH.code,
    render: (t) => createCodeCell(get(t)),
  }
}

/** 현재가 컬럼 */
export function makePriceColumn<T>(
  getPrice: (t: T) => number | null | undefined,
  getRate: (t: T) => number | null | undefined,
): ColumnDef<T> {
  return {
    key: 'cur_price',
    label: '현재가',
    align: 'right',
    type: 'price',
    ...COLUMN_WIDTH.price,
    flash: true,
    render: (t) => {
      return createPriceCell(getPrice(t), getRate(t))
    },
  }
}

/** 대비 컬럼 */
export function makeChangeColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'change',
    label: '대비',
    align: 'center',
    type: 'change',
    ...COLUMN_WIDTH.change,
    render: (t) => createChangeCell(get(t)),
  }
}

/** 등락률 컬럼 */
export function makeRateColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'change_rate',
    label: '등락률',
    align: 'right',
    type: 'rate',
    ...COLUMN_WIDTH.rate,
    render: (t) => createRateCell(get(t)),
  }
}

/** 체결강도 컬럼 */
export function makeStrengthColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'strength',
    label: '체결강도',
    align: 'right',
    type: 'strength',
    ...COLUMN_WIDTH.strength,
    render: (t) => createStrengthCell(get(t)),
  }
}

/** 거래대금 컬럼 (억 단위 표시) */
export function makeAmountColumn<T>(get: (t: T) => number | null | undefined): ColumnDef<T> {
  return {
    key: 'trade_amount',
    label: '거래대금(억)',
    align: 'right',
    type: 'amount',
    ...COLUMN_WIDTH.amount,
    render: (t) => createAmountCell(get(t)),
  }
}

/** 5일평균거래대금 컬럼 (억 단위 표시) */
export function makeAvgAmountColumn<T>(get: (t: T) => number): ColumnDef<T> {
  return {
    key: 'avg_amt_5d',
    label: '5일평균(억)',
    align: 'right',
    type: 'avg_amount',
    ...COLUMN_WIDTH.avg_amount,
    render: (t) => createAvgAmountCell(get(t)),
  }
}

/* ── 표준화된 종목명 컬럼 생성 함수 ── */

/** 표준 종목명 컬럼 정의 - 모든 페이지에서 동일한 스타일과 구조 사용 */
export function createStockNameColumn<T extends object>(
  fallbackLookup: (item: T) => { name: string; market_type?: string; nxt_enable?: boolean }
): ColumnDef<T> {
  return {
    key: 'name',
    label: '종목명',
    align: 'left',
    type: 'name',
    ...COLUMN_WIDTH.name,
    cellStyle: { fontWeight: 'normal', color: COLOR.neutral },
    render: (item: T) => {
      const lookup = fallbackLookup(item)
      return createStockNameCell(lookup.name, lookup.market_type, lookup.nxt_enable)
    }
  }
}
