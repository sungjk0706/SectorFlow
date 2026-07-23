/**
 * 공통 DataTable — createDataTable<T>() 팩토리 함수.
 *
 * 고정 테이블(virtualScroll: false)과 가상 스크롤(virtualScroll: true) 모드를
 * 하나의 인터페이스로 통합한다.
 *
 * 모드 구현은 분할됨 (F06-01, P24 단순성):
 * - 고정 모드: data-table-fixed.ts (createFixedMode)
 * - 가상 스크롤 모드: data-table-virtual.ts (createVirtualScrollMode)
 */

import {
  computeColWidths,
  widthsToPercentages,
  type ColumnWidthInput,
} from './auto-width'
import { COLUMN_WIDTH, type ColumnType } from './table-config'
import { uiStore } from '../../stores/uiStore'
import { createFixedMode } from './data-table-fixed'
import { createVirtualScrollMode } from './data-table-virtual'

/* ── ColumnDef<T> 인터페이스 ─────────────────────────────── */

export interface ColumnDef<T> {
  key: string
  label: string | HTMLElement
  align: 'left' | 'right' | 'center'
  render: (row: T, index: number) => string | HTMLElement
  /** 표준 컬럼 유형. minWidth/maxWidth가 모두 생략되면 COLUMN_WIDTH[type]이 자동 적용된다. */
  type?: ColumnType
  minWidth?: number
  maxWidth?: number
  headerStyle?: Partial<CSSStyleDeclaration>
  cellStyle?: Partial<CSSStyleDeclaration>
  /** 값이 변경되면 셀 배경에 노란 플래시 애니메이션 적용 (ui_price_flash_on 설정 연동) */
  flash?: boolean
}

/* ── GroupRow, TableRow, Options, Api ───────────────────── */

export interface GroupRow {
  type: 'group'
  label: string
  key: string
  score?: number
  style?: Partial<CSSStyleDeclaration>
}

export type TableRow<T> = T | GroupRow

export interface DataTableOptions<T> {
  columns: ColumnDef<T>[]
  virtualScroll?: boolean
  keyFn?: (row: T, index: number) => string
  stickyHeader?: boolean
  emptyText?: string
  rowStyle?: (row: T, index: number) => Partial<CSSStyleDeclaration> | undefined
  /** 행 전체 너비(1 / -1)를 차지하는 하단 footer 요소 렌더링. 가상 스크롤 호환. */
  rowFooter?: (row: T, index: number) => HTMLElement
  rowHeight?: number
  groupRowHeight?: number
  zebraStriping?: boolean
}

export interface DataTableApi<T> {
  el: HTMLElement
  updateRows: (rows: TableRow<T>[]) => void
  destroy: () => void
  updateItems?: (items: TableRow<T>[]) => void
  updateItem?: (index: number, item: TableRow<T>) => void
  updateItemByKey?: (key: string) => void
  scrollToIndex?: (index: number) => void
}


/* ── 유틸리티 ──────────────────────────────────────────── */

/** 실시간 현재가 플래시 효과 — Web Animations API 기반 (reflow/setTimeout/class 관리 없음) */
export function triggerFlash(cell: HTMLElement): void {
  const settings = uiStore.getState().settings
  if (settings && settings.ui_price_flash_on === false) return
  cell.animate(
    [{ backgroundColor: 'rgba(255, 235, 59, 0.4)' }, { backgroundColor: 'transparent' }],
    { duration: 500, easing: 'ease-out', composite: 'replace' },
  )
}

export function isGroupRow<T>(row: TableRow<T>): row is GroupRow {
  return (row as GroupRow).type === 'group'
}

/** 점수 색상 (0~100 점수에 따라 단계별 색상 반환) */
export function scoreColor(score: number): string {
  if (score >= 80) return '#e67e22'   // 고득점: 주황
  if (score >= 60) return '#2c3e50'   // 중간: 다크 네이비
  return '#7f8c8d'                    // 저득점: 회색
}

function extractSamples<T>(
  columns: ColumnDef<T>[],
  rows: TableRow<T>[],
): string[][] {
  const samplesByCol: string[][] = columns.map(() => [])
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (isGroupRow(row)) continue
    for (let c = 0; c < columns.length; c++) {
      // P25: 셀 단위 격리 — render throw 시 빈 문자열(기본 너비 사용) + 로깅, 다음 셀 계속
      try {
        const result = columns[c].render(row as T, i)
        samplesByCol[c].push(typeof result === 'string' ? result : result.textContent || '')
      } catch (e) {
        console.error('[DataTable] sample render error', e)
        samplesByCol[c].push('')
      }
    }
  }
  return samplesByCol
}

/**
 * 컬럼 너비 관리자 — 첫 updateRows 시 1회만 데이터 기반 폭 계산 후 고정.
 * 두 모드(fixed/virtualScroll)가 공통 사용하며 applyWidths 콜백만 모드별 주입.
 * 첫 데이터로 적절한 폭을 자동 계산하고, 이후 어떤 데이터 변화에도 재계산하지 않아 컬럼 구분선이 완전 고정됨.
 */
export function createColumnWidthManager<T extends object>(
  columns: ColumnDef<T>[],
  applyWidths: (percentages: number[]) => void,
) {
  const fontSize = 13 // FONT_SIZE.body (13px) — auto-width.ts DEFAULT_FONT_SIZE와 동일
  let initialized = false

  /** 첫 updateRows 시 1회만 전체 데이터로 폭 계산 + 적용. 이후 호출은 no-op. */
  function initFromRows(rows: TableRow<T>[]) {
    if (initialized) return
    initialized = true
    const samples = extractSamples(columns, rows)
    const inputs: ColumnWidthInput[] = columns.map((col, i) => {
      const typeWidth = col.type ? COLUMN_WIDTH[col.type] : undefined
      const hasExplicitWidth = col.minWidth !== undefined || col.maxWidth !== undefined
      return {
        label: typeof col.label === 'string' ? col.label : (col.label.textContent || ''),
        minWidth: hasExplicitWidth ? col.minWidth : typeWidth?.minWidth,
        maxWidth: hasExplicitWidth ? col.maxWidth : typeWidth?.maxWidth,
        samples: samples[i],
      }
    })
    const colWidths = computeColWidths(inputs, fontSize)
    const percentages = widthsToPercentages(colWidths)
    applyWidths(percentages)
  }

  return { initFromRows }
}


/* ── createDataTable 팩토리 함수 ──────────────────────── */

export function createDataTable<T extends object>(
  options: DataTableOptions<T>,
): DataTableApi<T> {
  const {
    columns,
    virtualScroll = false,
    stickyHeader = true,
    emptyText = '데이터가 없습니다.',
    rowStyle,
    rowFooter,
    rowHeight = 32,
    groupRowHeight = 48,
    zebraStriping = false,
  } = options

  if (virtualScroll && !options.keyFn) {
    throw new Error('virtualScroll: true requires keyFn')
  }

  if (virtualScroll) {
    return createVirtualScrollMode(options, columns, stickyHeader, emptyText, rowStyle, rowFooter, rowHeight, groupRowHeight, zebraStriping)
  }
  return createFixedMode(options, columns, stickyHeader, emptyText, rowStyle, zebraStriping)
}
