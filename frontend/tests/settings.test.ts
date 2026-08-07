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
    const detailMsg = '유효하지 않은 설정값: 타임테이블 시간 순서 오류: NXT 시작(07:58) < KRX 시작(09:30) < 15:20 이어야 합니다'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: detailMsg }),
    }))

    const mgr = createSettingsManager(makeMockStore())
    const res = await mgr.saveSection({ 'timetable.krx_start': '09:30' })
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

describe('createSettingsManager.saveSection — 구조화 오류 전파 (B21-01 세션6, 설계 5/7.3)', () => {
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

  function makeMockStoreWithSettings(initial: Record<string, unknown>): { store: StoreApi<UIState>; setStateSpy: ReturnType<typeof vi.fn> } {
    let s: UIState = { settings: { ...initial } } as unknown as UIState
    const setStateSpy = vi.fn((next: Partial<UIState> | ((state: UIState) => Partial<UIState>)) => {
      const patch = typeof next === 'function' ? next(s) : next
      s = { ...s, ...patch } as UIState
    })
    return {
      store: {
        getState: () => s,
        setState: setStateSpy as unknown as StoreApi<UIState>['setState'],
        subscribe: () => () => {},
      },
      setStateSpy,
    }
  }

  it('구조화 detail 객체 → SaveResult.errorCode/errorField 전파', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          code: 'ENCRYPTION_KEY_MISSING',
          message: '암호화 키가 설정되지 않아 인증정보를 저장할 수 없습니다.',
          field: 'kiwoom_app_key',
        },
      }),
    }))

    const { store } = makeMockStoreWithSettings({ kiwoom_app_key: '***' })
    const mgr = createSettingsManager(store)
    const res = await mgr.saveSection({ kiwoom_app_key: 'new_key' })
    expect(res.ok).toBe(false)
    expect(res.error).toBe('암호화 키가 설정되지 않아 인증정보를 저장할 수 없습니다.')
    expect(res.errorCode).toBe('ENCRYPTION_KEY_MISSING')
    expect(res.errorField).toBe('kiwoom_app_key')
  })

  it('저장 실패 시 store.setState 미호출 — 평문 입력값이 성공 상태로 반영되지 않음 (설계 7.3)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: { code: 'ENCRYPTION_KEY_INVALID', message: '키 오류', field: 'ls_app_secret' },
      }),
    }))

    const { store, setStateSpy } = makeMockStoreWithSettings({ ls_app_secret: '***' })
    const mgr = createSettingsManager(store)
    await mgr.saveSection({ ls_app_secret: 'new_secret' })
    // 실패 경로 → store.setState 호출 0회 (성공 시에만 반영)
    expect(setStateSpy).not.toHaveBeenCalled()
  })

  it('문자열 detail 실패 시에도 store.setState 미호출 (하위 호환 경로)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: '유효하지 않은 설정값: 타임테이블 오류' }),
    }))

    const { store, setStateSpy } = makeMockStoreWithSettings({ 'timetable.nxt_start': '07:58' })
    const mgr = createSettingsManager(store)
    const res = await mgr.saveSection({ 'timetable.nxt_start': '07:59' })
    expect(res.ok).toBe(false)
    expect(res.errorCode).toBeUndefined()
    expect(res.errorField).toBeUndefined()
    expect(setStateSpy).not.toHaveBeenCalled()
  })

  it('저장 성공 시에만 store.setState 호출 — 기존 동작 회귀 검증', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }))

    const { store, setStateSpy } = makeMockStoreWithSettings({ foo: 'old' })
    const mgr = createSettingsManager(store)
    const res = await mgr.saveSection({ foo: 'new' })
    expect(res.ok).toBe(true)
    expect(setStateSpy).toHaveBeenCalledTimes(1)
    expect(store.getState().settings).toMatchObject({ foo: 'new' })
  })
})
