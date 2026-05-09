/** 증권사별 고유 색상 */
export const BROKER_COLORS: Record<string, string> = {
  kiwoom: '#FF8C00',
}

/** 증권사별 표시 이름 */
export const BROKER_LABELS: Record<string, string> = {
  kiwoom: '키움',
}

export function createBrokerBadge(broker: string, onClick?: () => void): HTMLElement {
  const color = BROKER_COLORS[broker] ?? '#888'
  const label = BROKER_LABELS[broker] ?? broker
  const clickable = !!onClick

  const span = document.createElement('span')
  Object.assign(span.style, {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '2px 8px',
    borderRadius: '10px',
    fontSize: '0.7em',
    fontWeight: 'normal',
    color: '#fff',
    backgroundColor: color,
    cursor: clickable ? 'pointer' : 'default',
    userSelect: 'none',
    lineHeight: '1.4',
  })
  span.textContent = label
  span.title = `데이터 출처: ${label}증권` + (clickable ? ' (클릭하여 브로커 설정으로 이동)' : '')
  span.setAttribute('role', 'status')
  span.setAttribute('aria-label', `데이터 출처: ${label}증권`)

  if (onClick) span.addEventListener('click', onClick)

  return span
}
