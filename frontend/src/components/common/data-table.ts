/**
 * 공통 DataTable — createDataTable<T>() 팩토리 함수.
 *
 * 고정 테이블(virtualScroll: false)과 가상 스크롤(virtualScroll: true) 모드를
 * 하나의 인터페이스로 통합한다.
 */

import { CELL_BORDER, COLOR, FONT_SIZE, FONT_WEIGHT, FONT_FAMILY } from './ui-styles'
import {
  computeColWidths,
  widthsToPercentages,
  type ColumnWidthInput,
} from './auto-width'
import { createVirtualScroller } from '../virtual-scroller'
import { uiStore } from '../../stores/uiStore'

interface CellWithPrevContent extends HTMLElement {
  _prevContent?: string
}

interface RowWithKey extends HTMLElement {
  _rowKey?: string
}

/* ── ColumnDef<T> 인터페이스 ─────────────────────────────── */

export interface ColumnDef<T> {
  key: string
  label: string | HTMLElement
  align: 'left' | 'right' | 'center'
  render: (row: T, index: number) => string | HTMLElement
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
function triggerFlash(cell: HTMLElement): void {
  const settings = uiStore.getState().settings
  if (settings && settings.ui_price_flash_on === false) return
  cell.animate(
    [{ backgroundColor: 'rgba(255, 235, 59, 0.4)' }, { backgroundColor: 'transparent' }],
    { duration: 500, easing: 'ease-out', composite: 'replace' },
  )
}

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
  const samplesByCol: string[][] = columns.map(() => [])
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (isGroupRow(row)) continue
    for (let c = 0; c < columns.length; c++) {
      const result = columns[c].render(row as T, i)
      samplesByCol[c].push(typeof result === 'string' ? result : result.textContent || '')
    }
  }
  return samplesByCol
}

/**
 * 컬럼 너비 관리자 — 첫 updateRows 시 1회만 데이터 기반 폭 계산 후 고정.
 * 두 모드(fixed/virtualScroll)가 공통 사용하며 applyWidths 콜백만 모드별 주입.
 * 첫 데이터로 적절한 폭을 자동 계산하고, 이후 어떤 데이터 변화에도 재계산하지 않아 컬럼 구분선이 완전 고정됨.
 */
function createColumnWidthManager<T extends object>(
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
    const inputs: ColumnWidthInput[] = columns.map((col, i) => ({
      label: typeof col.label === 'string' ? col.label : (col.label.textContent || ''),
      minWidth: col.minWidth,
      maxWidth: col.maxWidth,
      samples: samples[i],
    }))
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
  return createFixedMode(options, columns, stickyHeader, emptyText, rowStyle, zebraStriping)
}

/* ── 고정 테이블 모드 ─────────────────────────────────── */

