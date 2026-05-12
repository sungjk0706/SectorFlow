/**
 * 공통 DataTable — createDataTable<T>() 팩토리 함수.
 *
 * 고정 테이블(virtualScroll: false)과 가상 스크롤(virtualScroll: true) 모드를
 * 하나의 인터페이스로 통합한다.
 */

import { CELL_BORDER, FONT_SIZE, FONT_WEIGHT, FONT_FAMILY } from './ui-styles'
import { computeColumnWidths, type ColumnWidthInput } from './auto-width'
import { createVirtualScroller } from '../virtual-scroller'

/* ── ColumnDef<T> 인터페이스 ─────────────────────────────── */

export interface ColumnDef<T> {
  key: string
  label: string
  align: 'left' | 'right' | 'center'
  render: (row: T, index: number) => string | HTMLElement
  minWidth?: number
  maxWidth?: number
  headerStyle?: Partial<CSSStyleDeclaration>
  cellStyle?: Partial<CSSStyleDeclaration>
  /** 값이 변경되면 셀 배경에 노란 플래시 애니메이션 적용 */
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
  scrollToIndex?: (index: number) => void
}


/* ── 유틸리티 ──────────────────────────────────────────── */

function isGroupRow<T>(row: TableRow<T>): row is GroupRow {
  return (row as GroupRow).type === 'group'
}

/** 점수 색상 (0~100 점수에 따라 단계별 색상 반환) */
function scoreColor(score: number): string {
  if (score >= 80) return '#e67e22'   // 고득점: 주황
  if (score >= 60) return '#2c3e50'   // 중간: 다크 네이비
  return '#7f8c8d'                    // 저득점: 회색
}

function extractSamples<T>(
  columns: ColumnDef<T>[],
  rows: TableRow<T>[],
): string[][] {
  const maxSamples = 50
  const samplesByCol: string[][] = columns.map(() => [])
  let count = 0
  for (let i = 0; i < rows.length && count < maxSamples; i++) {
    const row = rows[i]
    if (isGroupRow(row)) continue
    for (let c = 0; c < columns.length; c++) {
      const result = columns[c].render(row as T, i)
      samplesByCol[c].push(typeof result === 'string' ? result : result.textContent || '')
    }
    count++
  }
  return samplesByCol
}

function calcPercentages<T>(
  columns: ColumnDef<T>[],
  rows: TableRow<T>[],
): number[] {
  const samples = extractSamples(columns, rows)
  const inputs: ColumnWidthInput[] = columns.map((col, i) => ({
    label: col.label,
    minWidth: col.minWidth,
    maxWidth: col.maxWidth,
    samples: samples[i],
  }))
  return computeColumnWidths(inputs, 800).percentages
}

/** 셀에 노란 플래시 애니메이션 한 번 발동 (중복 발동 시 기존 타이머 정리) */
function triggerFlash(cell: HTMLElement, duration = 600): void {
  const key = '_flashTimer' as keyof HTMLElement
  const prev = (cell as any)[key] as number | undefined
  if (prev) clearTimeout(prev)

  cell.classList.remove('cell-flash')
  void cell.offsetWidth // reflow 강제 → 애니메이션 재시작
  cell.classList.add('cell-flash')

  const timer = setTimeout(() => {
    cell.classList.remove('cell-flash')
    ;(cell as any)[key] = undefined
  }, duration)
  ;(cell as any)[key] = timer
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
    rowHeight = 32,
    groupRowHeight = 48,
    zebraStriping = false,
  } = options

  if (virtualScroll && !options.keyFn) {
    throw new Error('virtualScroll: true requires keyFn')
  }

  if (virtualScroll) {
    return createVirtualScrollMode(options, columns, stickyHeader, emptyText, rowStyle, rowHeight, groupRowHeight, zebraStriping)
  }
  return createFixedMode(columns, stickyHeader, emptyText, rowStyle, zebraStriping)
}

/* ── 고정 테이블 모드 ─────────────────────────────────── */

