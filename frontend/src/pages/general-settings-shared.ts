// frontend/src/pages/general-settings-shared.ts
// 일반설정 공통 모듈 — 모듈 상태 + GS 상수 + 공통 헬퍼 (F-04 분할, P24 단순성)
// general-settings.ts에서 이관. 순수 이동, 동작 변경 없음.
//
// 파일 분할 (F-04, P24 단순성):
// - general-settings.ts (메인): 탭 바, refreshUI, syncFromSettings, mount/unmount
// - general-settings-shared.ts (본 파일): 상태 객체 + GS 상수 + 공통 헬퍼
// - general-settings-time-settings-tab.ts: 시간 설정 탭 (+ 자동매수/매도 토글)
// - general-settings-auto-trade-tab.ts: 자동매매 탭 (마스터+배지+안전장치)
// - general-settings-news-settings-tab.ts: 뉴스 설정 탭 (Step 2 신설)
// - general-settings-display-settings-tab.ts: 화면 설정 탭 (Step 2 신설)
// - general-settings-telegram-tab.ts: 텔레그램 탭
// - general-settings-account-tab.ts: 투자모드 탭
// - general-settings-api-settings-tab.ts: API 설정 탭

import type { SettingsManager } from '../settings'
import { createToggleBtn } from '../components/common/setting-row'
import { createMoneyInput, createNumInput } from '../components/common/setting-row'
import { type TagChipHandle } from '../components/common/tag-chip'
import { createRadioGroup } from '../components/common/setting-row'
import type { TimePairInputHandle } from '../components/common/time-pair-input'
import { toastResult } from '../components/common/toast'
import { COLOR, FONT_SIZE, RADIUS } from '../components/common/ui-styles'

/* ── 탭 ID ── */
export type TabId = 'auto-trade' | 'time-settings' | 'news-settings' | 'display-settings' | 'telegram' | 'account-manage' | 'api-settings'

/* ── 일반설정 페이지 전용 스타일 상수 (공유 FONT_SIZE와 분리) ── */
export const GS = {
  label: FONT_SIZE.settingsLabel,   // 토글/행 라벨 (FONT_SIZE.settingsLabel = 14px)
  input: '13px',   // 입력박스 폰트
  rowPad: '10px 0', // 행 상하 패딩
  inputPad: '6px 10px', // 입력박스 패딩
  btnPad: '6px 20px',   // 저장/액션 버튼 패딩
  rowBorder: '1px solid ' + COLOR.borderLight,    // 설정 행 구분선
  saveMargin: '12px 0 0',         // 저장 버튼 상단 마진
} as const

// 증권사 코드 → 표시명 (라디오 items 라벨과 SSOT 일치)
export const BROKER_NAMES: Record<string, string> = { kiwoom: '키움증권', ls: 'LS증권' }

/* ── 상태 객체 (P10 SSOT — 모든 가변 상태를 단일 소스로 관리) ── */

export interface GeneralSettingsState {
  // 설정 관리
  settingsMgr: SettingsManager | null
  unsubSettings: (() => void) | null
  vals: Record<string, unknown>
  isTradingDay: boolean
  tradingDayLoading: boolean

  // 탭 상태
  activeTab: TabId
  tabBar: HTMLElement | null
  tabBarHandle: ReturnType<typeof import('../components/common/button').createTabBar> | null
  tabContent: HTMLElement | null
  rootEl: HTMLElement | null
  tabPanels: Record<TabId, HTMLElement> | null

  // 자동매매 탭 참조
  masterToggle: ReturnType<typeof createToggleBtn> | null
  autoBuyToggle: ReturnType<typeof createToggleBtn> | null
  buyTimeHandle: TimePairInputHandle | null
  autoSellToggle: ReturnType<typeof createToggleBtn> | null
  sellTimeHandle: TimePairInputHandle | null
  holidayBadgeEls: HTMLElement[]
  uiFlashToggle: ReturnType<typeof createToggleBtn> | null
  // 자동매수/매도 상태 배지 (자동매매 탭, 읽기 전용 — Step 2, P21)
  autoBuyBadge: HTMLElement | null
  autoSellBadge: HTMLElement | null

