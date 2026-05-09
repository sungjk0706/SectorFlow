import { FONT_SIZE } from './ui-styles'

/**
 * 공통 팝업 컴포넌트.
 * overlay + box + title + content + action buttons 패턴.
 * overlay 클릭 또는 action 버튼 클릭 시 overlay를 document.body에서 제거한다.
 */
export function showPopup(
  title: string,
  content: HTMLElement,
  actions: Array<{ label: string; onClick: () => void; variant?: string }>,
): HTMLElement {
  const overlay = document.createElement('div')
  Object.assign(overlay.style, {
    position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
    background: 'rgba(0,0,0,0.3)', zIndex: '10000', display: 'flex', alignItems: 'center', justifyContent: 'center',
  })
  const box = document.createElement('div')
  Object.assign(box.style, {
    background: '#fff', borderRadius: '12px', padding: '20px', minWidth: '300px', maxWidth: '400px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
  })
  const h = document.createElement('div')
  Object.assign(h.style, { fontWeight: 'normal', fontSize: FONT_SIZE.section, marginBottom: '12px' })
  h.textContent = title
  box.appendChild(h)
  box.appendChild(content)
  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, { display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' })
  for (const a of actions) {
    const btn = document.createElement('button')
    btn.type = 'button'
    Object.assign(btn.style, {
      padding: '6px 16px', borderRadius: '6px', border: '1px solid #ccc', cursor: 'pointer', fontSize: FONT_SIZE.label,
      background: a.variant === 'primary' ? '#1976d2' : a.variant === 'danger' ? '#dc3545' : '#f8f9fa',
      color: (a.variant === 'primary' || a.variant === 'danger') ? '#fff' : '#333',
    })
    btn.textContent = a.label
    btn.addEventListener('click', () => { overlay.remove(); a.onClick() })
    btnRow.appendChild(btn)
  }
  box.appendChild(btnRow)
  overlay.appendChild(box)
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove() })
  document.body.appendChild(overlay)
  return overlay
}
