/**
 * 공통 DataTable — 고정 테이블 모드 (virtualScroll: false).
 * data-table.ts에서 분할 (F06-01, P24 단순성).
 */

import { CELL_BORDER, COLOR, FONT_SIZE, FONT_WEIGHT, FONT_FAMILY } from './ui-styles'
import {
  type ColumnDef,
  type GroupRow,
  type TableRow,
  type DataTableOptions,
  type DataTableApi,
  triggerFlash,
  isGroupRow,
  scoreColor,
  createColumnWidthManager,
} from './data-table'

interface CellWithPrevContent extends HTMLElement {
  _prevContent?: string
}

/* ── 고정 테이블 모드 ─────────────────────────────────── */

export function createFixedMode<T extends object>(
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
    rafId = -1
    requestAnimationFrame((timestamp) => {
      rafId = null
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
            // P25: 행 단위 격리 — renderDataRow throw 시 해당 행 스킵, 다음 행 계속
            try {
              const newRow = renderDataRow(row as T, index)
              newRow.dataset.rowKey = key
              rowCaches.push(newRow)
              tbody.appendChild(newRow)
            } catch (e) { console.error('[DataTable] row render error', e) }
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
            // P25: 행 단위 격리 — renderDataRow/renderGroupRow throw 시 인덱스 정렬 유지용 placeholder 추가, 다음 행 계속
            try {
              const newRow = currentIsGroup ? renderGroupRow(row as GroupRow) : renderDataRow(row as T, i)
              rowCaches.push(newRow)
              tbody.appendChild(newRow)
            } catch (e) {
              console.error('[DataTable] row render error', e)
              const placeholder = document.createElement('tr')
              placeholder.setAttribute('data-row-type', 'data')
              placeholder.style.display = 'none'
              rowCaches.push(placeholder)
              tbody.appendChild(placeholder)
            }
            continue
          }

          const rowEl = rowCaches[i]
          rowEl.style.display = ''

          if (currentIsGroup !== wasGroupRow(rowEl)) {
            // P25: 행 단위 격리 — 교체 실패 시 기존 rowEl 유지, 테이블 전체 중단 방지
            try {
              const newRow = currentIsGroup ? renderGroupRow(row as GroupRow) : renderDataRow(row as T, i)
              tbody.replaceChild(newRow, rowEl)
              rowCaches[i] = newRow
            } catch (e) { console.error('[DataTable] row render error', e) }
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
