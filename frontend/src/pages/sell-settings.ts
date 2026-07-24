// frontend/src/pages/sell-settings.ts
// 매도설정 카드 — Vanilla TS PageModule
// SellSettingsCard.tsx + SellSettingsSection.tsx + QuickToggle + TimePairInput 통합

import { createSettingRow, createNumInput, createToggleBtn, createFixedValue, createToggleLabelControlsRow } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { initSettingsPage, startSettingsSubscription, destroySettingsPage } from '../utils/settings-page'
import type { AutoSaveHelper } from '../utils/settings-save'
import type { SettingsManager } from '../settings'
import { setDisabled } from '../components/common/ui-styles'
import { createCardTitle } from '../components/common/card-title'
import type { AppSettings } from '../types'

/* ── 모듈 상태 ── */
let settingsMgr: SettingsManager | null = null
let unsubSettings: (() => void) | null = null
let saveHelper: AutoSaveHelper | null = null
let vals: Record<string, unknown> = {}

// 익절/손절 UI 참조
let tpToggle: ReturnType<typeof createToggleBtn> | null = null
let tpValInput: ReturnType<typeof createNumInput> | null = null
let tpValControls: HTMLElement | null = null

let lossToggle: ReturnType<typeof createToggleBtn> | null = null
let lossValInput: ReturnType<typeof createNumInput> | null = null
let lossValControls: HTMLElement | null = null

// 추적 매도 UI 참조
let tsToggle: ReturnType<typeof createToggleBtn> | null = null
let tsStartValInput: ReturnType<typeof createNumInput> | null = null
let tsStartControls: HTMLElement | null = null
let tsDropValInput: ReturnType<typeof createNumInput> | null = null
let tsDropRow: HTMLElement | null = null

// 매도 주문 간격 UI 참조
let sellIntervalToggle: ReturnType<typeof createToggleBtn> | null = null
let sellIntervalInput: ReturnType<typeof createNumInput> | null = null
let sellIntervalControls: HTMLElement | null = null

/* ── 설정 동기화 ── */
function syncFromSettings(s: AppSettings): void {
  const r = s as Record<string, unknown>
  vals = { ...r }

  const act = document.activeElement

  // 익절
  const tpOn = !!r.tp_apply
  tpToggle?.setOn(tpOn)
  if (tpValInput && (!act || !tpValInput.el.contains(act))) tpValInput.setValue(Number(r.tp_val ?? 0))
  if (tpValControls) setDisabled(tpValControls, !tpOn)

  // 손절
  const lossOn = !!r.loss_apply
  lossToggle?.setOn(lossOn)
  if (lossValInput && (!act || !lossValInput.el.contains(act))) lossValInput.setValue(Number(r.loss_val ?? 0))
  if (lossValControls) setDisabled(lossValControls, !lossOn)

  // 추적 매도
  const tsOn = !!r.ts_apply
  tsToggle?.setOn(tsOn)
  if (tsStartValInput && (!act || !tsStartValInput.el.contains(act))) tsStartValInput.setValue(Number(r.ts_start_val ?? 0))
  if (tsDropValInput && (!act || !tsDropValInput.el.contains(act))) tsDropValInput.setValue(Number(r.ts_drop_val ?? 0))
  if (tsStartControls) setDisabled(tsStartControls, !tsOn)
  if (tsDropRow) setDisabled(tsDropRow, !tsOn)

  // 매도 주문 간격
  const sellIntervalOn = !!r.sell_interval_on
  sellIntervalToggle?.setOn(sellIntervalOn)
  if (sellIntervalInput && (!act || !sellIntervalInput.el.contains(act))) sellIntervalInput.setValue(Number(r.sell_interval_sec ?? 30))
  if (sellIntervalControls) {
    setDisabled(sellIntervalControls, !sellIntervalOn)
  }
}

/* ── mount 섹션 빌더 ── */
// mount() 80줄 → 섹션별 빌더로 분할 (P24)

