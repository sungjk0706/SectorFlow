import { describe, it, expect, beforeEach, vi } from 'vitest'
import { showAlertDialog, showConfirmDialog, showCustomDialog } from '../../src/components/common/dialog'

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('showAlertDialog', () => {
  it('renders dialog with title and message', async () => {
    const promise = showAlertDialog({ title: '알림', message: '작업이 완료되었습니다' })
    expect(document.body.textContent).toContain('알림')
    expect(document.body.textContent).toContain('작업이 완료되었습니다')
    promise.catch(() => {})
  })

  it('renders confirm button with default text', async () => {
    const promise = showAlertDialog({ title: '알림', message: '메시지' })
    expect(document.body.textContent).toContain('확인')
    promise.catch(() => {})
  })

  it('renders confirm button with custom text', async () => {
    const promise = showAlertDialog({ title: '알림', message: '메시지', confirmText: '닫기' })
    expect(document.body.textContent).toContain('닫기')
    promise.catch(() => {})
  })

  it('resolves promise when confirm button is clicked', async () => {
    const promise = showAlertDialog({ title: '알림', message: '메시지' })
    const btn = document.body.querySelector('button')!
    btn.click()
    await expect(promise).resolves.toBeUndefined()
  })

  it('resolves promise on Enter key', async () => {
    const promise = showAlertDialog({ title: '알림', message: '메시지' })
    const event = new KeyboardEvent('keydown', { key: 'Enter' })
    document.dispatchEvent(event)
    await expect(promise).resolves.toBeUndefined()
  })

  it('resolves promise on Escape key', async () => {
    const promise = showAlertDialog({ title: '알림', message: '메시지' })
    const event = new KeyboardEvent('keydown', { key: 'Escape' })
    document.dispatchEvent(event)
    await expect(promise).resolves.toBeUndefined()
  })

  it('removes overlay from DOM after close', async () => {
    const promise = showAlertDialog({ title: '알림', message: '메시지' })
    const btn = document.body.querySelector('button')!
    btn.click()
    await promise
    expect(document.body.querySelector('div')).toBeNull()
  })
})

describe('showConfirmDialog', () => {
  it('renders title, message, confirm and cancel buttons', async () => {
    const promise = showConfirmDialog({ title: '확인', message: '삭제하시겠습니까?' })
    expect(document.body.textContent).toContain('확인')
    expect(document.body.textContent).toContain('삭제하시겠습니까?')
    expect(document.body.textContent).toContain('취소')
    promise.catch(() => {})
  })

  it('resolves true when confirm button is clicked', async () => {
    const promise = showConfirmDialog({ title: '확인', message: '메시지' })
    const buttons = document.body.querySelectorAll('button')
    const confirmBtn = buttons[1]
    confirmBtn.click()
    await expect(promise).resolves.toBe(true)
  })

  it('resolves false when cancel button is clicked', async () => {
    const promise = showConfirmDialog({ title: '확인', message: '메시지' })
    const buttons = document.body.querySelectorAll('button')
    const cancelBtn = buttons[0]
    cancelBtn.click()
    await expect(promise).resolves.toBe(false)
  })

  it('resolves true on Enter key', async () => {
    const promise = showConfirmDialog({ title: '확인', message: '메시지' })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await expect(promise).resolves.toBe(true)
  })

  it('resolves false on Escape key', async () => {
    const promise = showConfirmDialog({ title: '확인', message: '메시지' })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(promise).resolves.toBe(false)
  })

  it('renders custom button texts', async () => {
    const promise = showConfirmDialog({
      title: '확인',
      message: '메시지',
      confirmText: '삭제',
      cancelText: '뒤로',
    })
    expect(document.body.textContent).toContain('삭제')
    expect(document.body.textContent).toContain('뒤로')
    promise.catch(() => {})
  })
})

describe('showCustomDialog', () => {
  it('renders dialog with custom content element', () => {
    const content = document.createElement('div')
    content.textContent = '커스텀 내용'
    const overlay = showCustomDialog({
      title: '커스텀',
      content,
      actions: [{ label: '적용', onClick: () => {} }],
    })
    expect(document.body.textContent).toContain('커스텀')
    expect(document.body.textContent).toContain('커스텀 내용')
    expect(document.body.textContent).toContain('적용')
    overlay.remove()
  })

  it('calls action onClick when button is clicked', () => {
    const content = document.createElement('div')
    let clicked = false
    const overlay = showCustomDialog({
      title: '커스텀',
      content,
      actions: [{ label: '실행', onClick: () => { clicked = true } }],
    })
    const btn = document.body.querySelector('button')!
    btn.click()
    expect(clicked).toBe(true)
  })

  it('removes overlay from DOM after action click', () => {
    const content = document.createElement('div')
    const overlay = showCustomDialog({
      title: '커스텀',
      content,
      actions: [{ label: '닫기', onClick: () => {} }],
    })
    const btn = document.body.querySelector('button')!
    btn.click()
    expect(document.body.contains(overlay)).toBe(false)
  })
})
