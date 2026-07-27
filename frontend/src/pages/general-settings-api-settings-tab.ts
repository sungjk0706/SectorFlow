// frontend/src/pages/general-settings-api-settings-tab.ts
// 일반설정 — API 설정 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createRadioGroup } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { createActionButton } from '../components/common/button'
import { showConfirmDialog, showAlertDialog } from '../components/common/dialog'
import { FONT_WEIGHT, COLOR, RADIUS, createDarkInput } from '../components/common/ui-styles'
import { extractDirty } from '../settings'
import { focusNext } from '../components/common/setting-row'
import {
  type GeneralSettingsState, GS, BROKER_NAMES,
  SECRET_FIELD_STATUS_MESSAGES, mapEncryptionErrorMessage,
  currentSecretFieldStatus, isEncryptionBlockingSave,
} from './general-settings-shared'

export function renderApiSettingsTab(state: GeneralSettingsState, container: HTMLElement): void {
  // Step 2A: 주 사용 증권사 선택 (통신망 전환)
  container.appendChild(sectionTitle('주 사용 증권사'))
  state.brokerRadioGroup = createRadioGroup({
    items: [
      { value: 'kiwoom', label: '키움증권' },
      { value: 'ls', label: 'LS증권' },
    ],
    name: 'primary-broker',
    value: String(state.vals.broker ?? 'kiwoom'),
    onChange: (v) => handleBrokerChange(state, v as 'kiwoom' | 'ls'),
  })
  Object.assign(state.brokerRadioGroup.el.style, { justifyContent: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  container.appendChild(state.brokerRadioGroup.el)

  container.appendChild(createDescText('선택한 증권사로 시스템 전체 통신망(시세, 계좌, 주문)이 전환됩니다. 엔진이 재기동되어 실시간 연결이 잠시 끊깁니다.', { textAlign: 'center' }))

  // Step 2B: API 키 보관용 탭 (키움 API / LS API)
  const apiTabBar = document.createElement('div')
  Object.assign(apiTabBar.style, { display: 'flex', gap: '8px', marginBottom: '12px' })

  const tabConfigs = [
    { id: 'kiwoom', label: '키움 API' },
    { id: 'ls', label: 'LS API' },
  ] as const

  for (const tab of tabConfigs) {
    const btn = document.createElement('button')
    btn.type = 'button'
    const isActive = state.activeApiTab === tab.id
    Object.assign(btn.style, {
      padding: '6px 12px', cursor: 'pointer', border: '1px solid ' + COLOR.borderDark, background: isActive ? COLOR.hoverBg : COLOR.white,
      borderRadius: RADIUS.xs, fontSize: GS.label, color: isActive ? COLOR.neutral : COLOR.tertiary,
    })
    btn.textContent = tab.label
    btn.addEventListener('click', () => { state.activeApiTab = tab.id; refreshApiTabContent(state) })
    state.apiTabButtons[tab.id] = btn
    apiTabBar.appendChild(btn)
  }
  container.appendChild(apiTabBar)

  // API 필드 컨테이너
  const apiFieldsContainer = document.createElement('div')
  apiFieldsContainer.id = 'api-fields-container'
  container.appendChild(apiFieldsContainer)

  // 초기 렌더링
  renderApiFields(state, apiFieldsContainer)
}

const API_FIELDS_CONFIG: Record<string, { key: string; label: string; type: 'password' | 'text' }[]> = {
  kiwoom: [
    { key: 'kiwoom_app_key', label: '앱키', type: 'password' },
    { key: 'kiwoom_app_secret', label: '앱시크릿', type: 'password' },
    { key: 'kiwoom_account_no', label: '계좌번호', type: 'text' },
  ],
  ls: [
    { key: 'ls_app_key', label: '앱키', type: 'password' },
    { key: 'ls_app_secret', label: '앱시크릿', type: 'password' },
    { key: 'ls_account_no', label: '계좌번호', type: 'text' },
  ],
}

function buildApiInputRows(state: GeneralSettingsState, container: HTMLElement, fields: { key: string; label: string; type: 'password' | 'text' }[]): void {
  for (const field of fields) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
    const lbl = document.createElement('span')
    Object.assign(lbl.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, flex: '1' })
    lbl.textContent = field.label
    row.appendChild(lbl)

    const input = createDarkInput(field.type)
    input.value = String(state.vals[field.key] || '')
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); focusNext(input) }
    })
    state.apiKeyInputs[field.key] = input
    row.appendChild(input)
    container.appendChild(row)

    // B21-01 세션7: 민감 필드 상태 배지 (설계 7.2 — 필드 영역 구체적 상태 안내)
    const status = currentSecretFieldStatus(field.key)
    if (status && status !== 'EMPTY' && status !== 'ENCRYPTED') {
      const badge = createSecretStatusBadge(status)
      state.apiStatusBadges[field.key] = badge
      container.appendChild(badge)
    }
  }
}

