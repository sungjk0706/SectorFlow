const THEME = {
  on:   { bg: '#e8f5e9', color: '#2e7d32' },
  off:  { bg: '#f5f5f5', color: '#9e9e9e' },
  blue: { bg: '#e3f2fd', color: '#1565c0' },
  red:  { bg: '#ffebee', color: '#c62828' },
  warn: { bg: '#fff3e0', color: '#e65100' },
} as const

export type ChipVariant = keyof typeof THEME

export interface StatusChipOptions {
  label: string
  active?: boolean
  variant?: ChipVariant
}

export function createStatusChip(options: StatusChipOptions) {
  const span = document.createElement('span')
  Object.assign(span.style, {
    padding: '3px 8px',
    borderRadius: '10px',
    fontSize: '0.75em',
    fontWeight: 'normal',
    cursor: 'default',
    whiteSpace: 'nowrap',
  })

  function applyTheme(opts: Partial<StatusChipOptions>) {
    const v = opts.variant ?? (opts.active ? 'on' : 'off')
    const t = THEME[v]
    span.style.background = t.bg
    span.style.color = t.color
    span.style.border = `1px solid ${t.color}20`
    if (opts.label !== undefined) span.textContent = opts.label
  }

  applyTheme(options)

  function update(opts: Partial<StatusChipOptions>) {
    applyTheme({ ...options, ...opts })
    Object.assign(options, opts)
  }

  return { el: span as HTMLElement, update }
}
