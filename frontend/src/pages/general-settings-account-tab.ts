// frontend/src/pages/general-settings-account-tab.ts
// 일반설정 — 투자모드 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.

import { createRadioGroup, createMoneyInput } from '../components/common/setting-row'
import { sectionTitle, createDescText } from '../components/common/settings-common'
import { createActionButton } from '../components/common/button'
import { showConfirmDialog, showAlertDialog, showCustomDialog } from '../components/common/dialog'
import { showSaveToast } from '../components/common/toast'
import { FONT_SIZE, COLOR, RADIUS } from '../components/common/ui-styles'
import { api } from '../api/client'
import { applyTestDataResetCompleted } from '../stores/uiStore'
import { type GeneralSettingsState, GS } from './general-settings-shared'

export function renderAccountTab(state: GeneralSettingsState, container: HTMLElement): void {
  // 투자모드 선택 (중앙정렬)
  state.tradeModeRadioGroup = createRadioGroup({
    items: [
      { value: 'virtual', label: '가상매매' },
      { value: 'live', label: '실전매매' },
    ],
    name: 'trade-mode-acct',
    value: String(state.vals.trade_mode ?? 'virtual'),
    onChange: (v) => handleTradeMode(state, v),
  })
  Object.assign(state.tradeModeRadioGroup.el.style, { justifyContent: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  container.appendChild(state.tradeModeRadioGroup.el)

  // 가상 예수금 (항상 렌더링, display로 토글)
  const virtualTitle = sectionTitle('가상 투자금 (가상매매 전용)')
  state.testVirtualSection = document.createElement('div')
  const innerSection = renderTestVirtualSection(state)
  state.testVirtualSection.appendChild(virtualTitle)
  state.testVirtualSection.appendChild(innerSection)
  state.testVirtualSection.style.display = state.vals.trade_mode === 'virtual' ? '' : 'none'
  container.appendChild(state.testVirtualSection)
}

function handleTradeMode(state: GeneralSettingsState, val: string): void {
  if (val === state.vals.trade_mode) return

  if (val === 'live') {
    const container = document.createElement('div')
    Object.assign(container.style, { fontSize: FONT_SIZE.label, color: COLOR.code, lineHeight: '1.6' })

    const checkboxTexts = [
      '실제 증권사 계좌의 자금이 사용됩니다',
      '자동 매매로 인해 손실이 발생할 수 있습니다',
      '실제 주문이 증권사 서버로 전송됩니다',
    ]
    const checkboxes: HTMLInputElement[] = []
    for (const text of checkboxTexts) {
      const row = document.createElement('label')
      Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '8px', margin: '8px 0', cursor: 'pointer' })
      const cb = document.createElement('input')
      cb.type = 'checkbox'
      Object.assign(cb.style, { margin: '0', cursor: 'pointer' })
      const label = document.createElement('span')
      Object.assign(label.style, { fontSize: FONT_SIZE.label, color: COLOR.code })
      label.textContent = text
      row.appendChild(cb)
      row.appendChild(label)
      container.appendChild(row)
      checkboxes.push(cb)
    }

    const overlay = showCustomDialog({
      title: '실전매매 모드 전환',
      content: container,
      actions: [
        { label: '취소', onClick: () => {} },
        { label: '전환', onClick: async () => {
          state.vals.trade_mode = 'live'
          const res = await state.settingsMgr!.saveSection({ trade_mode: 'live' })
          if (!res.ok) state.vals.trade_mode = 'virtual'
          syncTradeMode(state)
        }, variant: 'danger' },
      ]
    })

    const convertBtn = Array.from(overlay.querySelectorAll('button')).find(b => b.textContent === '전환')
    if (convertBtn) {
      convertBtn.disabled = true
      convertBtn.style.opacity = '0.4'
      convertBtn.style.cursor = 'not-allowed'
      const updateConvertBtn = () => {
        const allChecked = checkboxes.every(cb => cb.checked)
        convertBtn.disabled = !allChecked
        convertBtn.style.opacity = allChecked ? '' : '0.4'
        convertBtn.style.cursor = allChecked ? 'pointer' : 'not-allowed'
      }
      for (const cb of checkboxes) cb.addEventListener('change', updateConvertBtn)
    }

    return
  }

  state.vals.trade_mode = val
  state.settingsMgr?.saveSection({ trade_mode: val }).then(res => {
    if (!res.ok) state.vals.trade_mode = 'virtual'
    syncTradeMode(state)
  })
}

