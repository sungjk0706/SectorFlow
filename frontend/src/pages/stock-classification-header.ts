// frontend/src/pages/stock-classification-header.ts
// 종목분류 페이지 — tripleHeader + Indicator_Bar + 다운로드 트리거 (F-04 분할 3단계, P24 단순성)
// stock-classification.ts에서 이관. 순수 이동, 동작 변경 없음.
//
// 포함:
//   - buildHeaderLeft / buildHeaderCenter / buildHeaderRight (private)
//   - buildTripleHeader(state) (export — mount 시 호출)
//   - updateIndicatorBar(state) (export — store 구독 시 호출)
//   - onTriggerConfirmedDownload / onTrigger5dDownload (private — buildHeaderLeft onClick에서만 참조)

import { shell } from '../main'
import { stockClassificationStore } from '../stores/stockClassificationStore'
import { uiStore } from '../stores/uiStore'
import { api } from '../api/client'
import { toastResult } from '../components/common/toast'
import { showContextPopup } from '../components/common/context-popup'
import { createSolidBtn } from '../components/common/button'
import { createStepLabel } from '../components/common/settings-common'
import { FONT_SIZE, FONT_FAMILY, COLOR } from '../components/common/ui-styles'
import type { StockClassificationMutationResponse } from '../types'
import { handleMutationResult } from './stock-classification-shared'
import type { StockClassificationPageState } from './stock-classification'

/* ── 8.2: tripleHeader — 공통 헤더 (Indicator_Bar) ── */

function buildHeaderLeft(): HTMLElement {
  const left = document.createElement('div')
  Object.assign(left.style, {
    flex: '1', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start', gap: '6px', alignItems: 'flex-start'
  })

  const descLabel = createStepLabel('', '장마감 후 매매적격종목 확정시세 및 5거래일 일봉 거래대금,고가 데이터 저장', { whiteSpace: 'nowrap' })
  left.appendChild(descLabel)

  const buttonContainer = document.createElement('div')
  Object.assign(buttonContainer.style, { display: 'flex', gap: '6px' })

  const btn1 = createSolidBtn({
    label: '⬇️ 일봉차트 시세 다운로드',
    color: COLOR.success,
    hoverColor: COLOR.successHover,
    onClick: (e) => onTriggerConfirmedDownload(e),
  })
  const btn2 = createSolidBtn({
    label: '⬇️ 5거래일 일봉차트 거래대금,고가 다운로드',
    color: COLOR.success,
    hoverColor: COLOR.successHover,
    onClick: (e) => onTrigger5dDownload(e),
  })

  buttonContainer.appendChild(btn1)
  buttonContainer.appendChild(btn2)
  left.appendChild(buttonContainer)
  return left
}

function buildHeaderCenter(): HTMLElement {
  const center = document.createElement('div')
  Object.assign(center.style, {
    flex: '1', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
    textAlign: 'center', fontSize: FONT_SIZE.title,
    minWidth: '0',
  })
  return center
}

function buildHeaderRight(state: StockClassificationPageState): HTMLElement {
  const right = document.createElement('div')
  Object.assign(right.style, {
    flex: '3', display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
    justifyContent: 'center', textAlign: 'right', minWidth: '0', gap: '2px',
  })

  state.indicatorLabelMain = document.createElement('span')
  Object.assign(state.indicatorLabelMain.style, {
    fontSize: FONT_SIZE.body, color: COLOR.neutral, whiteSpace: 'nowrap',
    overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%',
  })

  state.indicatorLabelSub = document.createElement('span')
  Object.assign(state.indicatorLabelSub.style, {
    fontSize: FONT_SIZE.label, color: COLOR.tertiary, whiteSpace: 'nowrap',
    overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%',
  })

  right.appendChild(state.indicatorLabelMain)
  right.appendChild(state.indicatorLabelSub)
  return right
}

export function buildTripleHeader(state: StockClassificationPageState): void {
  const header = shell.tripleHeader
  while (header.firstChild) header.removeChild(header.firstChild)
  header.style.fontFamily = FONT_FAMILY
  header.appendChild(buildHeaderLeft())
  header.appendChild(buildHeaderCenter())
  header.appendChild(buildHeaderRight(state))
}

export function updateIndicatorBar(state: StockClassificationPageState): void {
  const storeState = stockClassificationStore.getState()
  const { filter_summary } = storeState
  if (!state.indicatorLabelMain || !state.indicatorLabelSub) return
  if (!filter_summary) {
    state.indicatorLabelMain.textContent = ''
    state.indicatorLabelSub.textContent = ''
    return
  }
  // "전체 N종목 → 매매 가능 N종목 (제외 N종목, N%)" | "주요 제외: ..."
  const sepIdx = filter_summary.indexOf(' | ')
  if (sepIdx === -1) {
    state.indicatorLabelMain.textContent = filter_summary
    state.indicatorLabelSub.textContent = ''
  } else {
    state.indicatorLabelMain.textContent = filter_summary.slice(0, sepIdx)
    state.indicatorLabelSub.textContent = filter_summary.slice(sepIdx + 3)
  }
}

