/**
 * 설정 페이지 공통 컴포넌트 — buy-settings / sell-settings / general-settings 에서 공유
 * 중복 함수 6개를 한 곳에서 관리: parseHM, sectionTitle, createTimeSlot,
 * updateTimeSlotDisplay, createTimeDropdown(+createGridPanel+createFineAdjust), createTimePairInput
 */

import { FONT_SIZE, FONT_WEIGHT } from './ui-styles'

/* ── 상수 ── */
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINS_10 = ['00', '10', '20', '30', '40', '50']

/* ── parseHM ── */
export function parseHM(v: string): [string, string] {
  const parts = String(v || '09:00').split(':')
  return [parts[0]?.padStart(2, '0') || '09', parts[1]?.padStart(2, '0') || '00']
}

/* ── sectionTitle ── */
export function sectionTitle(text: string): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, {
    fontWeight: FONT_WEIGHT.normal,
    fontSize: FONT_SIZE.section,
    padding: '10px 0 6px',
    borderBottom: '2px solid #eee',
    marginBottom: '8px',
  })
  div.textContent = text
  return div
}

/* ── createTimeSlot ── */
export function createTimeSlot(
  hour: string,
  minute: string,
  onChange: (h: string, m: string) => void,
): HTMLElement {
  const span = document.createElement('span')
  span.style.position = 'relative'
  span.style.display = 'inline-block'

  const display = document.createElement('span')
  Object.assign(display.style, {
    display: 'inline-flex', alignItems: 'center', gap: '1px',
    background: '#f7f8fa', border: '1px solid #e0e0e0', borderRadius: '6px',
    padding: '4px 8px', cursor: 'pointer', fontVariantNumeric: 'tabular-nums',
    fontSize: FONT_SIZE.label, userSelect: 'none',
  })
  display.innerHTML =
    `<span style="color:#333;font-weight:500">${hour}</span>` +
    `<span style="color:#aaa">:</span>` +
    `<span style="color:#333;font-weight:500">${minute}</span>` +
    `<span style="font-size:${FONT_SIZE.chip};color:#aaa;margin-left:2px">▼</span>`

  let dropdownEl: HTMLElement | null = null

  display.addEventListener('click', () => {
    if (dropdownEl) { dropdownEl.remove(); dropdownEl = null; return }
    const curH = display.children[0].textContent || hour
    const curM = display.children[2].textContent || minute
    dropdownEl = createTimeDropdown(curH, curM,
      (h) => onChange(h, display.children[2].textContent || minute),
      (m) => onChange(display.children[0].textContent || hour, m),
      () => { if (dropdownEl) { dropdownEl.remove(); dropdownEl = null } },
      display,
    )
    document.body.appendChild(dropdownEl)
  })

  span.appendChild(display)
  return span
}

/* ── updateTimeSlotDisplay ── */
export function updateTimeSlotDisplay(slot: HTMLElement, h: string, m: string): void {
  const spans = slot.firstElementChild!.children
  if (spans[0]) (spans[0] as HTMLElement).textContent = h
  if (spans[2]) (spans[2] as HTMLElement).textContent = m
}