function buildSellTypeSection(root: HTMLElement): void {
  root.appendChild(sectionTitle('매도 유형'))

  // 매도 주문 유형
  root.appendChild(createSettingRow('매도 주문 유형', createFixedValue('시장가')))

  // 익절 (토글 + 입력)
  tpValInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.tp_val); vals.tp_val = v; saveHelper!.autoSave('tp_val', v, () => { vals.tp_val = orig; tpValInput!.setValue(orig) }) }, step: 0.1, min: 0, max: 100, name: 'tp_val' })
  {
    const r = createToggleLabelControlsRow({
      labelText: '익절 (상승률 %)',
      infoText: '종목 상승률이 이 값 이상이면 익절 매도. 0~100%',
      toggleOn: false,
      onToggle: next => { vals.tp_apply = next; saveHelper!.saveImmediate({ tp_apply: next }) },
      controlsChild: tpValInput.el,
    })
    tpToggle = r.toggle; tpValControls = r.controls
    root.appendChild(r.el)
  }

  // 손절 (토글 + 입력)
  lossValInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.loss_val); vals.loss_val = v; saveHelper!.autoSave('loss_val', v, () => { vals.loss_val = orig; lossValInput!.setValue(orig) }) }, step: 0.1, min: 0, max: 100, name: 'loss_val' })
  {
    const r = createToggleLabelControlsRow({
      labelText: '손절 (하락률 %)',
      infoText: '종목 하락률이 이 값 이상이면 손절 매도. 0~100%',
      toggleOn: false,
      onToggle: next => { vals.loss_apply = next; saveHelper!.saveImmediate({ loss_apply: next }) },
      controlsChild: lossValInput.el,
    })
    lossToggle = r.toggle; lossValControls = r.controls
    root.appendChild(r.el)
  }

  // 추적 매도 (토글 + 시작값 한 줄, 하락값 별도 행)
  tsStartValInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.ts_start_val); vals.ts_start_val = v; saveHelper!.autoSave('ts_start_val', v, () => { vals.ts_start_val = orig; tsStartValInput!.setValue(orig) }) }, step: 0.1, min: 0, max: 100, name: 'ts_start_val' })
  tsDropValInput = createNumInput({ value: 0, onChange: v => { const orig = Number(vals.ts_drop_val); vals.ts_drop_val = v; saveHelper!.autoSave('ts_drop_val', v, () => { vals.ts_drop_val = orig; tsDropValInput!.setValue(orig) }) }, step: 0.1, min: 0, max: 100, name: 'ts_drop_val' })
  tsDropRow = createSettingRow('추적 고점대비 하락률 (%)', tsDropValInput.el, { infoText: '추적 시작 후 고점 대비 하락률이 이 값 이상이면 매도. 0~100%' })
  {
    const r = createToggleLabelControlsRow({
      labelText: '고점추적매도 (시작상승률%)',
      infoText: '고점 대비 하락 추적 매도. 시작 상승률 도달 시 추적 시작. 0~100%',
      toggleOn: false,
      onToggle: next => { vals.ts_apply = next; saveHelper!.saveImmediate({ ts_apply: next }) },
      controlsChild: tsStartValInput.el,
      extraDisableTargets: [tsDropRow],
    })
    tsToggle = r.toggle; tsStartControls = r.controls
    root.appendChild(r.el)
  }
  root.appendChild(tsDropRow)
}

function buildSellIntervalSection(root: HTMLElement): void {
  root.appendChild(sectionTitle('매도 주문 간격'))
  {
    sellIntervalInput = createNumInput({ value: 30, onChange: v => { const orig = Number(vals.sell_interval_sec); vals.sell_interval_sec = v; saveHelper!.autoSave('sell_interval_sec', v, () => { vals.sell_interval_sec = orig; sellIntervalInput!.setValue(orig) }) }, step: 5, min: 5, max: 300, name: 'sell_interval_sec' })
    const r = createToggleLabelControlsRow({
      labelText: '주문 간격',
      infoText: '매도 주문 사이 대기 시간. 5초 단위, 5~300초, 기본 30초. 손절 포함 모든 매도에 적용.',
      toggleOn: false,
      onToggle: next => { vals.sell_interval_on = next; saveHelper!.saveImmediate({ sell_interval_on: next }) },
      controlsChild: sellIntervalInput.el,
    })
    sellIntervalToggle = r.toggle; sellIntervalControls = r.controls
    root.appendChild(r.el)
  }
}

/* ── mount ── */
function mount(container: HTMLElement): void {
  const ctx = initSettingsPage(syncFromSettings)
  settingsMgr = ctx.settingsMgr
  saveHelper = ctx.saveHelper
  vals = {}

  const root = document.createElement('div')

  root.appendChild(createCardTitle('매도설정'))
  buildSellTypeSection(root)
  buildSellIntervalSection(root)

  container.appendChild(root)

  // 초기 설정 동기화 + 구독
  unsubSettings = startSettingsSubscription(settingsMgr, syncFromSettings)
}

/* ── unmount ── */
function unmount(): void {
  destroySettingsPage(unsubSettings, saveHelper, settingsMgr)
  unsubSettings = null; saveHelper = null; settingsMgr = null
  // 익절/손절
  tpToggle = null; tpValInput = null; tpValControls = null
  lossToggle = null; lossValInput = null; lossValControls = null
  // 추적 매도
  tsToggle = null; tsStartValInput = null; tsStartControls = null
  tsDropValInput = null; tsDropRow = null
  // 매도 주문 간격
  sellIntervalToggle = null; sellIntervalInput = null; sellIntervalControls = null
  vals = {}
}

export default { mount, unmount }
