// frontend/src/settings.ts — 설정 관리 모듈 (순수 TS, React 의존성 없음)

import { uiStore } from './stores/uiStore'
import { api, ApiError } from './api/client'
import type { StoreApi } from './stores/store'
import type { UIState } from './stores/uiStore'
import type { AppSettings, SaveResult } from './types'

export const MASKED_VALUE = '***'

/** 마스킹 필드 — 서버에서 *** 로 내려오는 키 */
export const MASKED_FIELDS = new Set([
  'kiwoom_app_key', 'kiwoom_app_secret',
  'ls_app_key', 'ls_app_secret',
  'telegram_bot_token_test', 'telegram_bot_token_real',
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
  subscribe(cb: () => void): () => void
  destroy(): void
}

export function createSettingsManager(store: StoreApi<UIState> = uiStore): SettingsManager {
  const subscribers = new Set<() => void>()

  function notify(): void {
    for (const cb of subscribers) cb()
  }

  // store의 settings 변경 감지 — settings가 실제로 바뀔 때만 반영 (무관한 store 변경 무시)
  let prevSettings = store.getState().settings
  const unsubStore = store.subscribe((state) => {
    if (state.settings !== prevSettings) {
      prevSettings = state.settings
      notify()
    }
  })

  function getSettings(): AppSettings | null {
    return store.getState().settings
  }

  function isLoading(): boolean {
    return store.getState().settings === null
  }

  async function saveSection(data: Record<string, unknown>): Promise<SaveResult> {
    if (Object.keys(data).length === 0) return { ok: true }
    try {
      for (const [key, value] of Object.entries(data)) {
        await api.patchSettingField(key, value)
      }
      // API 저장 성공 → 로컬 store 반영 (WS settings-changed는 외부 변경 감지용으로 보조)
      // 설계 7.3: 서버에서 거부되면 기존 설정값을 성공한 것처럼 store에 반영하지 않는다.
      //   → 실패 경로는 catch 로 빠지므로 이 블록은 성공 시에만 실행됨 (이미 충족).
      const current = store.getState().settings
      if (current) {
        store.setState({ settings: { ...current, ...data } })
      }
      return { ok: true }
    } catch (e: unknown) {
      // B21-01 세션6: ApiError 인 경우 구조화 오류 코드/필드 전달 (설계 5 — 세션7 UI에서 매핑).
      if (e instanceof ApiError) {
        return { ok: false, error: e.message, errorCode: e.code, errorField: e.field }
      }
      const msg = e instanceof Error ? e.message : '저장 실패'
      return { ok: false, error: msg }
    }
  }

  function subscribe(cb: () => void): () => void {
    subscribers.add(cb)
    return () => { subscribers.delete(cb) }
  }

  function destroy(): void {
    unsubStore()
    subscribers.clear()
  }

  return { getSettings, isLoading, saveSection, subscribe, destroy }
}

// ── 전역 싱글톤 Settings Manager ──
export const globalSettingsManager = createSettingsManager(uiStore)
