// frontend/src/pages/sell-settings.ts
// 매도설정 카드 — Vanilla TS PageModule
// SellSettingsCard.tsx + SellSettingsSection.tsx + QuickToggle + TimePairInput 통합

import { createSettingRow, createNumInput, createToggleBtn, createFixedValue } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { initSettingsPage, startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import type { AutoSaveHelper } from '../utils/settings-save'
import type { SettingsManager } from '../settings'
import { setDisabled } from '../components/common/ui-styles'
import type { AppSettings } from '../types'

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let saveHelper: AutoSaveHelper | null = null
let vals: Record<string, unknown> = {}

// 토글 참조
let tpToggle: ReturnType<typeof createToggleBtn> | null = null
let lossToggle: ReturnType<typeof createToggleBtn> | null = null
let tsToggle: ReturnType<typeof createToggleBtn> | null = null

// 입력 참조
let tpValInput: ReturnType<typeof createNumInput> | null = null
let lossValInput: ReturnType<typeof createNumInput> | null = null
let tsStartValInput: ReturnType<typeof createNumInput> | null = null
let tsDropValInput: ReturnType<typeof createNumInput> | null = null

// 비활성 래퍼
let tpValRow: HTMLElement | null = null
let lossValRow: HTMLElement | null = null
let tsStartRow: HTMLElement | null = null
let tsDropRow: HTMLElement | null = null

/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings): void {
  const r = s as Record<string, unknown>
  vals = { ...r }

  const act = document.activeElement

  // 익절
  const tpOn = !!r.tp_apply
  tpToggle?.setOn(tpOn)
  if (tpValInput && (!act || !tpValInput.el.contains(act))) tpValInput.setValue(Number(r.tp_val) || 0)
  setDisabled(tpValRow!, !tpOn)

  // 손절
  const lossOn = !!r.loss_apply
  lossToggle?.setOn(lossOn)
  if (lossValInput && (!act || !lossValInput.el.contains(act))) lossValInput.setValue(Number(r.loss_val) || 0)
  setDisabled(lossValRow!, !lossOn)

  // 추적매도
  const tsOn = !!r.ts_apply
  tsToggle?.setOn(tsOn)
  if (tsStartValInput && (!act || !tsStartValInput.el.contains(act))) tsStartValInput.setValue(Number(r.ts_start_val) || 0)
  if (tsDropValInput && (!act || !tsDropValInput.el.contains(act))) tsDropValInput.setValue(Number(r.ts_drop_val) || 0)
  setDisabled(tsStartRow!, !tsOn)
  setDisabled(tsDropRow!, !tsOn)
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  const ctx = initSettingsPage(syncFromSettings)
  settingsMgr = ctx.settingsMgr
  saveHelper = ctx.saveHelper
  vals = {}

  const root = document.createElement('div')


  // ── 익절 / 손절 / 추적 매도 섹션 ──
  root.appendChild(sectionTitle('매도 유형'))

  // 매도 주문 유형
  root.appendChild(createSettingRow('매도 주문 유형', createFixedValue('시장가')))

  // 익절
  tpToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.tp_apply; vals.tp_apply = next; tpToggle!.setOn(next)
    setDisabled(tpValRow!, !next)
    await saveHelper!.saveImmediate({ tp_apply: next })
  }})
  root.appendChild(createSettingRow('익절', tpToggle.el))

  tpValInput = createNumInput({ value: 0, onChange: v => { vals.tp_val = v; saveHelper!.autoSave('tp_val', v) }, step: 0.1, name: 'tp_val' })
  tpValRow = createSettingRow('익절 상승률 (%)', tpValInput.el)
  root.appendChild(tpValRow)

  // 손절
  lossToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.loss_apply; vals.loss_apply = next; lossToggle!.setOn(next)
    setDisabled(lossValRow!, !next)
    await saveHelper!.saveImmediate({ loss_apply: next })
  }})
  root.appendChild(createSettingRow('손절', lossToggle.el))

  lossValInput = createNumInput({ value: 0, onChange: v => { vals.loss_val = v; saveHelper!.autoSave('loss_val', v) }, step: 0.1, name: 'loss_val' })
  lossValRow = createSettingRow('손절 하락률 (%)', lossValInput.el)
  root.appendChild(lossValRow)

  // 추적 매도
  tsToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !vals.ts_apply; vals.ts_apply = next; tsToggle!.setOn(next)
    setDisabled(tsStartRow!, !next)
    setDisabled(tsDropRow!, !next)
    await saveHelper!.saveImmediate({ ts_apply: next })
  }})
  root.appendChild(createSettingRow('고점 추적 매도(Trailing Stop)', tsToggle.el))

  tsStartValInput = createNumInput({ value: 0, onChange: v => { vals.ts_start_val = v; saveHelper!.autoSave('ts_start_val', v) }, step: 0.1, name: 'ts_start_val' })
  tsStartRow = createSettingRow('추적 시작 상승률 (%)', tsStartValInput.el)
  root.appendChild(tsStartRow)

  tsDropValInput = createNumInput({ value: 0, onChange: v => { vals.ts_drop_val = v; saveHelper!.autoSave('ts_drop_val', v) }, step: 0.1, name: 'ts_drop_val' })
  tsDropRow = createSettingRow('추적 고점대비 하락률 (%)', tsDropValInput.el)
  root.appendChild(tsDropRow)

  container.appendChild(root)

  // 초기 설정 동기화 + 구독
  unsubSettings = startSettingsSubscription(settingsMgr, syncFromSettings)
}

/* ── unmount ── */
function unmount(): void {
  destroySettingsPage(unsubSettings, saveHelper, settingsMgr)
  unsubSettings = null; saveHelper = null; settingsMgr = null
  tpToggle = null; lossToggle = null; tsToggle = null
  tpValInput = null; lossValInput = null
  tsStartValInput = null; tsDropValInput = null
  tpValRow = null; lossValRow = null; tsStartRow = null; tsDropRow = null
  vals = {}
}

export default { mount, unmount }