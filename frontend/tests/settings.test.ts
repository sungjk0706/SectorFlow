import { describe, it, expect } from 'vitest'
import { extractDirty, MASKED_VALUE, MASKED_FIELDS } from '../src/settings'

describe('extractDirty', () => {
  it('returns empty object when no changes', () => {
    const original = { a: 1, b: 2 }
    const current = { a: 1, b: 2 }
    const result = extractDirty(original, current, ['a', 'b'])
    expect(result).toEqual({})
  })

  it('extracts changed keys only', () => {
    const original = { a: 1, b: 2, c: 3 }
    const current = { a: 1, b: 99, c: 3 }
    const result = extractDirty(original, current, ['a', 'b', 'c'])
    expect(result).toEqual({ b: 99 })
  })

  it('extracts multiple changed keys', () => {
    const original = { a: 1, b: 2, c: 3 }
    const current = { a: 10, b: 20, c: 3 }
    const result = extractDirty(original, current, ['a', 'b', 'c'])
    expect(result).toEqual({ a: 10, b: 20 })
  })

  it('skips masked fields when value is MASKED_VALUE', () => {
    const original = { kiwoom_app_key: 'real_key', b: 2 }
    const current = { kiwoom_app_key: MASKED_VALUE, b: 2 }
    const result = extractDirty(original, current, ['kiwoom_app_key', 'b'])
    expect(result).toEqual({})
  })

  it('skips masked fields when value is empty string', () => {
    const original = { kiwoom_app_secret: 'real_secret', b: 2 }
    const current = { kiwoom_app_secret: '', b: 2 }
    const result = extractDirty(original, current, ['kiwoom_app_secret', 'b'])
    expect(result).toEqual({})
  })

  it('includes masked fields when value is a real new value', () => {
    const original = { kiwoom_app_key: 'old_key', b: 2 }
    const current = { kiwoom_app_key: 'new_key', b: 2 }
    const result = extractDirty(original, current, ['kiwoom_app_key', 'b'])
    expect(result).toEqual({ kiwoom_app_key: 'new_key' })
  })

  it('handles keys not present in current', () => {
    const original = { a: 1 }
    const current: Record<string, unknown> = {}
    const result = extractDirty(original, current, ['a'])
    expect(result).toEqual({ a: undefined })
  })

  it('handles empty keys array', () => {
    const original = { a: 1 }
    const current = { a: 2 }
    const result = extractDirty(original, current, [])
    expect(result).toEqual({})
  })
})

describe('MASKED_FIELDS', () => {
  it('contains kiwoom_app_key', () => {
    expect(MASKED_FIELDS.has('kiwoom_app_key')).toBe(true)
  })

  it('contains kiwoom_app_secret', () => {
    expect(MASKED_FIELDS.has('kiwoom_app_secret')).toBe(true)
  })

  it('contains ls_app_key', () => {
    expect(MASKED_FIELDS.has('ls_app_key')).toBe(true)
  })

  it('contains ls_app_secret', () => {
    expect(MASKED_FIELDS.has('ls_app_secret')).toBe(true)
  })

  it('contains telegram_bot_token_test', () => {
    expect(MASKED_FIELDS.has('telegram_bot_token_test')).toBe(true)
  })

  it('contains telegram_bot_token_real', () => {
    expect(MASKED_FIELDS.has('telegram_bot_token_real')).toBe(true)
  })
})
