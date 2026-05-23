// frontend/src/pages/sell-settings.ui.ts
// 매도설정 카드 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createSettingRow, createNumInput, createToggleBtn, createFixedValue } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import { createTimePairInput, type TimePairInputHandle } from '../components/common/time-pair-input'
import { createCardHeader } from '../components/common/card-header'
import { createGlobalWsBadge } from '../settings'

// ── Props 타입 정의 ──

export interface SellSettingsProps {
  // 자동매도 설정
  autoSellOn: boolean
  sellTimeStart: string
  sellTimeEnd: string
  
  // 익절
  tpApply: boolean
  tpVal: number
  
  // 손절
  lossApply: boolean
  lossVal: number
  
  // 추적 매도
  tsApply: boolean
  tsStartVal: number
  tsDropVal: number
  
  // 실시간 상태
  wsSubscribed: boolean
  
  // 이벤트 핸들러 (UI 전용 상태 변경)
  onAutoSellToggle: (on: boolean) => void
  onTimePairChange: (start: string, end: string) => void
  onTpToggle: (on: boolean) => void
  onTpValChange: (value: number) => void
  onLossToggle: (on: boolean) => void
  onLossValChange: (value: number) => void
  onTsToggle: (on: boolean) => void
  onTsStartValChange: (value: number) => void
  onTsDropValChange: (value: number) => void
}

function setRowDisabled(row: HTMLElement | null, disabled: boolean): void {
  if (!row) return
  row.style.opacity = disabled ? '0.4' : '1'
  row.style.pointerEvents = disabled ? 'none' : 'auto'
}

/* ── 컴포넌트 생성 함수 ── */

export function createSellSettingsCard(props: SellSettingsProps): { el: HTMLElement; update: (newProps: SellSettingsProps) => void; destroy: () => void } {
  const root = document.createElement('div')
  
  // 토글 참조
  let wsBadge: HTMLElement | null = null
  let autoSellToggle: ReturnType<typeof createToggleBtn> | null = null
  let timePairHandle: TimePairInputHandle | null = null
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

  // 제목 + WS 상태 배지
  wsBadge = createGlobalWsBadge()
  const headerRow = createCardHeader('매도 설정', wsBadge)
  root.appendChild(headerRow)

  // 자동매도 토글 + TimePairInput (1행)
  const autoRow = document.createElement('div')
  Object.assign(autoRow.style, { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', padding: '4px 0' })

  const toggleLabel = document.createElement('span')
  Object.assign(toggleLabel.style, { fontSize: FONT_SIZE.label, fontWeight: FONT_WEIGHT.normal, whiteSpace: 'nowrap' })
  toggleLabel.textContent = '자동매도'

  autoSellToggle = createToggleBtn({
    on: props.autoSellOn,
    onClick: () => {
      props.onAutoSellToggle(!props.autoSellOn)
    },
  })

  const startTime = props.sellTimeStart
  const endTime = props.sellTimeEnd
  
  const { el: tpWrap, handle: handle } = createTimePairInput(
    startTime,
    endTime,
    (start, end) => {
      props.onTimePairChange(start, end)
    }
  )
  timePairHandle = handle
  tpWrap.style.marginLeft = 'auto'

  autoRow.appendChild(toggleLabel)
  autoRow.appendChild(autoSellToggle.el)
  autoRow.appendChild(tpWrap)
  root.appendChild(autoRow)

  // 익절 / 손절 / 추적 매도 섹션
  root.appendChild(sectionTitle('매도 유형'))

  // 매도 주문 유형
  root.appendChild(createSettingRow('매도 주문 유형', createFixedValue('시장가')))

  // 익절
  tpToggle = createToggleBtn({ on: props.tpApply, onClick: () => {
    props.onTpToggle(!props.tpApply)
  }})
  root.appendChild(createSettingRow('익절', tpToggle.el))

  tpValInput = createNumInput({ value: props.tpVal, onChange: props.onTpValChange, step: 0.1, name: 'tp_val' })
  tpValRow = createSettingRow('익절 상승률 (%)', tpValInput.el)
  root.appendChild(tpValRow)

  // 손절
  lossToggle = createToggleBtn({ on: props.lossApply, onClick: () => {
    props.onLossToggle(!props.lossApply)
  }})
  root.appendChild(createSettingRow('손절', lossToggle.el))

  lossValInput = createNumInput({ value: props.lossVal, onChange: props.onLossValChange, step: 0.1, name: 'loss_val' })
  lossValRow = createSettingRow('손절 하락률 (%)', lossValInput.el)
  root.appendChild(lossValRow)

  // 추적 매도
  tsToggle = createToggleBtn({ on: props.tsApply, onClick: () => {
    props.onTsToggle(!props.tsApply)
  }})
  root.appendChild(createSettingRow('고점 추적 매도(Trailing Stop)', tsToggle.el))

  tsStartValInput = createNumInput({ value: props.tsStartVal, onChange: props.onTsStartValChange, step: 0.1, name: 'ts_start_val' })
  tsStartRow = createSettingRow('추적 시작 상승률 (%)', tsStartValInput.el)
  root.appendChild(tsStartRow)

  tsDropValInput = createNumInput({ value: props.tsDropVal, onChange: props.onTsDropValChange, step: 0.1, name: 'ts_drop_val' })
  tsDropRow = createSettingRow('추적 고점대비 하락률 (%)', tsDropValInput.el)
  root.appendChild(tsDropRow)

  // 초기 상태 설정
  setRowDisabled(tpValRow, !props.tpApply)
  setRowDisabled(lossValRow, !props.lossApply)
  setRowDisabled(tsStartRow, !props.tsApply)
  setRowDisabled(tsDropRow, !props.tsApply)

  // Props 업데이트 함수
  function update(newProps: SellSettingsProps): void {
    Object.assign(props, newProps)
    
    // 입력 값 동기화
    autoSellToggle?.setOn(props.autoSellOn)
    if (timePairHandle) {
      timePairHandle.setValue(props.sellTimeStart, props.sellTimeEnd)
      timePairHandle.setEnabled(props.autoSellOn)
    }
    
    tpToggle?.setOn(props.tpApply)
    tpValInput?.setValue(props.tpVal)
    setRowDisabled(tpValRow, !props.tpApply)
    
    lossToggle?.setOn(props.lossApply)
    lossValInput?.setValue(props.lossVal)
    setRowDisabled(lossValRow, !props.lossApply)
    
    tsToggle?.setOn(props.tsApply)
    tsStartValInput?.setValue(props.tsStartVal)
    tsDropValInput?.setValue(props.tsDropVal)
    setRowDisabled(tsStartRow, !props.tsApply)
    setRowDisabled(tsDropRow, !props.tsApply)
  }

  // 파괴 함수
  function destroy(): void {
    wsBadge = null
    autoSellToggle = null
    timePairHandle = null
    tpToggle = null; lossToggle = null; tsToggle = null
    tpValInput = null; lossValInput = null
    tsStartValInput = null; tsDropValInput = null
    tpValRow = null; lossValRow = null; tsStartRow = null; tsDropRow = null
  }

  return { el: root, update, destroy }
}
