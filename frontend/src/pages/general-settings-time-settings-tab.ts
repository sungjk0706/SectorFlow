// frontend/src/pages/general-settings-time-settings-tab.ts
// 일반설정 — 시간 설정 탭 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.
//
// Step 1 골조 + Step 2 자동매수/매도 시간쌍 이동 + Step 3 사전 준비 시간·거래소 고정 시간 이동 + Step 4 일봉 다운로드 이동.
// Step 2(탭 재분류): 자동매수/매도 토글을 자동매매 탭에서 이관 — 시간+토글 통합 행 (설계서 3.2).
// 토글 OFF 시에도 시간 입력 활성화 유지 (설계서 2-1, P24 탭 간 의존성 최소화, P21 안내 문구로 보완).
// 마스터 토글(time_scheduler_on) 이관 — 시간 기반 자동매매 설정을 한 탭에 통합 (P24 단순성, P21 투명성).

import { createNumInput, createSettingRow, createSettingToggleRow } from '../components/common/setting-row'
import { sectionTitle, createDescText, parseHM, createTimeSlot, updateTimeSlotDisplay } from '../components/common/settings-common'
import { createTimePairInput } from '../components/common/time-pair-input'
import { FONT_SIZE, FONT_WEIGHT, COLOR, RADIUS, setDisabled } from '../components/common/ui-styles'
import { toastResult } from '../components/common/toast'
import { type GeneralSettingsState, scheduleTimetableSave, createHolidayBadge, state } from './general-settings-shared'

// 자동매매 마스터 토글 (time_scheduler_on) — 시간 기반 스케줄러 전체 스위치
// 자동매수/매도 시간·토글과 동일 탭에 배치하여 시간 기반 자동매매 설정 통합 (P24 단순성)
async function handleMasterToggle(state: GeneralSettingsState): Promise<void> {
  const next = !state.vals.time_scheduler_on
  state.vals.time_scheduler_on = next; state.masterToggle?.setOn(next)
  const r = await state.settingsMgr!.saveSection({ time_scheduler_on: next })
  toastResult(r)
  if (!r.ok) { state.vals.time_scheduler_on = !next; state.masterToggle?.setOn(!next) }
}

function buildMasterToggleRow(state: GeneralSettingsState): HTMLElement {
  // 자동매수 시간 행의 시간쌍 입력란과 동일 폭의 투명 스페이서 — 비거래일 배지 세로 정렬용 (P23 일관성)
  const spacer = createTimePairInput('09:00', '15:20', () => {})
  Object.assign(spacer.el.style, { visibility: 'hidden', pointerEvents: 'none' })
  const r = createSettingToggleRow({
    label: '자동매매',
    toggleOn: false,
    controls: [spacer.el],
    extrasBeforeControls: true,
    extras: [createHolidayBadge()],
    onToggle: () => handleMasterToggle(state),
  })
  state.masterToggle = r.toggle
  return r.el
}

// 시간쌍 순서 위반 경고 메시지 영역 (P21 투명성 — 행 하단 지속 표시, P23 createDescText 위치·폰트 일치, 경고색 적용)
function createTimeOrderWarnEl(): HTMLElement {
  const el = document.createElement('div')
  Object.assign(el.style, {
    fontSize: FONT_SIZE.desc, color: COLOR.warning,
    padding: '0 0 4px', marginTop: '-4px',
  })
  return el
}

// 시간 행 + 경고 메시지를 묶어 반환 (row 단독 반환 시 메시지 배치 불가 → 컨테이너로 래핑)
function wrapTimeRowWithWarn(row: HTMLElement, warnEl: HTMLElement): HTMLElement {
  const wrap = document.createElement('div')
  wrap.appendChild(row)
  wrap.appendChild(warnEl)
  return wrap
}

