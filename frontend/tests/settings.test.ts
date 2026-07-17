import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { extractDirty, MASKED_VALUE, MASKED_FIELDS, createSettingsManager } from '../src/settings'
import type { StoreApi } from '../src/stores/store'
import type { UIState } from '../src/stores/uiStore'

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

describe('createSettingsManager.saveSection — 422 detail 전파 (P21)', () => {
  const store = new Map<string, string>()
  const localStorageMock = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
  }

  beforeEach(() => {
    store.clear()
    store.set('token', 'test-token')
    vi.stubGlobal('localStorage', localStorageMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  // saveSection은 내부적으로 api.patchSettingField → request → fetch 호출.
  // fetch를 mock하여 422 응답 본문의 detail이 SaveResult.error로 전파되는지 검증.
  function makeMockStore(): StoreApi<UIState> {
    let s: UIState = { settings: {} } as unknown as UIState
    return {
      getState: () => s,
      setState: (next: Partial<UIState> | ((state: UIState) => Partial<UIState>)) => {
        const patch = typeof next === 'function' ? next(s) : next
        s = { ...s, ...patch } as UIState
      },
      subscribe: () => () => {},
    }
  }

  it('422 응답 detail이 SaveResult.error로 전파됨', async () => {
    const detailMsg = '유효하지 않은 설정값: 타임테이블 시간 순서 오류: 실시간 초기화(07:58) ≤ 구독 시작(07:59) ≤ 정규장 사전 구독(09:30) < 09:00 이어야 합니다'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: detailMsg }),
    }))

    const mgr = createSettingsManager(makeMockStore())
    const res = await mgr.saveSection({ 'timetable.krx_pre_subscribe': '09:30' })
    expect(res.ok).toBe(false)
    expect(res.error).toBe(detailMsg)
  })

  it('detail 없는 422 응답은 status 코드 메시지 전파', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({}),
    }))

    const mgr = createSettingsManager(makeMockStore())
    const res = await mgr.saveSection({ foo: 'bar' })
    expect(res.ok).toBe(false)
    expect(res.error).toBe('API error: 422')
  })

  it('정상 저장 시 ok: true', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }))

    const mgr = createSettingsManager(makeMockStore())
    const res = await mgr.saveSection({ foo: 'bar' })
    expect(res.ok).toBe(true)
    expect(res.error).toBeUndefined()
  })
})
