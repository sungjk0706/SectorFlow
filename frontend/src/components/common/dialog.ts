// frontend/src/components/common/dialog.ts — 공통 모달 다이얼로그 시스템
import { FONT_SIZE } from './ui-styles'

export interface AlertDialogOptions {
  title: string
  message: string
  confirmText?: string
}

export interface ConfirmDialogOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  isDanger?: boolean // 위험 작업 시 확인 버튼 강조용 (예: 빨간색)
}

export interface CustomDialogOptions {
  title: string
  content: HTMLElement
  actions: Array<{
    label: string
    onClick: () => void
    variant?: 'primary' | 'danger' | 'default'
  }>
}

/** CSS 키프레임 주입 (1회 실행) */
function ensureDialogKeyframes() {
  if (!document.getElementById('dialog-system-keyframes')) {
    const style = document.createElement('style')
    style.id = 'dialog-system-keyframes'
    style.textContent = `
      @keyframes dialog-backdrop-in {
        from { background: rgba(0, 0, 0, 0); backdrop-filter: blur(0px); -webkit-backdrop-filter: blur(0px); }
        to { background: rgba(0, 0, 0, 0.4); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); }
      }
      @keyframes dialog-box-in {
        from { opacity: 0; transform: scale(0.96) translateY(8px); }
        to { opacity: 1; transform: scale(1) translateY(0); }
      }
    `
    document.head.appendChild(style)
  }
}

/** 공통 다이얼로그 박스 스타일 */
function applyBoxStyle(box: HTMLElement) {
  Object.assign(box.style, {
    background: '#fff',
    borderRadius: '12px',
    padding: '20px 24px',
    minWidth: '320px',
    maxWidth: '460px',
    boxShadow: '0 12px 36px rgba(0, 0, 0, 0.16)',
    fontFamily: 'inherit',
    boxSizing: 'border-box',
    animation: 'dialog-box-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards',
  })
}

/** 공통 오버레이(백드롭) 스타일 */
function applyOverlayStyle(overlay: HTMLElement) {
  Object.assign(overlay.style, {
    position: 'fixed',
    inset: '0',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: '99990', // 토스트(_container: 99999) 보다는 살짝 낮게 설정
    animation: 'dialog-backdrop-in 0.25s ease-out forwards',
  })
}

/** 공통 제목 스타일 */
function createTitleElement(title: string): HTMLElement {
  const el = document.createElement('div')
  Object.assign(el.style, {
    fontSize: '15px',
    fontWeight: '600',
    marginBottom: '12px',
    color: '#111',
  })
  el.textContent = title
  return el
}

/** 1. 경고/알림 팝업 (window.alert 대체) */
export function showAlertDialog(options: AlertDialogOptions): Promise<void> {
  ensureDialogKeyframes()
  const { title, message, confirmText = '확인' } = options

  return new Promise<void>((resolve) => {
    const overlay = document.createElement('div')
    applyOverlayStyle(overlay)

    const box = document.createElement('div')
    applyBoxStyle(box)

    // 제목
    box.appendChild(createTitleElement(title))

    // 메시지
    const msgEl = document.createElement('div')
    Object.assign(msgEl.style, {
      fontSize: '13px',
      color: '#555',
      marginBottom: '20px',
      whiteSpace: 'pre-wrap',
      lineHeight: '1.5',
    })
    msgEl.textContent = message
    box.appendChild(msgEl)

    // 버튼 영역
    const btnRow = document.createElement('div')
    Object.assign(btnRow.style, {
      display: 'flex',
      justifyContent: 'flex-end',
    })

    const confirmBtn = document.createElement('button')
    confirmBtn.type = 'button'
    confirmBtn.textContent = confirmText
    Object.assign(confirmBtn.style, {
      padding: '7px 20px',
      border: 'none',
      borderRadius: '6px',
      background: '#1976d2',
      color: '#fff',
      cursor: 'pointer',
      fontSize: '13px',
      fontWeight: '500',
      fontFamily: 'inherit',
    })
    
    btnRow.appendChild(confirmBtn)
    box.appendChild(btnRow)
    overlay.appendChild(box)
    document.body.appendChild(overlay)

    confirmBtn.focus()

    function close() {
      document.removeEventListener('keydown', onKeyDown, true)
      overlay.remove()
      resolve()
    }

    confirmBtn.addEventListener('click', close)

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' || e.key === 'Enter') {
        e.preventDefault()
        e.stopPropagation()
        close()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
  })
}

