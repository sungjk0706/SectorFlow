import { describe, it, expect } from 'vitest'
import { resolveRoute } from '../src/router'

const VALID_PATHS = [
  '#/sector-ranking',
  '#/buy-settings',
  '#/sell-settings',
  '#/profit-overview',
  '#/general-settings',
]

describe('resolveRoute', () => {
  it('returns valid path as-is', () => {
    expect(resolveRoute('#/sector-ranking', VALID_PATHS)).toBe('#/sector-ranking')
  })

  it('returns valid path for buy-settings', () => {
    expect(resolveRoute('#/buy-settings', VALID_PATHS)).toBe('#/buy-settings')
  })

  it('redirects #/sector to #/sector-ranking', () => {
    expect(resolveRoute('#/sector', VALID_PATHS)).toBe('#/sector-ranking')
  })

  it('redirects #/buy to #/buy-settings', () => {
    expect(resolveRoute('#/buy', VALID_PATHS)).toBe('#/buy-settings')
  })

  it('redirects #/sell to #/sell-settings', () => {
    expect(resolveRoute('#/sell', VALID_PATHS)).toBe('#/sell-settings')
  })

  it('redirects #/account to #/profit-overview', () => {
    expect(resolveRoute('#/account', VALID_PATHS)).toBe('#/profit-overview')
  })

  it('redirects #/profit to #/profit-overview', () => {
    expect(resolveRoute('#/profit', VALID_PATHS)).toBe('#/profit-overview')
  })

  it('redirects #/settings to #/general-settings', () => {
    expect(resolveRoute('#/settings', VALID_PATHS)).toBe('#/general-settings')
  })

  it('returns default route for empty hash', () => {
    expect(resolveRoute('', VALID_PATHS)).toBe('#/sector-ranking')
  })

  it('returns default route for unknown hash', () => {
    expect(resolveRoute('#/unknown', VALID_PATHS)).toBe('#/sector-ranking')
  })

  it('returns default route for invalid path', () => {
    expect(resolveRoute('#/nonexistent', VALID_PATHS)).toBe('#/sector-ranking')
  })
})
