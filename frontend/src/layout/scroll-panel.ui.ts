// frontend/src/layout/scroll-panel.ui.ts
// 스크롤 위치를 경로별 Map에 캐시/복원
// 비즈니스 로직 제거, Props로 데이터 수신

/* ── Props 타입 ── */

export interface ScrollPanelUiProps {
  cacheKey?: string
}

/* ── UI 참조 ── */

const scrollCache = new Map<string, number>()

/* ── createScrollPanel ── */

export function createScrollPanel(container: HTMLElement, props: ScrollPanelUiProps): {
  el: HTMLElement
  saveScroll(): void
  restoreScroll(): void
  destroy(): void
} {
  const el = document.createElement('div')
  el.tabIndex = -1
  el.style.cssText = 'outline:none;overflow-y:auto;'

  const cacheKey = props.cacheKey ?? 'default'

  function onScroll(): void {
    scrollCache.set(cacheKey, el.scrollTop)
  }

  el.addEventListener('scroll', onScroll)

  container.appendChild(el)

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
