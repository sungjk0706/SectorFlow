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
import { COLOR } from './ui-styles'
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
  /** 그룹행에 표시할 순위 번호. 제공 시 업종명과 별도의 고정폭 영역으로 분리 렌더링되어
   *  순위 변동(1자리↔2자리)에도 업종명·점수 위치가 흔들리지 않는다. */
  rank?: number
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
  /**
   * 컬럼 폭 계산 준비 조건 (실시간 업종 데이터 테이블 전용).
   * - false 반환 시 최종 폭 계산을 보류하고 헤더/type 캡 기반 안전 폭으로 대기.
   * - true 반환 시 현재 rows의 render 결과로 1회 계산 후 영구 고정.
   * - 생략 시 기본값 true — 일반 테이블은 기존 즉시 계산 정책 유지.
   * 백엔드 수신율 임계값 게이트 결과(sectorDataReady)를 재사용하며 프론트에서 재계산하지 않음.
   */
  widthReady?: () => boolean
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
  if (score >= 80) return COLOR.scoreHigh   // 고득점: 주황
  if (score >= 60) return COLOR.scoreMid    // 중간: 다크 네이비
  return COLOR.scoreLow                     // 저득점: 회색
}

/** 너비 측정용 샘플 최대 행 수 — 초과 시 균등 분포 샘플링으로 render 호출 제한.
 *  P95 계산에 충분한 샘플(P95_MIN_SAMPLES=20)을 확보하면서 대량 행의 중복 렌더 비용을 O(전체) → O(100)로 축소. */
const MAX_WIDTH_SAMPLES = 100

function extractSamples<T>(
  columns: ColumnDef<T>[],
  rows: TableRow<T>[],
): string[][] {
  const samplesByCol: string[][] = columns.map(() => [])
  // 데이터 행 수 카운트 (그룹 행 제외) — 샘플링 간격 계산용
  let dataCount = 0
  for (let i = 0; i < rows.length; i++) {
    if (!isGroupRow(rows[i])) dataCount++
  }
  // 행 수가 MAX_WIDTH_SAMPLES 이하면 전체 측정, 초과면 균등 분포 샘플링
  const shouldSample = dataCount > MAX_WIDTH_SAMPLES
  const interval = shouldSample ? dataCount / MAX_WIDTH_SAMPLES : 1
  let nextSampleAt = 0
  let dataIdx = 0
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (isGroupRow(row)) continue
    if (!shouldSample || dataIdx >= nextSampleAt) {
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
      nextSampleAt += interval
    }
    dataIdx++
  }
  return samplesByCol
}

/**
 * 컬럼 너비 관리자 — 첫 updateRows 시 1회만 데이터 기반 폭 계산 후 고정.
 * 두 모드(fixed/virtualScroll)가 공통 사용하며 applyWidths 콜백만 모드별 주입.
 * 첫 데이터로 적절한 폭을 자동 계산하고, 이후 어떤 데이터 변화에도 재계산하지 않아 컬럼 구분선이 완전 고정됨.
 *
 * widthReady 준비 조건(실시간 업종 데이터 전용):
 * - widthReady가 false를 반환하면 최종 폭을 고정하지 않고 대기(헤더/type 캡 기반 안전 폭 유지).
 * - widthReady가 true를 반환하면 현재 rows의 render 결과로 1회 계산 후 영구 고정.
 * - 준비 완료 이벤트가 중복되어도 이미 initialized면 폭을 변경하지 않음.
 * - 생략 시 기본값 true — 일반 테이블은 기존 즉시 계산 정책 유지.
 */
