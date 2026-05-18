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

  schedulerToggle1 = createToggleBtn({
    on: props.schedulerMarketCloseOn ?? true,
    onClick: () => {
      if (props.onToggleScheduler && schedulerToggle1) {
        props.onToggleScheduler('scheduler_market_close_on', !schedulerToggle1.isOn())
      }
    },
  })
  const row1Label = document.createElement('div')
  const row1Title = document.createElement('div')
  row1Title.style.fontWeight = FONT_WEIGHT.normal
  row1Title.textContent = '전종목 확정시세 다운로드(매일 20:30)'
  const row1Desc = document.createElement('div')
  Object.assign(row1Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  row1Desc.textContent = '전종목 목록 + 확정 시세 + 당일 거래대금 롤링'
  row1Label.appendChild(row1Title)
  row1Label.appendChild(row1Desc)
  card.appendChild(createSettingRow(row1Label, schedulerToggle1.el))

  schedulerToggle2 = createToggleBtn({
    on: props.scheduler5dDownloadOn ?? true,
    onClick: () => {
      if (props.onToggleScheduler && schedulerToggle2) {
        props.onToggleScheduler('scheduler_5d_download_on', !schedulerToggle2.isOn())
      }
    },
  })
  const row2Label = document.createElement('div')
  const row2Title = document.createElement('div')
  row2Title.style.fontWeight = FONT_WEIGHT.normal
  row2Title.textContent = '전종목 5일 거래대금 다운로드'
  const row2Desc = document.createElement('div')
  Object.assign(row2Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  row2Desc.textContent = '전종목 5일 거래대금 REST 다운로드 (캐시 만료 시 자동 실행)'
  row2Label.appendChild(row2Title)
  row2Label.appendChild(row2Desc)
  card.appendChild(createSettingRow(row2Label, schedulerToggle2.el))

  container.appendChild(card)
}

/* ── 데이터 관리 카드 ── */

export function buildDataManageCard(container: HTMLElement, props: SectorSchedulerUiProps): void {
  const card = cardWrap()
  const dataManageTitle = createCardTitleWithContent('데이터 관리 (키움증권 기준)')
  dataManageTitle.style.fontSize = FONT_SIZE.section
  card.appendChild(dataManageTitle)

  // 시세 캐시 삭제
  const cache1Row = document.createElement('div')
  Object.assign(cache1Row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #eee' })
  const cache1Info = document.createElement('div')
  const cache1Title = document.createElement('div')
  cache1Title.style.fontWeight = FONT_WEIGHT.normal
  cache1Title.textContent = '🗑️ 전종목 확정시세 캐시 삭제'
  const cache1Desc = document.createElement('div')
  Object.assign(cache1Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  cache1Desc.textContent = '확정 시세 + 종목명 + 업종 레이아웃 캐시를 삭제합니다. 장마감 전종목 확정시세 다운로드로 복구됩니다'
  cache1Info.appendChild(cache1Title)
  cache1Info.appendChild(cache1Desc)
  const cacheSnapshotBtn = actionBtn('삭제', '#dc3545')
  cacheSnapshotBtn.addEventListener('click', () => {
    if (confirm('전종목 확정시세 저장데이터를 삭제하시겠습니까?') && props.onDeleteCache) {
      props.onDeleteCache('snapshot')
    }
  })
  cache1Row.appendChild(cache1Info)
  cache1Row.appendChild(cacheSnapshotBtn)
  card.appendChild(cache1Row)

  // 전종목 5일 거래대금 캐시 삭제
  const cache2Row = document.createElement('div')
  Object.assign(cache2Row.style, { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' })
  const cache2Info = document.createElement('div')
  const cache2Title = document.createElement('div')
  cache2Title.style.fontWeight = FONT_WEIGHT.normal
  cache2Title.textContent = '🗑️ 전종목 5일 거래대금,고가 저장데이터 삭제'
  const cache2Desc = document.createElement('div')
  Object.assign(cache2Desc.style, { fontSize: FONT_SIZE.small, color: '#888' })
  cache2Desc.textContent = '전종목 5일 거래대금,고가 저장데이터를 삭제합니다. 전종목 5일 전체 다운로드로 복구됩니다'
  cache2Info.appendChild(cache2Title)
  cache2Info.appendChild(cache2Desc)
  const cacheAvgAmtBtn = actionBtn('삭제', '#dc3545')
  cacheAvgAmtBtn.addEventListener('click', () => {
    if (confirm('전종목 5일 거래대금,고가 저장데이터를 삭제하시겠습니까?') && props.onDeleteCache) {
      props.onDeleteCache('avg_amt')
    }
  })
  cache2Row.appendChild(cache2Info)
  cache2Row.appendChild(cacheAvgAmtBtn)
  card.appendChild(cache2Row)

  container.appendChild(card)
}

/* ── 메인 렌더 함수 ── */

export function renderSectorSchedulerUi(
  container: HTMLElement,
  props: SectorSchedulerUiProps
): void {
  buildSchedulerCard(container, props)
  buildDataManageCard(container, props)
}

/* ── Props 갱신 ── */

export function updateSectorSchedulerUi(props: SectorSchedulerUiProps): void {
  if (schedulerToggle1) {
    schedulerToggle1.setOn(props.schedulerMarketCloseOn ?? true)
  }
  if (schedulerToggle2) {
    schedulerToggle2.setOn(props.scheduler5dDownloadOn ?? true)
  }
}
