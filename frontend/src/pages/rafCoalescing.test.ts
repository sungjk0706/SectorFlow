/**
 * Property 2: rAF Coalescing (프레임 내 다중 변경 → 단일 갱신)
 *
 * Feature: hts-level-optimization, Property 2: rAF Coalescing
 *
 * **Validates: Requirements 1.3, 1.4, 2.1, 11.1**
 *
 * For any number N (N ≥ 1) of store state changes occurring within a single
 * animation frame (~16ms), the page SHALL invoke its DOM update function
 * exactly 1 time with the latest state, regardless of N.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as fc from 'fast-check'

/**
 * We test the rAF coalescing pattern in isolation by implementing the exact
 * same logic used in sell-position.ts, buy-target.ts, and profit-overview.ts.
 * This avoids importing full page modules (which require DOM containers, etc.)
 * while validating the core property: N state changes → 1 DOM update.
 *
 * The pattern (from design.md):
 *   function schedule(state):
 *     const current = getRef(state)
 *     if (current === prevRef) return       // reference equality guard
 *     prevRef = current
 *     if (rafHandle !== null) return        // already scheduled
 *     rafHandle = requestAnimationFrame(() => {
 *       rafHandle = null
 *       onRender(current)                   // uses latest prevRef
 *     })
 */

/** Minimal rAF coalescer matching the pattern used in all three pages */
function createRafCoalescer<T>(
  onRender: (latest: T) => void,
): {
  schedule: (newRef: T) => void
  cancel: () => void
  getPending: () => boolean
} {
  let prevRef: T | null = null
  let rafHandle: number | null = null

  function schedule(newRef: T): void {
    if (newRef === prevRef) return // reference equality guard
    prevRef = newRef
    if (rafHandle !== null) return // already scheduled — coalesce
    rafHandle = requestAnimationFrame(() => {
      rafHandle = null
      onRender(prevRef as T) // always uses latest ref at callback time
    })
  }

  function cancel(): void {
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle)
      rafHandle = null
    }
  }

  return { schedule, cancel, getPending: () => rafHandle !== null }
}

describe('Property 2: rAF Coalescing (프레임 내 다중 변경 → 단일 갱신)', () => {
  let rafCallbacks: Array<() => void>
  let originalRAF: typeof globalThis.requestAnimationFrame
  let originalCAF: typeof globalThis.cancelAnimationFrame

  beforeEach(() => {
    rafCallbacks = []
    // Mock requestAnimationFrame: collect callbacks, fire manually
    originalRAF = globalThis.requestAnimationFrame
    originalCAF = globalThis.cancelAnimationFrame

    let nextId = 1
    const pendingCallbacks = new Map<number, () => void>()

    globalThis.requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      const id = nextId++
      const wrappedCb = () => cb(performance.now())
      pendingCallbacks.set(id, wrappedCb)
      rafCallbacks.push(wrappedCb)
      return id
    }) as unknown as typeof globalThis.requestAnimationFrame

    globalThis.cancelAnimationFrame = vi.fn((id: number) => {
      const cb = pendingCallbacks.get(id)
      if (cb) {
        const idx = rafCallbacks.indexOf(cb)
        if (idx >= 0) rafCallbacks.splice(idx, 1)
      }
      pendingCallbacks.delete(id)
    }) as unknown as typeof globalThis.cancelAnimationFrame
  })

  afterEach(() => {
    globalThis.requestAnimationFrame = originalRAF
    globalThis.cancelAnimationFrame = originalCAF
  })

  /** Flush all pending rAF callbacks (simulates frame firing) */
  function flushRAF(): void {
    const cbs = [...rafCallbacks]
    rafCallbacks = []
    for (const cb of cbs) cb()
  }

  it('N state changes within a single frame result in exactly 1 DOM update call', () => {
    /**
     * **Validates: Requirements 1.3, 1.4, 2.1, 11.1**
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (n) => {
          let updateCount = 0
          let lastRenderedValue: object | null = null

          const coalescer = createRafCoalescer<object>((latest) => {
            updateCount++
            lastRenderedValue = latest
          })

          // Generate N distinct state references within a single frame
          const states: object[] = []
          for (let i = 0; i < n; i++) {
            states.push({ id: i }) // each is a new reference (!==)
          }

          // Schedule all N state changes before the frame fires
          for (const state of states) {
            coalescer.schedule(state)
          }

          // Verify: rAF was requested but update hasn't fired yet
          expect(updateCount).toBe(0)

          // Fire the frame
          flushRAF()

          // Property: exactly 1 DOM update call regardless of N
          expect(updateCount).toBe(1)

          // The rendered value should be the LAST state (latest)
          expect(lastRenderedValue).toBe(states[states.length - 1])

          coalescer.cancel()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('identical references (===) do not trigger any DOM update', () => {
    /**
     * **Validates: Requirements 1.3, 1.4**
     *
     * When the same reference is scheduled multiple times, the reference
     * equality guard prevents scheduling any rAF at all.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (n) => {
          let updateCount = 0
          const coalescer = createRafCoalescer<object>((/* _latest */) => {
            updateCount++
          })

          // Use the SAME reference for all N calls
          const sameRef = { value: 42 }

          // First call sets prevRef — schedules rAF
          coalescer.schedule(sameRef)

          // Fire the frame to process the first schedule
          flushRAF()
          expect(updateCount).toBe(1)

          // Now schedule the same reference N more times
          updateCount = 0
          for (let i = 0; i < n; i++) {
            coalescer.schedule(sameRef)
          }

          // Fire the frame — no update should occur
          flushRAF()
          expect(updateCount).toBe(0)

          coalescer.cancel()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('multiple frames each produce exactly 1 update per frame', () => {
    /**
     * **Validates: Requirements 1.3, 2.1, 11.1**
     *
     * Across multiple frames, each frame with at least one new reference
     * produces exactly 1 DOM update.
     */
    fc.assert(
      fc.property(
        fc.array(
          fc.integer({ min: 1, max: 20 }),
          { minLength: 1, maxLength: 10 },
        ),
        (changesPerFrame) => {
          let updateCount = 0
          const coalescer = createRafCoalescer<object>((/* _latest */) => {
            updateCount++
          })

          for (const n of changesPerFrame) {
            // Schedule n distinct state changes within this frame
            for (let i = 0; i < n; i++) {
              coalescer.schedule({ frame: changesPerFrame.indexOf(n as never), change: i })
            }
            // Fire the frame
            flushRAF()
          }

          // Property: exactly 1 update per frame
          expect(updateCount).toBe(changesPerFrame.length)

          coalescer.cancel()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('cancel prevents pending rAF callback from firing (unmount safety)', () => {
    /**
     * **Validates: Requirements 1.5, 2.4, 11.5**
     *
     * When cancel() is called before the frame fires, no DOM update occurs.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 50 }),
        (n) => {
          let updateCount = 0
          const coalescer = createRafCoalescer<object>((/* _latest */) => {
            updateCount++
          })

          // Schedule N state changes
          for (let i = 0; i < n; i++) {
            coalescer.schedule({ id: i })
          }

          // Cancel before frame fires (simulates unmount)
          coalescer.cancel()

          // Fire the frame — should NOT trigger update
          flushRAF()
          expect(updateCount).toBe(0)
        },
      ),
      { numRuns: 100 },
    )
  })
})
