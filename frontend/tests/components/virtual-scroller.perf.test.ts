/**
 * VirtualScroller 성능 테스트
 *
 * 대량 데이터 스크롤 성능 측정 (performance.now() 사용)
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createVirtualScroller } from '../../src/components/virtual-scroller'

/* ── 테스트 데이터 타입 ── */

interface PerfItem {
  id: string
  value: number
}

/* ── 테스트 데이터 생성 ── */

function generateItems(count: number): PerfItem[] {
  const items: PerfItem[] = []
  for (let i = 0; i < count; i++) {
    items.push({
      id: `item-${i}`,
      value: Math.random() * 1000,
    })
  }
  return items
}

/* ── 성능 테스트 ── */

describe('VirtualScroller Performance Test', () => {
  let container: HTMLElement

  beforeEach(() => {
    container = document.createElement('div')
    container.style.height = '400px'
    container.style.overflow = 'auto'
    document.body.appendChild(container)
  })

  afterEach(() => {
    document.body.removeChild(container)
  })

  describe('초기 렌더링 성능', () => {
    it('100행 초기 렌더링 < 50ms', () => {
      const start = performance.now()
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(100),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(50)
    })

    it('500행 초기 렌더링 < 100ms', () => {
      const start = performance.now()
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(500),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(100)
    })

    it('1000행 초기 렌더링 < 200ms', () => {
      const start = performance.now()
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(1000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(200)
    })

    it('5000행 초기 렌더링 < 500ms', () => {
      const start = performance.now()
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(5000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(500)
    })
  })

  describe('업데이트 성능', () => {
    it('100행 업데이트 < 50ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(100),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.updateItems(generateItems(100))
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(50)
    })

    it('1000행 업데이트 < 200ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(1000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.updateItems(generateItems(1000))
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(200)
    })

    it('5000행 업데이트 < 500ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(5000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.updateItems(generateItems(5000))
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(500)
    })
  })

  describe('단일 항목 업데이트 성능', () => {
    it('updateItem (1000행 중 1개) < 10ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(1000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.updateItem(500, { id: 'item-500', value: 999 })
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(10)
    })

    it('updateItemByKey (1000행 중 1개) < 10ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(1000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.updateItemByKey('item-500')
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(10)
    })
  })

  describe('스크롤 성능', () => {
    it('scrollToIndex (1000행) < 50ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(1000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.scrollToIndex(500)
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(50)
    })

    it('scrollToIndex (5000행) < 100ms', () => {
      const scroller = createVirtualScroller<PerfItem>({
        container,
        items: generateItems(5000),
        getRowHeight: () => 32,
        renderRow: (item, _index, rowEl) => {
          rowEl.textContent = `${item.id}: ${item.value.toFixed(2)}`
        },
        keyFn: (item) => item.id,
      })

      const start = performance.now()
      scroller.scrollToIndex(2500)
      const end = performance.now()

      scroller.destroy()
      expect(end - start).toBeLessThan(100)
    })
  })
})
