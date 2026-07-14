// frontend/src/components/common/create-slider.ts
import { COLOR, FONT_SIZE } from './ui-styles'
// 슬라이더 공통 컴포넌트 — <input type="range"> 팩토리

export interface SliderOptions {
  min?: number          // 기본 0
  max?: number          // 기본 100
  value?: number        // 초기값
  step?: number         // 기본 1
  onChange?: (value: number) => void   // input 이벤트
  onCommit?: (value: number) => void   // mouseup/touchend 이벤트 (저장 시점)
  leftColor?: string    // 좌측 색상 (기본 #0d6efd)
  rightColor?: string   // 우측 색상 (기본 #e9ecef)
  valueLabel?: (value: number) => string  // 현재 값 표시 라벨 (선택 — 지정 시 상단 우측에 표시)
}

export interface SliderHandle {
  el: HTMLElement
  input: HTMLInputElement
  setValue: (v: number) => void
  getValue: () => number
}

function updateTrackGradient(el: HTMLInputElement, left: string, right: string): void {
  const min = Number(el.min) || 0
  const max = Number(el.max) || 100
  const val = Number(el.value)
  const pct = max > min ? ((val - min) / (max - min)) * 100 : 0
  el.style.background = `linear-gradient(to right, ${left} ${pct}%, ${right} ${pct}%)`
}

export function createSlider(opts: SliderOptions = {}): SliderHandle {
  const min = opts.min ?? 0
  const max = opts.max ?? 100
  const value = opts.value ?? min
  const step = opts.step ?? 1
  const leftColor = opts.leftColor ?? COLOR.down
  const rightColor = opts.rightColor ?? '#e9ecef'

  const input = document.createElement('input')
  input.type = 'range'
  input.min = String(min)
  input.max = String(max)
  input.step = String(step)
  input.value = String(value)
  Object.assign(input.style, {
    width: '100%',
    cursor: 'pointer',
    height: '6px',
    borderRadius: '3px',
    WebkitAppearance: 'none',
    appearance: 'none',
  })

  updateTrackGradient(input, leftColor, rightColor)

  // 값 표시 라벨이 있으면 컨테이너로 감싸기 (P23 일관성 — 매수설정 슬라이더와 동일 UX)
  let el: HTMLElement = input
  let labelSpan: HTMLSpanElement | null = null

  if (opts.valueLabel) {
    const container = document.createElement('div')
    const labelRow = document.createElement('div')
    Object.assign(labelRow.style, { display: 'flex', justifyContent: 'flex-end', marginBottom: '4px' })
    labelSpan = document.createElement('span')
    Object.assign(labelSpan.style, { fontSize: FONT_SIZE.small, color: COLOR.down })
    labelSpan.textContent = opts.valueLabel(value)
    labelRow.appendChild(labelSpan)
    container.appendChild(labelRow)
    container.appendChild(input)
    el = container
  }

  input.addEventListener('input', () => {
    updateTrackGradient(input, leftColor, rightColor)
    if (labelSpan && opts.valueLabel) {
      labelSpan.textContent = opts.valueLabel(Number(input.value))
    }
    opts.onChange?.(Number(input.value))
  })
  input.addEventListener('mouseup', () => opts.onCommit?.(Number(input.value)))
  input.addEventListener('touchend', () => opts.onCommit?.(Number(input.value)))

  return {
    el,
    input,
    setValue(v: number) {
      input.value = String(v)
      updateTrackGradient(input, leftColor, rightColor)
      if (labelSpan && opts.valueLabel) {
        labelSpan.textContent = opts.valueLabel(v)
      }
    },
    getValue() {
      return Number(input.value)
    },
  }
}

/* ── 이중 라벨 슬라이더 ── */

export interface DualLabelSliderOptions extends SliderOptions {
  leftLabel: (v: number) => string     // e.g. (v) => `업종내 상승비율 ${v}%`
  rightLabel: (v: number) => string    // e.g. (v) => `업종내 거래대금 ${100-v}%`
  leftColor: string                    // bold color (e.g. COLOR.down)
  leftColorLight: string               // light color (e.g. '#8bb8f8')
  rightColor: string                   // bold color (e.g. '#fd7e14')
  rightColorLight: string              // light color (e.g. '#fdc89e')
}

export interface DualLabelSliderHandle {
  el: HTMLElement
  setValue(v: number): void
  getValue(): number
  isInteracting: boolean
  destroy(): void
}

export function createDualLabelSlider(opts: DualLabelSliderOptions): DualLabelSliderHandle {
  const max = opts.max ?? 100

  // 라벨 행
  const labelRow = document.createElement('div')
  Object.assign(labelRow.style, { display: 'flex', justifyContent: 'space-between', marginBottom: '4px' })

  const leftSpan = document.createElement('span')
  const rightSpan = document.createElement('span')
  labelRow.appendChild(leftSpan)
  labelRow.appendChild(rightSpan)

  // 내부 슬라이더 — onChange를 래핑하여 라벨 자동 갱신
  const slider = createSlider({
    ...opts,
    onChange(v: number) {
      applyLabels(v)
      opts.onChange?.(v)
    },
  })

  // 컨테이너
  const container = document.createElement('div')
  container.appendChild(labelRow)
  container.appendChild(slider.input)

  function applyLabels(v: number): void {
    const leftVal = max - v
    const rightVal = v
    const leftDominant = leftVal >= rightVal
    const rightDominant = rightVal >= leftVal

    leftSpan.textContent = opts.leftLabel(v)
    leftSpan.style.color = leftDominant ? opts.leftColor : opts.leftColorLight
    leftSpan.style.fontWeight = 'normal'

    rightSpan.textContent = opts.rightLabel(v)
    rightSpan.style.color = rightDominant ? opts.rightColor : opts.rightColorLight
    rightSpan.style.fontWeight = 'normal'

    // 트랙 그라디언트 (thumb 위치와 일치)
    const min = opts.min ?? 0
    const pct = max > min ? ((v - min) / (max - min)) * 100 : 0
    slider.input.style.background = `linear-gradient(to right, ${leftSpan.style.color} ${pct}%, ${rightSpan.style.color} ${pct}%)`
  }

  // 초기 라벨 적용
  applyLabels(opts.value ?? opts.min ?? 0)

  // 사용자 인터랙션 감지
  let isInteracting = false
  const onStart = () => { isInteracting = true }
  const onEnd = () => { isInteracting = false }

  slider.input.addEventListener('mousedown', onStart)
  slider.input.addEventListener('touchstart', onStart)
  window.addEventListener('mouseup', onEnd)
  window.addEventListener('touchend', onEnd)

  function destroy() {
    slider.input.removeEventListener('mousedown', onStart)
    slider.input.removeEventListener('touchstart', onStart)
    window.removeEventListener('mouseup', onEnd)
    window.removeEventListener('touchend', onEnd)
  }

  return {
    el: container,
    setValue(v: number) {
      slider.setValue(v)
      applyLabels(v)
    },
    getValue() {
      return slider.getValue()
    },
    get isInteracting() {
      return isInteracting
    },
    destroy,
  }
}