  // 실시간 뉴스 설정 (자동매매 탭)
  newsKeywordsTagChip: TagChipHandle | null
  newsTtlInput: ReturnType<typeof createNumInput> | null

  // 매매 안전장치 참조 (전역매매설정 섹션)
  riskManagerToggle: ReturnType<typeof createToggleBtn> | null
  riskManagerChildren: HTMLElement | null
  dailyLossToggle: ReturnType<typeof createToggleBtn> | null
  dailyLossInput: ReturnType<typeof createMoneyInput> | null
  dailyLossControls: HTMLElement | null
  dailyLossRateToggle: ReturnType<typeof createToggleBtn> | null
  dailyLossRateInput: ReturnType<typeof createNumInput> | null
  dailyLossRateControls: HTMLElement | null
  consecLossToggle: ReturnType<typeof createToggleBtn> | null
  consecLossInput: ReturnType<typeof createNumInput> | null
  consecLossControls: HTMLElement | null
  riskBlockBuyToggle: ReturnType<typeof createToggleBtn> | null
  riskBlockSellToggle: ReturnType<typeof createToggleBtn> | null

  // 확정 시세 다운로드 시간 (단일 슬롯) + 자동다운로드 토글
  confirmedDlSlot: HTMLElement | null
  confirmedDlToggle: ReturnType<typeof createToggleBtn> | null
  confirmedDlH: string
  confirmedDlM: string

  // 장 시작 전 사전 준비 시간 (타임테이블 사용자 조정 3개 슬롯)
  timetableResetSlot: HTMLElement | null
  timetableWsSlot: HTMLElement | null
  timetableKrxSlot: HTMLElement | null
  savingTimetable: boolean

  // 구독 한도
  subscribeMaxInput: ReturnType<typeof createNumInput> | null

  // 텔레그램 탭 참조
  teleToggle: ReturnType<typeof createToggleBtn> | null
  teleInputs: Record<string, HTMLInputElement>

  // 계정관리 탭 참조
  tradeModeRadioGroup: ReturnType<typeof createRadioGroup> | null
  testVirtualSection: HTMLElement | null
  depositInput: ReturnType<typeof createMoneyInput> | null
  depositDisplay: HTMLElement | null

  // API 설정 탭 참조
  apiKeyInputs: Record<string, HTMLInputElement>
  apiStatusBadges: Record<string, HTMLElement>
  apiSaveBtn: HTMLButtonElement | null
  brokerRadioGroup: ReturnType<typeof createRadioGroup> | null
  activeApiTab: 'kiwoom' | 'ls'
  apiTabButtons: Record<string, HTMLElement>
  brokerSaving: boolean

  // B21-01 세션7: 암호화 상태 배너 참조 (일반설정 상단 — 설계 7.1).
  encryptionBanner: HTMLElement | null
  // B21-01 세션7: 텔레그램 탭 필드 상태 배지 + 저장 버튼 참조.
  teleStatusBadges: Record<string, HTMLElement>
  teleSaveBtn: HTMLButtonElement | null
}

function createState(): GeneralSettingsState {
  return {
    settingsMgr: null,
    unsubSettings: null,
    vals: {},
    isTradingDay: true,
    tradingDayLoading: true,

    activeTab: 'auto-trade',
    tabBar: null,
    tabBarHandle: null,
    tabContent: null,
    rootEl: null,
    tabPanels: null,

    masterToggle: null,
    autoBuyToggle: null,
    buyTimeHandle: null,
    autoSellToggle: null,
    sellTimeHandle: null,
    holidayBadgeEls: [],
    uiFlashToggle: null,
    autoBuyBadge: null,
    autoSellBadge: null,

    newsKeywordsTagChip: null,
    newsTtlInput: null,

    riskManagerToggle: null,
    riskManagerChildren: null,
    dailyLossToggle: null,
    dailyLossInput: null,
    dailyLossControls: null,
    dailyLossRateToggle: null,
    dailyLossRateInput: null,
    dailyLossRateControls: null,
    consecLossToggle: null,
    consecLossInput: null,
    consecLossControls: null,
    riskBlockBuyToggle: null,
    riskBlockSellToggle: null,

    confirmedDlSlot: null,
    confirmedDlToggle: null,
    confirmedDlH: '20',
    confirmedDlM: '40',

    timetableResetSlot: null,
    timetableWsSlot: null,
    timetableKrxSlot: null,
    savingTimetable: false,

    subscribeMaxInput: null,

    teleToggle: null,
    teleInputs: {},

    tradeModeRadioGroup: null,
    testVirtualSection: null,
    depositInput: null,
    depositDisplay: null,

    apiKeyInputs: {},
    apiStatusBadges: {},
    apiSaveBtn: null,
    brokerRadioGroup: null,
    activeApiTab: 'kiwoom',
    apiTabButtons: {},
    brokerSaving: false,

    encryptionBanner: null,
    teleStatusBadges: {},
    teleSaveBtn: null,
  }
}

