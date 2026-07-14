import { describe, it, expect, beforeEach } from 'vitest'
import { createSlider, createDualLabelSlider } from '../../src/components/common/create-slider'

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('createSlider', () => {
  it('creates an input element of type range', () => {
    const handle = createSlider()
    expect(handle.input.type).toBe('range')
  })

  it('uses default min 0 and max 100', () => {
    const handle = createSlider()
    expect(handle.input.min).toBe('0')
    expect(handle.input.max).toBe('100')
  })

  it('uses custom min, max, value, and step', () => {
    const handle = createSlider({ min: 10, max: 50, value: 30, step: 5 })
    expect(handle.input.min).toBe('10')
    expect(handle.input.max).toBe('50')
    expect(handle.input.value).toBe('30')
    expect(handle.input.step).toBe('5')
  })

  it('getValue returns current value as number', () => {
    const handle = createSlider({ value: 42 })
    expect(handle.getValue()).toBe(42)
  })

  it('setValue updates element value', () => {
    const handle = createSlider({ value: 0 })
    handle.setValue(75)
    expect(handle.getValue()).toBe(75)
    expect(handle.input.value).toBe('75')
  })

  it('fires onChange callback on input event', () => {
    let changedValue: number | null = null
    const handle = createSlider({ onChange: (v) => { changedValue = v } })
    handle.input.value = '50'
    handle.input.dispatchEvent(new Event('input'))
    expect(changedValue).toBe(50)
  })

  it('fires onCommit callback on mouseup event', () => {
    let committedValue: number | null = null
    const handle = createSlider({ onCommit: (v) => { committedValue = v } })
    handle.input.value = '80'
    handle.input.dispatchEvent(new MouseEvent('mouseup'))
    expect(committedValue).toBe(80)
  })

  it('sets background gradient style', () => {
    const handle = createSlider({ value: 50 })
    expect(handle.input.style.background).toContain('linear-gradient')
  })

  it('updates gradient when value changes via input event', () => {
    const handle = createSlider({ value: 0 })
    const initialBg = handle.input.style.background
    handle.input.value = '100'
    handle.input.dispatchEvent(new Event('input'))
    expect(handle.input.style.background).not.toBe(initialBg)
  })

  it('wraps in container with value label when valueLabel is provided', () => {
    const handle = createSlider({ value: 30, valueLabel: v => `${v}%` })
    expect(handle.el.tagName).toBe('DIV')
    const labelSpan = handle.el.querySelector('span')
    expect(labelSpan?.textContent).toBe('30%')
  })

  it('updates value label on input event', () => {
    const handle = createSlider({ value: 0, valueLabel: v => `${v}%` })
    handle.input.value = '50'
    handle.input.dispatchEvent(new Event('input'))
    const labelSpan = handle.el.querySelector('span')
    expect(labelSpan?.textContent).toBe('50%')
  })

  it('updates value label on setValue', () => {
    const handle = createSlider({ value: 0, valueLabel: v => `${v}%` })
    handle.setValue(75)
    const labelSpan = handle.el.querySelector('span')
    expect(labelSpan?.textContent).toBe('75%')
  })
})

