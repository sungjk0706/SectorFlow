/**
 * 공통 DataTable — 고정 테이블 모드 (virtualScroll: false).
 * data-table.ts에서 분할 (F06-01, P24 단순성).
 */

import { CELL_BORDER, COLOR, FONT_SIZE, FONT_WEIGHT, FONT_FAMILY } from './ui-styles'
import { CELL_PADDING } from './table-config'
import { createFrameScheduler } from './frame-scheduler'
import { createIcon } from './icon'
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
import type { CellWithPrevContent } from '../virtual-scroller'

/* ── 고정 테이블 모드 ─────────────────────────────────── */

export function createFixedMode<T extends object>(
  options: DataTableOptions<T>,
  columns: ColumnDef<T>[],
  stickyHeader: boolean,
  emptyText: string,
  rowStyle?: (row: T, index: number) => Partial<CSSStyleDeclaration> | undefined,
  zebraStriping?: boolean,
  widthReady?: () => boolean,
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
      padding: `${CELL_PADDING}px`,
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
    // 순위 번호: 고정폭 영역으로 분리 — 순위 변동(1자리↔2자리)에도 업종명·점수 위치 고정.
    // 가상 스크롤 모드와 동일 패턴 (P23 일관성).
    if (g.rank != null && g.rank > 0) {
      const rankSpan = document.createElement('span')
      Object.assign(rankSpan.style, {
        display: 'inline-block',
        width: '2.5em',
        textAlign: 'right',
        fontVariantNumeric: 'tabular-nums',
        marginRight: '6px',
      })
      rankSpan.setAttribute('data-group-rank', 'true')
      rankSpan.textContent = `${g.rank}.`
      td.appendChild(rankSpan)
    }
    const groupIcon = createIcon('bar-chart', { size: 14 })
    groupIcon.style.verticalAlign = 'middle'
    groupIcon.style.marginRight = '4px'
    td.appendChild(groupIcon)
    td.appendChild(document.createTextNode(g.label))
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
        padding: `${CELL_PADDING}px`,
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

  // 컬럼 너비 관리자 — 첫 updateRows 시 1회만 데이터 기반 폭 계산 후 고정.
  // widthReady 게이트(실시간 업종 데이터 전용): false면 최종 폭 고정 보류, true면 1회 계산 후 고정.
  const widthMgr = createColumnWidthManager(columns, updateColWidths, widthReady)
  // 즉시 라벨/캡 기반 안전 폭 적용 — 데이터 준비 전 균등 분배로 인한 종목명 잘림 방지.
  // 가상 스크롤 모드와 동일 패턴 (P23 일관성). widthReady=true 시 initFromRows가 실제 데이터로 덮어씀.
  widthMgr.initSafe()

  // Phase 2.1: 렌더링 주기 제한 — 공통 화면주기 갱신 도구 사용 (W11 표현 통일)
  let pendingRows: TableRow<T>[] | null = null
  const scheduler = createFrameScheduler(() => {
    if (pendingRows === null) return
    const rows = pendingRows
    currentRows = rows
    pendingRows = null
    if (destroyed) return

    if (rows.length === 0) {
      emptyTr.style.display = ''
      for (const tr of rowCaches) tr.style.display = 'none'
      // 빈 데이터라도 라벨 폭 기반으로 헤더 잘림 방지 (computeColWidths는 샘플 비어도 라벨 폭 사용).
      widthMgr.initFromRows(rows)
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
            } catch (e) { console.error('[DataTable] cell render error', e) }
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
            // ── 순위 span 갱신 (고정폭 영역) ──
            let rankSpan = td.querySelector('[data-group-rank]') as HTMLElement | null
            const hasRank = row.rank != null && row.rank > 0
            const rankText = hasRank ? `${row.rank}.` : ''
            if (hasRank) {
              if (rankSpan) {
                if (rankSpan.textContent !== rankText) rankSpan.textContent = rankText
              } else {
                rankSpan = document.createElement('span')
                Object.assign(rankSpan.style, { display: 'inline-block', width: '2.5em', textAlign: 'right', fontVariantNumeric: 'tabular-nums', marginRight: '6px' })
                rankSpan.setAttribute('data-group-rank', 'true')
                rankSpan.textContent = rankText
                td.insertBefore(rankSpan, td.firstChild)
              }
            } else if (rankSpan) {
              rankSpan.remove()
              rankSpan = null
            }

            // ── 업종명 텍스트 갱신 ──
            const newLabel = row.label
            // 아이콘 SVG 요소 다음의 텍스트 노드를 찾아 갱신
            const iconEl = rankSpan ? rankSpan.nextElementSibling : td.firstElementChild
            const labelNode = iconEl ? iconEl.nextSibling : null
            if (labelNode && labelNode.nodeType === Node.TEXT_NODE) {
              if (labelNode.textContent !== newLabel) labelNode.textContent = newLabel
            } else {
              const tn = document.createTextNode(newLabel)
              if (iconEl) iconEl.after(tn)
              else if (rankSpan) rankSpan.after(tn)
              else td.insertBefore(tn, td.firstChild)
            }

            // ── 점수 span 갱신 ──
            if (row.score != null) {
              let span = td.querySelector('span:not([data-group-rank])') as HTMLElement | null
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
              const span = td.querySelector('span:not([data-group-rank])')
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

  function updateRows(rows: TableRow<T>[]) {
    if (destroyed) return
    pendingRows = rows
    scheduler.schedule()
  }

  function destroy() {
    destroyed = true
    scheduler.destroy()
    wrapper.remove()
    rowCaches = []
  }

  function updateItemByKey(key: string) {
    if (destroyed) return
    if (!options.keyFn) return
    // M-10: findIndex 콜백 내 indexOf 중복 호출(O(n²)) 제거 — 외부 인덱스 변수로 단일 순회(O(n))
    let idx = -1
    for (let i = 0; i < currentRows.length; i++) {
      const row = currentRows[i]
      if (isGroupRow(row)) continue
      if (options.keyFn!(row as T, i) === key) {
        idx = i
        break
      }
    }
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
