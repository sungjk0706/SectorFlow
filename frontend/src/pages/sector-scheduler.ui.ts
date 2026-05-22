// frontend/src/pages/sector-scheduler.ui.ts
// 업종분류 커스텀 페이지 — 스케줄러 카드 + 데이터 관리 카드

import { FONT_SIZE, FONT_FAMILY, FONT_WEIGHT } from '../components/common/ui-styles'
import { createCardTitleWithContent } from '../components/common/card-title'
import { createSettingRow, createToggleBtn } from '../components/common/setting-row'

/* ── Props 타입 ── */

export interface SectorSchedulerUiProps {
  schedulerMarketCloseOn?: boolean
  scheduler5dDownloadOn?: boolean
  onToggleScheduler?: (key: string, value: boolean) => void
  onDeleteCache?: (type: 'snapshot' | 'avg_amt') => void
}

/* ── UI 참조 ── */

let schedulerToggle1: ReturnType<typeof createToggleBtn> | null = null
let schedulerToggle2: ReturnType<typeof createToggleBtn> | null = null

/* ── 공통: 액션 버튼 ── */
function actionBtn(text: string, color = '#198754'): HTMLButtonElement {
  const btn = document.createElement('button')
  Object.assign(btn.style, {
    padding: '4px 10px', border: 'none', borderRadius: '4px',
    background: color, color: '#fff', cursor: 'pointer',
    fontSize: FONT_SIZE.small, fontFamily: FONT_FAMILY,
    flexShrink: '0', whiteSpace: 'nowrap',
  })
  btn.textContent = text
  return btn
}

/* ── 공통: 카드 래퍼 ── */
function cardWrap(): HTMLElement {
  const div = document.createElement('div')
  Object.assign(div.style, {
    background: '#fff', border: '1px solid #ddd', borderRadius: '8px',
    padding: '16px', marginBottom: '12px',
  })
  return div
}

/* ── 스케줄러 카드 ── */

export function buildSchedulerCard(container: HTMLElement, props: SectorSchedulerUiProps): void {
  const card = cardWrap()
  const schedulerTitle = createCardTitleWithContent('장마감 후 데이터 갱신 (키움증권 기준)')
  schedulerTitle.style.fontSize = FONT_SIZE.section
  card.appendChild(schedulerTitle)

  // 1. 전종목 확정시세 다운로드 (수동)
  const row1Label = document.createElement('div')
  const row1Title = document.createElement('div')
  row1Title.style.fontWeight = FONT_WEIGHT.normal
  row1Title.textContent = '전종목 확정시세 다운로드'
  const row1Desc = document.createElement('div')
  Object.assign(row1Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  row1Desc.textContent = '전종목 목록 + 확정 시세 + 당일 거래대금을 수동으로 즉시 갱신합니다'
  row1Label.appendChild(row1Title)
  row1Label.appendChild(row1Desc)

  const btn1 = actionBtn('수동 실행', '#198754')
  btn1.addEventListener('click', () => {
    if (props.onToggleScheduler) props.onToggleScheduler('trigger_snapshot_download', true)
  })
  card.appendChild(createSettingRow(row1Label, btn1))

  // 2. 전종목 5일 거래대금 다운로드 (수동)
  const row2Label = document.createElement('div')
  const row2Title = document.createElement('div')
  row2Title.style.fontWeight = FONT_WEIGHT.normal
  row2Title.textContent = '전종목 5일 거래대금 다운로드'
  const row2Desc = document.createElement('div')
  Object.assign(row2Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  row2Desc.textContent = '전종목 5일 거래대금 전체를 수동으로 즉시 갱신합니다'
  row2Label.appendChild(row2Title)
  row2Label.appendChild(row2Desc)

  const btn2 = actionBtn('수동 실행', '#198754')
  btn2.addEventListener('click', () => {
    if (props.onToggleScheduler) props.onToggleScheduler('trigger_avg_amt_download', true)
  })
  card.appendChild(createSettingRow(row2Label, btn2))

  container.appendChild(card)
}

/* ── 메인 렌더 함수 ── */

export function renderSectorSchedulerUi(
  container: HTMLElement,
  props: SectorSchedulerUiProps
): void {
  buildSchedulerCard(container, props)
}

/* ── Props 갱신 ── */

export function updateSectorSchedulerUi(props: SectorSchedulerUiProps): void {
  // 토글 UI가 제거되었으므로 더 이상 상태 갱신은 필요하지 않습니다.
}
