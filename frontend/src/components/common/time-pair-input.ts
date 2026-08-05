// frontend/src/components/common/time-pair-input.ts
import { parseHM, createTimeSlot, updateTimeSlotDisplay } from './settings-common'
import { COLOR, FONT_SIZE } from './ui-styles'

export interface TimePairInputHandle {
  getValue: () => { start: string; end: string }
  setValue: (start: string, end: string) => void
  setEnabled: (enabled: boolean) => void
}

// 시간쌍 순서 위반 안내 메시지 (P21 투명성, P10 SSOT — 컴포넌트 단일 상수)
const TIME_ORDER_INVALID_MSG = '시작 시간이 종료 시간보다 빨라야 합니다'

export function createTimePairInput(
  initialStart: string,
  initialEnd: string,
  onTimeChange: (start: string, end: string) => void,
  onInvalid?: (msg: string) => void
): { el: HTMLElement; handle: TimePairInputHandle } {
  let [sH, sM] = parseHM(initialStart)
  let [eH, eM] = parseHM(initialEnd)
  let startSlot: HTMLElement | null = null
  let endSlot: HTMLElement | null = null
  let wrap: HTMLElement | null = null

  // onTimeChange 호출 전 순서 검증 (P20 폴백 금지 — 자동 교정/스왑 안 함, 저장만 차단)
  // 시작 ≥ 종료 → onInvalid 호출, onTimeChange 건너뜀. 유효 → onTimeChange 호출.
  const tryTimeChange = () => {
    const startMin = Number(sH) * 60 + Number(sM)
    const endMin = Number(eH) * 60 + Number(eM)
    if (startMin >= endMin) {
      onInvalid?.(TIME_ORDER_INVALID_MSG)
      return
    }
    onTimeChange(`${sH}:${sM}`, `${eH}:${eM}`)
  }

  const createElement = () => {
    wrap = document.createElement('div')
    Object.assign(wrap.style, { display: 'flex', alignItems: 'center', gap: '6px' })

    startSlot = createTimeSlot(sH, sM, (h, m) => {
      sH = h; sM = m
      updateTimeSlotDisplay(startSlot!, h, m)
      tryTimeChange()
    })
    endSlot = createTimeSlot(eH, eM, (h, m) => {
      eH = h; eM = m
      updateTimeSlotDisplay(endSlot!, h, m)
      tryTimeChange()
    })

    const tilde = document.createElement('span')
    Object.assign(tilde.style, { color: COLOR.disabled, fontSize: FONT_SIZE.badge, margin: '0 2px' })
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