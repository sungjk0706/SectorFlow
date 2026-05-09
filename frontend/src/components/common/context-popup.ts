// frontend/src/components/common/context-popup.ts — 마우스 위치 기반 컨텍스트 팝업
import { FONT_SIZE } from './ui-styles'

/* ── 타입 ── */

export interface InputPopupOptions {
  type: 'input'
  x: number
  y: number
  title: string
  defaultValue?: string
  placeholder?: string
  confirmText?: string
  cancelText?: string
}

export interface ConfirmPopupOptions {
  type: 'confirm'
  x: number
  y: number
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  confirmColor?: string
}

export type ContextPopupOptions = InputPopupOptions | ConfirmPopupOptions

export type ContextPopupResult =
  | { confirmed: true; value: string }
  | { confirmed: true }
  | { confirmed: false }

/* ── 싱글톤 상태 ── */

let currentCleanup: ((result: ContextPopupResult) => void) | null = null

/* ── 위치 계산 ── */

const MARGIN = 8

export function clampPosition(
  x: number, y: number,
  popupW: number, popupH: number,
  vw: number, vh: number,
): { left: number; top: number } {
  let left = x
  let top = y
  if (left + popupW + MARGIN > vw) left = vw - popupW - MARGIN
  if (top + popupH + MARGIN > vh) top = vh - popupH - MARGIN
  if (left < MARGIN) left = MARGIN
  if (top < MARGIN) top = MARGIN
  return { left, top }
}

/* ── 강제 닫기 ── */

export function closeContextPopup(): void {
  if (currentCleanup) {
    currentCleanup({ confirmed: false })
    currentCleanup = null
  }
}

/* ── 메인 ── */

export function showContextPopup(options: ContextPopupOptions): Promise<ContextPopupResult> {
  // 싱글톤: 기존 팝업 닫기
  closeContextPopup()

  return new Promise<ContextPopupResult>((resolve) => {
    let resolved = false

    function cleanup(result: ContextPopupResult): void {
      if (resolved) return
      resolved = true
      currentCleanup = null
      document.removeEventListener('keydown', onKeyDown, true)
      overlay.remove()
      resolve(result)
    }

    currentCleanup = cleanup

    /* ── 오버레이 (외부 클릭 감지) ── */
    const overlay = document.createElement('div')
    Object.assign(overlay.style, {
      position: 'fixed',
      inset: '0',
      zIndex: '10000',
    })
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) cleanup({ confirmed: false })
    })

    /* ── 팝업 컨테이너 ── */
    const popup = document.createElement('div')
    popup.setAttribute('role', 'dialog')
    popup.setAttribute('aria-modal', 'true')
    popup.setAttribute('aria-label', options.title)
    Object.assign(popup.style, {
      position: 'fixed',
      zIndex: '10001',
      minWidth: '220px',
      maxWidth: '320px',
      borderRadius: '8px',
      boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
      background: '#fff',
      padding: '12px',
      fontFamily: 'inherit',
      boxSizing: 'border-box',
    })

    /* ── 제목 ── */
    const titleEl = document.createElement('div')
    Object.assign(titleEl.style, {
      fontWeight: 'normal',
      fontSize: FONT_SIZE.body,
      marginBottom: '8px',
      color: '#222',
    })
    titleEl.textContent = options.title
    popup.appendChild(titleEl)

    /* ── 모드별 콘텐츠 ── */
    const confirmText = options.confirmText ?? '확인'
    const cancelText = options.cancelText ?? '취소'
    const confirmColor = options.type === 'confirm'
      ? (options.confirmColor ?? '#198754')
      : '#198754'

    let inputEl: HTMLInputElement | null = null
    const focusable: HTMLElement[] = []

    if (options.type === 'input') {
      inputEl = document.createElement('input')
      inputEl.type = 'text'
      if (options.defaultValue != null) inputEl.value = options.defaultValue
      if (options.placeholder) inputEl.placeholder = options.placeholder
      Object.assign(inputEl.style, {
        width: '100%',
        padding: '6px 8px',
        border: '1px solid #ccc',
        borderRadius: '4px',
        fontSize: FONT_SIZE.body,
        marginBottom: '12px',
        boxSizing: 'border-box',
        fontFamily: 'inherit',
      })
      popup.appendChild(inputEl)
      focusable.push(inputEl)
    } else {
      const msgEl = document.createElement('div')
      Object.assign(msgEl.style, {
        fontSize: FONT_SIZE.label,
        color: '#555',
        marginBottom: '12px',
        whiteSpace: 'pre-wrap',
      })
      msgEl.textContent = options.message
      popup.appendChild(msgEl)
    }

    /* ── 버튼 영역 ── */
    const btnRow = document.createElement('div')
    Object.assign(btnRow.style, {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: '6px',
    })

    const confirmBtn = document.createElement('button')
    confirmBtn.textContent = confirmText
    Object.assign(confirmBtn.style, {
      padding: '5px 14px',
      border: 'none',
      borderRadius: '4px',
      color: '#fff',
      background: confirmColor,
      cursor: 'pointer',
      fontSize: FONT_SIZE.label,
      fontFamily: 'inherit',
    })
    confirmBtn.addEventListener('click', () => {
      if (options.type === 'input') {
        cleanup({ confirmed: true, value: inputEl!.value })
      } else {
        cleanup({ confirmed: true })
      }
    })

    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = cancelText
    Object.assign(cancelBtn.style, {
      padding: '5px 14px',
      border: 'none',
      borderRadius: '4px',
      color: '#fff',
      background: '#6c757d',
      cursor: 'pointer',
      fontSize: FONT_SIZE.label,
      fontFamily: 'inherit',
    })
    cancelBtn.addEventListener('click', () => cleanup({ confirmed: false }))

    btnRow.appendChild(confirmBtn)
    btnRow.appendChild(cancelBtn)
    popup.appendChild(btnRow)

    focusable.push(confirmBtn, cancelBtn)

    /* ── 키보드 핸들링 ── */
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        cleanup({ confirmed: false })
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        e.stopPropagation()
        if (options.type === 'input') {
          cleanup({ confirmed: true, value: inputEl!.value })
        } else {
          cleanup({ confirmed: true })
        }
        return
      }
      if (e.key === 'Tab') {
        e.preventDefault()
        e.stopPropagation()
        const idx = focusable.indexOf(document.activeElement as HTMLElement)
        if (e.shiftKey) {
          const next = idx <= 0 ? focusable.length - 1 : idx - 1
          focusable[next].focus()
        } else {
          const next = idx >= focusable.length - 1 ? 0 : idx + 1
          focusable[next].focus()
        }
      }
    }

    document.addEventListener('keydown', onKeyDown, true)

    /* ── DOM 삽입 ── */
    overlay.appendChild(popup)
    document.body.appendChild(overlay)

    /* ── 위치 계산 (렌더 후 실제 크기 기반) ── */
    const rect = popup.getBoundingClientRect()
    const pos = clampPosition(
      options.x, options.y,
      rect.width, rect.height,
      window.innerWidth, window.innerHeight,
    )
    popup.style.left = `${pos.left}px`
    popup.style.top = `${pos.top}px`

    /* ── 자동 포커스 ── */
    if (inputEl) {
      inputEl.focus()
      inputEl.select()
    } else {
      confirmBtn.focus()
    }
  })
}
