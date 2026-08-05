// frontend/src/pages/general-settings-telegram-tab.ts
// 일반설정 — 텔레그램 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createTextInput, createSettingToggleRow } from '../components/common/setting-row'
import { createActionButton } from '../components/common/button'
import { createDataTable, type ColumnDef } from '../components/common/data-table'
import { fixedTableOptions } from '../components/common/table-options'
import { extractDirty, MASKED_FIELDS } from '../settings'
import { toastResult, showSaveToast } from '../components/common/toast'
import { FONT_WEIGHT, COLOR, RADIUS } from '../components/common/ui-styles'
import {
  type GeneralSettingsState, GS,
  SECRET_FIELD_STATUS_MESSAGES, mapEncryptionErrorMessage,
  currentSecretFieldStatus, isEncryptionBlockingSave,
} from './general-settings-shared'

const TELE_STR_KEYS = ['telegram_chat_id', 'telegram_bot_token_test', 'telegram_bot_token_real'] as const
const TELE_LABELS: Record<string, string> = { telegram_chat_id: '채팅 ID', telegram_bot_token_test: '테스트 봇 토큰', telegram_bot_token_real: '실전 봇 토큰' }
// B21-01 세션7: 텔레그램 민감 필드 (상태 배지 표시 대상 — chat_id는 비민감이므로 제외)
const TELE_SECRET_KEYS = ['telegram_bot_token_test', 'telegram_bot_token_real'] as const

function buildTeleToggleRow(state: GeneralSettingsState): HTMLElement {
  const r = createSettingToggleRow({
    label: '텔레그램 알림',
    toggleOn: false,
    onToggle: async next => {
      state.vals.tele_on = next
      const res = await state.settingsMgr!.saveSection({ tele_on: next })
      toastResult(res)
      if (!res.ok) { state.vals.tele_on = !next; r.toggle.setOn(!next) }
    },
  })
  state.teleToggle = r.toggle
  return r.el
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

    // B21-01 세션7: 민감 필드 상태 배지 (설계 7.2 — chat_id는 비민속이므로 제외)
    if (TELE_SECRET_KEYS.includes(k as typeof TELE_SECRET_KEYS[number])) {
      const status = currentSecretFieldStatus(k)
      if (status && status !== 'EMPTY' && status !== 'ENCRYPTED') {
        const badge = createTeleStatusBadge(status)
        state.teleStatusBadges[k] = badge
        container.appendChild(badge)
      }
    }
  }
}

function createTeleStatusBadge(status: string): HTMLElement {
  const badge = document.createElement('div')
  const msg = SECRET_FIELD_STATUS_MESSAGES[status as keyof typeof SECRET_FIELD_STATUS_MESSAGES]
  Object.assign(badge.style, {
    padding: '4px 10px', fontSize: '11px', color: msg?.color ?? COLOR.tertiary,
    background: msg?.bg ?? 'transparent', borderRadius: RADIUS.xs, marginBottom: '4px',
  })
  badge.textContent = msg?.text ?? ''
  badge.dataset.status = status
  return badge
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
      // B21-01 세션7: 구조화 오류 코드 매핑 (설계 7.3)
      if (res.ok) {
        showSaveToast('saved')
      } else {
        showSaveToast('error', mapEncryptionErrorMessage(res.errorCode, res.error))
      }
      saveBtn.textContent = '저장'
      saveBtn.disabled = isEncryptionBlockingSave()
    },
  })
  // B21-01 세션7: 키 없음 상태 시 저장 버튼 사전 비활성화 (설계 7.3)
  saveBtn.disabled = isEncryptionBlockingSave()
  state.teleSaveBtn = saveBtn
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
    { cmd: '자동', desc: '자동매매 ON/OFF' }, { cmd: '매수', desc: '매수 체결 내역 (최근 10건)' },
    { cmd: '매도', desc: '매도 체결 내역 (최근 10건)' }, { cmd: '상태', desc: '엔진·스케줄·스위치 + 리스크 상태 (현황)' },
    { cmd: '잔고', desc: '계좌 현황 (계좌)' }, { cmd: '당일', desc: '당일 실현 손익' },
    { cmd: '5일', desc: '최근 5거래일 실현 손익' }, { cmd: '당월', desc: '당월 실현 손익' },
    { cmd: '누적', desc: '누적 실현 손익' }, { cmd: '업종', desc: '업종 상위 5 (가산점 + 종목 5개)' },
    { cmd: '후보', desc: '매수 후보 (가드 통과) 10위 + 대비/등락률/가산점' }, { cmd: '도움말', desc: '명령어 목록' },
  ]
  const tableWrap = document.createElement('div')
  tableWrap.style.marginTop = '16px'
  const table = createDataTable<CommandRow>(
    fixedTableOptions<CommandRow>({ columns: COMMAND_COLUMNS, stickyHeader: false }),
  )
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

/** B21-01 세션7: 텔레그램 탭 암호화 상태 동기화 — 저장 버튼 활성화/비활성화 + 배지 업데이트. */
export function syncTelegramEncryptionStatus(state: GeneralSettingsState): void {
  if (state.teleSaveBtn) {
    state.teleSaveBtn.disabled = isEncryptionBlockingSave()
  }
  for (const k of TELE_SECRET_KEYS) {
    const status = currentSecretFieldStatus(k)
    const existing = state.teleStatusBadges[k]
    if (status && status !== 'EMPTY' && status !== 'ENCRYPTED') {
      if (existing) {
        const msg = SECRET_FIELD_STATUS_MESSAGES[status]
        existing.style.color = msg.color
        existing.style.background = msg.bg
        existing.textContent = msg.text
        existing.dataset.status = status
      }
    } else if (existing) {
      existing.style.display = 'none'
    }
  }
}
