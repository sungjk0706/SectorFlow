/**
 * 순수 TypeScript 가상 스크롤러 — react-window 대체
 *
 * 핵심 설계:
 * - sentinel div로 전체 높이 확보 (총 높이 = Σ getRowHeight)
 * - scroll 이벤트에서 visible range 계산 → overscan 포함 범위만 DOM 렌더링
 * - DOM 요소 풀(pool) 재활용: 뷰포트 밖 행 DOM을 새 행에 재사용
 * - keyFn으로 행 식별 → 같은 키의 행은 DOM 재사용
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4
 */

// ── 인터페이스 ──────────────────────────────────────────────

export interface VirtualScrollerOptions<T> {
  container: HTMLElement
  items: T[]
  getRowHeight: (item: T, index: number) => number
  renderRow: (item: T, index: number, rowEl: HTMLElement) => void
  overscan?: number  // 기본 5
  keyFn: (item: T, index: number) => string
}

export interface VirtualScrollerApi<T> {
  updateItems(items: T[]): void
  updateItem(index: number, item: T): void
  scrollToIndex(index: number): void
  destroy(): void
}

// ── 순수 함수 (PBT 테스트 가능) ─────────────────────────────

/**
 * 각 행의 누적 오프셋(top)과 총 높이를 계산한다.
 * offsets[i] = items[0..i-1]의 높이 합 (즉, items[i]의 top 위치)
 * totalHeight = 모든 행 높이의 합
 */
export function computeOffsets<T>(
  items: T[],
  getRowHeight: (item: T, index: number) => number,
): { offsets: number[]; totalHeight: number } {
  const offsets: number[] = new Array(items.length)
  let acc = 0
  for (let i = 0; i < items.length; i++) {
    offsets[i] = acc
    acc += getRowHeight(items[i], i)
  }
  return { offsets, totalHeight: acc }
}

/**
 * 주어진 scrollTop과 viewportHeight에서 보여야 할 행 범위를 계산한다.
 * 이진 탐색으로 시작 인덱스를 찾고, 끝 인덱스까지 선형 탐색.
 * overscan 포함.
 */
export function computeVisibleRange(
  offsets: number[],
  _totalHeight: number,
  scrollTop: number,
  viewportHeight: number,
  overscan: number,
  getRowHeight: (index: number) => number,
): { start: number; end: number } {
  const count = offsets.length
  if (count === 0) return { start: 0, end: 0 }

  // 이진 탐색: scrollTop 이상인 첫 행 찾기
  let lo = 0
  let hi = count - 1
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    // offsets[mid] + height(mid) > scrollTop → mid가 후보
    if (offsets[mid] + getRowHeight(mid) > scrollTop) {
      hi = mid
    } else {
      lo = mid + 1
    }
  }
  const visibleStart = lo

  // 끝 인덱스: scrollTop + viewportHeight를 넘는 첫 행
  const bottomEdge = scrollTop + viewportHeight
  let visibleEnd = visibleStart
  while (visibleEnd < count && offsets[visibleEnd] < bottomEdge) {
    visibleEnd++
  }

  // overscan 적용
  const start = Math.max(0, visibleStart - overscan)
  const end = Math.min(count, visibleEnd + overscan)

  return { start, end }
}

// ── 가상 스크롤러 팩토리 ────────────────────────────────────

