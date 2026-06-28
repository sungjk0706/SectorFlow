/** 셀에 노란 플래시 애니메이션 한 번 발동 (중복 발동 시 기존 타이머 정리) */
export function triggerFlash(cell: HTMLElement, duration = 600): void {
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

export function injectFlashStyle(wrapper: HTMLElement): void {
  const style = document.createElement('style')
  style.textContent = `
    @keyframes cell-flash {
      0%   { background-color: rgba(255, 235, 59, 0.45); }
      100% { background-color: transparent; }
    }
    .cell-flash {
      animation: cell-flash 0.6s ease-out forwards;
    }
  `
  wrapper.appendChild(style)
}
