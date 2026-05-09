// frontend/src/components/common/time-pair-input.ts
import { parseHM, createTimeSlot, updateTimeSlotDisplay } from './settings-common'
import { FONT_SIZE } from './ui-styles'

export interface TimePairInputHandle {
  getValue: () => { start: string; end: string }
  setValue: (start: string, end: string) => void
  setEnabled: (enabled: boolean) => void
}

export function createTimePairInput(
  initialStart: string,
  initialEnd: string,
  onTimeChange: (start: string, end: string) => void
): { el: HTMLElement; handle: TimePairInputHandle } {
  let [sH, sM] = parseHM(initialStart)
  let [eH, eM] = parseHM(initialEnd)
  let startSlot: HTMLElement | null = null
  let endSlot: HTMLElement | null = null
  let wrap: HTMLElement | null = null

  const createElement = () => {
    wrap = document.createElement('div')
    Object.assign(wrap.style, { display: 'flex', alignItems: 'center', gap: '6px' })

    startSlot = createTimeSlot(sH, sM, (h, m) => {
      sH = h; sM = m
      updateTimeSlotDisplay(startSlot!, h, m)
      onTimeChange(`${sH}:${sM}`, `${eH}:${eM}`)
    })
    endSlot = createTimeSlot(eH, eM, (h, m) => {
      eH = h; eM = m
      updateTimeSlotDisplay(endSlot!, h, m)
      onTimeChange(`${sH}:${sM}`, `${eH}:${eM}`)
    })

    const tilde = document.createElement('span')
    Object.assign(tilde.style, { color: '#999', fontSize: FONT_SIZE.badge, margin: '0 2px' })
    tilde.textContent = '~'

    wrap.appendChild(startSlot)
    wrap.appendChild(tilde)
    wrap.appendChild(endSlot)
  }

  const handle: TimePairInputHandle = {
    getValue: () => ({ start: `${sH}:${sM}`, end: `${eH}:${eM}` }),
    setValue: (start: string, end: string) => {
      const [nh, nm] = parseHM(start)
      const [neh, nem] = parseHM(end)
      sH = nh; sM = nm; eH = neh; eM = nem
      if (startSlot) updateTimeSlotDisplay(startSlot, sH, sM)
      if (endSlot) updateTimeSlotDisplay(endSlot, eH, eM)
    },
    setEnabled: (enabled: boolean) => {
      if (wrap) {
        wrap.style.opacity = enabled ? '1' : '0.4'
        wrap.style.pointerEvents = enabled ? 'auto' : 'none'
      }
    }
  }

  createElement()
  return { el: wrap!, handle }
}