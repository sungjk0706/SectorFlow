import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearPageRefreshCache,
  PAGE_REFRESH_TTL_MS,
  refreshPageData,
} from '../src/utils/page-refresh'
import type { FreshnessMetadata } from '../src/types'

const freshness: FreshnessMetadata = { group: 'account', revision: 1 }

function response(data: string, revision = freshness.revision) {
  return { data, freshness: { ...freshness, revision } }
}

describe('refreshPageData', () => {
  beforeEach(() => {
    clearPageRefreshCache()
  })

  it('always-fresh 데이터는 TTL 안에서 중복 HTTP 요청을 차단한다', async () => {
    const fetcher = vi.fn().mockResolvedValue(response('latest'))
    const now = vi.fn().mockReturnValue(1_000)
    const options = { key: 'account', policy: 'always-fresh' as const, fetcher, now }

    await expect(refreshPageData(options)).resolves.toMatchObject({ status: 'fresh', data: 'latest' })
    now.mockReturnValue(1_000 + PAGE_REFRESH_TTL_MS['always-fresh'] - 1)
    await expect(refreshPageData(options)).resolves.toMatchObject({ status: 'cached', data: 'latest', fromCache: true })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('always-fresh 데이터는 TTL 경과 후 다시 조회한다', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(response('first'))
      .mockResolvedValueOnce(response('second', 2))
    const now = vi.fn().mockReturnValue(1_000)
    const options = { key: 'account', policy: 'always-fresh' as const, fetcher, now }

    await refreshPageData(options)
    now.mockReturnValue(1_000 + PAGE_REFRESH_TTL_MS['always-fresh'])
    await expect(refreshPageData(options)).resolves.toMatchObject({ status: 'fresh', data: 'second' })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('SWR은 캐시를 즉시 반환하고 백그라운드 요청을 합친다', async () => {
    let resolveRefresh: ((value: ReturnType<typeof response>) => void) | undefined
    const fetcher = vi.fn()
      .mockResolvedValueOnce(response('cached'))
      .mockImplementationOnce(() => new Promise(resolve => { resolveRefresh = resolve }))
    const now = vi.fn().mockReturnValue(1_000)
    const options = { key: 'reference', policy: 'swr' as const, fetcher, now }

    await refreshPageData(options)
    now.mockReturnValue(1_000 + PAGE_REFRESH_TTL_MS.swr)
    const first = await refreshPageData(options)
    const second = await refreshPageData(options)

    expect(first).toMatchObject({ status: 'refreshing', data: 'cached', fromCache: true })
    expect(second.refreshPromise).toBe(first.refreshPromise)
    expect(fetcher).toHaveBeenCalledTimes(2)

    resolveRefresh!(response('updated', 2))
    await expect(first.refreshPromise).resolves.toMatchObject({ status: 'fresh', data: 'updated' })
  })

  it('최신성 가드가 거부한 HTTP 응답은 캐시하지 않는다', async () => {
    const apply = vi.fn().mockReturnValue(false)
    const fetcher = vi.fn().mockResolvedValue(response('older'))
    const result = await refreshPageData({ key: 'account', policy: 'always-fresh' as const, fetcher, apply })

    expect(result).toMatchObject({ status: 'ignored', fromCache: false })
    expect(result.data).toBeUndefined()
    expect(apply).toHaveBeenCalledOnce()
  })

  it('갱신 실패를 결과로 반환하고 예외를 전파하지 않는다', async () => {
    const error = new Error('network')
    const result = await refreshPageData({
      key: 'account',
      policy: 'always-fresh' as const,
      fetcher: vi.fn().mockRejectedValue(error),
    })

    expect(result).toMatchObject({ status: 'error', error })
  })
})
