// frontend/src/components/common/create-slider.ts
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
}

export interface SliderHandle {
  el: HTMLInputElement
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
  const leftColor = opts.leftColor ?? '#0d6efd'
  const rightColor = opts.rightColor ?? '#e9ecef'

  const el = document.createElement('input')
  el.type = 'range'
  el.min = String(min)
  el.max = String(max)
  el.step = String(step)
  el.value = String(value)
  Object.assign(el.style, {
    width: '100%',
    cursor: 'pointer',
    height: '6px',
    borderRadius: '3px',
    WebkitAppearance: 'none',
    appearance: 'none',
  })

  updateTrackGradient(el, leftColor, rightColor)

  el.addEventListener('input', () => {
    updateTrackGradient(el, leftColor, rightColor)
    opts.onChange?.(Number(el.value))
  })
  el.addEventListener('mouseup', () => opts.onCommit?.(Number(el.value)))
  el.addEventListener('touchend', () => opts.onCommit?.(Number(el.value)))

  return {
    el,
    setValue(v: number) {
      el.value = String(v)
      updateTrackGradient(el, leftColor, rightColor)
    },
    getValue() {
      return Number(el.value)
    },
  }
}

/* ── 이중 라벨 슬라이더 ── */

export interface DualLabelSliderOptions extends SliderOptions {
  leftLabel: (v: number) => string     // e.g. (v) => `업종내 상승비율 ${v}%`
  rightLabel: (v: number) => string    // e.g. (v) => `업종내 거래대금 ${100-v}%`
  leftColor: string                    // bold color (e.g. '#0d6efd')
  leftColorLight: string               // light color (e.g. '#8bb8f8')
  rightColor: string                   // bold color (e.g. '#fd7e14')
  rightColorLight: string              // light color (e.g. '#fdc89e')
}

export interface DualLabelSliderHandle {
  el: HTMLElement
  setValue(v: number): void
  getValue(): number
  isInteracting: boolean
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
  container.appendChild(slider.el)

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
    slider.el.style.background = `linear-gradient(to right, ${leftSpan.style.color} ${pct}%, ${rightSpan.style.color} ${pct}%)`
  }

  // 초기 라벨 적용
  applyLabels(opts.value ?? opts.min ?? 0)

  // 사용자 인터랙션 감지
  let isInteracting = false
  slider.el.addEventListener('mousedown', () => { isInteracting = true })
  slider.el.addEventListener('touchstart', () => { isInteracting = true })
  slider.el.addEventListener('mouseup', () => { isInteracting = false })
  slider.el.addEventListener('touchend', () => { isInteracting = false })

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
  }
}