export function createColumnWidthManager<T extends object>(
  columns: ColumnDef<T>[],
  applyWidths: (percentages: number[]) => void,
  widthReady?: () => boolean,
) {
  const fontSize = 13 // FONT_SIZE.body (13px) — auto-width.ts DEFAULT_FONT_SIZE와 동일
  let initialized = false

  /** type 캡과 페이지 min/max를 각 축별로 교집합 병합.
   *  - 최소 폭: type 최소값과 페이지 최소값 중 큰 값 (한쪽만 지정 시 반대쪽 type 캡 유지).
   *  - 최대 폭: type 최대값과 페이지 최대값 중 작은 값 (한쪽만 지정 시 반대쪽 type 캡 유지).
   *  기존에는 페이지 min/max 중 하나라도 있으면 type 캡을 통째로 대체했으나,
   *  축별 교집합으로 병합하여 페이지 특수 의도와 type 안전 범위를 함께 보존. */
  function mergeCaps(col: ColumnDef<T>): { minWidth?: number; maxWidth?: number } {
    const typeWidth = col.type ? COLUMN_WIDTH[col.type] : undefined
    const typeMin = typeWidth?.minWidth
    const typeMax = typeWidth?.maxWidth
    const pageMin = col.minWidth
    const pageMax = col.maxWidth
    // 최소 축: 둘 다 있으면 큰 값, 한쪽만 있으면 그 값, 없으면 undefined
    const minWidth = typeMin !== undefined && pageMin !== undefined
      ? Math.max(typeMin, pageMin)
      : typeMin !== undefined ? typeMin : pageMin
    // 최대 축: 둘 다 있으면 작은 값, 한쪽만 있으면 그 값, 없으면 undefined
    const maxWidth = typeMax !== undefined && pageMax !== undefined
      ? Math.min(typeMax, pageMax)
      : typeMax !== undefined ? typeMax : pageMax
    return { minWidth, maxWidth }
  }

  /** 라벨/캡 기반 안전 폭 적용 — 데이터 준비 전 임시 배치.
   *  샘플 데이터 없이 헤더 라벨과 컬럼 캡(minWidth/maxWidth)만으로 안전한 폭을 계산한다.
   *  initialized=false 유지 — 이후 widthReady=true 시 initFromRows가 실제 데이터로 최종 고정.
   *  근본 목적: 데이터 준비 전 균등 분배로 인한 종목명 잘림·빈칸 칸 배치로 인한 행 겹침 방지. */
  function initSafe() {
    if (initialized) return
    const inputs: ColumnWidthInput[] = columns.map((col) => {
      const caps = mergeCaps(col)
      return {
        label: typeof col.label === 'string' ? col.label : (col.label.textContent || ''),
        minWidth: caps.minWidth,
        maxWidth: caps.maxWidth,
        samples: [],
      }
    })
    const colWidths = computeColWidths(inputs, fontSize)
    const percentages = widthsToPercentages(colWidths)
    applyWidths(percentages)
  }

  /** 준비 완료 시 1회만 전체 데이터로 폭 계산 + 적용. 이후 호출은 no-op. */
  function initFromRows(rows: TableRow<T>[]) {
    if (initialized) return
    // widthReady 게이트 — false면 최종 폭 고정 보류 (initSafe가 적용한 안전 폭 유지)
    if (widthReady && !widthReady()) return
    initialized = true
    const samples = extractSamples(columns, rows)
    const inputs: ColumnWidthInput[] = columns.map((col, i) => {
      const caps = mergeCaps(col)
      return {
        label: typeof col.label === 'string' ? col.label : (col.label.textContent || ''),
        minWidth: caps.minWidth,
        maxWidth: caps.maxWidth,
        samples: samples[i],
      }
    })
    const colWidths = computeColWidths(inputs, fontSize)
    const percentages = widthsToPercentages(colWidths)
    applyWidths(percentages)
  }

  return { initFromRows, initSafe }
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
    widthReady,
  } = options

  if (virtualScroll && !options.keyFn) {
    throw new Error('virtualScroll: true requires keyFn')
  }

  if (virtualScroll) {
    return createVirtualScrollMode(options, columns, stickyHeader, emptyText, rowStyle, rowFooter, rowHeight, groupRowHeight, zebraStriping, widthReady)
  }
  return createFixedMode(options, columns, stickyHeader, emptyText, rowStyle, zebraStriping, widthReady)
}