async function onTriggerConfirmedDownload(e: MouseEvent): Promise<void> {
  const label = '일봉차트 시세 다운로드'
  const endpoint = '/api/stock-classification/trigger-confirmed-download'

  // 설정 재로드 완료 확인
  const { engineReloadComplete } = uiStore.getState()
  if (!engineReloadComplete) {
    toastResult({ ok: false, error: '설정 재로드가 완료되지 않았습니다. 잠시 후 다시 시도하세요.' })
    return
  }

  // 당일 데이터 존재 여부 사전 확인 (P21 사용자 투명성)
  let dataExists: boolean
  try {
    const check = await api.get<{ confirmed_exists: boolean; '5d_exists': boolean }>(
      '/api/stock-classification/download-data-exists',
    )
    dataExists = check.confirmed_exists
  } catch {
    // 확인 API 실패 시 기존 동작 유지 (폴백 아님 — 사용자에게 알림)
    toastResult({ ok: false, error: '데이터 저장 여부 확인에 실패했습니다.' })
    return
  }

  const message = dataExists
    ? `이미 당일 시세 데이터가 저장되어 있습니다.\n${label}를 다시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`
    : `${label}를 지금 수동으로 즉시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`

  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: `${label} 실행`,
    message,
    confirmText: '실행',
    confirmColor: COLOR.success,
  })

  if (!result.confirmed) return

  try {
    const res = await api.post<StockClassificationMutationResponse>(endpoint, {})
    handleMutationResult(res)
  } catch {
    toastResult({ ok: false })
  }
}

async function onTrigger5dDownload(e: MouseEvent): Promise<void> {
  const label = '5거래일 일봉차트 거래대금,고가 다운로드'
  const endpoint = '/api/stock-classification/trigger-5d-download'

  // 설정 재로드 완료 확인
  const { engineReloadComplete } = uiStore.getState()
  if (!engineReloadComplete) {
    toastResult({ ok: false, error: '설정 재로드가 완료되지 않았습니다. 잠시 후 다시 시도하세요.' })
    return
  }

  // 종목별 최근 5거래일 완전성 사전 확인 (설계서 결정 5, 세션 4·5)
  // 기존 하루 자료 존재 여부(5d_exists)에서 5거래일 완전성 기준으로 확장.
  // 새 필드: ok_count·ineligible_count·missing_days·has_missing_amounts·has_missing_highs
  let check: {
    confirmed_exists: boolean
    '5d_exists': boolean
    ok_count: number
    ineligible_count: number
    missing_days: string[]
    has_missing_amounts: boolean
    has_missing_highs: boolean
  }
  try {
    check = await api.get<typeof check>(
      '/api/stock-classification/download-data-exists',
    )
  } catch {
    toastResult({ ok: false, error: '데이터 저장 여부 확인에 실패했습니다.' })
    return
  }

  // 5거래일 완전성 기준 — 정상 종목만 있고 빠진 날·값 누락이 없으면 완전 준비
  const fullyPrepared = check.ok_count > 0
    && check.ineligible_count === 0
    && check.missing_days.length === 0
    && !check.has_missing_amounts
    && !check.has_missing_highs

  // 메시지에 종목별 상태 수 반영 (P21 사용자 투명성 — 설계서 결정 5)
  const detailLines: string[] = []
  if (check.ok_count > 0) detailLines.push(`정상 ${check.ok_count}종목`)
  if (check.ineligible_count > 0) detailLines.push(`부적합 ${check.ineligible_count}종목`)
  if (check.missing_days.length > 0) detailLines.push(`빠진 거래일 ${check.missing_days.length}일`)
  if (check.has_missing_amounts) detailLines.push('거래대금 누락 있음')
  if (check.has_missing_highs) detailLines.push('고가 누락 있음')
  const detail = detailLines.length > 0 ? `\n(${detailLines.join(', ')})` : ''

  const message = fullyPrepared
    ? `이미 5거래일 자료가 모두 준비되어 있습니다.${detail}\n${label}를 다시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`
    : `${label}를 지금 수동으로 즉시 실행하시겠습니까?${detail}\n이 작업은 백그라운드에서 진행됩니다.`

  const result = await showContextPopup({
    type: 'confirm',
    x: e.clientX,
    y: e.clientY,
    title: `${label} 실행`,
    message,
    confirmText: '실행',
    confirmColor: COLOR.success,
  })

  if (!result.confirmed) return

  try {
    const res = await api.post<StockClassificationMutationResponse>(endpoint, {})
    handleMutationResult(res)
  } catch {
    toastResult({ ok: false })
  }
}
