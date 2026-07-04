import { describe, it, expect, beforeEach, vi } from 'vitest'

beforeEach(() => {
  document.body.innerHTML = ''
  vi.resetModules()
})

describe('showToast', () => {
  it('creates toast container in DOM on first call', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('success', '테스트 메시지')
    const container = document.getElementById('toast-container')
    expect(container).toBeTruthy()
  })

  it('appends toast element with message text', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('success', '저장 완료')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('저장 완료')
  })

  it('renders success icon for success type', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('success', '성공')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('✓')
  })

  it('renders error icon for error type', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('error', '실패')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('✗')
  })

  it('renders warning icon for warning type', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('warning', '경고')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('⚠')
  })

  it('renders info icon for info type', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('info', '정보')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('ℹ')
  })

  it('auto-removes toast after default duration', async () => {
    vi.useFakeTimers()
    const { showToast } = await import('../../src/components/common/toast')
    showToast('success', '자동 삭제')
    const container = document.getElementById('toast-container')!
    expect(container.children.length).toBe(1)
    vi.advanceTimersByTime(2500)
    const toastEl = container.children[0] as HTMLElement
    toastEl.dispatchEvent(new Event('animationend'))
    expect(container.children.length).toBe(0)
    vi.useRealTimers()
  })

  it('auto-removes error toast after longer duration', async () => {
    vi.useFakeTimers()
    const { showToast } = await import('../../src/components/common/toast')
    showToast('error', '에러')
    const container = document.getElementById('toast-container')!
    expect(container.children.length).toBe(1)
    vi.advanceTimersByTime(2500)
    expect(container.children.length).toBe(1)
    vi.advanceTimersByTime(2000)
    const toastEl = container.children[0] as HTMLElement
    toastEl.dispatchEvent(new Event('animationend'))
    expect(container.children.length).toBe(0)
    vi.useRealTimers()
  })

  it('removes toast on click', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('success', '클릭 삭제')
    const container = document.getElementById('toast-container')!
    const toastEl = container.children[0] as HTMLElement
    toastEl.click()
    toastEl.dispatchEvent(new Event('animationend'))
    expect(container.children.length).toBe(0)
  })

  it('appends multiple toasts', async () => {
    const { showToast } = await import('../../src/components/common/toast')
    showToast('success', '첫 번째')
    showToast('error', '두 번째')
    const container = document.getElementById('toast-container')!
    expect(container.children.length).toBe(2)
  })
})

describe('showSaveToast', () => {
  it('shows success toast for saved type with default message', async () => {
    const { showSaveToast } = await import('../../src/components/common/toast')
    showSaveToast('saved')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('저장 완료')
  })

  it('shows error toast for error type with default message', async () => {
    const { showSaveToast } = await import('../../src/components/common/toast')
    showSaveToast('error')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('저장 실패')
  })

  it('uses custom message when provided', async () => {
    const { showSaveToast } = await import('../../src/components/common/toast')
    showSaveToast('saved', '설정이 적용되었습니다')
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('설정이 적용되었습니다')
  })
})

describe('toastResult', () => {
  it('shows success toast when ok is true', async () => {
    const { toastResult } = await import('../../src/components/common/toast')
    toastResult({ ok: true })
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('저장 완료')
  })

  it('shows error toast with error message when ok is false', async () => {
    const { toastResult } = await import('../../src/components/common/toast')
    toastResult({ ok: false, error: '네트워크 오류' })
    const container = document.getElementById('toast-container')!
    expect(container.textContent).toContain('네트워크 오류')
  })
})

describe('initToastContainer', () => {
  it('creates container with correct id', async () => {
    const { initToastContainer } = await import('../../src/components/common/toast')
    initToastContainer(document.body)
    const container = document.getElementById('toast-container')
    expect(container).toBeTruthy()
  })

  it('does not create duplicate container on second call', async () => {
    const { initToastContainer } = await import('../../src/components/common/toast')
    initToastContainer(document.body)
    initToastContainer(document.body)
    const containers = document.querySelectorAll('#toast-container')
    expect(containers.length).toBe(1)
  })

  it('injects keyframes style element', async () => {
    const { initToastContainer } = await import('../../src/components/common/toast')
    initToastContainer(document.body)
    const keyframes = document.getElementById('toast-system-keyframes')
    expect(keyframes).toBeTruthy()
  })
})
