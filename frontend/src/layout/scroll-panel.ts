// frontend/src/layout/scroll-panel.ts
// 스크롤 위치를 경로별 Map에 캐시/복원

const scrollCache = new Map<string, number>()

export function createScrollPanel(cacheKey: string): {
  el: HTMLElement
  saveScroll(): void
  restoreScroll(): void
  destroy(): void
} {
  const el = document.createElement('div')
  el.tabIndex = -1
  el.style.cssText = 'outline:none;overflow-y:auto;'

  function onScroll(): void {
    scrollCache.set(cacheKey, el.scrollTop)
  }

  el.addEventListener('scroll', onScroll)

  function saveScroll(): void {
    scrollCache.set(cacheKey, el.scrollTop)
  }

  function restoreScroll(): void {
    const saved = scrollCache.get(cacheKey) ?? 0
    if (saved > 0) {
      requestAnimationFrame(() => {
        el.scrollTop = saved
      })
    }
  }

  function destroy(): void {
    el.removeEventListener('scroll', onScroll)
  }

  return { el, saveScroll, restoreScroll, destroy }
}
