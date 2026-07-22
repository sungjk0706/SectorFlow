/**
 * 공통 DataTable — 가상 스크롤 모드 (virtualScroll: true).
 * data-table.ts에서 분할 (F06-01, P24 단순성).
 */

import { CELL_BORDER, COLOR, FONT_SIZE, FONT_WEIGHT, FONT_FAMILY } from './ui-styles'
import { createVirtualScroller } from '../virtual-scroller'
import {
  type ColumnDef,
  type TableRow,
  type DataTableOptions,
  type DataTableApi,
  triggerFlash,
  isGroupRow,
  scoreColor,
  createColumnWidthManager,
} from './data-table'

interface RowWithKey extends HTMLElement {
  _rowKey?: string
}

/* ── 가상 스크롤 모드 ─────────────────────────────────── */

export function createVirtualScrollMode<T extends object>(
  options: DataTableOptions<T>,
  columns: ColumnDef<T>[],
  stickyHeader: boolean,
  emptyText: string,
  rowStyle: ((row: T, index: number) => Partial<CSSStyleDeclaration> | undefined) | undefined,
  rowFooter: ((row: T, index: number) => HTMLElement) | undefined,
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
      // rowFooter 사용 시 2행 grid (데이터 행 + footer 행)
      if (rowFooter) {
        rowEl.style.gridTemplateRows = 'auto auto'
      }
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

      // rowFooter — 행 전체 너비(1 / -1) 하단 별도 줄
      if (rowFooter) {
        const footerCell = document.createElement('div')
        Object.assign(footerCell.style, {
          gridColumn: '1 / -1',
          padding: '0 4px 2px',
          overflow: 'hidden',
        })
        footerCell.setAttribute('data-row-footer', 'true')
        try {
          const footerContent = rowFooter(dataRow, index)
          footerCell.appendChild(footerContent)
        } catch (e) { console.error('[DataTable] rowFooter render error', e) }
        rowEl.appendChild(footerCell)
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

    // rowFooter diff — 행 전체 너비 하단 줄 갱신
    if (rowFooter) {
      const footerCell = rowEl.querySelector('[data-row-footer="true"]') as HTMLElement | null
      if (footerCell) {
        try {
          const newFooter = rowFooter(dataRow, index)
          const existing = footerCell.firstElementChild as HTMLElement | null
          if (!existing || !existing.isEqualNode(newFooter)) {
            while (footerCell.firstChild) {
              footerCell.removeChild(footerCell.firstChild)
            }
            footerCell.appendChild(newFooter)
          }
        } catch (e) { console.error('[DataTable] rowFooter diff error', e) }
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
      pendingRows = null
      if (destroyed) return
      internalUpdate(rows)
    })
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
