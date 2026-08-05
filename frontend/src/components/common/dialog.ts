// frontend/src/components/common/dialog.ts — 공통 모달 다이얼로그 시스템 (Facade 패턴)
import { COLOR, RADIUS, SHADOW, BLUR, SURFACE_ALPHA } from './ui-styles'
import { createActionButton, type ActionVariant } from './button'

/* ── 공개 타입 ── */

interface AlertDialogOptions {
  title: string
  message: string
  confirmText?: string
}

interface ConfirmDialogOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  isDanger?: boolean
}

interface CustomDialogOptions {
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
        to { background: ${SURFACE_ALPHA.overlay}; backdrop-filter: ${BLUR.overlay}; -webkit-backdrop-filter: ${BLUR.overlay}; }
      }
      @keyframes dialog-box-in {
        from { opacity: 0; transform: translateY(-24px); }
        to { opacity: 1; transform: translateY(0); }
      }
    `
    document.head.appendChild(style)
  }
}

/* ── 공통 스타일 ── */

function applyBoxStyle(box: HTMLElement) {
  Object.assign(box.style, {
    background: SURFACE_ALPHA.panel,
    backdropFilter: BLUR.panel,
    webkitBackdropFilter: BLUR.panel,
    borderRadius: RADIUS.xl,
    padding: '20px 24px',
    minWidth: '280px',
    maxWidth: '520px',
    width: 'fit-content',
    maxHeight: '80vh',
    overflow: 'auto',
    boxShadow: SHADOW.modal,
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
    color: COLOR.neutral, // keep — no COLOR constant for near-black
  })
  el.textContent = title
  return el
}

function createMessageElement(message: string): HTMLElement {
  const el = document.createElement('div')
  Object.assign(el.style, {
    fontSize: '13px',
    color: `${COLOR.code}`,
    marginBottom: '20px',
    whiteSpace: 'pre-wrap',
    lineHeight: '1.5',
  })
  el.textContent = message
  return el
}

/* ── 내부 공통 렌더링 함수 (유일한 구현) ── */

// 싱글톤 — 동시 다중 모달 방지 (context-popup 패턴 참조, P24 단순성)
// 새 다이얼로그 오픈 시 기존 다이얼로그를 닫고 onEscape로 Promise resolve (P22 정합성)
let _currentDialogClose: (() => void) | null = null

function renderDialog(config: DialogConfig): HTMLElement {
  ensureDialogKeyframes()

  // 기존 다이얼로그 강제 닫기 (싱글톤)
  if (_currentDialogClose) _currentDialogClose()

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
    const actionVariant: ActionVariant = (!act.variant || act.variant === 'default') ? 'secondary' : act.variant
    const btn = createActionButton({
      label: act.label,
      variant: actionVariant,
      onClick: () => {
        close()
        act.onClick()
      },
    })
    btnRow.appendChild(btn)
    buttons.push(btn)
  }

  box.appendChild(btnRow)
  overlay.appendChild(box)

  function close() {
    if (closed) return
    closed = true
    if (_currentDialogClose === forceClose) _currentDialogClose = null
    document.removeEventListener('keydown', onKeyDown, true)
    overlay.remove()
  }

  // 싱글톤 등록용 — 기존 다이얼로그를 닫고 onEscape로 Promise resolve
  function forceClose() {
    if (closed) return
    close()
    config.onEscape?.()
  }
  _currentDialogClose = forceClose

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

  const defaultFocusBtn = buttons.find(b => b.style.background.includes(COLOR.down) || b.style.background.includes(COLOR.up)) ?? buttons[0]
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