function buildBuyTimeRow(state: GeneralSettingsState): HTMLElement {
  const buyStart = String(state.vals.buy_time_start ?? '09:00')
  const buyEnd = String(state.vals.buy_time_end ?? '15:20')
  // 행 하단 경고 메시지 영역 (P21 투명성 — 순서 위반 시 지속 표시, P23 createDescText 위치와 일치)
  const warnEl = createTimeOrderWarnEl()
  const { el: tpWrap, handle } = createTimePairInput(buyStart, buyEnd, (s, e) => {
    warnEl.textContent = '' // 유효 복귀 시 즉시 해제
    if (state.settingsMgr) {
      const origS = String(state.vals.buy_time_start ?? '09:00')
      const origE = String(state.vals.buy_time_end ?? '15:20')
      const dirty: Record<string, unknown> = {}
      if (s !== state.vals.buy_time_start) dirty.buy_time_start = s
      if (e !== state.vals.buy_time_end) dirty.buy_time_end = e
      if (Object.keys(dirty).length > 0) {
        state.settingsMgr.saveSection(dirty).then(res => {
          toastResult(res)
          if (res.ok) Object.assign(state.vals, dirty)
          else handle.setValue(origS, origE)
        })
      }
    }
  }, (msg) => { warnEl.textContent = msg })
  state.buyTimeHandle = handle
  const r = createSettingToggleRow({
    label: '자동매수 시간',
    toggleOn: !!state.vals.auto_buy_on,
    disableControlsOnToggle: false,
    controls: [tpWrap],
    extrasBeforeControls: true,
    extras: [createHolidayBadge()],
    onToggle: async next => {
      state.vals.auto_buy_on = next
      const res = await state.settingsMgr!.saveSection({ auto_buy_on: next })
      toastResult(res)
      if (!res.ok) { state.vals.auto_buy_on = !next; r.toggle.setOn(!next) }
    },
  })
  state.autoBuyToggle = r.toggle
  return wrapTimeRowWithWarn(r.el, warnEl)
}

function buildSellTimeRow(state: GeneralSettingsState): HTMLElement {
  const sellStart = String(state.vals.sell_time_start ?? '09:00')
  const sellEnd = String(state.vals.sell_time_end ?? '15:20')
  // 행 하단 경고 메시지 영역 (P21 투명성 — 순서 위반 시 지속 표시, P23 createDescText 위치와 일치)
  const warnEl = createTimeOrderWarnEl()
  const { el: tpWrap, handle } = createTimePairInput(sellStart, sellEnd, (s, e) => {
    warnEl.textContent = '' // 유효 복귀 시 즉시 해제
    if (state.settingsMgr) {
      const origS = String(state.vals.sell_time_start ?? '09:00')
      const origE = String(state.vals.sell_time_end ?? '15:20')
      const dirty: Record<string, unknown> = {}
      if (s !== state.vals.sell_time_start) dirty.sell_time_start = s
      if (e !== state.vals.sell_time_end) dirty.sell_time_end = e
      if (Object.keys(dirty).length > 0) {
        state.settingsMgr.saveSection(dirty).then(res => {
          toastResult(res)
          if (res.ok) Object.assign(state.vals, dirty)
          else handle.setValue(origS, origE)
        })
      }
    }
  }, (msg) => { warnEl.textContent = msg })
  state.sellTimeHandle = handle
  const r = createSettingToggleRow({
    label: '자동매도 시간',
    toggleOn: !!state.vals.auto_sell_on,
    disableControlsOnToggle: false,
    controls: [tpWrap],
    extrasBeforeControls: true,
    extras: [createHolidayBadge()],
    onToggle: async next => {
      state.vals.auto_sell_on = next
      const res = await state.settingsMgr!.saveSection({ auto_sell_on: next })
      toastResult(res)
      if (!res.ok) { state.vals.auto_sell_on = !next; r.toggle.setOn(!next) }
    },
  })
  state.autoSellToggle = r.toggle
  return wrapTimeRowWithWarn(r.el, warnEl)
}

function buildTimetablePairRow(
  state: GeneralSettingsState,
  labelText: string,
  startKey: 'timetable.nxt_start' | 'timetable.krx_start',
  endKey: 'timetable.nxt_end' | 'timetable.krx_end',
  defaultStart: string,
  defaultEnd: string,
  infoText?: string,
): HTMLElement {
  // 시간쌍 순서 위반 경고 메시지 영역 (P21 투명성)
  const warnEl = createTimeOrderWarnEl()
  const startVal = String(state.vals[startKey] ?? defaultStart)
  const endVal = String(state.vals[endKey] ?? defaultEnd)
  const { el: tpWrap, handle } = createTimePairInput(startVal, endVal, (s, e) => {
    warnEl.textContent = ''
    if (state.settingsMgr) {
      const origS = String(state.vals[startKey] ?? defaultStart)
      const origE = String(state.vals[endKey] ?? defaultEnd)
      const dirty: Record<string, unknown> = {}
      if (s !== state.vals[startKey]) dirty[startKey] = s
      if (e !== state.vals[endKey]) dirty[endKey] = e
      if (Object.keys(dirty).length > 0) {
        state.settingsMgr.saveSection(dirty).then(res => {
          toastResult(res)
          if (res.ok) Object.assign(state.vals, dirty)
          else handle.setValue(origS, origE)
        })
      }
    }
  }, (msg) => { warnEl.textContent = msg })
  // 모듈 상태 업데이트 (NXT/KRX별)
  if (startKey === 'timetable.nxt_start') { state.timetableNxtHandle = handle }
  else { state.timetableKrxHandle = handle }
  // 공통 설정 행 컴포넌트 사용 (P23 일관성, P24 단순성)
  const row = createSettingRow(labelText, tpWrap, { infoText })
  return wrapTimeRowWithWarn(row, warnEl)
}

