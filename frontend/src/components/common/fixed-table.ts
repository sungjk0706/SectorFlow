/* ── 컬럼 정의 ─────────────────────────────────────────────── */
export interface ColDef<T> {
  key: string
  label: string
  width: string
  align?: 'left' | 'right' | 'center'
  render: (row: T, idx: number) => string | HTMLElement
  headerStyle?: Partial<CSSStyleDeclaration>
  tdStyle?: Partial<CSSStyleDeclaration>
}

/* ── 업종 구분 행 (선택) ───────────────────────────────────── */
export interface GroupRow {
  type: 'group'
  label: string
  key: string
  score?: number
  style?: Partial<CSSStyleDeclaration>
}

export type TableRow<T> = T | GroupRow

/* ── 셀 스타일 헬퍼 ───────────────────────────────────────── */
import { CELL_BORDER, FONT_SIZE, FONT_WEIGHT } from './ui-styles'

const CELL_BASE = `box-sizing:border-box;padding:4px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border-right:${CELL_BORDER};`

export function cellStyle(align?: 'left' | 'right' | 'center', _mono = true): string {
  if (align === 'left') return CELL_BASE + 'text-align:left;font-weight:500;color:#111;'
  if (align === 'right') return CELL_BASE + 'text-align:right;'
  return CELL_BASE + 'text-align:center;'
}

/* ── 점수 색상 (0~100 그라데이션) ──────────────────────────── */
function scoreColor(score: number): string {
  const t = Math.max(0, Math.min(score, 100)) / 100
  const r = Math.round(240 + (230 - 240) * t)
  const g = Math.round(192 + (81 - 192) * t)
  const b = Math.round(128 + (0 - 128) * t)
  return `rgb(${r},${g},${b})`
}

/* ── 팩토리 함수 ───────────────────────────────────────────── */
export interface FixedTableOptions<T> {
  columns: ColDef<T>[]
  emptyText?: string
  stickyHeader?: boolean
  bordered?: boolean
  rowKey?: (row: T, idx: number) => string
  rowStyle?: (row: T, idx: number) => Partial<CSSStyleDeclaration> | undefined
}

export function createFixedTable<T extends object>(options: FixedTableOptions<T>) {
  const {
    columns,
    emptyText = '데이터가 없습니다.',
    stickyHeader = true,
    bordered = false,
    rowStyle,
  } = options

  const table = document.createElement('table')
  table.tabIndex = -1
  Object.assign(table.style, {
    width: '100%',
    borderCollapse: 'collapse',
    tableLayout: 'fixed',
    outline: 'none',
  } as Partial<CSSStyleDeclaration>)
  if (bordered) table.style.border = CELL_BORDER

  // colgroup
  const colgroup = document.createElement('colgroup')
  for (const c of columns) {
    const col = document.createElement('col')
    col.style.width = c.width
    colgroup.appendChild(col)
  }
  table.appendChild(colgroup)

  // thead
  const thead = document.createElement('thead')
  if (stickyHeader) {
    Object.assign(thead.style, { position: 'sticky', top: '0', background: '#fff', zIndex: '2' })
  }
  const headerTr = document.createElement('tr')
  if (!bordered) headerTr.style.borderBottom = '2px solid #ddd'
  for (const c of columns) {
    const th = document.createElement('th')
    Object.assign(th.style, {
      boxSizing: 'border-box',
      textAlign: 'center',
      padding: '4px 6px',
      fontSize: FONT_SIZE.header,
      fontWeight: FONT_WEIGHT.normal,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      borderRight: CELL_BORDER,
    })
    if (bordered) th.style.borderBottom = CELL_BORDER
    if (c.headerStyle) Object.assign(th.style, c.headerStyle)
    th.textContent = c.label
    headerTr.appendChild(th)
  }
  thead.appendChild(headerTr)
  table.appendChild(thead)

  // tbody
  const tbody = document.createElement('tbody')
  table.appendChild(tbody)

  // empty row
  function renderEmpty() {
    tbody.innerHTML = ''
    const tr = document.createElement('tr')
    const td = document.createElement('td')
    td.colSpan = columns.length
    Object.assign(td.style, { color: '#aaa', padding: '20px 0', textAlign: 'center' })
    td.textContent = emptyText
    tr.appendChild(td)
    tbody.appendChild(tr)
  }

  function renderGroupRow(g: GroupRow) {
    const tr = document.createElement('tr')
    if (g.style) Object.assign(tr.style, g.style)
    const td = document.createElement('td')
    td.colSpan = columns.length
    Object.assign(td.style, {
      padding: '10px 0 4px',
      fontWeight: FONT_WEIGHT.normal,
      fontSize: '1.25em',
      color: '#1a73e8',
      textAlign: 'center',
    })
    td.textContent = `◆ ${g.label}`
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

  function renderDataRow(row: T, idx: number) {
    const tr = document.createElement('tr')
    const rs = rowStyle ? rowStyle(row, idx) : undefined
    if (rs) Object.assign(tr.style, rs)
    if (!bordered) tr.style.borderBottom = CELL_BORDER
    for (const c of columns) {
      const td = document.createElement('td')
      td.setAttribute('style', cellStyle(c.align))
      if (bordered) td.style.borderBottom = CELL_BORDER
      if (c.tdStyle) Object.assign(td.style, c.tdStyle)
      const content = c.render(row, idx)
      if (typeof content === 'string') {
        td.textContent = content
      } else {
        td.appendChild(content)
      }
      tr.appendChild(td)
    }
    return tr
  }

  renderEmpty()

  function updateRows(rows: TableRow<T>[]) {
    tbody.innerHTML = ''
    if (rows.length === 0) {
      renderEmpty()
      return
    }
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i]
      if ('type' in row && (row as GroupRow).type === 'group') {
        tbody.appendChild(renderGroupRow(row as GroupRow))
      } else {
        tbody.appendChild(renderDataRow(row as T, i))
      }
    }
  }

  function destroy() {
    table.remove()
  }

  return { el: table as HTMLElement, updateRows, destroy }
}
