// frontend/src/pages/buy-settings.ui.ts
// 매수설정 카드 — 순수 UI 껍데기 (Dumb Component)
// 비즈니스 로직 제거, Props로 데이터 수신

import { createSettingRow, createNumInput, createMoneyInput, createToggleBtn, createFixedValue } from '../components/common/setting-row'
import { sectionTitle } from '../components/common/settings-common'
import { createDualLabelSlider, type DualLabelSliderHandle } from '../components/common/create-slider'
import { FONT_SIZE, FONT_WEIGHT } from '../components/common/ui-styles'
import { createTimePairInput, type TimePairInputHandle } from '../components/common/time-pair-input'
import { createGlobalWsBadge } from '../settings'

// ── Props 타입 정의 ──

export interface BuySettingsProps {
  // 자동매수 설정
  autoBuyOn: boolean
  buyTimeStart: string
  buyTimeEnd: string
  
  // 전역 조건
  buyIndexGuardKospiOn: boolean
  buyIndexKospiDrop: number
  buyIndexGuardKosdaqOn: boolean
  buyIndexKosdaqDrop: number
  buyBlockRisePct: number
  buyBlockFallPct: number
  buyMinStrength: number
  
  // 매수 가산점
  boostHighBreakoutOn: boolean
  boostHighBreakoutScore: number
  boostOrderRatioOn: boolean
  boostOrderRatioPct: number
  boostOrderRatioScore: number
  
  // 매수 한도
  maxDailyTotalBuyAmt: number
  maxStockCnt: number
  buyAmt: number
  
  // 실시간 상태
  wsSubscribed: boolean
  
  // 이벤트 핸들러 (UI 전용 상태 변경)
  onAutoBuyToggle: (on: boolean) => void
  onTimePairChange: (start: string, end: string) => void
  onKospiGuardToggle: (on: boolean) => void
  onKospiDropChange: (value: number) => void
  onKosdaqGuardToggle: (on: boolean) => void
  onKosdaqDropChange: (value: number) => void
  onRiseChange: (value: number) => void
  onFallChange: (value: number) => void
  onStrengthChange: (value: number) => void
  onBoostHighToggle: (on: boolean) => void
  onBoostHighScoreChange: (value: number) => void
  onBoostOrderToggle: (on: boolean) => void
  onBoostOrderRatioChange: (value: number) => void
  onBoostOrderScoreChange: (value: number) => void
  onMaxDailyChange: (value: number) => void
  onMaxStockCntChange: (value: number) => void
  onBuyAmtChange: (value: number) => void
}

/* ── 컴포넌트 생성 함수 ── */

