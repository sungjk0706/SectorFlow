// frontend/src/pages/general-settings-time-settings-tab.ts
// 일반설정 — 시간 설정 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.
//
// Step 1 골조 + Step 2 자동매수/매도 시간쌍 이동 + Step 3 사전 준비 시간·거래소 고정 시간 이동 + Step 4 1일봉 다운로드 이동.
// 토글 OFF 시에도 시간 입력 활성화 유지 (설계서 2-1, P24 탭 간 의존성 최소화, P21 안내 문구로 보완).

import { createToggleBtn, createNumInput } from '../components/common/setting-row'
import { sectionTitle, createDescText, parseHM, createTimeSlot, updateTimeSlotDisplay } from '../components/common/settings-common'
import { createTimePairInput } from '../components/common/time-pair-input'
import { FONT_SIZE, FONT_WEIGHT, COLOR, setDisabled } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, GS, scheduleTimetableSave } from './general-settings-shared'

function buildBuyTimeRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매수 시간'
  row.appendChild(label)
  const buyStart = String(state.vals.buy_time_start ?? '09:00')
  const buyEnd = String(state.vals.buy_time_end ?? '15:00')
  const { el: tpWrap, handle } = createTimePairInput(buyStart, buyEnd, (s, e) => {
    if (state.settingsMgr) {
      const dirty: Record<string, unknown> = {}
      if (s !== state.vals.buy_time_start) dirty.buy_time_start = s
      if (e !== state.vals.buy_time_end) dirty.buy_time_end = e
      if (Object.keys(dirty).length > 0) {
        state.settingsMgr.saveSection(dirty).then(toastResult)
        Object.assign(state.vals, dirty)
      }
    }
  })
  state.buyTimeHandle = handle
  row.appendChild(tpWrap)
  return row
}

function buildSellTimeRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '자동매도 시간'
  row.appendChild(label)
  const sellStart = String(state.vals.sell_time_start ?? '09:00')
  const sellEnd = String(state.vals.sell_time_end ?? '15:00')
  const { el: tpWrap, handle } = createTimePairInput(sellStart, sellEnd, (s, e) => {
    if (state.settingsMgr) {
      const dirty: Record<string, unknown> = {}
      if (s !== state.vals.sell_time_start) dirty.sell_time_start = s
      if (e !== state.vals.sell_time_end) dirty.sell_time_end = e
      if (Object.keys(dirty).length > 0) {
        state.settingsMgr.saveSection(dirty).then(toastResult)
        Object.assign(state.vals, dirty)
      }
    }
  })
  state.sellTimeHandle = handle
  row.appendChild(tpWrap)
  return row
}

function buildTimetableRow(state: GeneralSettingsState, labelText: string, key: 'timetable.realtime_reset' | 'timetable.ws_prestart' | 'timetable.krx_pre_subscribe', defaultTime: string): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, paddingLeft: '20px', borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = labelText
  row.appendChild(label)
  const [h, m] = parseHM(String(state.vals[key] ?? defaultTime))
  const slot = createTimeSlot(h, m, (nh, nm) => {
    updateTimeSlotDisplay(slot, nh, nm)
    scheduleTimetableSave(key, `${nh}:${nm}`)
  })
  row.appendChild(slot)
  // 모듈 상태 업데이트 (키별)
  if (key === 'timetable.realtime_reset') { state.timetableResetSlot = slot }
  else if (key === 'timetable.ws_prestart') { state.timetableWsSlot = slot }
  else if (key === 'timetable.krx_pre_subscribe') { state.timetableKrxSlot = slot }
  return row
}

function buildConfirmedDownloadRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal, whiteSpace: 'nowrap' })
  label.textContent = '1일봉차트 자동다운로드'
  row.appendChild(label)

  const right = document.createElement('span')
  right.style.cssText = 'display:flex;align-items:center;gap:10px;'

  const [cdh, cdm] = parseHM(String(state.vals['timetable.confirmed_download'] ?? '20:40'))
  state.confirmedDlH = cdh; state.confirmedDlM = cdm
  state.confirmedDlSlot = createTimeSlot(state.confirmedDlH, state.confirmedDlM, (h, m) => {
    state.confirmedDlH = h; state.confirmedDlM = m; updateTimeSlotDisplay(state.confirmedDlSlot!, h, m)
    scheduleTimetableSave('timetable.confirmed_download', `${h}:${m}`)
  })
  right.appendChild(state.confirmedDlSlot)

  const dlOn = state.vals.scheduler_market_close_on !== false
  state.confirmedDlToggle = createToggleBtn({ on: dlOn, onClick: async () => {
    const next = !state.confirmedDlToggle!.isOn()
    state.confirmedDlToggle!.setOn(next)
    setDisabled(state.confirmedDlSlot!, !next)
    state.vals.scheduler_market_close_on = next
    const res = await state.settingsMgr!.saveSection({ scheduler_market_close_on: next })
    toastResult(res)
    if (!res.ok) {
      state.vals.scheduler_market_close_on = !next
      state.confirmedDlToggle!.setOn(!next)
      setDisabled(state.confirmedDlSlot!, next)
    }
  }})
  right.appendChild(state.confirmedDlToggle.el)
  row.appendChild(right)
  setDisabled(state.confirmedDlSlot, !dlOn)
  return row
}

