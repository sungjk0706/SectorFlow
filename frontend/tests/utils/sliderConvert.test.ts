import { describe, it, expect } from 'vitest'
import { toDisplayValue, toServerValue } from '../../src/utils/sliderConvert'

describe('toDisplayValue', () => {
  it('converts 0.0 to 0', () => {
    expect(toDisplayValue(0.0)).toBe(0)
  })

  it('converts 1.0 to 100', () => {
    expect(toDisplayValue(1.0)).toBe(100)
  })

  it('converts 0.5 to 50', () => {
    expect(toDisplayValue(0.5)).toBe(50)
  })

  it('rounds 0.333 to 33', () => {
    expect(toDisplayValue(0.333)).toBe(33)
  })

  it('rounds 0.666 to 67', () => {
    expect(toDisplayValue(0.666)).toBe(67)
  })
})

describe('toServerValue', () => {
  it('converts 0 to 0.0', () => {
    expect(toServerValue(0)).toBe(0.0)
  })

  it('converts 100 to 1.0', () => {
    expect(toServerValue(100)).toBe(1.0)
  })

  it('converts 50 to 0.5', () => {
    expect(toServerValue(50)).toBe(0.5)
  })

  it('converts 33 to 0.33', () => {
    expect(toServerValue(33)).toBe(0.33)
  })
})

describe('round-trip', () => {
  it('toDisplayValue(toServerValue(50)) === 50', () => {
    expect(toDisplayValue(toServerValue(50))).toBe(50)
  })

  it('toDisplayValue(toServerValue(100)) === 100', () => {
    expect(toDisplayValue(toServerValue(100))).toBe(100)
  })
})