function createFixedMode<T extends object>(
  columns: ColumnDef<T>[],
  stickyHeader: boolean,
  emptyText: string,
  rowStyle?: (row: T, index: number) => Partial<CSSStyleDeclaration> | undefined,
  zebraStriping?: boolean,
): DataTableApi<T> {
  let destroyed = false
  let currentPercentages: number[] = columns.map(() => 100 / (columns.length || 1))

  const wrapper = document.createElement('div')
  Object.assign(wrapper.style, { border: CELL_BORDER, overflow: 'hidden' })

  const table = document.createElement('table')
  Object.assign(table.style, {
    width: '100%',
    borderCollapse: 'separate',
    borderSpacing: '0',
    tableLayout: 'fixed',
  })

  const colgroup = document.createElement('colgroup')
  const colEls: HTMLElement[] = []
  for (let i = 0; i < columns.length; i++) {
    const col = document.createElement('col')
    col.style.width = `${currentPercentages[i]}%`
    colEls.push(col)
    colgroup.appendChild(col)
  }
  table.appendChild(colgroup)

  const thead = document.createElement('thead')
  if (stickyHeader) {
    Object.assign(thead.style, { position: 'sticky', top: '0', background: '#fff', zIndex: '2' })
  }
  const headerTr = document.createElement('tr')
  for (let i = 0; i < columns.length; i++) {
    const c = columns[i]
    const th = document.createElement('th')
    Object.assign(th.style, {
      boxSizing: 'border-box',
      textAlign: 'center',
      padding: '4px 6px',
      fontSize: FONT_SIZE.header,
      fontWeight: FONT_WEIGHT.normal,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      background: '#fff',
      borderRight: i < columns.length - 1 ? '1px solid #d0d0d0' : 'none',
      borderBottom: '2px solid #ddd',
    })
    if (c.headerStyle) Object.assign(th.style, c.headerStyle)
    th.textContent = c.label
    headerTr.appendChild(th)
  }
  thead.appendChild(headerTr)
  table.appendChild(thead)

  const tbody = document.createElement('tbody')
  table.appendChild(tbody)
  wrapper.appendChild(table)

  function renderEmpty() {
    while (tbody.firstChild) {
      tbody.removeChild(tbody.firstChild)
    }
    const tr = document.createElement('tr')
    const td = document.createElement('td')
    td.colSpan = columns.length
    Object.assign(td.style, { color: '#aaa', padding: '20px 0', textAlign: 'center' })
    td.textContent = emptyText
    tr.appendChild(td)
    tbody.appendChild(tr)
  }

  function renderGroupRow(g: GroupRow): HTMLElement {
    const tr = document.createElement('tr')
    if (g.style) Object.assign(tr.style, g.style)
    const td = document.createElement('td')
    td.colSpan = columns.length
    Object.assign(td.style, {
      padding: '10px 0 4px',
      fontWeight: FONT_WEIGHT.normal,
      fontSize: FONT_SIZE.group,
      color: '#1a237e',
      textAlign: 'center',
    })
    td.textContent = `📊 ${g.label}`
    if (g.score != null) {
      const span = document.createElement('span')
      Object.assign(span.style, {
        marginLeft: '10px',
        fontSize: '0.75em',
        fontWeight: FONT_WEIGHT.normal,
        color: scoreColor(g.score),
      })
      span.textContent = `(종합점수 : ${g.score.toFixed(1)})`
      td.appendChild(span)
    }
    tr.appendChild(td)
    return tr
  }

  function renderDataRow(row: T, idx: number): HTMLElement {
    const tr = document.createElement('tr')
    const rs = rowStyle ? rowStyle(row, idx) : undefined
    if (rs) Object.assign(tr.style, rs)
    if (zebraStriping && idx % 2 === 1) tr.style.backgroundColor = '#f9f9f9'
    for (let i = 0; i < columns.length; i++) {
      const c = columns[i]
      const td = document.createElement('td')
      Object.assign(td.style, {
        boxSizing: 'border-box',
        padding: '4px 6px',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        fontSize: FONT_SIZE.body,
        fontFamily: FONT_FAMILY,
        textAlign: c.align,
        borderRight: i < columns.length - 1 ? '1px solid #d0d0d0' : 'none',
        borderBottom: '1px solid #e5e7eb',
      })
      if (c.cellStyle) Object.assign(td.style, c.cellStyle)
      const content = c.render(row, idx)
      if (typeof content === 'string') td.textContent = content
      else if (content instanceof HTMLElement) td.appendChild(content)
      tr.appendChild(td)
    }
    return tr
  }

  renderEmpty()

  function updateColWidths(percentages: number[]) {
    for (let i = 0; i < colEls.length; i++) colEls[i].style.width = `${percentages[i]}%`
    currentPercentages = percentages
  }

  function updateRows(rows: TableRow<T>[]) {
    if (destroyed) return
    while (tbody.firstChild) {
      tbody.removeChild(tbody.firstChild)
    }
    if (rows.length === 0) {
      renderEmpty()
      return
    }
    const percentages = calcPercentages(columns, rows)
    updateColWidths(percentages)
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i]
      if (isGroupRow(row)) tbody.appendChild(renderGroupRow(row))
      else tbody.appendChild(renderDataRow(row as T, i))
    }
  }

  function destroy() {
    destroyed = true
    wrapper.remove()
  }

  return { el: wrapper, updateRows, destroy }
}

