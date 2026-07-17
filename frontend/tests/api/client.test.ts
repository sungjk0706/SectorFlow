import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// api/client.ts는 모듈 로드 시 localStorage를 참조하므로 jsdom 환경에서 그대로 사용 가능.
// 각 테스트에서 fetch 전역을 mock하여 422 응답 본문의 detail 추출 동작을 검증.

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
