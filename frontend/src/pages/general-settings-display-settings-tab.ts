// frontend/src/pages/general-settings-display-settings-tab.ts
// 일반설정 — 화면 설정 탭 (Step 2 신설, P21/P24)
// 자동매매 탭에서 이관: 실시간 현재가 플래시 효과 토글

import { createToggleBtn } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { FONT_WEIGHT } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, GS, state } from './general-settings-shared'

function buildUiFlashRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '실시간 현재가 플래시 효과'
  row.appendChild(label)
  state.uiFlashToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.ui_price_flash_on
    state.vals.ui_price_flash_on = next
    state.uiFlashToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ ui_price_flash_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.ui_price_flash_on = !next; state.uiFlashToggle!.setOn(!next) }
  }})
  row.appendChild(state.uiFlashToggle.el)
  return row
}

export function renderDisplaySettingsTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(sectionTitle('화면 표시'))
  container.appendChild(buildUiFlashRow(state))
  container.appendChild(createDescText('실시간 시세 변경 시 노란색 플래시 깜빡임 효과 적용 여부'))
}

export function syncDisplaySettingsTab(r: Record<string, unknown>): void {
  state.uiFlashToggle?.setOn(r.ui_price_flash_on !== false)
}