export function createVirtualScroller<T>(
  options: VirtualScrollerOptions<T>,
): VirtualScrollerApi<T> {
  const { container, renderRow, keyFn } = options
  const overscan = options.overscan ?? 5

  let items = options.items
  let getRowHeight = options.getRowHeight
  let offsets: number[] = []
  let totalHeight = 0

  // container에 overflow-y: auto 설정
  container.style.overflowY = 'auto'
  container.style.position = 'relative'

  // sentinel div — 전체 높이 확보 + CSS containment로 내부 변경 격리
  const sentinel = document.createElement('div')
  sentinel.style.position = 'relative'
  sentinel.style.width = '100%'
  sentinel.style.overflow = 'visible'
  sentinel.style.contain = 'layout style'
  container.appendChild(sentinel)

  // 활성 행 DOM: key → { el, index }
  const activeRows = new Map<string, { el: HTMLElement; index: number }>()

  // DOM 풀: 재사용 가능한 행 요소
  const pool: HTMLElement[] = []

  // 현재 렌더링 범위
  let currentStart = 0
  let currentEnd = 0

  // ── 내부 함수 ──────────────────────────────────────────

  function recomputeOffsets() {
    const result = computeOffsets(items, getRowHeight)
    offsets = result.offsets
    totalHeight = result.totalHeight
    sentinel.style.height = totalHeight + 'px'
  }

  function acquireRow(): HTMLElement {
    if (pool.length > 0) return pool.pop()!
    const el = document.createElement('div')
    el.style.position = 'absolute'
    el.style.left = '0'
    el.style.top = '0'
    el.style.width = '100%'
    el.style.overflow = 'hidden'
    el.style.willChange = 'transform'
    return el
  }

  function releaseRow(el: HTMLElement) {
    el.style.display = 'none'
    pool.push(el)
  }

  function renderRange(start: number, end: number) {
    // 현재 활성 행 중 범위 밖인 것을 풀로 반환
    const keysToRemove: string[] = []
    for (const [key, entry] of activeRows) {
      if (entry.index < start || entry.index >= end) {
        releaseRow(entry.el)
        keysToRemove.push(key)
      }
    }
    for (const key of keysToRemove) {
      activeRows.delete(key)
    }

    // 범위 내 행 렌더링
    for (let i = start; i < end; i++) {
      const item = items[i]
      const key = keyFn(item, i)
      const existing = activeRows.get(key)

      if (existing) {
        // 같은 키의 행이 이미 활성 — 인덱스/위치만 갱신
        if (existing.index !== i) {
          existing.index = i
          existing.el.style.transform = `translateY(${offsets[i]}px)`
          existing.el.style.height = getRowHeight(item, i) + 'px'
          renderRow(item, i, existing.el)
        }
      } else {
        // 새 행 필요
        const el = acquireRow()
        el.style.display = ''
        el.style.transform = `translateY(${offsets[i]}px)`
        el.style.height = getRowHeight(item, i) + 'px'
        renderRow(item, i, el)
        if (!el.parentNode) sentinel.appendChild(el)
        activeRows.set(key, { el, index: i })
      }
    }

    currentStart = start
    currentEnd = end
  }

  function onScroll() {
    const scrollTop = container.scrollTop
    const viewportHeight = container.clientHeight

    const { start, end } = computeVisibleRange(
      offsets,
      totalHeight,
      scrollTop,
      viewportHeight,
      overscan,
      (idx) => getRowHeight(items[idx], idx),
    )

    if (start !== currentStart || end !== currentEnd) {
      renderRange(start, end)
    }
  }

  // ── 초기화 ────────────────────────────────────────────

  recomputeOffsets()
  container.addEventListener('scroll', onScroll, { passive: true })

  // 초기 렌더링 (container가 이미 크기를 가지고 있을 때)
  // 레이아웃 확정 후 렌더링 — clientHeight가 0이면 재시도
  function initialRender() {
    if (container.clientHeight > 0) {
      onScroll()
    } else {
      requestAnimationFrame(initialRender)
    }
  }
  requestAnimationFrame(initialRender)

  // ── API ───────────────────────────────────────────────

  function updateItems(newItems: T[]) {
    const oldItems = items
    items = newItems

    recomputeOffsets()

    const scrollTop = container.scrollTop
    const viewportHeight = container.clientHeight

    const { start, end } = computeVisibleRange(
      offsets,
      totalHeight,
      scrollTop,
      viewportHeight,
      overscan,
      (idx) => getRowHeight(items[idx], idx),
    )

    // 기존 활성 행 중 새 items에서 같은 키+같은 아이템인 것은 유지
    // 나머지는 재렌더링
    const newActiveKeys = new Set<string>()
    for (let i = start; i < end; i++) {
      newActiveKeys.add(keyFn(newItems[i], i))
    }

    // 범위 밖이거나 키가 바뀐 행 제거
    const keysToRemove: string[] = []
    for (const [key, entry] of activeRows) {
      if (!newActiveKeys.has(key) || entry.index < start || entry.index >= end) {
        releaseRow(entry.el)
        keysToRemove.push(key)
      }
    }
    for (const key of keysToRemove) {
      activeRows.delete(key)
    }

    // 범위 내 행 렌더링 (변경된 행만 renderRow 재호출)
    for (let i = start; i < end; i++) {
      const item = newItems[i]
      const key = keyFn(item, i)
      const existing = activeRows.get(key)

      if (existing) {
        // 위치 갱신
        existing.el.style.transform = `translateY(${offsets[i]}px)`
        existing.el.style.height = getRowHeight(item, i) + 'px'
        existing.index = i

        // 아이템이 변경되었으면 재렌더링
        if (i >= oldItems.length || oldItems[i] !== item) {
          renderRow(item, i, existing.el)
        }
      } else {
        const el = acquireRow()
        el.style.display = ''
        el.style.transform = `translateY(${offsets[i]}px)`
        el.style.height = getRowHeight(item, i) + 'px'
        renderRow(item, i, el)
        if (!el.parentNode) sentinel.appendChild(el)
        activeRows.set(key, { el, index: i })
      }
    }

    currentStart = start
    currentEnd = end
  }

  function updateItem(index: number, item: T) {
    if (index < 0 || index >= items.length) return
    items[index] = item

    // 높이가 변경될 수 있으므로 오프셋 재계산
    recomputeOffsets()

    // 현재 렌더링 범위 내에 있으면 해당 행만 갱신
    if (index >= currentStart && index < currentEnd) {
      const key = keyFn(item, index)
      const existing = activeRows.get(key)
      if (existing) {
        existing.el.style.transform = `translateY(${offsets[index]}px)`
        existing.el.style.height = getRowHeight(item, index) + 'px'
        renderRow(item, index, existing.el)
      }
    }
  }

  function scrollToIndex(index: number) {
    if (index < 0 || index >= items.length) return
    container.scrollTop = offsets[index]
  }

  function destroy() {
    container.removeEventListener('scroll', onScroll)
    // 모든 활성 행 제거
    for (const [, entry] of activeRows) {
      if (entry.el.parentNode) entry.el.parentNode.removeChild(entry.el)
    }
    activeRows.clear()
    // 풀 정리
    for (const el of pool) {
      if (el.parentNode) el.parentNode.removeChild(el)
    }
    pool.length = 0
    // sentinel 제거
    if (sentinel.parentNode) sentinel.parentNode.removeChild(sentinel)
  }

  return { updateItems, updateItem, scrollToIndex, destroy }
}
