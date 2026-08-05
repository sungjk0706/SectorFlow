// frontend/src/utils/settings-save.ts
// 설정 저장 로직 공통 헬퍼 — 디바운스, 저장 중 상태 관리, pending save 큐

import type { SettingsManager } from '../settings'
import { toastResult } from '../components/common/toast'

export interface AutoSaveHelper {
  // onFail: 저장 실패 시 호출 (호출처에서 vals·입력란을 원래 값으로 복원 — 토글 복원 패턴과 동일, P23)
  autoSave(key: string, value: unknown, onFail?: () => void): void
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
  let pendingSave: { key: string; value: unknown; onFail: (() => void) | undefined } | null = null
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function autoSave(key: string, value: unknown, onFail?: () => void): void {
    if (!settingsMgr) return
    // 디바운스: 마지막 입력 후 400ms 대기 후 저장. 디바운스 중 새 호출이 오면 이전 onFail은 무시되고 마지막 onFail이 사용됨.
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      flushSave(key, value, onFail)
    }, 400)
  }

  async function flushSave(key: string, value: unknown, onFail?: () => void): Promise<void> {
    if (!settingsMgr) return
    if (saving) {
      pendingSave = { key, value, onFail }
      return
    }
    saving = true
    let cur = { key, value, onFail }
    try {
      while (true) {
        const res = await settingsMgr.saveSection({ [cur.key]: cur.value })
        toastResult(res)
        if (!res.ok && cur.onFail) cur.onFail()
        if (pendingSave) {
          cur = pendingSave
          pendingSave = null
        } else {
          break
        }
      }
    } catch (err) {
      console.error('[AutoSaveHelper] save failed:', err)
      if (cur.onFail) cur.onFail()
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
