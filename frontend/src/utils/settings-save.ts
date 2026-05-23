// frontend/src/utils/settings-save.ts
// 설정 저장 로직 공통 헬퍼 — 디바운스, 저장 중 상태 관리, pending save 큐

import type { SettingsManager } from '../settings'
import { toastResult } from '../components/common/save-toast'

export interface AutoSaveHelper {
  autoSave(key: string, value: unknown): void
  saveImmediate(patch: Record<string, unknown>): Promise<void>
  destroy(): void
}

/**
 * 설정 저장 헬퍼 생성
 * @param settingsMgr - SettingsManager 인스턴스
 * @param onSync - 저장 완료 후 동기화 콜백 (선택)
 * @returns AutoSaveHelper 인스턴스
 */
export function createAutoSaveHelper(
  settingsMgr: SettingsManager | null,
  onSync?: () => void
): AutoSaveHelper {
  let saving = false
  let pendingSave: { key: string; value: unknown } | null = null
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function autoSave(key: string, value: unknown): void {
    if (!settingsMgr) return
    // 디바운스: 마지막 입력 후 400ms 대기 후 저장
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      flushSave(key, value)
    }, 400)
  }

  async function flushSave(key: string, value: unknown): Promise<void> {
    if (!settingsMgr) return
    if (saving) {
      pendingSave = { key, value }
      return
    }
    saving = true
    try {
      let currentKey = key
      let currentValue = value
      while (true) {
        const res = await settingsMgr.saveSection({ [currentKey]: currentValue })
        toastResult(res)
        if (pendingSave) {
          currentKey = pendingSave.key
          currentValue = pendingSave.value
          pendingSave = null
        } else {
          break
        }
      }
    } catch (err) {
      console.error('[AutoSaveHelper] save failed:', err)
    } finally {
      saving = false
      // 저장 완료 후 동기화 콜백 호출
      if (onSync) onSync()
    }
  }

  async function saveImmediate(patch: Record<string, unknown>): Promise<void> {
    if (!settingsMgr) return
    const res = await settingsMgr.saveSection(patch)
    toastResult(res)
  }

  function destroy(): void {
    if (debounceTimer) clearTimeout(debounceTimer)
  }

  return { autoSave, saveImmediate, destroy }
}
