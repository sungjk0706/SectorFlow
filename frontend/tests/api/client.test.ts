import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// api/client.ts는 모듈 로드 시 localStorage를 참조하므로 jsdom 환경에서 그대로 사용 가능.
// 각 테스트에서 fetch 전역을 mock하여 422 응답 본문의 detail 추출 동작을 검증.
// B21-01 세션6: detail 객체(code/message/field) → ApiError 전환, 문자열 detail 하위 호환 유지.

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

describe('페이지 진입 HTTP 조회 API', () => {
  it('계좌 스냅샷 조회가 인증 헤더와 페이지 컨텍스트를 전달한다', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: {}, freshness: { group: 'account', revision: 1 } }) })
    vi.stubGlobal('fetch', fetchMock)

    const { api } = await import('../../src/api/client')
    await api.getAccountSnapshot('profit-detail')

    expect(fetchMock).toHaveBeenCalledWith('/api/account/snapshot', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer test-token', 'X-Page-Context': 'profit-detail' }),
    }))
  })

  it('5개 페이지 진입 API가 서버 응답 계약을 그대로 반환한다', async () => {
    const payload = { data: [], freshness: { group: 'sector_stocks', revision: 3 } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => payload }))
    const { api } = await import('../../src/api/client')

    await expect(api.getAccountPositions()).resolves.toEqual(payload)
    await expect(api.getBuyTargets()).resolves.toEqual(payload)
    await expect(api.getSectorScores()).resolves.toEqual(payload)
    await expect(api.getSectorStocks()).resolves.toEqual(payload)
  })

  it('종목상세 자료 조회가 전용 경로와 인증 헤더를 사용한다', async () => {
    const payload = { date: '20260804', response_date: '20260804', items: [] }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => payload })
    vi.stubGlobal('fetch', fetchMock)
    const { api } = await import('../../src/api/client')

    await expect(api.getStockDetail5d()).resolves.toEqual(payload)
    expect(fetchMock).toHaveBeenCalledWith('/api/stock-detail/5d-array', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
    }))
  })
})

describe('api.patchSettingField — 422 응답 detail 추출 (P21)', () => {
  it('422 응답 본문에 detail이 있으면 Error 메시지에 detail 포함', async () => {
    const detailMsg = '유효하지 않은 설정값: 타임테이블 시간 순서 오류: 실시간 초기화(08:59) ≤ 구독 시작(07:59) ≤ 정규장 사전 구독(08:59) < 09:00 이어야 합니다'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: detailMsg }),
    }))

    const { api } = await import('../../src/api/client')
    await expect(api.patchSettingField('timetable.ws_prestart', '07:59')).rejects.toThrow(detailMsg)
  })

  it('422 응답 본문에 detail이 없으면 status 코드 메시지 사용', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({}),
    }))

    const { api } = await import('../../src/api/client')
    await expect(api.patchSettingField('foo', 'bar')).rejects.toThrow('API error: 422')
  })

  it('422 응답 본문이 JSON이 아니면 status 코드 메시지 사용', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => { throw new SyntaxError('Unexpected token') },
    }))

    const { api } = await import('../../src/api/client')
    await expect(api.patchSettingField('foo', 'bar')).rejects.toThrow('API error: 422')
  })

  it('400 응답도 detail 추출 (일관성 — P23)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'value 필드가 필요합니다' }),
    }))

    const { api } = await import('../../src/api/client')
    await expect(api.patchSettingField('foo', 'bar')).rejects.toThrow('value 필드가 필요합니다')
  })

  it('정상 응답은 본문 그대로 반환', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }))

    const { api } = await import('../../src/api/client')
    await expect(api.patchSettingField('foo', 'bar')).resolves.toEqual({ ok: true })
  })
})

describe('api.patchSettingField — 구조화 detail 객체 → ApiError (B21-01 세션6, 설계 5)', () => {
  beforeEach(() => {
    store.set('token', 'test-token')
    vi.stubGlobal('localStorage', localStorageMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('detail 객체(code/message/field) → ApiError throw, code/field/message 전달', async () => {
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

    const { api, ApiError } = await import('../../src/api/client')
    await expect(api.patchSettingField('kiwoom_app_key', 'new_key')).rejects.toMatchObject({
      name: 'ApiError',
      message: '암호화 키가 설정되지 않아 인증정보를 저장할 수 없습니다.',
      code: 'ENCRYPTION_KEY_MISSING',
      field: 'kiwoom_app_key',
    })
    // ApiError 클래스 인스턴스 확인 (Error 상속 호환)
    await expect(api.patchSettingField('kiwoom_app_key', 'new_key')).rejects.toBeInstanceOf(ApiError)
  })

  it('detail 객체 message 누락 시 status 코드 폴백 메시지 + code/field 전달', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: { code: 'ENCRYPTION_FAILED', field: 'ls_app_secret' },
      }),
    }))

    const { api, ApiError } = await import('../../src/api/client')
    await expect(api.patchSettingField('ls_app_secret', 'x')).rejects.toMatchObject({
      name: 'ApiError',
      message: 'API error: 422',
      code: 'ENCRYPTION_FAILED',
      field: 'ls_app_secret',
    })
    await expect(api.patchSettingField('ls_app_secret', 'x')).rejects.toBeInstanceOf(ApiError)
  })

  it('detail 객체 code/field 누락 시 message만 전달 (ApiError.code/field undefined)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: { message: '부분 오류' } }),
    }))

    const { api, ApiError } = await import('../../src/api/client')
    await expect(api.patchSettingField('foo', 'bar')).rejects.toMatchObject({
      name: 'ApiError',
      message: '부분 오류',
      code: undefined,
      field: undefined,
    })
    await expect(api.patchSettingField('foo', 'bar')).rejects.toBeInstanceOf(ApiError)
  })

  it('문자열 detail 은 ApiError 아닌 일반 Error 유지 (하위 호환 — 비암호화 검증)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: '유효하지 않은 설정값: 타임테이블 오류' }),
    }))

    const { api, ApiError } = await import('../../src/api/client')
    await expect(api.patchSettingField('timetable.ws_prestart', '07:59')).rejects.toMatchObject({
      message: '유효하지 않은 설정값: 타임테이블 오류',
    })
    await expect(api.patchSettingField('timetable.ws_prestart', '07:59')).rejects.not.toBeInstanceOf(ApiError)
  })
})
