/* ── 컬럼 정의 ─────────────────────────────────────────────── */
export interface ColDef<T> {
  key: string
  label: string
  width: string
  align?: 'left' | 'right' | 'center'
  render: (row: T, idx: number) => string | HTMLElement
  headerStyle?: Partial<CSSStyleDeclaration>
  tdStyle?: Partial<CSSStyleDeclaration>
  /** 값이 변경되면 셀 배경에 노란 플래시 애니메이션 적용 */
  flash?: boolean
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
    rowKey,
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
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild)
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

  /* ── rowKey 기반 증분 갱신을 위한 내부 상태 ── */
  // 현재 tbody에 렌더링된 행의 key → tr 매핑
  const _renderedKeyMap = new Map<string, HTMLElement>()
  // 초기 로딩 완료 여부 (첫 updateRows 호출 전까지 false)
  let _initialLoaded = false

  /** 행이 GroupRow인지 판별 */
  function isGroupRow(row: TableRow<T>): row is GroupRow {
    return 'type' in row && (row as GroupRow).type === 'group'
  }

  /** 행의 key를 반환 (rowKey 옵션 또는 인덱스 기반) */
  function getRowKey(row: TableRow<T>, idx: number): string {
    if (isGroupRow(row)) return `__group__${(row as GroupRow).key}`
    if (rowKey) return rowKey(row as T, idx)
    return `__idx__${idx}`
  }

  /** 기존 데이터 행의 셀을 diff하여 변경된 셀만 갱신 */
  function diffDataRowCells(tr: HTMLElement, row: T, idx: number): void {
    const cells = tr.children
    for (let i = 0; i < columns.length; i++) {
      const cell = cells[i] as HTMLElement
      if (!cell) continue
      try {
        const content = columns[i].render(row, idx)
        if (typeof content === 'string') {
          if (cell.textContent !== content) {
            cell.textContent = content
            if (columns[i].flash) triggerFlash(cell)
          }
        } else if (content instanceof HTMLElement) {
          const existing = cell.firstElementChild as HTMLElement | null
          if (!existing || existing.outerHTML !== content.outerHTML) {
            cell.textContent = ''
            cell.appendChild(content)
            if (columns[i].flash) triggerFlash(cell)
          }
        }
      } catch {
        // 개별 셀 render 예외 시 해당 셀만 건너뛰기
      }
    }
    // rowStyle 갱신
    const rs = rowStyle ? rowStyle(row, idx) : undefined
    if (rs) Object.assign(tr.style, rs)
  }

  /** 기존 GroupRow의 내용을 diff하여 변경된 부분만 갱신 */
  function diffGroupRow(tr: HTMLElement, g: GroupRow): void {
    const td = tr.firstElementChild as HTMLElement
    if (!td) return
    const expectedText = `◆ ${g.label}`
    // textContent에는 score span 텍스트도 포함되므로 첫 번째 텍스트 노드만 비교
    const textNode = td.firstChild
    if (textNode && textNode.nodeType === Node.TEXT_NODE) {
      if (textNode.textContent !== expectedText) {
        textNode.textContent = expectedText
      }
    }
    // score span 갱신
    const span = td.querySelector('span')
    if (g.score != null) {
      const scoreText = `(종합점수 : ${g.score.toFixed(1)})`
      if (span) {
        if (span.textContent !== scoreText) span.textContent = scoreText
        ;(span as HTMLElement).style.color = scoreColor(g.score)
      } else {
        const newSpan = document.createElement('span')
        Object.assign(newSpan.style, {
          marginLeft: '10px',
          fontSize: '0.75em',
          fontWeight: FONT_WEIGHT.normal,
          color: scoreColor(g.score),
        })
        newSpan.textContent = scoreText
        td.appendChild(newSpan)
      }
    } else if (span) {
      span.remove()
    }
    if (g.style) Object.assign(tr.style, g.style)
  }

  function updateRows(rows: TableRow<T>[]) {
    // 빈 데이터 처리
    if (rows.length === 0) {
      _renderedKeyMap.clear()
      renderEmpty()
      _initialLoaded = true
      return
    }

    // 초기 로딩 또는 rowKey 미제공 시 — 일괄 렌더링
    if (!_initialLoaded || !rowKey) {
      while (tbody.firstChild) tbody.removeChild(tbody.firstChild)
      _renderedKeyMap.clear()
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i]
        const key = getRowKey(row, i)
        let tr: HTMLElement
        if (isGroupRow(row)) {
          tr = renderGroupRow(row as GroupRow)
        } else {
          tr = renderDataRow(row as T, i)
        }
        tr.dataset.rowKey = key
        tbody.appendChild(tr)
        _renderedKeyMap.set(key, tr)
      }
      _initialLoaded = true
      return
    }

    // ── rowKey 기반 증분 갱신 ──
    const newKeySet = new Set<string>()
    const newKeyOrder: string[] = []

    // 1. 신규/기존 행 처리
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i]
      const key = getRowKey(row, i)
      newKeySet.add(key)
      newKeyOrder.push(key)

      const existingTr = _renderedKeyMap.get(key)
      if (existingTr) {
        // 기존 행 — 셀별 diff 갱신
        if (isGroupRow(row)) {
          diffGroupRow(existingTr, row as GroupRow)
        } else {
          diffDataRowCells(existingTr, row as T, i)
        }
      } else {
        // 신규 행 — DOM 생성
        let tr: HTMLElement
        if (isGroupRow(row)) {
          tr = renderGroupRow(row as GroupRow)
        } else {
          tr = renderDataRow(row as T, i)
        }
        tr.dataset.rowKey = key
        _renderedKeyMap.set(key, tr)
      }
    }

    // 2. 제거된 행 DOM 삭제
    for (const [key, tr] of _renderedKeyMap) {
      if (!newKeySet.has(key)) {
        tr.remove()
        _renderedKeyMap.delete(key)
      }
    }

    // 3. 순서 보정 — DOM 순서를 newKeyOrder와 일치시킴
    let prevNode: HTMLElement | null = null
    for (const key of newKeyOrder) {
      const tr = _renderedKeyMap.get(key)!
      if (prevNode === null) {
        // 첫 번째 행이 tbody의 첫 자식이 아니면 이동
        if (tbody.firstElementChild !== tr) {
          tbody.insertBefore(tr, tbody.firstElementChild)
        }
      } else {
        // prevNode 다음에 위치해야 함
        if (prevNode.nextElementSibling !== tr) {
          tbody.insertBefore(tr, prevNode.nextElementSibling)
        }
      }
      prevNode = tr
    }
  }

  function destroy() {
    table.remove()
  }

  return { el: table as HTMLElement, updateRows, destroy }
}
