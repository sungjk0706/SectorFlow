// frontend/src/components/common/confirm-modal.ts — 확인 팝업 모달

export interface ConfirmModalOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
}

/**
 * 확인/취소 모달을 표시하고 사용자 선택을 Promise로 반환한다.
 * confirm → true, cancel/Escape → false.
 * 키보드 접근성: Tab 순환, Escape 취소, Enter 확인, focus trap.
 */
export function showConfirmModal(options: ConfirmModalOptions): Promise<boolean> {
  const { title, message, confirmText = '확인', cancelText = '취소' } = options

  return new Promise<boolean>((resolve) => {
    let resolved = false

    function cleanup(result: boolean): void {
      if (resolved) return
      resolved = true
      document.removeEventListener('keydown', onKeyDown, true)
      overlay.remove()
      resolve(result)
    }

    /* ── 오버레이 ── */
    const overlay = document.createElement('div')
    Object.assign(overlay.style, {
      position: 'fixed',
      inset: '0',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.4)',
      zIndex: '10000',
    })
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) cleanup(false)
    })

    /* ── 다이얼로그 ── */
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    dialog.setAttribute('aria-modal', 'true')
    dialog.setAttribute('aria-label', title)
    Object.assign(dialog.style, {
      background: '#fff',
      borderRadius: '8px',
      padding: '20px 24px',
      minWidth: '320px',
      maxWidth: '440px',
      boxShadow: '0 4px 24px rgba(0,0,0,0.18)',
      fontFamily: 'inherit',
      fontSize: '13px',
      lineHeight: '1.5',
    })

    /* ── 제목 ── */
    const titleEl = document.createElement('div')
    Object.assign(titleEl.style, {
      fontSize: '15px',
      fontWeight: 'normal',
      marginBottom: '10px',
      color: '#222',
    })
    titleEl.textContent = title
    dialog.appendChild(titleEl)

    /* ── 메시지 ── */
    const msgEl = document.createElement('div')
    Object.assign(msgEl.style, {
      fontSize: '13px',
      color: '#555',
      marginBottom: '20px',
      whiteSpace: 'pre-wrap',
    })
    msgEl.textContent = message
    dialog.appendChild(msgEl)

    /* ── 버튼 영역 ── */
    const btnRow = document.createElement('div')
    Object.assign(btnRow.style, {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: '8px',
    })

    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = cancelText
    Object.assign(cancelBtn.style, {
      padding: '6px 16px',
      border: '1px solid #ccc',
      borderRadius: '4px',
      background: '#fff',
      cursor: 'pointer',
      fontSize: '13px',
      fontFamily: 'inherit',
      color: '#333',
    })
    cancelBtn.addEventListener('click', () => cleanup(false))

    const confirmBtn = document.createElement('button')
    confirmBtn.textContent = confirmText
    Object.assign(confirmBtn.style, {
      padding: '6px 16px',
      border: 'none',
      borderRadius: '4px',
      background: '#198754',
      color: '#fff',
      cursor: 'pointer',
      fontSize: '13px',
      fontFamily: 'inherit',
      fontWeight: 'normal',
    })
    confirmBtn.addEventListener('click', () => cleanup(true))

    btnRow.appendChild(cancelBtn)
    btnRow.appendChild(confirmBtn)
    dialog.appendChild(btnRow)
    overlay.appendChild(dialog)

    /* ── Focus trap: Tab 순환 ── */
    const focusable = [cancelBtn, confirmBtn]

    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        cleanup(false)
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        e.stopPropagation()
        cleanup(true)
        return
      }
      if (e.key === 'Tab') {
        e.preventDefault()
        e.stopPropagation()
        const idx = focusable.indexOf(document.activeElement as HTMLButtonElement)
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
    document.body.appendChild(overlay)

    // 초기 포커스 → 확인 버튼
    confirmBtn.focus()
  })
}
