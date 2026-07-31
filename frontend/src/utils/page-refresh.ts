import type { FreshnessMetadata } from '../types'

export type PageRefreshPolicy = 'always-fresh' | 'swr'
export type PageRefreshStatus = 'fresh' | 'cached' | 'refreshing' | 'ignored' | 'error'

export const PAGE_REFRESH_TTL_MS = {
  'always-fresh': 3_000,
  swr: 60_000,
} as const

export interface PageRefreshResponse<T> {
  data: T
  freshness: FreshnessMetadata
}

export interface PageRefreshResult<T> {
  status: PageRefreshStatus
  data?: T
  freshness?: FreshnessMetadata
  fromCache: boolean
  error?: unknown
  refreshPromise?: Promise<PageRefreshResult<T>>
}

export interface PageRefreshOptions<T> {
  key: string
  policy: PageRefreshPolicy
  fetcher: () => Promise<PageRefreshResponse<T>>
  apply?: (response: PageRefreshResponse<T>) => boolean
  isActive?: () => boolean
  now?: () => number
}

interface CacheEntry<T> {
  response: PageRefreshResponse<T>
  updatedAt: number
}

interface RequestEntry<T> {
  promise: Promise<PageRefreshResult<T>>
  generation: number
}

const cache = new Map<string, CacheEntry<unknown>>()
const requests = new Map<string, RequestEntry<unknown>>()
const generations = new Map<string, number>()

function currentGeneration(key: string): number {
  return generations.get(key) ?? 0
}

function isActive(options: PageRefreshOptions<unknown>): boolean {
  return options.isActive ? options.isActive() : true
}

async function fetchAndApply<T>(options: PageRefreshOptions<T>, generation: number): Promise<PageRefreshResult<T>> {
  try {
    const response = await options.fetcher()
    if (generation !== currentGeneration(options.key) || !isActive(options as PageRefreshOptions<unknown>)) {
      return { status: 'ignored', fromCache: false }
    }

    const applied = options.apply ? options.apply(response) : true
    if (!applied) {
      return { status: 'ignored', fromCache: false, freshness: response.freshness }
    }

    const now = (options.now ?? Date.now)()
    cache.set(options.key, { response, updatedAt: now })
    return { status: 'fresh', data: response.data, freshness: response.freshness, fromCache: false }
  } catch (error) {
    console.error(`[page-refresh] ${options.key} 갱신 실패`, error)
    return { status: 'error', fromCache: false, error }
  } finally {
    const activeRequest = requests.get(options.key)
    if (activeRequest?.generation === generation) requests.delete(options.key)
  }
}

function startRequest<T>(options: PageRefreshOptions<T>): Promise<PageRefreshResult<T>> {
  const generation = currentGeneration(options.key)
  generations.set(options.key, generation)
  const promise = fetchAndApply(options, generation)
  requests.set(options.key, { promise: promise as Promise<PageRefreshResult<unknown>>, generation })
  return promise
}

export function refreshPageData<T>(options: PageRefreshOptions<T>): Promise<PageRefreshResult<T>> {
  const now = (options.now ?? Date.now)()
  const entry = cache.get(options.key) as CacheEntry<T> | undefined
  const age = entry ? now - entry.updatedAt : Number.POSITIVE_INFINITY
  const ttl = PAGE_REFRESH_TTL_MS[options.policy]
  const activeRequest = requests.get(options.key) as RequestEntry<T> | undefined

  if (entry && age < ttl) {
    if (options.policy === 'swr' && activeRequest) {
      return Promise.resolve({
        status: 'refreshing',
        data: entry.response.data,
        freshness: entry.response.freshness,
        fromCache: true,
        refreshPromise: activeRequest.promise,
      })
    }
    return Promise.resolve({
      status: 'cached',
      data: entry.response.data,
      freshness: entry.response.freshness,
      fromCache: true,
    })
  }

  if (activeRequest) {
    if (entry && options.policy === 'swr') {
      return Promise.resolve({
        status: 'refreshing',
        data: entry.response.data,
        freshness: entry.response.freshness,
        fromCache: true,
        refreshPromise: activeRequest.promise,
      })
    }
    return activeRequest.promise
  }

  const refreshPromise = startRequest(options)
  if (entry && options.policy === 'swr') {
    return Promise.resolve({
      status: 'refreshing',
      data: entry.response.data,
      freshness: entry.response.freshness,
      fromCache: true,
      refreshPromise,
    })
  }
  return refreshPromise
}

export function invalidatePageRefresh(key?: string): void {
  if (key === undefined) {
    for (const existingKey of generations.keys()) {
      generations.set(existingKey, currentGeneration(existingKey) + 1)
    }
    cache.clear()
    return
  }
  generations.set(key, currentGeneration(key) + 1)
  cache.delete(key)
}

export function clearPageRefreshCache(): void {
  invalidatePageRefresh()
  requests.clear()
}