function createFixedMode<T extends object>(
  options: DataTableOptions<T>,
  columns: ColumnDef<T>[],
  stickyHeader: boolean,
  emptyText: string,
  rowStyle?: (row: T, index: number) => Partial<CSSStyleDeclaration> | undefined,
  zebraStriping?: boolean,
): DataTableApi<T> {
  let destroyed = false
  let currentRows: TableRow<T>[] = []
  const initialPercentages = columns.map(() => 100 / (columns.length || 1))

  const wrapper = document.createElement('div')
  Object.assign(wrapper.style, { border: CELL_BORDER, overflowY: 'auto', height: '100%', flex: '1', minHeight: 0 })

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
    col.style.width = `${initialPercentages[i]}%`
    colEls.push(col)
    colgroup.appendChild(col)
  }
  table.appendChild(colgroup)

  const thead = document.createElement('thead')
  if (stickyHeader) {
    Object.assign(thead.style, { position: 'sticky', top: '0', background: COLOR.white, zIndex: '2' })
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
      background: COLOR.white,
      borderRight: i < columns.length - 1 ? `1px solid ${COLOR.borderGrid}` : 'none',
      borderBottom: `2px solid ${COLOR.borderDark}`,
    })
    if (c.headerStyle) Object.assign(th.style, c.headerStyle)
    if (typeof c.label === 'string') th.textContent = c.label
    else th.appendChild(c.label)
    headerTr.appendChild(th)
  }
  thead.appendChild(headerTr)
  table.appendChild(thead)

  const tbody = document.createElement('tbody')
  table.appendChild(tbody)
  wrapper.appendChild(table)

  let rowCaches: HTMLElement[] = []
  const emptyTr = document.createElement('tr')
  const emptyTd = document.createElement('td')
  emptyTd.colSpan = columns.length
  Object.assign(emptyTd.style, { color: COLOR.disabled, padding: '20px 0', textAlign: 'center' })
  emptyTd.textContent = emptyText
  emptyTr.appendChild(emptyTd)
  tbody.appendChild(emptyTr)

  function wasGroupRow(rowEl: HTMLElement): boolean {
    return rowEl.getAttribute('data-row-type') === 'group'
  }

  function renderGroupRow(g: GroupRow): HTMLElement {
    const tr = document.createElement('tr')
    tr.setAttribute('data-row-type', 'group')
    if (g.style) Object.assign(tr.style, g.style)
    const td = document.createElement('td')
    td.colSpan = columns.length
    Object.assign(td.style, {
      padding: '10px 0 4px',
      fontWeight: FONT_WEIGHT.normal,
      fontSize: FONT_SIZE.group,
      color: COLOR.groupHeader,
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
      span.textContent = `(종합점수 : ${g.score})`
      td.appendChild(span)
    }
    tr.appendChild(td)
    return tr
  }

  function renderDataRow(row: T, idx: number): HTMLElement {
    const tr = document.createElement('tr')
    tr.setAttribute('data-row-type', 'data')
    if (zebraStriping && idx % 2 === 1) tr.style.backgroundColor = COLOR.zebra
    const rs = rowStyle ? rowStyle(row, idx) : undefined
    if (rs) Object.assign(tr.style, rs)
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
        borderRight: i < columns.length - 1 ? `1px solid ${COLOR.borderGrid}` : 'none',
        borderBottom: `1px solid ${COLOR.borderRow}`,
      })
      if (c.cellStyle) Object.assign(td.style, c.cellStyle)
      try {
        const content = c.render(row, idx)
        if (typeof content === 'string') {
          td.textContent = content
          ;(td as CellWithPrevContent)._prevContent = content
        } else if (content instanceof HTMLElement) {
          td.appendChild(content)
        }
      } catch (e) { console.error('[DataTable] cell render error', e) }
      tr.appendChild(td)
    }
    return tr
  }

  function updateColWidths(percentages: number[]) {
    for (let i = 0; i < colEls.length; i++) colEls[i].style.width = `${percentages[i]}%`
  }

  // 컬럼 너비 관리자 — 첫 updateRows 시 1회만 데이터 기반 폭 계산 후 고정
  const widthMgr = createColumnWidthManager(columns, updateColWidths)

  // Phase 2.1: 렌더링 주기 제한 (requestAnimationFrame)
  let pendingRows: TableRow<T>[] | null = null
  let rafId: number | null = null
  const TARGET_FPS = 60
  const FRAME_INTERVAL = 1000 / TARGET_FPS
  let lastRenderTime = 0

  function scheduleRender() {
    if (rafId !== null) return
    let callbackRan = false
    const id = requestAnimationFrame((timestamp) => {
      rafId = null
      callbackRan = true
      if (pendingRows === null) {
        return
      }
      const elapsed = timestamp - lastRenderTime
      if (elapsed < FRAME_INTERVAL) {
        scheduleRender()
        return
      }
      lastRenderTime = timestamp
      const rows = pendingRows
      currentRows = rows
      pendingRows = null
      if (destroyed) return

      if (rows.length === 0) {
        emptyTr.style.display = ''
        for (const tr of rowCaches) tr.style.display = 'none'
        return
      }
      emptyTr.style.display = 'none'

      // 첫 updateRows 시 1회만 데이터 기반 폭 계산 (이후 no-op, 구분선 고정)
      widthMgr.initFromRows(rows)

      // keyFn 기반 증분 갱신
      if (options.keyFn) {
        const keyFn = options.keyFn
        const newKeyMap = new Map<string, { row: TableRow<T>, index: number }>()
        for (let i = 0; i < rows.length; i++) {
          const row = rows[i]
          if (isGroupRow(row)) continue
          const key = keyFn(row as T, i)
          newKeyMap.set(key, { row, index: i })
        }

        const oldKeyMap = new Map<string, HTMLElement>()
        for (let i = 0; i < rowCaches.length; i++) {
          const rowEl = rowCaches[i]
          const key = rowEl.dataset.rowKey
          if (key) oldKeyMap.set(key, rowEl)
        }

        // 새로운 키 추가
        for (const [key, { row, index }] of newKeyMap) {
          if (!oldKeyMap.has(key)) {
            const newRow = renderDataRow(row as T, index)
            newRow.dataset.rowKey = key
            rowCaches.push(newRow)
            tbody.appendChild(newRow)
          }
        }

        // 제거된 키 삭제
        for (const [key, rowEl] of oldKeyMap) {
          if (!newKeyMap.has(key)) {
            rowEl.remove()
            const idx = rowCaches.indexOf(rowEl)
            if (idx >= 0) rowCaches.splice(idx, 1)
          }
        }

        // 기존 행 갱신
        for (let i = 0; i < rows.length; i++) {
          const row = rows[i]
          if (isGroupRow(row)) continue
          const key = keyFn(row as T, i)
          const rowEl = oldKeyMap.get(key)
          if (rowEl) {
            rowEl.style.display = ''
            const dataRow = row as T
            if (zebraStriping) {
               rowEl.style.backgroundColor = (i % 2 === 1) ? COLOR.zebra : 'transparent'
            }
            const rs = rowStyle ? rowStyle(dataRow, i) : undefined
            if (rs) {
              Object.assign(rowEl.style, rs)
            } else {
              rowEl.style.removeProperty('background')
              rowEl.style.removeProperty('background-color')
              rowEl.style.removeProperty('opacity')
            }

            // 셀 내용 갱신
            const tds = rowEl.children
            for (let cIdx = 0; cIdx < columns.length; cIdx++) {
              const cell = tds[cIdx] as HTMLElement
              if (!cell) continue
              try {
                const content = columns[cIdx].render(dataRow, i)

                if (typeof content === 'string') {
                  if (cell.textContent !== content) {
                    cell.textContent = content
                    if (columns[cIdx].flash) triggerFlash(cell)
                  }
                } else if (content instanceof HTMLElement) {
                  const existing = cell.firstElementChild as HTMLElement | null
                  if (!existing || !existing.isEqualNode(content)) {
                    while (cell.firstChild) cell.removeChild(cell.firstChild)
                    cell.appendChild(content)
                    if (columns[cIdx].flash) triggerFlash(cell)
                  }
                }
              } catch (err) { console.error('[data-table] cell render error:', err) }
            }
          }
        }
      } else {
        // 기존 인덱스 기반 갱신
        for (let i = 0; i < Math.max(rows.length, rowCaches.length); i++) {
          if (i >= rows.length) {
            rowCaches[i].style.display = 'none'
            continue
          }

          const row = rows[i]
          const currentIsGroup = isGroupRow(row)

          if (!rowCaches[i]) {
            const newRow = currentIsGroup ? renderGroupRow(row as GroupRow) : renderDataRow(row as T, i)
            rowCaches.push(newRow)
            tbody.appendChild(newRow)
            continue
          }

          const rowEl = rowCaches[i]
          rowEl.style.display = ''

          if (currentIsGroup !== wasGroupRow(rowEl)) {
            const newRow = currentIsGroup ? renderGroupRow(row as GroupRow) : renderDataRow(row as T, i)
            tbody.replaceChild(newRow, rowEl)
            rowCaches[i] = newRow
            continue
          }

          if (currentIsGroup) {
            if (row.style) Object.assign(rowEl.style, row.style)
            const td = rowEl.firstElementChild as HTMLElement
            if (td) {
              const newLabel = `📊 ${row.label}`
              const textNode = td.firstChild
              if (textNode && textNode.nodeType === Node.TEXT_NODE) {
                if (textNode.textContent !== newLabel) textNode.textContent = newLabel
              } else {
                td.textContent = newLabel
              }
              if (row.score != null) {
                let span = td.querySelector('span')
                const scoreText = `(종합점수 : ${row.score})`
                if (span) {
                  if (span.textContent !== scoreText) span.textContent = scoreText
                  if (span.style.color !== scoreColor(row.score)) span.style.color = scoreColor(row.score)
                } else {
                  span = document.createElement('span')
                  Object.assign(span.style, { marginLeft: '10px', fontSize: '0.75em', fontWeight: FONT_WEIGHT.normal, color: scoreColor(row.score) })
                  span.textContent = scoreText
                  td.appendChild(span)
                }
              } else {
                const span = td.querySelector('span')
                if (span) span.remove()
              }
            }
            continue
          }

          const dataRow = row as T
          if (zebraStriping) {
             rowEl.style.backgroundColor = (i % 2 === 1) ? COLOR.zebra : 'transparent'
          }
          const rs = rowStyle ? rowStyle(dataRow, i) : undefined
          if (rs) {
            Object.assign(rowEl.style, rs)
          } else {
            rowEl.style.removeProperty('background')
            rowEl.style.removeProperty('background-color')
            rowEl.style.removeProperty('opacity')
          }

          // 셀 내용 갱신 (keyFn 기반 경로와 동일)
          const tds = rowEl.children
          for (let cIdx = 0; cIdx < columns.length; cIdx++) {
            const cell = tds[cIdx] as HTMLElement
            if (!cell) continue
            try {
              const content = columns[cIdx].render(dataRow, i)
              if (typeof content === 'string') {
                if (cell.textContent !== content) {
                  cell.textContent = content
                  if (columns[cIdx].flash) triggerFlash(cell)
                }
              } else if (content instanceof HTMLElement) {
                const existing = cell.firstElementChild as HTMLElement | null
                if (!existing || !existing.isEqualNode(content)) {
                  while (cell.firstChild) cell.removeChild(cell.firstChild)
                  cell.appendChild(content)
                  if (columns[cIdx].flash) triggerFlash(cell)
                }
              }
            } catch (e) { console.error('[DataTable] cell render error', e) }
          }
        }
      }
    })
    if (!callbackRan) {
      rafId = id
    }
  }

  function updateRows(rows: TableRow<T>[]) {
    if (destroyed) return
    pendingRows = rows
    scheduleRender()
  }

  function destroy() {
    destroyed = true
    wrapper.remove()
    rowCaches = []
  }

  function updateItemByKey(key: string) {
    if (destroyed) return
    if (!options.keyFn) return
    const idx = currentRows.findIndex((row) => {
      if (isGroupRow(row)) return false
      return options.keyFn!(row as T, currentRows.indexOf(row)) === key
    })
    if (idx < 0) return
    const rowEl = rowCaches[idx]
    if (!rowEl || rowEl.style.display === 'none') return

    const dataRow = currentRows[idx] as T
    if (zebraStriping) {
       rowEl.style.backgroundColor = (idx % 2 === 1) ? COLOR.zebra : 'transparent'
    }
    const rs = rowStyle ? rowStyle(dataRow, idx) : undefined
    if (rs) {
      Object.assign(rowEl.style, rs)
    } else {
      rowEl.style.removeProperty('background')
      rowEl.style.removeProperty('background-color')
      rowEl.style.removeProperty('opacity')
    }
    
    const tds = rowEl.children
    for (let cIdx = 0; cIdx < columns.length; cIdx++) {
      const cell = tds[cIdx] as HTMLElement
      if (!cell) continue
      try {
        const content = columns[cIdx].render(dataRow, idx)

        if (typeof content === 'string') {
          if (cell.textContent !== content) {
            cell.textContent = content
            if (columns[cIdx].flash) triggerFlash(cell)
          }
        } else if (content instanceof HTMLElement) {
          const existing = cell.firstElementChild as HTMLElement | null
          if (!existing || !existing.isEqualNode(content)) {
            while (cell.firstChild) cell.removeChild(cell.firstChild)
            cell.appendChild(content)
            if (columns[cIdx].flash) triggerFlash(cell)
          }
        }
      } catch (e) { console.error('[DataTable] cell render error', e) }
    }
  }

  return { el: wrapper, updateRows, destroy, updateItems: updateRows, updateItemByKey }
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
  const priceMap = new Map<string, number>()


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
  Object.assign(headerDiv.style, { display: 'grid', borderBottom: `2px solid ${COLOR.borderDark}`, background: COLOR.white, flexShrink: '0' })
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
      borderLeft: i > 0 ? `1px solid ${COLOR.borderGrid}` : 'none',
      background: COLOR.white,
    })
    if (c.headerStyle) Object.assign(cell.style, c.headerStyle)
    if (typeof c.label === 'string') cell.textContent = c.label
    else cell.appendChild(c.label)
    headerDiv.appendChild(cell)
  }
  scrollContainer.appendChild(headerDiv)

  const emptyDiv = document.createElement('div')
  Object.assign(emptyDiv.style, { color: COLOR.disabled, padding: '20px 0', textAlign: 'center', display: 'none' })
  emptyDiv.textContent = emptyText
  scrollContainer.appendChild(emptyDiv)

  // 컬럼 폭 비율(%) 캐싱 — px 변환은 applyGridTemplatePx에서 수행
  let cachedPercentages: number[] = columns.map(() => 100 / (columns.length || 1))
  let lastContainerWidth = 0

  /** 캐싱된 percentages를 scrollContainer 너비 기준 px로 변환하여 DOM에 적용.
   *  scrollContainer.clientWidth는 스크롤바를 제외한 실제 렌더링 영역 너비이므로 px 합계가 정확히 일치.
   *  마지막 컬럼에 반올림 오차를 보정하여 좌우 스크롤 발생 방지. */
  function applyGridTemplatePx() {
    const w = scrollContainer.clientWidth
    if (w <= 0) return
    lastContainerWidth = w
    const pxWidths: number[] = new Array(cachedPercentages.length)
    let sum = 0
    for (let i = 0; i < cachedPercentages.length; i++) {
      const px = Math.round((cachedPercentages[i] / 100) * w)
      pxWidths[i] = px
      sum += px
    }
    // 마지막 컬럼에 반올림 오차 보정 — 합계가 w와 정확히 일치하도록
    if (pxWidths.length > 0) {
      pxWidths[pxWidths.length - 1] += w - sum
    }
    gridTemplateColumns = pxWidths.map(px => `${px}px`).join(' ')
    headerDiv.style.gridTemplateColumns = gridTemplateColumns
    // data-vs-sentinel 속성으로 virtual-scroller의 sentinel div를 정확히 식별.
    // querySelector('div')는 headerDiv를 반환하여 헤더 자식만 갱신하는 버그가 있었음.
    const sentinel = scrollContainer.querySelector('[data-vs-sentinel]')
    if (sentinel) {
      const rowEls = sentinel.children
      for (let i = 0; i < rowEls.length; i++) {
        const el = rowEls[i] as HTMLElement
        if (el.style.display !== 'none' && el.style.gridTemplateColumns) el.style.gridTemplateColumns = gridTemplateColumns
      }
    }
  }

  /** 데이터 기반 폭 비율 갱신 — initFromRows 시 호출 */
  function updateGridTemplate(percentages: number[]) {
    cachedPercentages = percentages
    applyGridTemplatePx()
  }

  updateGridTemplate(columns.map(() => 100 / (columns.length || 1)))

  // ResizeObserver — scrollContainer 너비 실제 변화 시에만 px 재계산 (데이터 변경과 무관)
  const gridRo = new ResizeObserver(() => {
    const w = scrollContainer.clientWidth
    if (w > 0 && w !== lastContainerWidth) {
      applyGridTemplatePx()
    }
  })
  gridRo.observe(scrollContainer)

  // 컬럼 너비 관리자 — 첫 updateRows 시 1회만 데이터 기반 폭 계산 후 고정
  const widthMgr = createColumnWidthManager(columns, updateGridTemplate)

  /** 행이 그룹 행으로 렌더링되었는지 판별 (data-row-type 속성 기반) */
  function wasGroupRow(rowEl: HTMLElement): boolean {
    return rowEl.getAttribute('data-row-type') === 'group'
  }

  function renderRow(row: TableRow<T>, index: number, rowEl: HTMLElement) {
    const isFirst = rowEl.childElementCount === 0
    const currentIsGroup = isGroupRow(row)
    const prevWasGroup = wasGroupRow(rowEl)

    const key = currentIsGroup ? row.key : keyFn(row as T, index)

    // 이전 키와 비교 — 행 요소가 풀에서 다른 데이터 행으로 재활용되었는지 판별
    // keyChanged=true면 스크롤 등으로 다른 종목 행이 재활용된 것이므로 플래시 억제
    const prevKey = (rowEl as RowWithKey)._rowKey
    const keyChanged = prevKey !== undefined && prevKey !== key

    ;(rowEl as RowWithKey)._rowKey = key

    // 공통 스타일 적용
    rowEl.classList.add('data-table-row')
    Object.assign(rowEl.style, { display: 'grid', gridTemplateColumns, borderBottom: `1px solid ${COLOR.borderRow}` })

    if (zebraStriping && index % 2 === 1) rowEl.style.backgroundColor = COLOR.zebra
    else rowEl.style.backgroundColor = 'transparent'

    if (!currentIsGroup) {
      const dataRow = row as T
      if ('price' in dataRow) {
        const newPrice = Number((dataRow as T & { price: unknown }).price)
        priceMap.set(key, newPrice)
      }
    }

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
          justifyContent: 'flex-start',
          fontWeight: FONT_WEIGHT.normal,
          fontSize: FONT_SIZE.group,
          color: COLOR.groupHeader,
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
          span.textContent = `(종합점수 : ${row.score})`
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
          borderLeft: i > 0 ? `1px solid ${COLOR.borderGrid}` : 'none',
        })
        if (c.cellStyle) Object.assign(cell.style, c.cellStyle)
        try {
          const content = c.render(dataRow, index)
          if (typeof content === 'string') {
            cell.textContent = content
          } else if (content instanceof HTMLElement) {
            cell.appendChild(content)
          }
        } catch (e) { console.error('[DataTable] cell render error', e) }
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
          const scoreText = `(종합점수 : ${row.score})`
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
          if (cell.textContent !== content) {
            cell.textContent = content
            if (columns[i].flash && !keyChanged) triggerFlash(cell)
          }
        } else if (content instanceof HTMLElement) {
          // HTMLElement 셀: isEqualNode 비교 후 변경 시에만 교체
          const existing = cell.firstElementChild as HTMLElement | null
          if (!existing || !existing.isEqualNode(content)) {
            while (cell.firstChild) {
              cell.removeChild(cell.firstChild)
            }
            cell.appendChild(content)
            if (columns[i].flash && !keyChanged) triggerFlash(cell)
          }
        }
      } catch (e) { console.error('[DataTable] cell render error', e) }
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
    if (rows.length > 0) {
      // 첫 updateRows 시 1회만 데이터 기반 폭 계산 (이후 no-op, 구분선 고정)
      widthMgr.initFromRows(rows)
    }
    scroller.updateItems(rows)
  }

  // Phase 2.1: 렌더링 주기 제한 (requestAnimationFrame)
  let pendingRows: TableRow<T>[] | null = null
  let rafId: number | null = null
  const TARGET_FPS = 60
  const FRAME_INTERVAL = 1000 / TARGET_FPS
  let lastRenderTime = 0

  function scheduleRender() {
    if (rafId !== null) return
    let callbackRan = false
    const id = requestAnimationFrame((timestamp) => {
      rafId = null
      callbackRan = true

      if (pendingRows === null) {
        return
      }
      const elapsed = timestamp - lastRenderTime
      if (elapsed < FRAME_INTERVAL) {
        scheduleRender()
        return
      }
      lastRenderTime = timestamp
      const rows = pendingRows
      pendingRows = null
      if (destroyed) return
      internalUpdate(rows)
    })
    if (!callbackRan) {
      rafId = id
    }
  }

  function updateRows(rows: TableRow<T>[]) {
    if (destroyed) return
    pendingRows = rows
    scheduleRender()
  }

  function destroy() {
    destroyed = true
    gridRo.disconnect()
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
    updateItemByKey: (key: string) => {
      if (!destroyed) {
        scroller.updateItemByKey(key)
      }
    },
    scrollToIndex: (index: number) => { if (!destroyed) scroller.scrollToIndex(index) },
  }
}