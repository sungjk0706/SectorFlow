// frontend/src/components/common/dialog.ts — 공통 모달 다이얼로그 시스템 (Facade 패턴)
import { FONT_SIZE } from './ui-styles'

/* ── 공개 타입 ── */

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
  isDanger?: boolean
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

/* ── 내부 타입 ── */

interface DialogAction {
  label: string
  onClick: () => void
  variant?: 'primary' | 'danger' | 'default'
}

interface DialogConfig {
  title: string
  content: HTMLElement
  actions: DialogAction[]
  closeOnExternalClick: boolean
  onEnter: (() => void) | null
  onEscape: (() => void) | null
  onExternalClick: (() => void) | null
}

/* ── CSS 키프레임 주입 (1회 실행) ── */

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

/* ── 공통 스타일 ── */

function applyBoxStyle(box: HTMLElement) {
  Object.assign(box.style, {
    background: '#fff',
    borderRadius: '12px',
    padding: '20px 24px',
    minWidth: '280px',
    maxWidth: '520px',
    width: 'fit-content',
    maxHeight: '80vh',
    overflow: 'auto',
    boxShadow: '0 12px 36px rgba(0, 0, 0, 0.16)',
    fontFamily: 'inherit',
    boxSizing: 'border-box',
    animation: 'dialog-box-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards',
  })
}

function applyOverlayStyle(overlay: HTMLElement) {
  Object.assign(overlay.style, {
    position: 'fixed',
    inset: '0',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: '99990',
    animation: 'dialog-backdrop-in 0.25s ease-out forwards',
  })
}

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

function createMessageElement(message: string): HTMLElement {
  const el = document.createElement('div')
  Object.assign(el.style, {
    fontSize: '13px',
    color: '#555',
    marginBottom: '20px',
    whiteSpace: 'pre-wrap',
    lineHeight: '1.5',
  })
  el.textContent = message
  return el
}

function createButton(label: string, variant: DialogAction['variant']): HTMLButtonElement {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = label
  const isPrimary = variant === 'primary'
  const isDanger = variant === 'danger'
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
  return btn
}

/* ── 내부 공통 렌더링 함수 (유일한 구현) ── */

function renderDialog(config: DialogConfig): HTMLElement {
  ensureDialogKeyframes()

  let closed = false
  const overlay = document.createElement('div')
  applyOverlayStyle(overlay)

  const box = document.createElement('div')
  applyBoxStyle(box)
  box.appendChild(createTitleElement(config.title))
  box.appendChild(config.content)

  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '8px',
    marginTop: '20px',
  })

  const buttons: HTMLButtonElement[] = []
  for (const act of config.actions) {
    const btn = createButton(act.label, act.variant)
    btn.addEventListener('click', () => {
      close()
      act.onClick()
    })
    btnRow.appendChild(btn)
    buttons.push(btn)
  }

  box.appendChild(btnRow)
  overlay.appendChild(box)

  function close() {
    if (closed) return
    closed = true
    document.removeEventListener('keydown', onKeyDown, true)
    overlay.remove()
  }

  if (config.closeOnExternalClick) {
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) {
        close()
        config.onExternalClick?.()
      }
    })
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      close()
      config.onEscape?.()
    } else if (e.key === 'Enter' && config.onEnter) {
      e.preventDefault()
      e.stopPropagation()
      close()
      config.onEnter()
    } else if (e.key === 'Tab' && buttons.length > 1) {
      e.preventDefault()
      e.stopPropagation()
      const idx = buttons.indexOf(document.activeElement as HTMLButtonElement)
      if (e.shiftKey) {
        buttons[idx <= 0 ? buttons.length - 1 : idx - 1].focus()
      } else {
        buttons[idx >= buttons.length - 1 ? 0 : idx + 1].focus()
      }
    }
  }

  document.addEventListener('keydown', onKeyDown, true)
  document.body.appendChild(overlay)

  const defaultFocusBtn = buttons.find(b => b.style.background !== '#fff') ?? buttons[0]
  if (defaultFocusBtn) defaultFocusBtn.focus()

  return overlay
}

/* ── 공개 API (얇은 래퍼) ── */

/** 1. 경고/알림 팝업 (window.alert 대체) */
export function showAlertDialog(options: AlertDialogOptions): Promise<void> {
  const { title, message, confirmText = '확인' } = options
  return new Promise<void>((resolve) => {
    renderDialog({
      title,
      content: createMessageElement(message),
      actions: [{ label: confirmText, onClick: () => resolve(), variant: 'primary' }],
      closeOnExternalClick: false,
      onEnter: () => resolve(),
      onEscape: () => resolve(),
      onExternalClick: null,
    })
  })
}

/** 2. 확인/취소 팝업 (window.confirm 대체) */
export function showConfirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
  const { title, message, confirmText = '확인', cancelText = '취소', isDanger = false } = options
  return new Promise<boolean>((resolve) => {
    renderDialog({
      title,
      content: createMessageElement(message),
      actions: [
        { label: cancelText, onClick: () => resolve(false), variant: 'default' },
        { label: confirmText, onClick: () => resolve(true), variant: isDanger ? 'danger' : 'primary' },
      ],
      closeOnExternalClick: true,
      onEnter: () => resolve(true),
      onEscape: () => resolve(false),
      onExternalClick: () => resolve(false),
    })
  })
}

/** 3. 커스텀 팝업 (임의 HTML 컨텐츠 및 버튼) */
export function showCustomDialog(options: CustomDialogOptions): HTMLElement {
  return renderDialog({
    title: options.title,
    content: options.content,
    actions: options.actions,
    closeOnExternalClick: true,
    onEnter: null,
    onEscape: null,
    onExternalClick: null,
  })
}