export const state: GeneralSettingsState = createState()

/* ── 헬퍼 ── */
export function shouldForceOff(): boolean {
  return !state.tradingDayLoading && !state.isTradingDay
}

export function createHolidayBadge(): HTMLElement {
  const span = document.createElement('span')
  Object.assign(span.style, { fontSize: FONT_SIZE.chip, color: COLOR.up, background: COLOR.upBg, borderRadius: RADIUS.xs, padding: '1px 6px', marginLeft: '6px', fontWeight: 'normal', display: 'none' })
  span.textContent = '비거래일'
  state.holidayBadgeEls.push(span)
  return span
}

export function updateHolidayBadges(): void {
  const show = shouldForceOff()
  for (const el of state.holidayBadgeEls) el.style.display = show ? 'inline' : 'none'
}

// 타임테이블 4개 키 저장 — 변경된 키만 전송 (P10 SSOT, P24 단순성)
// 백엔드 _validate_timetable_order()가 나머지 키를 DB에서 보충해 순서 검증
// 422 응답 시 api/client.ts가 detail 필드 추출 → toastResult가 검증 에러 메시지 토스트 (P21)
// onFail: 저장 실패 시 호출 (호출처에서 시간 슬롯 표시를 원래 값으로 복원 — P22/P23)
export function scheduleTimetableSave(
  key: 'timetable.realtime_reset' | 'timetable.ws_prestart' | 'timetable.krx_pre_subscribe' | 'timetable.confirmed_download',
  newVal: string,
  onFail?: () => void,
): void {
  if (!state.settingsMgr) return
  if (state.savingTimetable) return
  state.savingTimetable = true
  const run = async (): Promise<void> => {
    const serverVal = String(state.vals[key] ?? '')
    if (newVal !== serverVal) {
      const dirty: Record<string, unknown> = { [key]: newVal }
      const res = await state.settingsMgr!.saveSection(dirty)
      toastResult(res)
      if (res.ok) Object.assign(state.vals, dirty)
      else if (onFail) onFail()
    }
    state.savingTimetable = false
  }
  run()
}

/* ── 상태 초기화 (mount 시작 시 호출) ── */
export function resetState(): void {
  const fresh = createState()
  Object.assign(state, fresh)
}

/* ── B21-01 세션7: 암호화 상태 표시 헬퍼 (설계 7.2/9.2 — P24 중복 제거) ──
 * 배너·필드별 배지·오류 코드 매핑이 공유하는 메시지 SSOT.
 * 색상은 기존 COLOR 재사용 (신규 색상 체계 미생성 — P23). */

import type { EncryptionKeyState, SecretFieldStatus } from '../types'

export interface EncryptionStatusMessage {
  text: string
  color: string
  bg: string
}

// 암호화 키 상태별 메시지 (설계 7.2) — 일반설정 상단 배너에 사용.
export const ENCRYPTION_KEY_STATE_MESSAGES: Record<EncryptionKeyState, EncryptionStatusMessage> = {
  AVAILABLE: {
    text: '민감정보 암호화 정상',
    color: COLOR.success,
    bg: COLOR.successBg,
  },
  MISSING: {
    text: '암호화 키가 설정되지 않았습니다. API 키와 토큰을 저장할 수 없습니다.',
    color: COLOR.warning,
    bg: COLOR.warningBg,
  },
  INVALID: {
    text: '암호화 키를 사용할 수 없습니다. 키 설정을 확인한 뒤 다시 저장하세요.',
    color: COLOR.up,
    bg: COLOR.upBg,
  },
}

