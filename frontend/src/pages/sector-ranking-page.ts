// frontend/src/pages/sector-ranking-page.ts
// 업종순위 페이지 코디네이터 — triple 레이아웃 3패널 조율
// 좌측: 설정 (sector-settings), 중앙: 업종순위 (sector-ranking-list), 우측: 종목시세 (sector-stock-table)

import { shell } from '../main'
import { SETTINGS_PANEL_WIDTH } from '../layout/shell'
import sectorSettings from './sector-settings'
import sectorRankingList from './sector-ranking-list'
import type { PageModule } from '../router'

// 기본 flex 값 (stock-classification용) — unmount 시 복원
const DEFAULT_TRIPLE_LEFT_FLEX = '4'
const DEFAULT_TRIPLE_CENTER_FLEX = '3'
const DEFAULT_TRIPLE_RIGHT_FLEX = '3'
const DEFAULT_TRIPLE_LEFT_PADDING = '16px'
const DEFAULT_TRIPLE_CENTER_PADDING = '16px'
const DEFAULT_TRIPLE_RIGHT_PADDING = '16px'

let stockTableEl: HTMLElement | null = null

/* ── mount ── */
function mount(_container: HTMLElement): void {
  // triple 패널 초기화 (이전 페이지 잔류물 제거)
  while (shell.tripleHeader.firstChild) shell.tripleHeader.removeChild(shell.tripleHeader.firstChild)
  while (shell.tripleLeft.firstChild) shell.tripleLeft.removeChild(shell.tripleLeft.firstChild)
  while (shell.tripleCenter.firstChild) shell.tripleCenter.removeChild(shell.tripleCenter.firstChild)
  while (shell.tripleRight.firstChild) shell.tripleRight.removeChild(shell.tripleRight.firstChild)

  // tripleHeader 사용 안함 (sector-ranking은 헤더 불필요)
  shell.tripleHeader.style.display = 'none'

  // 좌측 패널: leftPanel(dual)과 동일 스타일 — SETTINGS_PANEL_WIDTH 상수 사용
  shell.tripleLeft.style.flex = `0 0 ${SETTINGS_PANEL_WIDTH}px`
  shell.tripleLeft.style.width = `${SETTINGS_PANEL_WIDTH}px`
  shell.tripleLeft.style.minWidth = `${SETTINGS_PANEL_WIDTH}px`
  shell.tripleLeft.style.padding = '8px'
  // 중앙·우측: 남은 공간 분할 (1:2.5) — 중앙 패널 너비 확대로 업종명 짤림 완화
  shell.tripleCenter.style.flex = '1'
  shell.tripleRight.style.flex = '2.5'
  // 패널 padding 16px→8px — 좌측 패널(8px)과 일치시켜 컬럼 너비 확보 (P21 가독성, P23 일관성)
  shell.tripleCenter.style.padding = '8px'
  shell.tripleRight.style.padding = '8px'

  // 좌측: 설정 패널 마운트
  sectorSettings.mount(shell.tripleLeft)

  // 중앙: 업종 순위 리스트 마운트
  sectorRankingList.mount(shell.tripleCenter)

  // 우측: 종목 시세 테이블 (Web Component)
  stockTableEl = document.createElement('sector-stock-table')
  shell.tripleRight.appendChild(stockTableEl)
}

/* ── unmount ── */
function unmount(): void {
  // 설정 패널 언마운트
  sectorSettings.unmount()

  // 순위 리스트 언마운트
  sectorRankingList.unmount()

  // 종목 시세 테이블 제거 (disconnectedCallback → notifyPageInactive 자동 호출)
  if (stockTableEl && stockTableEl.parentNode) {
    stockTableEl.parentNode.removeChild(stockTableEl)
  }
  stockTableEl = null

  // triple 패널 클리어
  while (shell.tripleHeader.firstChild) shell.tripleHeader.removeChild(shell.tripleHeader.firstChild)
  while (shell.tripleLeft.firstChild) shell.tripleLeft.removeChild(shell.tripleLeft.firstChild)
  while (shell.tripleCenter.firstChild) shell.tripleCenter.removeChild(shell.tripleCenter.firstChild)
  while (shell.tripleRight.firstChild) shell.tripleRight.removeChild(shell.tripleRight.firstChild)

  // tripleLeft 스타일 복원 (stock-classification용)
  shell.tripleLeft.style.flex = DEFAULT_TRIPLE_LEFT_FLEX
  shell.tripleLeft.style.width = ''
  shell.tripleLeft.style.minWidth = ''
  shell.tripleLeft.style.padding = DEFAULT_TRIPLE_LEFT_PADDING
  shell.tripleCenter.style.flex = DEFAULT_TRIPLE_CENTER_FLEX
  shell.tripleCenter.style.padding = DEFAULT_TRIPLE_CENTER_PADDING
  shell.tripleRight.style.flex = DEFAULT_TRIPLE_RIGHT_FLEX
  shell.tripleRight.style.padding = DEFAULT_TRIPLE_RIGHT_PADDING

  // tripleHeader 표시 상태 복원
  shell.tripleHeader.style.display = 'flex'
}

export default { mount, unmount } satisfies PageModule
