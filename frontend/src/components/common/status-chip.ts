import { COLOR } from './ui-styles'

const THEME = {
  on:   { bg: `${COLOR.successBg}`, color: `${COLOR.success}` },
  off:  { bg: `${COLOR.neutralBg}`, color: `${COLOR.disabled}` },
  blue: { bg: `${COLOR.downBg}`, color: `${COLOR.down}` },
  red:  { bg: `${COLOR.upBg}`, color: `${COLOR.up}` },
  warn: { bg: `${COLOR.warningBg}`, color: `${COLOR.warning}` },
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
