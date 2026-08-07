// frontend/src/components/common/toast.ts — 공통 토스트 알림 시스템
import { COLOR, hexToRgba, RADIUS, SHADOW, BLUR } from './ui-styles'
import { createIcon, type IconName } from './icon'

type ToastType = 'success' | 'error' | 'warning' | 'info'

// 하위 호환성을 위한 타입 정의
type LegacyToastType = 'saved' | 'error'

interface Toast {
  type: ToastType
  message: string
}

const DURATION_DEFAULT = 2500
const DURATION_ERROR = 4500
let _container: HTMLElement | null = null
// 단일 슬롯 — 동시 1개 토스트만 표시 (macOS 배너 스타일, 쌓임 방지)
let _currentEl: HTMLElement | null = null
let _currentTimer: ReturnType<typeof setTimeout> | null = null

const TYPE_CONFIG = {
  success: {
    bg: hexToRgba(COLOR.successBg, 0.95),
    color: `${COLOR.success}`,
    border: hexToRgba(COLOR.success, 0.25),
    icon: 'check' as IconName
  },
  error: {
    bg: hexToRgba(COLOR.upBg, 0.95),
    color: `${COLOR.up}`,
    border: hexToRgba(COLOR.up, 0.25),
    icon: 'x' as IconName
  },
  warning: {
    bg: hexToRgba(COLOR.warningBg, 0.95),
    color: `${COLOR.warning}`,
    border: hexToRgba(COLOR.warning, 0.25),
    icon: 'alert-triangle' as IconName
  },
  info: {
    bg: hexToRgba(COLOR.downBg, 0.95),
    color: `${COLOR.down}`,
    border: hexToRgba(COLOR.down, 0.25),
    icon: 'info' as IconName
  }
} as const

function addToast(t: Toast, duration?: number) {
  if (!_container) {
    // 컨테이너가 없으면 body에 동적으로 임시 삽입
    initToastContainer(document.body)
  }

  // 단일 슬롯 — 기존 토스트 즉시 제거 후 새 토스트로 교체 (쌓임 방지, macOS 배너 스타일)
  if (_currentEl) {
    clearCurrentTimer()
    _currentEl.remove()
    _currentEl = null
  }

  const cfg = TYPE_CONFIG[t.type]
  const div = document.createElement('div')

  Object.assign(div.style, {
    padding: '10px 18px',
    borderRadius: RADIUS.xl,
    fontSize: '12px',
    fontWeight: '500',
    background: cfg.bg,
    color: cfg.color,
    border: `1px solid ${cfg.border}`,
    boxShadow: SHADOW.modal,
    backdropFilter: BLUR.overlay,
    webkitBackdropFilter: BLUR.overlay,
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
    flexShrink: '0',
  })
  const iconEl = createIcon(cfg.icon, { size: 13, color: cfg.color })
  iconSpan.appendChild(iconEl)
  div.appendChild(iconSpan)

  // 텍스트 영역
  const textSpan = document.createElement('span')
  textSpan.style.flex = '1'
  textSpan.style.lineHeight = '1.4'
  textSpan.textContent = t.message
  div.appendChild(textSpan)

  // 클릭 시 즉시 닫기
  div.addEventListener('click', () => {
    removeToast(div)
  })

  _container!.appendChild(div)
  _currentEl = div

  const d = duration ?? (t.type === 'error' ? DURATION_ERROR : DURATION_DEFAULT)
  _currentTimer = setTimeout(() => {
    removeToast(div)
  }, d)
}

function clearCurrentTimer() {
  if (_currentTimer) {
    clearTimeout(_currentTimer)
    _currentTimer = null
  }
}

function removeToast(el: HTMLElement) {
  clearCurrentTimer()
  if (_currentEl === el) _currentEl = null

  // 페이드 아웃 애니메이션 후 삭제
  el.style.animation = 'toast-out 0.2s ease-in forwards'
  el.addEventListener('animationend', () => {
    el.remove()
  })
}

/** 새로운 공통 토스트 트리거 함수 */
export function showToast(type: ToastType, message: string, duration?: number) {
  addToast({ type, message }, duration)
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
    alignItems: 'center',
    justifyContent: 'center',
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
