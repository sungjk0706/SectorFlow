// frontend/src/pages/stock-classification-header.ts
// 업종관리 페이지 — tripleHeader + Indicator_Bar + 다운로드 트리거 (F-04 분할 3단계, P24 단순성)
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
    hoverColor: '#157347',
    onClick: (e) => onTriggerConfirmedDownload(e),
  })
  const btn2 = createSolidBtn({
    label: '⬇️ 5거래일 일봉차트 거래대금,고가 다운로드',
    color: COLOR.success,
    hoverColor: '#157347',
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
    fontSize: FONT_SIZE.small, color: COLOR.tertiary, whiteSpace: 'nowrap',
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

  // 당일 데이터 존재 여부 사전 확인 (P21 사용자 투명성)
  let dataExists: boolean
  try {
    const check = await api.get<{ confirmed_exists: boolean; '5d_exists': boolean }>(
      '/api/stock-classification/download-data-exists',
    )
    dataExists = check['5d_exists']
  } catch {
    toastResult({ ok: false, error: '데이터 저장 여부 확인에 실패했습니다.' })
    return
  }

  const message = dataExists
    ? `이미 당일 5거래일 일봉 데이터가 저장되어 있습니다.\n${label}를 다시 실행하시겠습니까?\n이 작업은 백그라운드에서 진행됩니다.`
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
