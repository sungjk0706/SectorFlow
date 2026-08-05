/**
 * DataTable 옵션 생성 헬퍼 — 페이지별 반복 설정을 공통화 (P23 일관성 · P24 단순성).
 *
 * 컴포넌트 인터페이스(DataTableOptions)는 그대로 사용하고, 옵션 "생성" 단계만 공통화한다.
 * 새 페이지는 헬퍼 한 줄로 동일 설정을 얻어 높이/스크롤/옵션을 다시 고민하지 않는다.
 *
 * 높이 계약(결정 1·3): 컴포넌트가 스스로 flex:1, minHeight:0을 부여하므로,
 * 페이지는 "높이가 제한된 flex 부모"에 컴포넌트를 넣기만 하면 된다.
 */

import type { DataTableOptions } from './data-table'

/**
 * 가상 스크롤 표준 옵션 프리셋.
 * - rowHeight: 32 (모든 가상 스크롤 페이지 표준 행 높이)
 * - stickyHeader: true (헤더 고정)
 * - zebraStriping: 기본 false, 필요 시 override
 *
 * 페이지 고유 옵션(columns·keyFn·emptyText·rowStyle·rowFooter·groupRowHeight·widthReady)은
 * 반환된 객체에 스프레드로 덮어쓴다.
 */
export function virtualScrollOptions<T extends object>(
  overrides: Omit<DataTableOptions<T>, 'virtualScroll' | 'rowHeight' | 'stickyHeader'> & {
    rowHeight?: number
    stickyHeader?: boolean
  },
): DataTableOptions<T> {
  return {
    virtualScroll: true,
    rowHeight: 32,
    stickyHeader: true,
    ...overrides,
  }
}

/**
 * 고정(비가상) 표준 옵션 프리셋.
 * - virtualScroll: false
 * - stickyHeader: 기본 true, 필요 시 override
 *
 * 보유종목·종목분류 등 행 수가 적어 비가상 모드가 적절한 페이지용.
 * 바깥 상자 규칙은 가상 모드와 동일(flex 부모에 컴포넌트 배치).
 */
export function fixedTableOptions<T extends object>(
  overrides: Omit<DataTableOptions<T>, 'virtualScroll'> & {
    stickyHeader?: boolean
  },
): DataTableOptions<T> {
  return {
    virtualScroll: false,
    stickyHeader: true,
    ...overrides,
  }
}

/**
 * 표 컨테이너 스타일 — 페이지가 표를 담는 바깥 상자에 적용하는 단일 규칙 (결정 2·3).
 *
 * 페이지는 이 스타일을 적용한 상자 하나에 컴포넌트를 넣기만 하면 된다.
 * - overflowY:auto를 바깥에 두지 않음 (컴포넌트 내부 단일 스크롤)
 * - flex:1 + minHeight:0으로 남은 공간 차지 + 높이 제한 전파
 */
export const TABLE_CONTAINER_STYLE = {
  display: 'flex',
  flexDirection: 'column',
  flex: '1',
  minHeight: '0',
  overflow: 'hidden',
} as const

/**
 * 표 토글 시 display 값 — flex 설정을 유지 (빈 문자열 '' 덮어쓰기 금지).
 *
 * 표 컴포넌트(wrapper)는 display:flex 기반이므로, 토글 시에도 'flex'를 사용해야
 * 자식 flex:1이 무효화되지 않는다. 수읉상세 버그(2026-08-05)의 근본 원인이
 * 빈 문자열 덮어쓰기로 flex가 풀리는 것이었음.
 */
export const TABLE_DISPLAY_VISIBLE = 'flex'
export const TABLE_DISPLAY_HIDDEN = 'none'