function createSecretStatusBadge(status: string): HTMLElement {
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

function buildApiSaveRow(state: GeneralSettingsState, fields: { key: string }[]): HTMLElement {
  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, { textAlign: 'right', margin: GS.saveMargin })
  const saveBtn = createActionButton({
    label: '저장', variant: 'warning', padding: GS.btnPad, borderRadius: RADIUS.xs, fontSize: GS.label,
    onClick: async () => {
      const keys = fields.map(f => f.key)
      const orig: Record<string, unknown> = {}
      const current: Record<string, unknown> = {}
      for (const k of keys) {
        orig[k] = state.vals[k]
        current[k] = state.apiKeyInputs[k]?.value ?? state.vals[k]
      }
      const dirty = extractDirty(orig, current, keys)
      let dataToSave: Record<string, unknown>
      if (Object.keys(dirty).length === 0) {
        const confirmed = await showConfirmDialog({
          title: '변경 사항 없음',
          message: '입력하신 값이 기존과 동일합니다.\n그래도 저장하시겠습니까?',
          confirmText: '저장',
          cancelText: '취소',
        })
        if (!confirmed) return
        dataToSave = current
      } else {
        dataToSave = dirty
      }
      saveBtn.textContent = '저장 중...'
      saveBtn.disabled = true
      const res = await state.settingsMgr!.saveSection(dataToSave)
      if (res.ok) {
        await showAlertDialog({
          title: '저장 완료',
          message: '✅ 저장이 완료되었습니다.',
          confirmText: '확인',
        })
      } else {
        await showAlertDialog({
          title: '저장 실패',
          message: `❌ 저장 실패: ${mapEncryptionErrorMessage(res.errorCode, res.error)}`,
          confirmText: '확인',
        })
      }
      saveBtn.textContent = '저장'
      saveBtn.disabled = isEncryptionBlockingSave()
    },
  })
  // B21-01 세션7: 키 없음 상태 시 저장 버튼 사전 비활성화 (설계 7.3 — 서버 검증이 최종 방어선)
  saveBtn.disabled = isEncryptionBlockingSave()
  state.apiSaveBtn = saveBtn
  btnRow.appendChild(saveBtn)
  return btnRow
}

function renderApiFields(state: GeneralSettingsState, container: HTMLElement): void {
  container.innerHTML = ''
  const fields = API_FIELDS_CONFIG[state.activeApiTab] || []
  buildApiInputRows(state, container, fields)
  container.appendChild(buildApiSaveRow(state, fields))
}

function refreshApiTabContent(state: GeneralSettingsState): void {
  const container = document.getElementById('api-fields-container')
  if (container) {
    // 탭 버튼 스타일 업데이트
    for (const [id, btn] of Object.entries(state.apiTabButtons)) {
      const isActive = id === state.activeApiTab
      Object.assign(btn.style, {
        background: isActive ? COLOR.hoverBg : COLOR.white,
        color: isActive ? COLOR.neutral : COLOR.tertiary,
      })
    }
    renderApiFields(state, container)
  }
}

async function handleBrokerChange(state: GeneralSettingsState, val: 'kiwoom' | 'ls'): Promise<void> {
  if (val === state.vals.broker || state.brokerSaving) return

  const prev = String(state.vals.broker ?? 'kiwoom')
  const prevName = BROKER_NAMES[prev] ?? prev
  const nextName = BROKER_NAMES[val] ?? val

  const message =
    '주 사용 증권사를 변경합니다.\n\n' +
    `변경 전: ${prevName}\n` +
    `변경 후: ${nextName}\n\n` +
    '수행될 작업:\n' +
    '  • 기존 증권사 연결 해제\n' +
    '  • 기존 인증 토큰 폐기\n' +
    '  • 거래 엔진 재기동\n' +
    '  • 새 증권사 연결 및 인증\n\n' +
    '확인을 누르면 즉시 실행되며, 실시간 연결이 잠시 끊깁니다.'

  const confirmed = await showConfirmDialog({
    title: '주 사용 증권사 변경',
    message,
    confirmText: '확인',
    cancelText: '취소',
  })

  if (!confirmed) {
    // 취소/Escape/외부클릭 — 라디오를 원래 값으로 복원
    syncBrokerRadios(state)
    return
  }

  // 확인 — 기존 변경 로직 그대로 진행
  state.brokerSaving = true
  const prevBroker = state.vals.broker
  state.settingsMgr?.saveSection({ broker: val }).then(res => {
    if (res.ok) {
      state.vals.broker = val
    } else {
      state.vals.broker = prevBroker
    }
    state.brokerSaving = false
    syncBrokerRadios(state)
  })
}

export function syncBrokerRadios(state: GeneralSettingsState): void {
  state.brokerRadioGroup?.setValue(String(state.vals.broker ?? 'kiwoom'))
  state.brokerRadioGroup?.setDisabled(state.brokerSaving)
}

/** B21-01 세션7: API 탭 암호화 상태 동기화 — 저장 버튼 활성화/비활성화 + 배지 업데이트. */
export function syncApiEncryptionStatus(state: GeneralSettingsState): void {
  // 저장 버튼 — 키 없음 상태 시 비활성화 (설계 7.3)
  if (state.apiSaveBtn) {
    state.apiSaveBtn.disabled = isEncryptionBlockingSave()
  }
  // 필드별 배지 — 현재 활성 서브탭 필드에 한해 업데이트
  const fields = API_FIELDS_CONFIG[state.activeApiTab] || []
  for (const field of fields) {
    const status = currentSecretFieldStatus(field.key)
    const existing = state.apiStatusBadges[field.key]
    if (status && status !== 'EMPTY' && status !== 'ENCRYPTED') {
      if (existing) {
        const msg = SECRET_FIELD_STATUS_MESSAGES[status]
        existing.style.color = msg.color
        existing.style.background = msg.bg
        existing.textContent = msg.text
        existing.dataset.status = status
      }
    } else if (existing) {
      // 상태가 해제됨(정상 저장 후 ENCRYPTED/EMPTY) — 배지 숨김
      existing.style.display = 'none'
    }
  }
}
