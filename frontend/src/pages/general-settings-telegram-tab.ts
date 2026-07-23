// frontend/src/pages/general-settings-telegram-tab.ts
// 일반설정 — 텔레그램 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createToggleBtn, createTextInput } from '../components/common/setting-row'
import { createActionButton } from '../components/common/button'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { extractDirty, MASKED_FIELDS } from '../settings'
import { toastResult, showSaveToast } from '../components/common/toast'
import { FONT_WEIGHT } from '../components/common/ui-styles'
import { type GeneralSettingsState, GS } from './general-settings-shared'

const TELE_STR_KEYS = ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real'] as const
const TELE_LABELS: Record<string, string> = { telegram_chat_id: '채팅 ID', telegram_bot_token_test: '테스트 봇 토큰', telegram_bot_token_real: '실전 봇 토큰' }

function buildTeleToggleRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '텔레그램 알림'
  row.appendChild(label)
  state.teleToggle = createToggleBtn({ on: false, onClick: async () => {
    const next = !state.vals.tele_on; state.vals.tele_on = next; state.teleToggle!.setOn(next)
    const res = await state.settingsMgr!.saveSection({ tele_on: next })
    toastResult(res)
    if (!res.ok) { state.vals.tele_on = !next; state.teleToggle!.setOn(!next) }
  }})
  row.appendChild(state.teleToggle.el)
  return row
}

function buildTeleInputRows(state: GeneralSettingsState, container: HTMLElement): void {
  for (const k of TELE_STR_KEYS) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
    lbl.textContent = TELE_LABELS[k]
    row.appendChild(lbl)
    const input = createTextInput({
      value: String(state.vals[k] || ''),
      type: MASKED_FIELDS.has(k) ? 'password' : 'text',
      name: k,
      style: { padding: GS.inputPad } as Partial<CSSStyleDeclaration>,
    })
    state.teleInputs[k] = input
    row.appendChild(input)
    container.appendChild(row)
  }
}

function buildTeleSaveRow(state: GeneralSettingsState): HTMLElement {
  const saveRow = document.createElement('div')
  Object.assign(saveRow.style, { margin: GS.saveMargin, textAlign: 'right' })
  const saveBtn = createActionButton({
    label: '저장', variant: 'secondary', padding: GS.btnPad, fontSize: GS.label,
    onClick: async () => {
      const orig: Record<string, unknown> = {}
      const current: Record<string, unknown> = {}
      for (const k of TELE_STR_KEYS) {
        orig[k] = state.vals[k]
        current[k] = state.teleInputs[k]?.value ?? state.vals[k]
      }
      const dirty = extractDirty(orig, current, TELE_STR_KEYS as unknown as string[])
      saveBtn.textContent = '저장 중...'
      saveBtn.disabled = true
      const res = await state.settingsMgr!.saveSection(dirty)
      showSaveToast(res.ok ? 'saved' : 'error')
      saveBtn.textContent = '저장'
      saveBtn.disabled = false
    },
  })
  saveRow.appendChild(saveBtn)
  return saveRow
}

function buildTeleCommandTable(): HTMLElement {
  interface CommandRow { cmd: string; desc: string }
  const COMMAND_COLUMNS: ColumnDef<CommandRow>[] = [
    { key: 'cmd', label: '명령어', align: 'center', type: 'cmd', render: r => r.cmd },
    { key: 'desc', label: '설명', align: 'left', type: 'desc', render: r => r.desc },
  ]
  const commands: CommandRow[] = [
    { cmd: '자동', desc: '자동매매 ON/OFF' }, { cmd: '매수', desc: '자동매수 ON/OFF' },
    { cmd: '매도', desc: '자동매도 ON/OFF' }, { cmd: '상태', desc: '현재 설정 + 계좌 요약' },
    { cmd: '잔고', desc: '계좌 현황' }, { cmd: '업종', desc: '업종 분석 요약' },
    { cmd: '후보', desc: '매수후보 1~10순위' }, { cmd: '휴일', desc: '공휴일 자동 차단 ON/OFF' },
    { cmd: '도움말', desc: '명령어 목록' },
  ]
  const tableWrap = document.createElement('div')
  tableWrap.style.marginTop = '16px'
  const table = createDataTable<CommandRow>({ columns: COMMAND_COLUMNS, stickyHeader: false })
  table.updateRows(commands)
  tableWrap.appendChild(table.el)
  return tableWrap
}

export function renderTelegramTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(buildTeleToggleRow(state))
  buildTeleInputRows(state, container)
  container.appendChild(buildTeleSaveRow(state))
  container.appendChild(buildTeleCommandTable())
}