function buildConfirmedDownloadRow(state: GeneralSettingsState): HTMLElement {
  const [cdh, cdm] = parseHM(String(state.vals['timetable.confirmed_download'] ?? '20:40'))
  state.confirmedDlH = cdh; state.confirmedDlM = cdm
  state.confirmedDlSlot = createTimeSlot(state.confirmedDlH, state.confirmedDlM, (h, m) => {
    state.confirmedDlH = h; state.confirmedDlM = m; updateTimeSlotDisplay(state.confirmedDlSlot!, h, m)
    const [origH, origM] = parseHM(String(state.vals['timetable.confirmed_download'] ?? '20:40'))
    scheduleTimetableSave('timetable.confirmed_download', `${h}:${m}`, () => { state.confirmedDlH = origH; state.confirmedDlM = origM; updateTimeSlotDisplay(state.confirmedDlSlot!, origH, origM) })
  })

  const dlOn = state.vals.scheduler_market_close_on !== false
  const r = createSettingToggleRow({
    label: '일봉차트 자동다운로드',
    toggleOn: dlOn,
    disableControlsOnToggle: true,
    controls: [state.confirmedDlSlot],
    onToggle: async next => {
      state.vals.scheduler_market_close_on = next
      const res = await state.settingsMgr!.saveSection({ scheduler_market_close_on: next })
      toastResult(res)
      if (!res.ok) {
        state.vals.scheduler_market_close_on = !next
        r.toggle.setOn(!next)
        setDisabled(r.controls, next)
      }
    },
  })
  state.confirmedDlToggle = r.toggle
  return r.el
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
    borderRadius: RADIUS.sm, fontSize: FONT_SIZE.desc, color: COLOR.tertiary,
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
  // 백엔드 settings_store.py가 1~1000 외 값 저장 차단 (422) — UI clamp와 이중 방어
  const initMax = Number(state.vals['subscribe.max_0b_count'] ?? 200) || 200
  state.subscribeMaxInput = createNumInput({
    value: initMax,
    min: 1, max: 1000, step: 10, suffix: '개',
    name: 'subscribe.max_0b_count',
    onChange: async (v) => {
      if (!state.settingsMgr) return
      const orig = Number(state.vals['subscribe.max_0b_count'] ?? 200) || 200
      const dirty: Record<string, unknown> = { 'subscribe.max_0b_count': v }
      const res = await state.settingsMgr.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
      else { state.vals['subscribe.max_0b_count'] = orig; state.subscribeMaxInput?.setValue(orig) }
    },
  })
  return createSettingRow('종목 동시 구독 최대 개수', state.subscribeMaxInput.el, {
    infoText: '종목 실시간 시세를 동시에 구독할 최대 개수.\n보유 종목을 우선 등록한 뒤 남은 자리만큼 필터 통과 종목이 추가 등록됩니다.\n범위: 1~1000, 기본 200.',
  })
}