function buildFixedTimesBox(): HTMLElement {
  const fixedTimes: Array<[string, string]> = [
    ['08:00', 'NXT 프리마켓 시작'],
    ['09:00', '정규장 시작'],
    ['15:20', '정규장 종료'],
    ['15:30', '종가 동시호가 종료'],
    ['15:40', 'NXT 애프터마켓 시작'],
    ['20:00', '장마감'],
  ]
  const box = document.createElement('div')
  Object.assign(box.style, {
    margin: '8px 0 0', padding: '8px 10px',
    background: COLOR.surface, border: '1px solid ' + COLOR.borderLight,
    borderRadius: '6px', fontSize: FONT_SIZE.desc, color: COLOR.tertiary,
  })
  const title = document.createElement('div')
  Object.assign(title.style, { fontWeight: FONT_WEIGHT.normal, color: COLOR.neutral, marginBottom: '4px' })
  title.textContent = '참고: 거래소 고정 시간 (변경 불가)'
  box.appendChild(title)
  for (const [t, label] of fixedTimes) {
    const row = document.createElement('div')
    Object.assign(row.style, { display: 'flex', gap: '8px', fontVariantNumeric: 'tabular-nums' })
    const time = document.createElement('span')
    Object.assign(time.style, { color: COLOR.neutral, minWidth: '48px' })
    time.textContent = t
    const desc = document.createElement('span')
    desc.textContent = label
    row.appendChild(time)
    row.appendChild(desc)
    box.appendChild(row)
  }
  return box
}

function buildSubscribeMaxRow(state: GeneralSettingsState): HTMLElement {
  const row = document.createElement('div')
  Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: GS.rowPad, borderBottom: GS.rowBorder })
  const label = document.createElement('span')
  Object.assign(label.style, { fontSize: GS.label, fontWeight: FONT_WEIGHT.normal })
  label.textContent = '종목 동시 구독 최대 개수'
  row.appendChild(label)

  // 백엔드 settings_store.py가 1~1000 외 값 저장 차단 (422) — UI clamp와 이중 방어
  const initMax = Number(state.vals['subscribe.max_0b_count'] ?? 200) || 200
  state.subscribeMaxInput = createNumInput({
    value: initMax,
    min: 1, max: 1000, step: 10,
    name: 'subscribe.max_0b_count',
    onChange: async (v) => {
      if (!state.settingsMgr) return
      const dirty: Record<string, unknown> = { 'subscribe.max_0b_count': v }
      const res = await state.settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
    },
  })
  row.appendChild(state.subscribeMaxInput.el)
  return row
}

export function renderTimeSettingsTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(buildBuyTimeRow(state))
  container.appendChild(buildSellTimeRow(state))
  container.appendChild(createDescText('자동매수/매도가 꺼져 있어도 시간을 미리 설정할 수 있습니다. "자동매매" 탭에서 자동매수/매도를 켜면 이 시간에 맞춰 실행됩니다.'))

  // 사전 준비 시간 설정 (타임테이블 사용자 조정 3개) — P21 투명성
  container.appendChild(sectionTitle('사전 준비 시간 설정'))
  container.appendChild(createDescText('너무 늦으면 실시간 데이터가 누락될 수 있습니다.'))
  container.appendChild(buildTimetableRow(state, '실시간 데이터 필드 초기화', 'timetable.realtime_reset', '07:58'))
  container.appendChild(createDescText('장 시작 전 필드를 비워 새 데이터를 받을 준비를 합니다'))
  container.appendChild(buildTimetableRow(state, 'NXT 종목 구독 신청', 'timetable.ws_prestart', '07:59'))
  container.appendChild(createDescText('NXT 프리마켓 시작 전 구독을 미리 신청합니다'))
  container.appendChild(buildTimetableRow(state, 'KRX 종목 추가 구독', 'timetable.krx_pre_subscribe', '08:59'))
  container.appendChild(createDescText('KRX 정규장 시작 전 KRX 단독 종목 구독을 추가합니다'))

  // 1일봉차트 자동다운로드 (토글 + 시간 슬롯) — 단일 항목이라 섹션 제목 생략 (P24)
  container.appendChild(buildConfirmedDownloadRow(state))
  container.appendChild(createDescText('장마감 후 자동 다운로드 시간 (기본값 20:40) — OFF 시 수동 다운로드만 가능'))

  // 거래소 고정 시간 참고 표시 (읽기 전용, 변경 불가) — P21 투명성
  container.appendChild(buildFixedTimesBox())

  // 구독 한도 — P10 SSOT 단일 설정 키, P21 사용자 조정 가능
  container.appendChild(sectionTitle('구독 한도'))
  container.appendChild(createDescText('종목 실시간 시세를 동시에 구독할 최대 개수입니다. 보유 종목을 우선 등록한 뒤, 남은 자리만큼 필터 통과 종목이 추가로 등록됩니다. (기본값 200, 범위 1~1000)'))
  container.appendChild(buildSubscribeMaxRow(state))
}