export function syncTradeMode(state: GeneralSettingsState): void {
  // 라디오 버튼 상태 업데이트
  state.tradeModeRadioGroup?.setValue(String(state.vals.trade_mode ?? 'virtual'))
  // 가상 예수금 섹션 표시/숨김
  if (state.testVirtualSection) {
    state.testVirtualSection.style.display = state.vals.trade_mode === 'virtual' ? '' : 'none'
  }
}

function buildTestVirtualInputRow(state: GeneralSettingsState, inputState: { inputAmount: number }): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '8px', padding: GS.rowPad })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, whiteSpace: 'nowrap' })
  label.textContent = '금액입력:'
  row.appendChild(label)

  state.depositInput = createMoneyInput({ value: inputState.inputAmount, onChange: v => { inputState.inputAmount = Math.max(0, v) }, unit: 'manwon', name: 'deposit_amount' })
  row.appendChild(state.depositInput.el)

  const chargeBtn = createActionButton({
    label: '투자금충전', variant: 'secondary', padding: '7px 12px', borderRadius: RADIUS.xs, fontSize: GS.label,
    onClick: async () => {
      if (inputState.inputAmount <= 0) return
      try {
        const res = await api.settlementCharge(inputState.inputAmount)
        showSaveToast(res.ok ? 'saved' : 'error')
      } catch {
        showSaveToast('error')
      }
    },
  })
  row.appendChild(chargeBtn)
  return row
}

function buildTestVirtualSaveRow(state: GeneralSettingsState, inputState: { inputAmount: number }): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'flex-end', margin: GS.saveMargin })
  const btn = createActionButton({
    label: '투자금 변경', variant: 'secondary', padding: '7px 16px', borderRadius: RADIUS.xs, fontSize: GS.label,
    onClick: async () => {
      const res = await state.settingsMgr!.saveSection({ virtual_deposit: inputState.inputAmount, virtual_balance: inputState.inputAmount })
      showSaveToast(res.ok ? 'saved' : 'error')
    },
  })
  row.appendChild(btn)
  return row
}

function buildTestVirtualInfoWrap(state: GeneralSettingsState): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { borderTop: '1px solid ' + COLOR.borderLight, padding: GS.rowPad })
  const depRow = document.createElement('div')
  Object.assign(depRow.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, fontSize: GS.label })
  depRow.innerHTML = '<span>기본투자금</span>'
  state.depositDisplay = document.createElement('span')
  state.depositDisplay.textContent = `${(Number(state.vals.virtual_deposit) || 0).toLocaleString()}원`
  depRow.appendChild(state.depositDisplay)
  wrap.appendChild(depRow)
  return wrap
}

function buildTestVirtualResetWrap(): HTMLElement {
  const wrap = document.createElement('div')
  Object.assign(wrap.style, { borderTop: '1px solid ' + COLOR.borderLight, padding: GS.rowPad })
  const resetBtn = createActionButton({
    label: '테스트 데이터 전체 초기화', variant: 'danger', padding: '8px 18px', borderRadius: RADIUS.xs, fontSize: GS.label,
    onClick: async () => {
      const confirmed = await showConfirmDialog({
        title: '테스트 데이터 초기화',
        message: '테스트 데이터를 전체 초기화하시겠습니까?\n가상 보유종목, 매매 이력, 투자금이 모두 초기화됩니다.',
        isDanger: true
      })
      if (!confirmed) return
      try {
        await api.resetTestData()
        applyTestDataResetCompleted()
        showSaveToast('saved')
      } catch {
        await showAlertDialog({ title: '오류', message: '초기화 실패' })
      }
    },
  })
  wrap.appendChild(resetBtn)
  return wrap
}

function renderTestVirtualSection(state: GeneralSettingsState): HTMLElement {
  const wrap = document.createElement('div')
  const disabled = state.vals.trade_mode !== 'virtual'
  if (disabled) { wrap.style.opacity = '0.4'; wrap.style.pointerEvents = 'none' }

  const inputState = { inputAmount: Number(state.vals.virtual_deposit) || 0 }
  wrap.appendChild(buildTestVirtualInputRow(state, inputState))
  wrap.appendChild(buildTestVirtualSaveRow(state, inputState))
  wrap.appendChild(createDescText('누적투자금과 주문가능금액을 입력한 금액으로 변경합니다. 데이터 초기화 시에도 이 금액이 기본값으로 사용됩니다.'))
  wrap.appendChild(buildTestVirtualInfoWrap(state))
  wrap.appendChild(buildTestVirtualResetWrap())
  return wrap
}