// 필드별 민감값 상태 메시지 (설계 7.2) — API/텔레그램 탭 필드 영역에 사용.
export const SECRET_FIELD_STATUS_MESSAGES: Record<SecretFieldStatus, EncryptionStatusMessage> = {
  EMPTY: { text: '', color: COLOR.tertiary, bg: 'transparent' },
  ENCRYPTED: { text: '암호화 저장됨', color: COLOR.success, bg: COLOR.successBg },
  PLAINTEXT_LEGACY: {
    text: '기존 인증정보가 안전하게 암호화되지 않았습니다. 인증정보를 다시 입력해 저장하세요.',
    color: COLOR.warning,
    bg: COLOR.warningBg,
  },
  KEY_UNAVAILABLE: {
    text: '암호화 키가 없어 저장된 인증정보를 읽을 수 없습니다.',
    color: COLOR.warning,
    bg: COLOR.warningBg,
  },
  DECRYPT_FAILED: {
    text: '저장된 인증정보를 복호화할 수 없습니다. 인증정보를 다시 입력하세요.',
    color: COLOR.up,
    bg: COLOR.upBg,
  },
}

// 저장 실패 오류 코드 → 사용자용 메시지 매핑 (설계 5 + 7.3).
// SaveResult.errorCode 기반 — 세션6가 ApiError에서 전달.
export const ENCRYPTION_ERROR_CODE_MESSAGES: Record<string, string> = {
  ENCRYPTION_KEY_MISSING: '암호화 키가 설정되지 않아 저장할 수 없습니다.',
  ENCRYPTION_KEY_INVALID: '암호화 키를 사용할 수 없어 저장할 수 없습니다. 키 설정을 확인하세요.',
  ENCRYPTION_FAILED: '인증정보 암호화에 실패해 저장할 수 없습니다.',
}

/** 오류 코드에 대응하는 사용자용 메시지 반환 (코드 없으면 기존 error 메시지 사용 — 하위 호환). */
export function mapEncryptionErrorMessage(errorCode?: string, fallback?: string): string {
  if (errorCode && ENCRYPTION_ERROR_CODE_MESSAGES[errorCode]) {
    return ENCRYPTION_ERROR_CODE_MESSAGES[errorCode]
  }
  return fallback ?? '저장 실패'
}

/** 암호화 키 백업 안내 문구 (설계 9.2). */
export const ENCRYPTION_KEY_BACKUP_GUIDE =
  'API 키와 텔레그램 토큰은 암호화하여 저장합니다. 암호화 키를 잃어버리면 저장된 인증정보를 복구할 수 없습니다. ' +
  '앱 데이터 백업과 암호화 키 백업을 서로 다른 안전한 장소에 보관하세요. 암호화 키를 화면이나 로그에 입력·기록하지 마세요.'

/** 현재 암호화 키 상태 조회 (vals에서 읽기 — 백엔드 GET /api/settings 응답 필드). */
export function currentEncryptionKeyState(): EncryptionKeyState | null {
  const v = state.vals.encryption_key_state
  if (v === 'AVAILABLE' || v === 'MISSING' || v === 'INVALID') return v
  return null
}

/** 지정 필드의 민감값 상태 조회 (vals.secret_field_states에서 읽기). */
export function currentSecretFieldStatus(field: string): SecretFieldStatus | null {
  const states = state.vals.secret_field_states
  if (states && typeof states === 'object') {
    const s = (states as Record<string, unknown>)[field]
    if (typeof s === 'string') return s as SecretFieldStatus
  }
  return null
}

/** 암호화 키가 없어(MISSING/INVALID) 민감정보 저장이 불가능한 상태인지 판정. */
export function isEncryptionBlockingSave(): boolean {
  const ks = currentEncryptionKeyState()
  return ks === 'MISSING' || ks === 'INVALID'
}
