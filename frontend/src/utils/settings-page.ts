// frontend/src/utils/settings-page.ts
// 설정 페이지 공통 라이프사이클 — mount/unmount/syncAfterSave 패턴 통합

import { uiStore } from '../stores/uiStore'
import { createSettingsManager, type SettingsManager } from '../settings'
import { createAutoSaveHelper, type AutoSaveHelper } from './settings-save'
import type { AppSettings } from '../types'

/**
 * 설정 페이지 초기화 — settingsMgr + saveHelper 생성
 * mount() 시작 시 호출. syncFromSettings는 페이지 고유 동기화 함수.
 */
export function initSettingsPage(
  syncFromSettings: (s: AppSettings) => void,
): { settingsMgr: SettingsManager; saveHelper: AutoSaveHelper } {
  const settingsMgr = createSettingsManager(uiStore)

  function syncAfterSave(): void {
    const latest = settingsMgr.getSettings()
    if (latest) syncFromSettings(latest)
  }

  const saveHelper = createAutoSaveHelper(settingsMgr, syncAfterSave)
  return { settingsMgr, saveHelper }
}

/**
 * 설정 구독 시작 — 초기 동기화 + subscribe.
 * mount() 마지막에 호출. 반환값을 unsubSettings에 저장.
 */
export function startSettingsSubscription(
  settingsMgr: SettingsManager,
  syncFromSettings: (s: AppSettings) => void,
): () => void {
  const initial = settingsMgr.getSettings()
  if (initial) syncFromSettings(initial)
  return settingsMgr.subscribe(() => {
    const s = settingsMgr.getSettings()
    if (s) syncFromSettings(s)
  })
}

/**
 * 설정 페이지 정리 — unmount()에서 호출.
 */
export function destroySettingsPage(
  unsubSettings: (() => void) | null,
  saveHelper: AutoSaveHelper | null,
  settingsMgr: SettingsManager | null,
): void {
  if (unsubSettings) unsubSettings()
  if (saveHelper) saveHelper.destroy()
  if (settingsMgr) settingsMgr.destroy()
}