export function createBuySettingsCard(props: BuySettingsProps): { el: HTMLElement; update: (newProps: BuySettingsProps) => void; destroy: () => void } {
  const root = document.createElement('div')
  
  // 입력 컴포넌트 참조
  let wsBadge: HTMLElement | null = null
  let autoBuyToggle: ReturnType<typeof createToggleBtn> | null = null
  let timePairHandle: TimePairInputHandle | null = null
  let kospiGuardToggle: ReturnType<typeof createToggleBtn> | null = null
  let kospiDropInput: ReturnType<typeof createNumInput> | null = null
  let kosdaqGuardToggle: ReturnType<typeof createToggleBtn> | null = null
  let kosdaqDropInput: ReturnType<typeof createNumInput> | null = null
  let riseInput: ReturnType<typeof createNumInput> | null = null
  let fallInput: ReturnType<typeof createNumInput> | null = null
  let strengthInput: ReturnType<typeof createNumInput> | null = null
  let maxDailyInput: ReturnType<typeof createMoneyInput> | null = null
  let maxStockCntInput: ReturnType<typeof createNumInput> | null = null
  let buyAmtInput: ReturnType<typeof createMoneyInput> | null = null
  
  // 가산점 UI 참조
  let boostHighToggle: ReturnType<typeof createToggleBtn> | null = null
  let boostHighScoreInput: ReturnType<typeof createNumInput> | null = null
  let boostHighControls: HTMLElement | null = null
  
  let boostOrderToggle: ReturnType<typeof createToggleBtn> | null = null
  let boostOrderDualSlider: DualLabelSliderHandle | null = null
  let boostOrderScoreInput: ReturnType<typeof createNumInput> | null = null
  let boostOrderControls: HTMLElement | null = null
  let boostOrderRow2: HTMLElement | null = null

  // 제목 + WS 상태 배지
  const headerRow = document.createElement('div')
  Object.assign(headerRow.style, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' })
  const h4 = document.createElement('h4')
  h4.style.margin = '0'
  h4.textContent = '매수 설정'
  headerRow.appendChild(h4)

  wsBadge = createGlobalWsBadge()
  headerRow.appendChild(wsBadge)
  root.appendChild(headerRow)

  // 자동매수 토글 + TimePairInput (1행)
  const autoRow = document.createElement('div')
  Object.assign(autoRow.style, { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', padding: '4px 0' })

  const toggleLabel = document.createElement('span')
  Object.assign(toggleLabel.style, { fontSize: FONT_SIZE.body, fontWeight: FONT_WEIGHT.normal, whiteSpace: 'nowrap' })
  toggleLabel.textContent = '자동매수'

  autoBuyToggle = createToggleBtn({
    on: props.autoBuyOn,
    onClick: () => {
      props.onAutoBuyToggle(!props.autoBuyOn)
    },
  })

  const startTime = props.buyTimeStart
  const endTime = props.buyTimeEnd
  
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
  autoRow.appendChild(autoBuyToggle.el)
  autoRow.appendChild(tpWrap)
  root.appendChild(autoRow)

  // 매수 조건 섹션
  root.appendChild(sectionTitle('전역 조건'))

  // 코스피 하락 제한
  kospiGuardToggle = createToggleBtn({ on: props.buyIndexGuardKospiOn, onClick: () => {
    props.onKospiGuardToggle(!props.buyIndexGuardKospiOn)
  }})
  const kospiLabelWrap = document.createElement('span')
  kospiLabelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
  kospiLabelWrap.appendChild(kospiGuardToggle.el)
  const kospiText = document.createElement('span')
  kospiText.textContent = '코스피 하락 매수차단'
  kospiLabelWrap.appendChild(kospiText)
  kospiDropInput = createNumInput({ value: props.buyIndexKospiDrop, onChange: props.onKospiDropChange, step: 1, name: 'buy_index_kospi_drop' })
  root.appendChild(createSettingRow(kospiLabelWrap, kospiDropInput.el))

  // 코스닥 하락 제한
  kosdaqGuardToggle = createToggleBtn({ on: props.buyIndexGuardKosdaqOn, onClick: () => {
    props.onKosdaqGuardToggle(!props.buyIndexGuardKosdaqOn)
  }})
  const kosdaqLabelWrap = document.createElement('span')
  kosdaqLabelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
  kosdaqLabelWrap.appendChild(kosdaqGuardToggle.el)
  const kosdaqText = document.createElement('span')
  kosdaqText.textContent = '코스닥 하락 매수차단'
  kosdaqLabelWrap.appendChild(kosdaqText)
  kosdaqDropInput = createNumInput({ value: props.buyIndexKosdaqDrop, onChange: props.onKosdaqDropChange, step: 1, name: 'buy_index_kosdaq_drop' })
  root.appendChild(createSettingRow(kosdaqLabelWrap, kosdaqDropInput.el))

  // 상승률 제한
  riseInput = createNumInput({ value: props.buyBlockRisePct, onChange: props.onRiseChange, step: 1, name: 'buy_block_rise_pct' })
  root.appendChild(createSettingRow('종목 상승률 매수차단', riseInput.el))

  // 하락률 제한
  fallInput = createNumInput({ value: props.buyBlockFallPct, onChange: props.onFallChange, step: 1, name: 'buy_block_fall_pct' })
  root.appendChild(createSettingRow('종목 하락률 매수차단', fallInput.el))

  // 체결강도 하한
  strengthInput = createNumInput({ value: props.buyMinStrength, onChange: props.onStrengthChange, step: 1, name: 'buy_min_strength' })
  root.appendChild(createSettingRow('종목 체결강도 매수차단', strengthInput.el))

  // 매수 가산점 섹션
  root.appendChild(sectionTitle('매수 가산점'))

  // 5일 고가 돌파
  {
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    boostHighToggle = createToggleBtn({ on: props.boostHighBreakoutOn, onClick: () => {
      props.onBoostHighToggle(!props.boostHighBreakoutOn)
    }})
    labelWrap.appendChild(boostHighToggle.el)
    const label = document.createElement('span')
    label.textContent = '5일 고가 돌파'
    labelWrap.appendChild(label)

    const controls = document.createElement('span')
    controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    controls.style.opacity = props.boostHighBreakoutOn ? '1' : '0.4'
    controls.style.pointerEvents = props.boostHighBreakoutOn ? 'auto' : 'none'
    boostHighControls = controls

    boostHighScoreInput = createNumInput({ value: props.boostHighBreakoutScore, onChange: props.onBoostHighScoreChange, step: 1, name: 'boost_high_breakout_score' })
    controls.appendChild(boostHighScoreInput.el)

    root.appendChild(createSettingRow(labelWrap, controls))
  }

  // 매수/매도 호가 잔량비율
  {
    const block = document.createElement('div')
    block.style.borderBottom = '1px solid #eee'

    // Row 1: toggle + label | 가산점 + input
    const labelWrap = document.createElement('span')
    labelWrap.style.cssText = 'display:flex;align-items:center;gap:8px;'
    boostOrderToggle = createToggleBtn({ on: props.boostOrderRatioOn, onClick: () => {
      props.onBoostOrderToggle(!props.boostOrderRatioOn)
    }})
    labelWrap.appendChild(boostOrderToggle.el)
    const label = document.createElement('span')
    label.textContent = '매수/매도 호가 잔량비율'
    labelWrap.appendChild(label)

    const row1Controls = document.createElement('span')
    row1Controls.style.cssText = 'display:flex;align-items:center;gap:6px;'
    row1Controls.style.opacity = props.boostOrderRatioOn ? '1' : '0.4'
    row1Controls.style.pointerEvents = props.boostOrderRatioOn ? 'auto' : 'none'
    boostOrderControls = row1Controls

    boostOrderScoreInput = createNumInput({ value: props.boostOrderRatioScore, onChange: props.onBoostOrderScoreChange, step: 1, name: 'boost_order_ratio_score' })
    row1Controls.appendChild(boostOrderScoreInput.el)

    const row1 = document.createElement('div')
    Object.assign(row1.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' })
    row1.appendChild(labelWrap)
    row1.appendChild(row1Controls)
    block.appendChild(row1)

    // Row 2: dual label slider
    boostOrderDualSlider = createDualLabelSlider({
      min: 0, max: 200, value: props.boostOrderRatioPct + 100, step: 1,
      leftLabel: (v) => v < 100 ? `매도잔량 +${100 - v}%` : '매도잔량',
      rightLabel: (v) => v > 100 ? `매수잔량 +${v - 100}%` : '매수잔량',
      leftColor: '#0d6efd',
      leftColorLight: '#8bb8f8',
      rightColor: '#dc3545',
      rightColorLight: '#f1aeb5',
      onChange() {
        // UI 상태만 업데이트 (비즈니스 로직 제거)
      },
      onCommit(v) {
        props.onBoostOrderRatioChange(v - 100)
      },
    })

    const row2 = document.createElement('div')
    Object.assign(row2.style, { padding: '0 0 6px' })
    row2.appendChild(boostOrderDualSlider.el)
    row2.style.opacity = props.boostOrderRatioOn ? '1' : '0.4'
    row2.style.pointerEvents = props.boostOrderRatioOn ? 'auto' : 'none'
    boostOrderRow2 = row2

    block.appendChild(row2)
    root.appendChild(block)
  }

  // 매수 금액 섹션
  root.appendChild(sectionTitle('매수 한도'))

  // 매수 주문 유형 (시장가 고정)
  root.appendChild(createSettingRow('매수 주문 유형', createFixedValue('시장가')))

  // 일일 최대 매수 금액
  maxDailyInput = createMoneyInput({ value: props.maxDailyTotalBuyAmt, onChange: props.onMaxDailyChange, name: 'max_daily_total_buy_amt' })
  root.appendChild(createSettingRow('일일 최대 매수 금액', maxDailyInput.el))

  // 최대 동시 보유 종목 수
  maxStockCntInput = createNumInput({ value: props.maxStockCnt, onChange: props.onMaxStockCntChange, name: 'max_stock_cnt' })
  root.appendChild(createSettingRow('최대 동시 보유 종목 수', maxStockCntInput.el))

  // 종목당 일일 최대 매수 금액
  buyAmtInput = createMoneyInput({ value: props.buyAmt, onChange: props.onBuyAmtChange, name: 'buy_amt' })
  root.appendChild(createSettingRow('종목당 일일 최대 매수 금액', buyAmtInput.el))

  // Props 업데이트 함수
  function update(newProps: BuySettingsProps): void {
    Object.assign(props, newProps)
    
    // 입력 값 동기화
    autoBuyToggle?.setOn(props.autoBuyOn)
    if (timePairHandle) {
      timePairHandle.setValue(props.buyTimeStart, props.buyTimeEnd)
      timePairHandle.setEnabled(props.autoBuyOn)
    }
    
    kospiGuardToggle?.setOn(props.buyIndexGuardKospiOn)
    kospiDropInput?.setValue(props.buyIndexKospiDrop)
    kosdaqGuardToggle?.setOn(props.buyIndexGuardKosdaqOn)
    kosdaqDropInput?.setValue(props.buyIndexKosdaqDrop)
    riseInput?.setValue(props.buyBlockRisePct)
    fallInput?.setValue(props.buyBlockFallPct)
    strengthInput?.setValue(props.buyMinStrength)
    
    boostHighToggle?.setOn(props.boostHighBreakoutOn)
    boostHighScoreInput?.setValue(props.boostHighBreakoutScore)
    if (boostHighControls) {
      boostHighControls.style.opacity = props.boostHighBreakoutOn ? '1' : '0.4'
      boostHighControls.style.pointerEvents = props.boostHighBreakoutOn ? 'auto' : 'none'
    }
    
    boostOrderToggle?.setOn(props.boostOrderRatioOn)
    if (!boostOrderDualSlider?.isInteracting) {
      boostOrderDualSlider?.setValue(props.boostOrderRatioPct + 100)
    }
    boostOrderScoreInput?.setValue(props.boostOrderRatioScore)
    if (boostOrderControls) {
      boostOrderControls.style.opacity = props.boostOrderRatioOn ? '1' : '0.4'
      boostOrderControls.style.pointerEvents = props.boostOrderRatioOn ? 'auto' : 'none'
    }
    if (boostOrderRow2) {
      boostOrderRow2.style.opacity = props.boostOrderRatioOn ? '1' : '0.4'
      boostOrderRow2.style.pointerEvents = props.boostOrderRatioOn ? 'auto' : 'none'
    }
    
    maxDailyInput?.setValue(props.maxDailyTotalBuyAmt)
    maxStockCntInput?.setValue(props.maxStockCnt)
    buyAmtInput?.setValue(props.buyAmt)
  }

  // 파괴 함수
  function destroy(): void {
    wsBadge = null
    autoBuyToggle = null
    timePairHandle = null
    kospiGuardToggle = null; kospiDropInput = null
    kosdaqGuardToggle = null; kosdaqDropInput = null
    riseInput = null; fallInput = null; strengthInput = null
    maxDailyInput = null; maxStockCntInput = null; buyAmtInput = null
    boostHighToggle = null; boostHighScoreInput = null; boostHighControls = null
    boostOrderToggle = null; boostOrderDualSlider = null; boostOrderScoreInput = null; boostOrderControls = null; boostOrderRow2 = null
  }

  return { el: root, update, destroy }
}