/* ── 가상 스크롤 모드 ─────────────────────────────────── */

function createVirtualScrollMode<T extends object>(
  options: DataTableOptions<T>,
  columns: ColumnDef<T>[],
  stickyHeader: boolean,
  emptyText: string,
  rowStyle: ((row: T, index: number) => Partial<CSSStyleDeclaration> | undefined) | undefined,
  rowHeight: number,
  groupRowHeight: number,
  zebraStriping: boolean,
): DataTableApi<T> {
  let destroyed = false
  const keyFn = options.keyFn!
  let currentRows: TableRow<T>[] = []
  let gridTemplateColumns = ''
  let columnWidthsCalculated = false

  const wrapper = document.createElement('div')
  Object.assign(wrapper.style, {
    border: CELL_BORDER,
    display: 'flex',
    flexDirection: 'column',
    flex: '1',
    minHeight: '0',
    overflow: 'hidden',
  })

  const scrollContainer = document.createElement('div')
  Object.assign(scrollContainer.style, { flex: '1', overflowY: 'auto', scrollbarGutter: 'stable', position: 'relative' })
  wrapper.appendChild(scrollContainer)

  const headerDiv = document.createElement('div')
  Object.assign(headerDiv.style, { display: 'grid', borderBottom: '2px solid #ddd', background: '#fff', flexShrink: '0' })
  if (stickyHeader) Object.assign(headerDiv.style, { position: 'sticky', top: '0', zIndex: '2' })
  for (let i = 0; i < columns.length; i++) {
    const c = columns[i]
    const cell = document.createElement('div')
    Object.assign(cell.style, {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxSizing: 'border-box',
      padding: '4px 6px',
      fontSize: FONT_SIZE.header,
      fontWeight: FONT_WEIGHT.normal,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      borderLeft: i > 0 ? '1px solid #d0d0d0' : 'none',
      background: '#fff',
    })
    if (c.headerStyle) Object.assign(cell.style, c.headerStyle)
    cell.textContent = c.label
    headerDiv.appendChild(cell)
  }
  scrollContainer.appendChild(headerDiv)

  const emptyDiv = document.createElement('div')
  Object.assign(emptyDiv.style, { color: '#aaa', padding: '20px 0', textAlign: 'center', display: 'none' })
  emptyDiv.textContent = emptyText
  scrollContainer.appendChild(emptyDiv)

  function updateGridTemplate(percentages: number[]) {
    gridTemplateColumns = percentages.map(p => `${p}%`).join(' ')
    headerDiv.style.gridTemplateColumns = gridTemplateColumns
    const sentinel = scrollContainer.querySelector('div')
    if (sentinel) {
      const rowEls = sentinel.children
      for (let i = 0; i < rowEls.length; i++) {
        const el = rowEls[i] as HTMLElement
        if (el.style.display !== 'none' && el.style.gridTemplateColumns) el.style.gridTemplateColumns = gridTemplateColumns
      }
    }
  }

  updateGridTemplate(columns.map(() => 100 / (columns.length || 1)))

  /** 행이 그룹 행으로 렌더링되었는지 판별 (data-row-type 속성 기반) */
  function wasGroupRow(rowEl: HTMLElement): boolean {
    return rowEl.getAttribute('data-row-type') === 'group'
  }

  function renderRow(row: TableRow<T>, index: number, rowEl: HTMLElement) {
    const isFirst = rowEl.childElementCount === 0
    const currentIsGroup = isGroupRow(row)
    const prevWasGroup = wasGroupRow(rowEl)

    // 공통 스타일 적용
    rowEl.classList.add('data-table-row')
    Object.assign(rowEl.style, { display: 'grid', gridTemplateColumns, borderBottom: '1px solid #e5e7eb' })
    if (zebraStriping && index % 2 === 1) rowEl.style.backgroundColor = '#f9f9f9'
    else rowEl.style.backgroundColor = 'transparent'

    // 최초 렌더링 또는 행 타입 변경 시에만 셀 전체 생성
    if (isFirst || currentIsGroup !== prevWasGroup) {
      while (rowEl.firstChild) {
        rowEl.removeChild(rowEl.firstChild)
      }

      if (currentIsGroup) {
        rowEl.setAttribute('data-row-type', 'group')
        const cell = document.createElement('div')
        Object.assign(cell.style, {
          gridColumn: '1 / -1',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: FONT_WEIGHT.normal,
          fontSize: FONT_SIZE.group,
          color: '#1a237e',
          padding: '10px 0 4px',
        })
        if (row.style) Object.assign(rowEl.style, row.style)
        cell.textContent = `📊 ${row.label}`
        if (row.score != null) {
          const span = document.createElement('span')
          Object.assign(span.style, {
            marginLeft: '10px',
            fontSize: '0.75em',
            fontWeight: FONT_WEIGHT.normal,
            color: scoreColor(row.score),
          })
          span.textContent = `(종합점수 : ${row.score.toFixed(1)})`
          cell.appendChild(span)
        }
        rowEl.appendChild(cell)
        return
      }

      // 데이터 행 — 최초 셀 생성
      rowEl.setAttribute('data-row-type', 'data')
      const dataRow = row as T
      const rs = rowStyle ? rowStyle(dataRow, index) : undefined
      if (rs) Object.assign(rowEl.style, rs)
      for (let i = 0; i < columns.length; i++) {
        const c = columns[i]
        const cell = document.createElement('div')
        Object.assign(cell.style, {
          boxSizing: 'border-box',
          padding: '4px 6px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontSize: FONT_SIZE.body,
          fontFamily: FONT_FAMILY,
          textAlign: c.align,
          display: 'flex',
          alignItems: 'center',
          minWidth: '0',
          justifyContent: c.align === 'right' ? 'flex-end' : c.align === 'center' ? 'center' : 'flex-start',
          borderLeft: i > 0 ? '1px solid #d0d0d0' : 'none',
        })
        if (c.cellStyle) Object.assign(cell.style, c.cellStyle)
        try {
          const content = c.render(dataRow, index)
          if (typeof content === 'string') cell.textContent = content
          else if (content instanceof HTMLElement) cell.appendChild(content)
        } catch (_) {
          // 개별 셀 render 예외 시 해당 셀만 건너뛰기
        }
        rowEl.appendChild(cell)
      }

      return
    }

    // ── 기존 셀 DOM 유지 + cell diffing ──

    if (currentIsGroup) {
      // 그룹 행 — 단일 셀 textContent 갱신
      if (row.style) Object.assign(rowEl.style, row.style)
      const cell = rowEl.firstElementChild as HTMLElement
      if (cell) {
        const newLabel = `📊 ${row.label}`
        // 텍스트 노드만 비교 (첫 번째 자식 텍스트)
        const textNode = cell.firstChild
        if (textNode && textNode.nodeType === Node.TEXT_NODE) {
          if (textNode.textContent !== newLabel) {
            textNode.textContent = newLabel
          }
        } else {
          cell.textContent = newLabel
        }
        // 점수 span 갱신
        if (row.score != null) {
          let span = cell.querySelector('span') as HTMLElement | null
          const scoreText = `(종합점수 : ${row.score.toFixed(1)})`
          if (span) {
            if (span.textContent !== scoreText) span.textContent = scoreText
            if (span.style.color !== scoreColor(row.score)) span.style.color = scoreColor(row.score)
          } else {
            span = document.createElement('span')
            Object.assign(span.style, {
              marginLeft: '10px',
              fontSize: '0.75em',
              fontWeight: FONT_WEIGHT.normal,
              color: scoreColor(row.score),
            })
            span.textContent = scoreText
            cell.appendChild(span)
          }
        } else {
          const span = cell.querySelector('span')
          if (span) span.remove()
        }
      }
      return
    }

    // 데이터 행 — 셀별 diff
    const dataRow = row as T
    const rs = rowStyle ? rowStyle(dataRow, index) : undefined
    if (rs) Object.assign(rowEl.style, rs)
    const cells = rowEl.children
    for (let i = 0; i < columns.length; i++) {
      const cell = cells[i] as HTMLElement
      if (!cell) continue
      try {
        const content = columns[i].render(dataRow, index)
        if (typeof content === 'string') {
          // 문자열 셀: textContent 비교 후 변경 시에만 갱신
          if (cell.textContent !== content) {
            cell.textContent = content
            if (columns[i].flash) triggerFlash(cell)
          }
        } else if (content instanceof HTMLElement) {
          // HTMLElement 셀: outerHTML 비교 후 변경 시에만 교체
          const existing = cell.firstElementChild as HTMLElement | null
          if (!existing || existing.outerHTML !== content.outerHTML) {
            while (cell.firstChild) {
              cell.removeChild(cell.firstChild)
            }
            cell.appendChild(content)
            if (columns[i].flash) triggerFlash(cell)
          }
        }
      } catch (_) {
        // 개별 셀 render 예외 시 해당 셀만 건너뛰고 기존 DOM 유지
      }
    }

  }

  function getRowHeight(row: TableRow<T>): number {
    return isGroupRow(row) ? groupRowHeight : rowHeight
  }

  function wrappedKeyFn(row: TableRow<T>, index: number): string {
    return isGroupRow(row) ? row.key : keyFn(row as T, index)
  }

  const scroller = createVirtualScroller<TableRow<T>>({
    container: scrollContainer,
    items: [],
    getRowHeight: (item) => getRowHeight(item),
    renderRow,
    keyFn: wrappedKeyFn,
  })

  function toggleEmpty(rows: TableRow<T>[]) {
    emptyDiv.style.display = rows.length === 0 ? 'block' : 'none'
  }

  function internalUpdate(rows: TableRow<T>[]) {
    currentRows = rows
    toggleEmpty(rows)
    if (rows.length > 0 && !columnWidthsCalculated) {
      const percentages = calcPercentages(columns, rows)
      updateGridTemplate(percentages)
      columnWidthsCalculated = true
    }
    scroller.updateItems(rows)
  }

  function updateRows(rows: TableRow<T>[]) {
    if (destroyed) return
    internalUpdate(rows)
  }

  function destroy() {
    destroyed = true
    scroller.destroy()
    wrapper.remove()
  }

  return {
    el: wrapper,
    updateRows,
    destroy,
    updateItems: (items: TableRow<T>[]) => { if (!destroyed) internalUpdate(items) },
    updateItem: (index: number, item: TableRow<T>) => {
      if (destroyed) return
      currentRows[index] = item
      scroller.updateItem(index, item)
    },
    scrollToIndex: (index: number) => { if (!destroyed) scroller.scrollToIndex(index) },
  }
}