export function renderTimeSettingsTab(state: GeneralSettingsState, container: HTMLElement): void {
  container.appendChild(buildMasterToggleRow(state))
  container.appendChild(buildBuyTimeRow(state))
  container.appendChild(buildSellTimeRow(state))
  container.appendChild(createDescText('자동매매 토글로 시간 기반 자동매매를 켜고 끕니다. 자동매수/자동매도 시간 우측 토글로 각각 켜고 끌 수 있으며, 토글이 꺼져 있어도 시간은 미리 설정할 수 있습니다. 거래일 설정시간 내에서만 실행되며, 공휴일·주말에는 자동매매가 항상 차단됩니다.'))

  // 구독 시간 설정 (타임테이블 사용자 조정 — NXT/KRX 시작·종료 시간쌍) — P21 투명성
  container.appendChild(sectionTitle('구독 시간 설정'))
  container.appendChild(createDescText('NXT와 KRX의 시작·종료 시간을 각각 설정합니다. 너무 늦으면 실시간 데이터가 누락될 수 있습니다.'))
  container.appendChild(buildTimetablePairRow(state, 'NXT 시간 설정', 'timetable.nxt_start', 'timetable.nxt_end', '07:58', '20:00', '시작: 실시간 필드 초기화 → 토큰 발급 → 실시간 연결 → NXT 종목 구독 순서로 진행됩니다.\n종료: NXT 종목 구독해지 → 실시간 연결 종료 → 토큰 폐기 순서로 진행됩니다.'))
  container.appendChild(buildTimetablePairRow(state, 'KRX 시간 설정', 'timetable.krx_start', 'timetable.krx_end', '08:59', '15:20', '시작: KRX 정규장 시작 전 KRX 단독 종목 구독을 추가합니다.\n종료: KRX 단독 종목 구독만 해지합니다. NXT 구독·연결·토큰은 유지됩니다.'))

  // 일봉차트 자동다운로드 (토글 + 시간 슬롯) — 단일 항목이라 섹션 제목 생략 (P24)
  container.appendChild(buildConfirmedDownloadRow(state))
  container.appendChild(createDescText('장마감 후 자동 다운로드 시간 (기본값 20:40) — OFF 시 수동 다운로드만 가능'))

  // 거래소 고정 시간 참고 표시 (읽기 전용, 변경 불가) — P21 투명성
  container.appendChild(buildFixedTimesBox())

  // 구독 한도 — P10 SSOT 단일 설정 키, P21 사용자 조정 가능
  container.appendChild(sectionTitle('구독 한도'))
  container.appendChild(buildSubscribeMaxRow(state))
}

/* ── 시간 설정 탭 동기화 ── */
// 마스터 토글 + 확정 시세 다운로드 시간 + 자동다운로드 토글 + 타임테이블 4슬롯 + 구독 한도 + 자동매수/매도 토글·시간쌍
export function syncTimeSettingsTab(r: Record<string, unknown>): void {
  // 마스터 토글 (time_scheduler_on)
  state.masterToggle?.setOn(!!r.time_scheduler_on)

  // 확정 시세 다운로드 시간 + 자동다운로드 토글
  const [cdh, cdm] = parseHM(String(r['timetable.confirmed_download'] ?? '20:40'))
  state.confirmedDlH = cdh; state.confirmedDlM = cdm
  if (state.confirmedDlSlot) updateTimeSlotDisplay(state.confirmedDlSlot, cdh, cdm)
  const dlOn = r.scheduler_market_close_on !== false
  state.confirmedDlToggle?.setOn(dlOn)
  if (state.confirmedDlSlot) setDisabled(state.confirmedDlSlot.parentElement as HTMLElement, !dlOn)

  // 타임테이블 시간쌍 (NXT/KRX 시작~종료)
  if (state.timetableNxtHandle) state.timetableNxtHandle.setValue(String(r['timetable.nxt_start'] ?? '07:58'), String(r['timetable.nxt_end'] ?? '20:00'))
  if (state.timetableKrxHandle) state.timetableKrxHandle.setValue(String(r['timetable.krx_start'] ?? '08:59'), String(r['timetable.krx_end'] ?? '15:20'))

  // 구독 한도
  state.subscribeMaxInput?.setValue(Number(r['subscribe.max_0b_count'] ?? 200) || 200)

  // 자동매수/매도 토글 + 시간쌍 (토글 OFF 시에도 시간 입력 활성화 유지 — 설계서 2-1)
  state.autoBuyToggle?.setOn(!!r.auto_buy_on)
  if (state.buyTimeHandle) state.buyTimeHandle.setValue(String(r.buy_time_start ?? '09:00'), String(r.buy_time_end ?? '15:20'))
  state.autoSellToggle?.setOn(!!r.auto_sell_on)
  if (state.sellTimeHandle) state.sellTimeHandle.setValue(String(r.sell_time_start ?? '09:00'), String(r.sell_time_end ?? '15:20'))
}
