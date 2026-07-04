import { describe, it, expect, beforeEach } from 'vitest'
import { createSlider, createDualLabelSlider } from '../../src/components/common/create-slider'

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('createSlider', () => {
  it('creates an input element of type range', () => {
    const handle = createSlider()
    expect(handle.el.type).toBe('range')
  })

  it('uses default min 0 and max 100', () => {
    const handle = createSlider()
    expect(handle.el.min).toBe('0')
    expect(handle.el.max).toBe('100')
  })

  it('uses custom min, max, value, and step', () => {
    const handle = createSlider({ min: 10, max: 50, value: 30, step: 5 })
    expect(handle.el.min).toBe('10')
    expect(handle.el.max).toBe('50')
    expect(handle.el.value).toBe('30')
    expect(handle.el.step).toBe('5')
  })

  it('getValue returns current value as number', () => {
    const handle = createSlider({ value: 42 })
    expect(handle.getValue()).toBe(42)
  })

  it('setValue updates element value', () => {
    const handle = createSlider({ value: 0 })
    handle.setValue(75)
    expect(handle.getValue()).toBe(75)
    expect(handle.el.value).toBe('75')
  })

  it('fires onChange callback on input event', () => {
    let changedValue: number | null = null
    const handle = createSlider({ onChange: (v) => { changedValue = v } })
    handle.el.value = '50'
    handle.el.dispatchEvent(new Event('input'))
    expect(changedValue).toBe(50)
  })

  it('fires onCommit callback on mouseup event', () => {
    let committedValue: number | null = null
    const handle = createSlider({ onCommit: (v) => { committedValue = v } })
    handle.el.value = '80'
    handle.el.dispatchEvent(new MouseEvent('mouseup'))
    expect(committedValue).toBe(80)
  })

  it('sets background gradient style', () => {
    const handle = createSlider({ value: 50 })
    expect(handle.el.style.background).toContain('linear-gradient')
  })

  it('updates gradient when value changes via input event', () => {
    const handle = createSlider({ value: 0 })
    const initialBg = handle.el.style.background
    handle.el.value = '100'
    handle.el.dispatchEvent(new Event('input'))
    expect(handle.el.style.background).not.toBe(initialBg)
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
})
