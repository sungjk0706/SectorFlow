// frontend/src/settings.ts — 설정 관리 모듈 (순수 TS, React 의존성 없음)

import { appStore } from './stores/appStore'
import { api } from './api/client'
import type { StoreApi } from './stores/store'
import type { AppState } from './stores/appStore'
import type { AppSettings, SaveResult } from './types'

export const MASKED_VALUE = '***'

/** 마스킹 필드 — 서버에서 *** 로 내려오는 키 */
export const MASKED_FIELDS = new Set([
  'kiwoom_app_key', 'kiwoom_app_secret',
  'kiwoom_app_key_real', 'kiwoom_app_secret_real',
  'telegram_bot_token',
])

/** 원본과 비교해 변경된 키-값만 추출 (마스킹 필드 자동 제외) */
export function extractDirty(
  original: Record<string, unknown>,
  current: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> {
  const dirty: Record<string, unknown> = {}
  for (const k of keys) {
    const cur = current[k]
    if (cur === original[k]) continue
    if (MASKED_FIELDS.has(k) && (cur === MASKED_VALUE || cur === '')) continue
    dirty[k] = cur
  }
  return dirty
}

export interface SettingsManager {
  getSettings(): AppSettings | null
  isLoading(): boolean
  saveSection(data: Record<string, unknown>): Promise<SaveResult>
  registerEditing(id: string, editing: boolean): void
  subscribe(cb: () => void): () => void
  destroy(): void
}

export function createSettingsManager(store: StoreApi<AppState> = appStore): SettingsManager {
  let localSettings: AppSettings | null = store.getState().settings
  const editingSet = new Set<string>()
  const subscribers = new Set<() => void>()

  function notify(): void {
    for (const cb of subscribers) cb()
  }

  // store의 settings 변경 감지 — 편집 중이 아닐 때만 반영
  const unsubStore = store.subscribe((state) => {
    if (editingSet.size > 0) return
    if (state.settings !== localSettings) {
      localSettings = state.settings
      notify()
    }
  })

  function getSettings(): AppSettings | null {
    return localSettings
  }

  function isLoading(): boolean {
    return localSettings === null
  }

  async function saveSection(data: Record<string, unknown>): Promise<SaveResult> {
    if (Object.keys(data).length === 0) return { ok: true }
    try {
      await api.updateSettings(data)
      // 저장 성공 시 로컬 settings에 즉시 병합
      if (localSettings) {
        localSettings = { ...localSettings, ...data } as AppSettings
        notify()
      }
      return { ok: true }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '저장 실패'
      return { ok: false, error: msg }
    }
  }

  function registerEditing(id: string, editing: boolean): void {
    if (editing) editingSet.add(id)
    else editingSet.delete(id)
  }

  function subscribe(cb: () => void): () => void {
    subscribers.add(cb)
    return () => { subscribers.delete(cb) }
  }

  function destroy(): void {
    unsubStore()
    subscribers.clear()
    editingSet.clear()
  }

  return { getSettings, isLoading, saveSection, registerEditing, subscribe, destroy }
}

// ── 전역 싱글톤 Settings Manager (Python GC 최적화) ──
export const globalSettingsManager = createSettingsManager(appStore)

// ── 전역 싱글톤 WebSocket 상태 배지 모듈 (store subscriber 1개만 유지) ──
let globalWsBadgeInstance: HTMLElement | null = null
let globalWsBadgeUnsub: (() => void) | null = null

export function createGlobalWsBadge(): HTMLElement {
  if (globalWsBadgeInstance) {
    return globalWsBadgeInstance
  }

  const badge = document.createElement('span')
  Object.assign(badge.style, {
    fontSize: '11px',
    fontWeight: 'normal',
    borderRadius: '3px',
    padding: '2px 6px',
    marginLeft: '8px',
    display: 'inline-block',
  })

  function updateBadge(): void {
    const state = appStore.getState()
    const connected = state.wsSubscribeStatus?.quote_subscribed ?? false
    badge.textContent = connected ? 'WS 연결' : 'WS 해제'
    badge.style.color = connected ? '#2e7d32' : '#d32f2f'
    badge.style.background = connected ? '#e8f5e9' : '#ffeaea'
  }

  updateBadge()
  globalWsBadgeUnsub = appStore.subscribe(updateBadge)
  globalWsBadgeInstance = badge

  return badge
}

export function destroyGlobalWsBadge(): void {
  if (globalWsBadgeUnsub) {
    globalWsBadgeUnsub()
    globalWsBadgeUnsub = null
  }
  globalWsBadgeInstance = null
}