describe('createDualLabelSlider', () => {
  it('creates container with label row and slider', () => {
    const handle = createDualLabelSlider({
      leftLabel: (v) => `왼쪽 ${v}`,
      rightLabel: (v) => `오른쪽 ${100 - v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
      value: 30,
    })
    expect(handle.el.tagName).toBe('DIV')
    const spans = handle.el.querySelectorAll('span')
    expect(spans.length).toBe(2)
    expect(spans[0].textContent).toContain('왼쪽')
    expect(spans[1].textContent).toContain('오른쪽')
  })

  it('getValue returns slider value', () => {
    const handle = createDualLabelSlider({
      leftLabel: (v) => `${v}`,
      rightLabel: (v) => `${100 - v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
      value: 40,
    })
    expect(handle.getValue()).toBe(40)
  })

  it('setValue updates labels and slider value', () => {
    const handle = createDualLabelSlider({
      leftLabel: (v) => `L ${v}`,
      rightLabel: (v) => `R ${100 - v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
      value: 50,
    })
    handle.setValue(70)
    expect(handle.getValue()).toBe(70)
    const spans = handle.el.querySelectorAll('span')
    expect(spans[0].textContent).toContain('70')
  })

  it('updates labels on input event', () => {
    const handle = createDualLabelSlider({
      leftLabel: (v) => `L ${v}`,
      rightLabel: (v) => `R ${100 - v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
      value: 50,
      onChange: () => {},
    })
    const input = handle.el.querySelector('input')!
    input.value = '80'
    input.dispatchEvent(new Event('input'))
    const spans = handle.el.querySelectorAll('span')
    expect(spans[0].textContent).toContain('80')
  })

  it('isInteracting starts false and becomes true on mousedown', () => {
    const handle = createDualLabelSlider({
      leftLabel: (v) => `${v}`,
      rightLabel: (v) => `${100 - v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
    })
    expect(handle.isInteracting).toBe(false)
    const input = handle.el.querySelector('input')!
    input.dispatchEvent(new MouseEvent('mousedown'))
    expect(handle.isInteracting).toBe(true)
  })

  it('destroy removes event listeners without error', () => {
    const handle = createDualLabelSlider({
      leftLabel: (v) => `${v}`,
      rightLabel: (v) => `${100 - v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
    })
    expect(() => handle.destroy()).not.toThrow()
  })

  // 일반화된 dominant 로직 — midpoint 기반 (매수설정 min=0/max=200, 업종순위 min=-100/max=100)
  it('uses left dominant color when value below midpoint (min=0, max=200)', () => {
    const handle = createDualLabelSlider({
      min: 0, max: 200, value: 50,
      leftLabel: (v) => `L ${v}`,
      rightLabel: (v) => `R ${v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
    })
    const spans = handle.el.querySelectorAll('span')
    expect(spans[0].style.color).toBe('rgb(13, 110, 253)')  // leftColor (dominant)
    expect(spans[1].style.color).toBe('rgb(253, 200, 158)') // rightColorLight (non-dominant)
  })

  it('uses right dominant color when value above midpoint (min=0, max=200)', () => {
    const handle = createDualLabelSlider({
      min: 0, max: 200, value: 150,
      leftLabel: (v) => `L ${v}`,
      rightLabel: (v) => `R ${v}`,
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#fd7e14',
      rightColorLight: '#fdc89e',
    })
    const spans = handle.el.querySelectorAll('span')
    expect(spans[0].style.color).toBe('rgb(139, 184, 248)') // leftColorLight (non-dominant)
    expect(spans[1].style.color).toBe('rgb(253, 126, 20)')  // rightColor (dominant)
  })

  it('uses left dominant color when value negative (min=-100, max=100, midpoint=0)', () => {
    const handle = createDualLabelSlider({
      min: -100, max: 100, value: -50,
      leftLabel: (v) => `${v}%`,
      rightLabel: (v) => `+${v}%`,
      leftColor: '#1e88e5',
      leftColorLight: '#90caf9',
      rightColor: '#f44336',
      rightColorLight: '#ef9a9a',
    })
    const spans = handle.el.querySelectorAll('span')
    expect(spans[0].style.color).toBe('rgb(30, 136, 229)')  // leftColor (dominant, 음수)
    expect(spans[1].style.color).toBe('rgb(239, 154, 154)') // rightColorLight (non-dominant)
  })

  it('uses right dominant color when value positive (min=-100, max=100, midpoint=0)', () => {
    const handle = createDualLabelSlider({
      min: -100, max: 100, value: 50,
      leftLabel: (v) => `${v}%`,
      rightLabel: (v) => `+${v}%`,
      leftColor: '#1e88e5',
      leftColorLight: '#90caf9',
      rightColor: '#f44336',
      rightColorLight: '#ef9a9a',
    })
    const spans = handle.el.querySelectorAll('span')
    expect(spans[0].style.color).toBe('rgb(144, 202, 249)') // leftColorLight (non-dominant)
    expect(spans[1].style.color).toBe('rgb(244, 67, 54)')   // rightColor (dominant, 양수)
  })
})
