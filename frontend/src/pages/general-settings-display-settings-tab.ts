// frontend/src/pages/general-settings-display-settings-tab.ts
// 일반설정 — 화면 설정 탭 (Step 2 신설, P21/P24)
// 자동매매 탭에서 이관: 실시간 현재가 플래시 효과 토글

import { createSettingToggleRow } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, state } from './general-settings-shared'

function buildUiFlashRow(state: GeneralSettingsState): HTMLElement {
  const r = createSettingToggleRow({
    label: '실시간 현재가 플래시 효과',
    toggleOn: false,
    onToggle: async next => {
      state.vals.ui_price_flash_on = next
      const res = await state.settingsMgr!.saveSection({ ui_price_flash_on: next })
      toastResult(res)
      if (!res.ok) { state.vals.ui_price_flash_on = !next; r.toggle.setOn(!next) }
    },
  })
  state.uiFlashToggle = r.toggle
  return r.el
}

export function renderDisplaySettingsTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(sectionTitle('화면 표시'))
  container.appendChild(buildUiFlashRow(state))
  container.appendChild(createDescText('실시간 시세 변경 시 노란색 플래시 깜빡임 효과 적용 여부'))
}

export function syncDisplaySettingsTab(r: Record<string, unknown>): void {
  state.uiFlashToggle?.setOn(r.ui_price_flash_on !== false)
}
