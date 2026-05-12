/**
 * withErrorBoundary — try-catch 래퍼.
 * mountFn 실행 중 에러 발생 시 에러 메시지 + "다시 시도" 버튼 표시.
 */
export function withErrorBoundary(
  mountFn: (container: HTMLElement) => void,
  container: HTMLElement,
): void {
  try {
    mountFn(container)
  } catch (err) {
    console.error('[ErrorBoundary]', err)
    renderError(container, err, mountFn)
  }
}

function renderError(
  container: HTMLElement,
  err: unknown,
  mountFn: (container: HTMLElement) => void,
) {
  while (container.firstChild) container.removeChild(container.firstChild)

  const wrap = document.createElement('div')
  Object.assign(wrap.style, {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '48px 24px',
    textAlign: 'center',
  })

  const msg = document.createElement('p')
  Object.assign(msg.style, { color: '#ef4444', fontSize: '14px', marginBottom: '16px' })
  msg.textContent = (err instanceof Error ? err.message : null) || '알 수 없는 오류가 발생했습니다'

  const btn = document.createElement('button')
  Object.assign(btn.style, {
    padding: '8px 20px',
    fontSize: '13px',
    color: '#fff',
    backgroundColor: '#3b82f6',
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
  })
  btn.textContent = '다시 시도'
  btn.addEventListener('click', () => {
    while (container.firstChild) container.removeChild(container.firstChild)
    withErrorBoundary(mountFn, container)
  })

  wrap.appendChild(msg)
  wrap.appendChild(btn)
  container.appendChild(wrap)
}