/** 2. 확인/취소 팝업 (window.confirm 및 기존 showConfirmModal 대체) */
export function showConfirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
  ensureDialogKeyframes()
  const { title, message, confirmText = '확인', cancelText = '취소', isDanger = false } = options

  return new Promise<boolean>((resolve) => {
    let resolved = false

    function cleanup(result: boolean) {
      if (resolved) return
      resolved = true
      document.removeEventListener('keydown', onKeyDown, true)
      overlay.remove()
      resolve(result)
    }

    const overlay = document.createElement('div')
    applyOverlayStyle(overlay)
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) cleanup(false)
    })

    const box = document.createElement('div')
    applyBoxStyle(box)

    // 제목
    box.appendChild(createTitleElement(title))

    // 메시지
    const msgEl = document.createElement('div')
    Object.assign(msgEl.style, {
      fontSize: '13px',
      color: '#555',
      marginBottom: '20px',
      whiteSpace: 'pre-wrap',
      lineHeight: '1.5',
    })
    msgEl.textContent = message
    box.appendChild(msgEl)

    // 버튼 영역
    const btnRow = document.createElement('div')
    Object.assign(btnRow.style, {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: '8px',
    })

    const cancelBtn = document.createElement('button')
    cancelBtn.type = 'button'
    cancelBtn.textContent = cancelText
    Object.assign(cancelBtn.style, {
      padding: '7px 18px',
      border: '1px solid #ccc',
      borderRadius: '6px',
      background: '#fff',
      color: '#333',
      cursor: 'pointer',
      fontSize: '13px',
      fontFamily: 'inherit',
    })
    cancelBtn.addEventListener('click', () => cleanup(false))

    const confirmBtn = document.createElement('button')
    confirmBtn.type = 'button'
    confirmBtn.textContent = confirmText
    Object.assign(confirmBtn.style, {
      padding: '7px 18px',
      border: 'none',
      borderRadius: '6px',
      background: isDanger ? '#d32f2f' : '#198754',
      color: '#fff',
      cursor: 'pointer',
      fontSize: '13px',
      fontWeight: '500',
      fontFamily: 'inherit',
    })
    confirmBtn.addEventListener('click', () => cleanup(true))

    btnRow.appendChild(cancelBtn)
    btnRow.appendChild(confirmBtn)
    box.appendChild(btnRow)
    overlay.appendChild(box)
    document.body.appendChild(overlay)

    confirmBtn.focus()

    // 포커스 트랩용 배열
    const focusable = [cancelBtn, confirmBtn]

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        cleanup(false)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        e.stopPropagation()
        cleanup(true)
      } else if (e.key === 'Tab') {
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
  })
}

/** 3. 커스텀 팝업 (기존 showPopup 대체 - 임의의 HTML 컨텐츠 및 버튼 노출 지원) */
export function showCustomDialog(options: CustomDialogOptions): HTMLElement {
  ensureDialogKeyframes()
  const { title, content, actions } = options

  const overlay = document.createElement('div')
  applyOverlayStyle(overlay)
  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay) close()
  })

  const box = document.createElement('div')
  applyBoxStyle(box)

  // 제목
  box.appendChild(createTitleElement(title))

  // 내용 노드 삽입
  box.appendChild(content)

  // 버튼 영역
  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '8px',
    marginTop: '20px',
  })

  const buttons: HTMLButtonElement[] = []

  function close() {
    document.removeEventListener('keydown', onKeyDown, true)
    overlay.remove()
  }

  for (const act of actions) {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.textContent = act.label
    
    // 버튼 테마 지정
    const isPrimary = act.variant === 'primary'
    const isDanger = act.variant === 'danger'
    
    Object.assign(btn.style, {
      padding: '7px 18px',
      borderRadius: '6px',
      border: (isPrimary || isDanger) ? 'none' : '1px solid #ccc',
      background: isPrimary ? '#1976d2' : isDanger ? '#d32f2f' : '#fff',
      color: (isPrimary || isDanger) ? '#fff' : '#333',
      cursor: 'pointer',
      fontSize: FONT_SIZE.label,
      fontFamily: 'inherit',
      fontWeight: '500',
    })

    btn.addEventListener('click', () => {
      close()
      act.onClick()
    })
    
    btnRow.appendChild(btn)
    buttons.push(btn)
  }

  box.appendChild(btnRow)
  overlay.appendChild(box)
  document.body.appendChild(overlay)

  // 첫 번째 버튼에 자동 포커스 (또는 기본이 있다면 그것에)
  const defaultFocusBtn = buttons.find(b => b.style.background !== '#fff') ?? buttons[0]
  if (defaultFocusBtn) defaultFocusBtn.focus()

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      close()
    } else if (e.key === 'Tab') {
      e.preventDefault()
      e.stopPropagation()
      const idx = buttons.indexOf(document.activeElement as HTMLButtonElement)
      if (e.shiftKey) {
        const next = idx <= 0 ? buttons.length - 1 : idx - 1
        buttons[next].focus()
      } else {
        const next = idx >= buttons.length - 1 ? 0 : idx + 1
        buttons[next].focus()
      }
    }
  }
  document.addEventListener('keydown', onKeyDown, true)

  return overlay
}
