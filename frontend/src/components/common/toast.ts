// frontend/src/components/common/toast.ts — 공통 토스트 알림 시스템

export type ToastType = 'success' | 'error' | 'warning' | 'info'

// 하위 호환성을 위한 타입 정의
export type LegacyToastType = 'saved' | 'error'

interface Toast {
  id: number
  type: ToastType
  message: string
}

const DURATION_DEFAULT = 2500
const DURATION_ERROR = 4500
let _nextId = 0
let _container: HTMLElement | null = null
const _timers = new Map<number, ReturnType<typeof setTimeout>>()

const TYPE_CONFIG = {
  success: {
    bg: 'rgba(232, 245, 233, 0.95)',
    color: '#2e7d32',
    border: 'rgba(46, 125, 50, 0.25)',
    icon: '✓'
  },
  error: {
    bg: 'rgba(255, 235, 235, 0.95)',
    color: '#c62828',
    border: 'rgba(198, 40, 40, 0.25)',
    icon: '✗'
  },
  warning: {
    bg: 'rgba(255, 243, 224, 0.95)',
    color: '#e65100',
    border: 'rgba(230, 81, 0, 0.25)',
    icon: '⚠'
  },
  info: {
    bg: 'rgba(227, 242, 253, 0.95)',
    color: '#1565c0',
    border: 'rgba(21, 101, 192, 0.25)',
    icon: 'ℹ'
  }
} as const

function addToast(t: Toast, duration?: number) {
  if (!_container) {
    // 컨테이너가 없으면 body에 동적으로 임시 삽입
    initToastContainer(document.body)
  }

  const cfg = TYPE_CONFIG[t.type]
  const div = document.createElement('div')
  
  Object.assign(div.style, {
    padding: '10px 18px',
    borderRadius: '10px',
    fontSize: '12px',
    fontWeight: '500',
    background: cfg.bg,
    color: cfg.color,
    border: `1px solid ${cfg.border}`,
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)',
    backdropFilter: 'blur(8px)',
    webkitBackdropFilter: 'blur(8px)',
    animation: 'toast-in 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    minWidth: '220px',
    maxWidth: '360px',
    pointerEvents: 'auto',
    cursor: 'pointer',
    transition: 'all 0.2s ease',
  })

  // 아이콘 영역
  const iconSpan = document.createElement('span')
  Object.assign(iconSpan.style, {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '18px',
    height: '18px',
    borderRadius: '50%',
    background: `${cfg.color}15`,
    fontSize: '11px',
    fontWeight: 'bold',
  })
  iconSpan.textContent = cfg.icon
  div.appendChild(iconSpan)

  // 텍스트 영역
  const textSpan = document.createElement('span')
  textSpan.style.flex = '1'
  textSpan.style.lineHeight = '1.4'
  textSpan.textContent = t.message
  div.appendChild(textSpan)

  // 클릭 시 즉시 닫기
  div.addEventListener('click', () => {
    removeToast(t.id, div)
  })

  _container!.appendChild(div)

  const d = duration ?? (t.type === 'error' ? DURATION_ERROR : DURATION_DEFAULT)
  const timer = setTimeout(() => {
    removeToast(t.id, div)
  }, d)
  _timers.set(t.id, timer)
}

function removeToast(id: number, el: HTMLElement) {
  const timer = _timers.get(id)
  if (timer) {
    clearTimeout(timer)
    _timers.delete(id)
  }
  
  // 페이드 아웃 애니메이션 후 삭제
  el.style.animation = 'toast-out 0.2s ease-in forwards'
  el.addEventListener('animationend', () => {
    el.remove()
  })
}

/** 새로운 공통 토스트 트리거 함수 */
export function showToast(type: ToastType, message: string, duration?: number) {
  addToast({ id: ++_nextId, type, message }, duration)
}

/** 하위 호환용 showSaveToast 함수 */
export function showSaveToast(type: LegacyToastType, message?: string) {
  const toastType: ToastType = type === 'saved' ? 'success' : 'error'
  const defaultMsg = type === 'saved' ? '저장 완료' : '저장 실패'
  showToast(toastType, message ?? defaultMsg)
}

/** 하위 호환용 toastResult 함수 */
export function toastResult(res: { ok: boolean; error?: string }) {
  if (res.ok) {
    showSaveToast('saved')
  } else {
    showSaveToast('error', res.error)
  }
}

/** 토스트 컨테이너 초기화 — shell.ts 또는 main.ts에서 호출 */
export function initToastContainer(parent: HTMLElement) {
  if (_container) return
  
  const container = document.createElement('div')
  container.id = 'toast-container'
  Object.assign(container.style, {
    position: 'fixed',
    top: '56px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: '99999',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '8px',
    pointerEvents: 'none',
  })
  
  parent.appendChild(container)
  _container = container

  // CSS Keyframes 주입
  if (!document.getElementById('toast-system-keyframes')) {
    const style = document.createElement('style')
    style.id = 'toast-system-keyframes'
    style.textContent = `
      @keyframes toast-in {
        from { opacity: 0; transform: translateY(-16px) scale(0.95); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      @keyframes toast-out {
        from { opacity: 1; transform: translateY(0) scale(1); }
        to { opacity: 0; transform: translateY(-8px) scale(0.95); }
      }
    `
    document.head.appendChild(style)
  }
}