/* ── createTimeDropdown ── */
function createTimeDropdown(
  hour: string, minute: string,
  onChangeH: (h: string) => void,
  onChangeM: (m: string) => void,
  onClose: () => void,
  anchor: HTMLElement,
): HTMLElement {
  const rect = anchor.getBoundingClientRect()
  const div = document.createElement('div')
  Object.assign(div.style, {
    position: 'fixed',
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
    zIndex: '10000',
    background: '#fff', border: '1px solid #d0d5dd', borderRadius: '8px',
    boxShadow: '0 4px 16px rgba(0,0,0,0.12)', width: '240px',
  })

  let currentTab: 'hour' | 'minute' = 'hour'
  let curH = hour, curM = minute

  const tabBar = document.createElement('div')
  tabBar.style.cssText = 'display:flex;border-bottom:1px solid #eee;'
  const hourTab = document.createElement('button'); hourTab.type = 'button'
  const minTab = document.createElement('button'); minTab.type = 'button'

  function renderTabs() {
    for (const [btn, label, active] of [
      [hourTab, `시 (${curH})`, currentTab === 'hour'],
      [minTab, `분 (${curM})`, currentTab === 'minute'],
    ] as [HTMLButtonElement, string, boolean][]) {
      Object.assign(btn.style, {
        flex: '1', padding: '6px 0', border: 'none', cursor: 'pointer',
        fontSize: FONT_SIZE.badge, fontWeight: FONT_WEIGHT.normal,
        color: active ? '#1a73e8' : '#999',
        background: active ? '#e8f0fe' : 'transparent',
      })
      btn.textContent = label
    }
  }

  hourTab.addEventListener('click', () => { currentTab = 'hour'; renderTabs(); renderContent() })
  minTab.addEventListener('click', () => { currentTab = 'minute'; renderTabs(); renderContent() })
  tabBar.appendChild(hourTab); tabBar.appendChild(minTab)
  div.appendChild(tabBar)

  const content = document.createElement('div')
  div.appendChild(content)

  function renderContent() {
    while (content.firstChild) content.removeChild(content.firstChild)
    if (currentTab === 'hour') {
      content.appendChild(createGridPanel(HOURS, curH, 6, (h) => {
        curH = h; onChangeH(h); currentTab = 'minute'; renderTabs(); renderContent()
      }))
    } else {
      content.appendChild(createGridPanel(MINS_10, MINS_10.includes(curM) ? curM : '', 6, (m) => {
        curM = m; onChangeM(m); onClose()
      }))
      content.appendChild(createFineAdjust(curM, (m) => { curM = m; onChangeM(m) }))
    }
  }

  renderTabs()
  renderContent()

  const outsideHandler = (e: MouseEvent) => {
    if (!div.contains(e.target as Node)) { onClose(); document.removeEventListener('mousedown', outsideHandler) }
  }
  setTimeout(() => document.addEventListener('mousedown', outsideHandler), 0)

  return div
}

/* ── createGridPanel ── */
function createGridPanel(
  items: string[], value: string, columns: number,
  onChange: (v: string) => void,
): HTMLElement {
  const grid = document.createElement('div')
  Object.assign(grid.style, { display: 'grid', gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: '2px', padding: '4px' })
  for (const item of items) {
    const btn = document.createElement('button'); btn.type = 'button'
    const isActive = item === value
    Object.assign(btn.style, {
      width: '36px', height: '30px', display: 'flex', alignItems: 'center', justifyContent: 'center',
      border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: FONT_SIZE.badge,
      fontVariantNumeric: 'tabular-nums',
      background: isActive ? '#1a73e8' : 'transparent',
      color: isActive ? '#fff' : '#555',
      fontWeight: FONT_WEIGHT.normal,
    })
    btn.textContent = item
    btn.addEventListener('mouseenter', () => { if (item !== value) btn.style.background = '#f0f0f0' })
    btn.addEventListener('mouseleave', () => { if (item !== value) btn.style.background = 'transparent' })
    btn.addEventListener('click', () => onChange(item))
    grid.appendChild(btn)
  }
  return grid
}

/* ── createFineAdjust ── */
function createFineAdjust(minute: string, onChange: (m: string) => void): HTMLElement {
  let m = parseInt(minute, 10)
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '4px 0', borderTop: '1px solid #eee' })

  const decBtn = document.createElement('button'); decBtn.type = 'button'
  Object.assign(decBtn.style, { width: '28px', height: '24px', border: '1px solid #ddd', borderRadius: '4px', background: '#f8f8f8', cursor: 'pointer', fontSize: FONT_SIZE.badge })
  decBtn.textContent = '−1'

  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: FONT_SIZE.badge, fontWeight: FONT_WEIGHT.normal, color: '#1a73e8', minWidth: '24px', textAlign: 'center' })
  label.textContent = minute

  const incBtn = document.createElement('button'); incBtn.type = 'button'
  Object.assign(incBtn.style, { width: '28px', height: '24px', border: '1px solid #ddd', borderRadius: '4px', background: '#f8f8f8', cursor: 'pointer', fontSize: FONT_SIZE.badge })
  incBtn.textContent = '+1'

  decBtn.addEventListener('click', () => { m = Math.max(0, m - 1); const s = String(m).padStart(2, '0'); label.textContent = s; onChange(s) })
  incBtn.addEventListener('click', () => { m = Math.min(59, m + 1); const s = String(m).padStart(2, '0'); label.textContent = s; onChange(s) })

  wrap.appendChild(decBtn); wrap.appendChild(label); wrap.appendChild(incBtn)
  return wrap
}
