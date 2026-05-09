type ToastType = 'saved' | 'error'

interface Toast {
  id: number
  type: ToastType
  message: string
}

const DURATION_SAVED = 1500
const DURATION_ERROR = 4000
let _nextId = 0
let _container: HTMLElement | null = null
const _timers = new Map<number, ReturnType<typeof setTimeout>>()

function addToast(t: Toast) {
  if (!_container) return

  const div = document.createElement('div')
  Object.assign(div.style, {
    padding: '6px 16px',
    borderRadius: '8px',
    fontSize: '11px',
    fontWeight: 'normal',
    background: t.type === 'saved' ? '#e8f5e9' : '#ffebee',
    color: t.type === 'saved' ? '#2e7d32' : '#c62828',
    border: `1px solid ${t.type === 'saved' ? '#2e7d3230' : '#c6282830'}`,
    boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
    animation: 'toast-in 0.2s ease-out',
  })
  div.textContent = `${t.type === 'saved' ? '✓' : '✗'} ${t.message}`
  _container.appendChild(div)

  const duration = t.type === 'error' ? DURATION_ERROR : DURATION_SAVED
  const timer = setTimeout(() => {
    div.remove()
    _timers.delete(t.id)
  }, duration)
  _timers.set(t.id, timer)
}

/** 어디서든 호출 가능한 토스트 트리거 */
export function showSaveToast(type: ToastType, message?: string) {
  const msg = message ?? (type === 'saved' ? '저장 완료' : '저장 실패')
  addToast({ id: ++_nextId, type, message: msg })
}

/** onSave 결과를 받아 토스트를 자동 표시하는 헬퍼 */
export function toastResult(res: { ok: boolean; error?: string }) {
  if (res.ok) {
    showSaveToast('saved')
  } else {
    showSaveToast('error', res.error)
  }
}

/** 토스트 컨테이너 초기화 — shell.ts에서 1회 호출 */
export function initToastContainer(parent: HTMLElement) {
  const container = document.createElement('div')
  Object.assign(container.style, {
    position: 'fixed',
    top: '56px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: '9999',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '6px',
    pointerEvents: 'none',
  })
  parent.appendChild(container)
  _container = container

  // inject keyframes once
  if (!document.getElementById('toast-keyframes')) {
    const style = document.createElement('style')
    style.id = 'toast-keyframes'
    style.textContent = '@keyframes toast-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }'
    document.head.appendChild(style)
  }
}
