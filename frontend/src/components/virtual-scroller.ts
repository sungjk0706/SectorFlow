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

// ── 고정 높이 모드 인터페이스 ────────────────────────────────

export interface FixedHeightMode {
  enabled: boolean
  rowHeight: number  // 모든 행이 동일한 높이 (enabled=false면 0)
}

// ── 순수 함수 (PBT 테스트 가능) ─────────────────────────────

/**
 * 초기화 시 행 높이 균일 여부를 감지한다.
 * 모든 행의 높이가 동일하면 고정 높이 모드를 활성화한다.
 */
export function detectFixedHeight<T>(
  items: T[],
  getRowHeight: (item: T, index: number) => number,
): FixedHeightMode {
  if (items.length === 0) return { enabled: false, rowHeight: 0 }
  const h0 = getRowHeight(items[0], 0)
  for (let i = 1; i < items.length; i++) {
    if (getRowHeight(items[i], i) !== h0) return { enabled: false, rowHeight: 0 }
  }
  return { enabled: true, rowHeight: h0 }
}

/**
 * 고정 높이 모드에서의 오프셋 계산 — O(1) 산술
 */
export function getOffsetFixed(index: number, rowHeight: number): number {
  return index * rowHeight
}

/**
 * 고정 높이 모드에서의 총 높이 계산 — O(1) 산술
 */
export function getTotalHeightFixed(count: number, rowHeight: number): number {
  return count * rowHeight
}

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
 * 가변 높이 모드: 특정 인덱스 이후만 증분 갱신한다.
 * fromIndex 이전의 오프셋은 변경하지 않는다.
 */
export function recomputeOffsetsFrom<T>(
  offsets: number[],
  items: T[],
  getRowHeight: (item: T, index: number) => number,
  fromIndex: number,
): number {
  if (items.length === 0) return 0
  let acc = fromIndex > 0 ? offsets[fromIndex - 1] + getRowHeight(items[fromIndex - 1], fromIndex - 1) : 0
  for (let i = fromIndex; i < items.length; i++) {
    offsets[i] = acc
    acc += getRowHeight(items[i], i)
  }
  return acc
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

  // 고정 높이 모드 상태
  let fixedMode: FixedHeightMode = detectFixedHeight(items, getRowHeight)

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

  /**
   * 오프셋을 재계산한다.
   * 고정 높이 모드에서는 산술 계산만 수행 (offsets 배열 순회 없음).
   */
  function recomputeAllOffsets() {
    if (fixedMode.enabled) {
      // 고정 높이 fast path: O(1) 산술 계산
      totalHeight = getTotalHeightFixed(items.length, fixedMode.rowHeight)
      // offsets 배열은 고정 높이 모드에서도 computeVisibleRange 호환을 위해 유지
      // 하지만 실제 순회 없이 lazy하게 사용 가능
      offsets = new Array(items.length)
      for (let i = 0; i < items.length; i++) {
        offsets[i] = i * fixedMode.rowHeight
      }
    } else {
      // 가변 높이: 전체 재계산
      const result = computeOffsets(items, getRowHeight)
      offsets = result.offsets
      totalHeight = result.totalHeight
    }
    sentinel.style.height = totalHeight + 'px'
  }

  /**
   * 오프셋 drift를 검증한다.
   * 고정 높이 모드에서 실제 높이와 산술 결과가 1px 이상 차이나면 전체 재계산 fallback.
   */
  function validateOffsetDrift(): boolean {
    if (!fixedMode.enabled || items.length === 0) return true
    // 샘플 검증: 마지막 항목의 실제 높이와 고정 높이 비교
    const lastIdx = items.length - 1
    const actualHeight = getRowHeight(items[lastIdx], lastIdx)
    // 마지막 행의 높이가 고정 높이와 다르면 drift 발생
    if (Math.abs(actualHeight - fixedMode.rowHeight) > 1) {
      return false
    }
    // 중간 샘플도 검증 (최대 5개)
    const step = Math.max(1, Math.floor(items.length / 5))
    for (let i = 0; i < items.length; i += step) {
      if (Math.abs(getRowHeight(items[i], i) - fixedMode.rowHeight) > 1) {
        return false
      }
    }
    return true
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

  recomputeAllOffsets()
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
    const oldLength = items.length
    items = newItems

    // 고정 높이 모드 재감지 (아이템이 변경되었으므로)
    const newFixedMode = detectFixedHeight(items, getRowHeight)

    if (fixedMode.enabled && newFixedMode.enabled && fixedMode.rowHeight === newFixedMode.rowHeight) {
      // 고정 높이 모드 유지
      if (items.length === oldLength) {
        // 길이 동일 + 고정 높이 → 오프셋 재계산 생략
        // totalHeight와 offsets 변경 없음
      } else {
        // 길이 변경 → 산술 계산으로 totalHeight만 갱신
        totalHeight = getTotalHeightFixed(items.length, fixedMode.rowHeight)
        offsets = new Array(items.length)
        for (let i = 0; i < items.length; i++) {
          offsets[i] = i * fixedMode.rowHeight
        }
        sentinel.style.height = totalHeight + 'px'
      }
    } else {
      // 모드 전환 또는 가변 높이 → 전체 재계산
      fixedMode = newFixedMode
      recomputeAllOffsets()
    }

    // 오프셋 drift 검증 (고정 높이 모드에서)
    if (fixedMode.enabled && !validateOffsetDrift()) {
      // drift > 1px → 고정 높이 모드 해제 + 전체 재계산 fallback
      fixedMode = { enabled: false, rowHeight: 0 }
      recomputeAllOffsets()
    }

    const scrollTop = container.scrollTop
    const viewportHeight = container.clientHeight

    const { start, end } = computeVisibleRange(
      offsets,
      totalHeight,
      scrollTop,
      viewportHeight,
      overscan,
      (idx) => fixedMode.enabled ? fixedMode.rowHeight : getRowHeight(items[idx], idx),
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
    const oldHeight = getRowHeight(items[index], index)
    items[index] = item
    const newHeight = getRowHeight(item, index)

    if (oldHeight !== newHeight) {
      if (fixedMode.enabled) {
        // 높이가 변경되었으므로 고정 높이 모드 해제 + 전체 재계산 fallback
        fixedMode = { enabled: false, rowHeight: 0 }
        recomputeAllOffsets()
      } else {
        // 가변 높이 모드: 변경된 행 이후만 증분 갱신
        totalHeight = recomputeOffsetsFrom(offsets, items, getRowHeight, index)
        sentinel.style.height = totalHeight + 'px'
      }
    }
    // 높이 미변경 시 오프셋 재계산 생략

    // 현재 렌더링 범위 내에 있으면 해당 행만 갱신
    if (index >= currentStart && index < currentEnd) {
      const key = keyFn(item, index)
      const existing = activeRows.get(key)
      if (existing) {
        existing.el.style.transform = `translateY(${offsets[index]}px)`
        existing.el.style.height = newHeight + 'px'
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
