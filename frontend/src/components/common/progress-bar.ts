// frontend/src/components/common/progress-bar.ts
// 진행률 바 공통 컴포넌트 — header.ts 인라인 패턴 추출 (P23 일관성)
// 사용처: header.ts (백그라운드 다운로드), sector-settings.ts (수신율)

import { COLOR } from './ui-styles'

export interface ProgressBarHandle {
  el: HTMLElement
  /** 진행률 설정 (0~100). fill 너비 + 색상 + 우측 % 텍스트 갱신. */
  setValue(pct: number): void
  /** 임계치 마커 위치 설정 (0~100, 미호출 시 마커 미표시 + 고정 색상). */
  setThreshold(thresholdPct: number): void
}

/**
 * 진행률에 따른 fill 색상 계산 — 임계치 기준 3구간 (P21 투명성).
 * - pct < threshold/2: 파랑 light (COLOR.downLight) — "아직 멀음"
 * - threshold/2 <= pct < threshold: 파랑 (COLOR.down) — "가까워짐"
 * - pct >= threshold: 초록 (COLOR.success) — "도달"
 * 임계치 미설정 시 기본 color 반환 (후방 호환).
 * 빨강 제거 — 증권 앱에서 빨강=위험/상승 관례와 충돌 회피 (P23 색 일관성).
 */
function _computeDynamicColor(pct: number, threshold: number | null, fallback: string): string {
  if (threshold === null) return fallback
  if (pct >= threshold) return COLOR.success
  if (pct >= threshold * 0.5) return COLOR.down
  return COLOR.downLight
}

/**
 * fill 색상을 그라데이션으로 변환 — light → 진함 부드러운 전환 (P23 시각 일관성).
 * COLOR.success/successLight, COLOR.down/downLight 매핑. 미매칭 시 단색 반환.
 */
function _colorGradient(color: string): string {
  if (color === COLOR.success) return `linear-gradient(to right, ${COLOR.successLight}, ${COLOR.success})`
  if (color === COLOR.down) return `linear-gradient(to right, ${COLOR.downLight}, ${COLOR.down})`
  return color
}

/**
 * 진행률 바 생성.
 * - fill: 좌측에서 우측으로 채워지는 색상 바 (width = pct%)
 * - threshold marker: 임계치 위치 세로선 (선택)
 * - pctText: 우측 끝 % 수치 (showPct=true 시 바와 같은 행)
 * - pctTop: 바 위 우측 고정 % 수치 (showPctTop=true 시) — showPct와 배타적
 * - 색상 변화: setThreshold 호출 시 자동 활성화 — 진행률에 따라 파랑light→파랑→초록
 * @param color fill 기본 색상 (COLOR 상수) — setThreshold 미호출 시 사용
 * @param options.showPct 우측 % 텍스트 표시 여부 (기본 true)
 * @param options.showPctTop 바 위 우측 고정 % 텍스트 표시 여부 (기본 false)
 * @param options.height 바 높이 (기본 '8px')
 */
export function createProgressBar(
  color: string = COLOR.down,
  options: { showPct?: boolean; height?: string; showPctTop?: boolean } = {},
): ProgressBarHandle {
  const { showPct = true, height = '8px', showPctTop = false } = options

  // 바 영역 (fill + marker 포함)
  const bar = document.createElement('div')
  Object.assign(bar.style, {
    position: 'relative',
    flex: '1',
    height,
    background: COLOR.neutralBg,
    borderRadius: '4px',
    overflow: 'visible',
  })

  // fill 바
  const fill = document.createElement('div')
  Object.assign(fill.style, {
    position: 'absolute',
    left: '0',
    top: '0',
    height: '100%',
    width: '0%',
    background: color,
    borderRadius: '4px',
    transition: 'width 0.3s ease, background 0.3s ease',
  })
  bar.appendChild(fill)

  // 임계치 마커 (초기 미표시)
  const marker = document.createElement('div')
  Object.assign(marker.style, {
    position: 'absolute',
    top: '-2px',
    height: 'calc(100% + 4px)',
    width: '2px',
    background: COLOR.tertiary,
    display: 'none',
    zIndex: '1',
  })
  bar.appendChild(marker)

  // 바 위 우측 고정 % 텍스트 — showPctTop=true 시 (바와 별도 행, 우측 정렬)
  let pctTopSpan: HTMLSpanElement | null = null
  let pctTopRow: HTMLDivElement | null = null
  if (showPctTop) {
    pctTopRow = document.createElement('div')
    Object.assign(pctTopRow.style, {
      display: 'flex',
      justifyContent: 'flex-end',
      marginBottom: '2px',
    })
    pctTopSpan = document.createElement('span')
    Object.assign(pctTopSpan.style, {
      fontSize: '12px',
      color: color,
      whiteSpace: 'nowrap',
      transition: 'color 0.3s ease',
    })
    pctTopSpan.textContent = '0%'
    pctTopRow.appendChild(pctTopSpan)
  }

  // 임계치 상태 (null = 고정 색상 모드)
  let _threshold: number | null = null

  function setValue(pct: number): void {
    const clamped = Math.max(0, Math.min(100, pct))
    fill.style.width = `${clamped}%`
    const dynamicColor = _computeDynamicColor(clamped, _threshold, color)
    fill.style.background = _colorGradient(dynamicColor)
    if (pctSpan) {
      pctSpan.textContent = `${clamped.toFixed(1)}%`
      pctSpan.style.color = dynamicColor
    }
    if (pctTopSpan) {
      pctTopSpan.textContent = `${clamped.toFixed(1)}%`
      pctTopSpan.style.color = dynamicColor
    }
  }

  function setThreshold(thresholdPct: number): void {
    const clamped = Math.max(0, Math.min(100, thresholdPct))
    _threshold = clamped
    marker.style.left = `${clamped}%`
    marker.style.display = ''
    // 임계치 설정 시 현재 값 기준으로 색상 즉시 갱신
    const curWidth = parseFloat(fill.style.width) || 0
    const dynamicColor = _computeDynamicColor(curWidth, _threshold, color)
    fill.style.background = _colorGradient(dynamicColor)
    if (pctSpan) pctSpan.style.color = dynamicColor
    if (pctTopSpan) pctTopSpan.style.color = dynamicColor
  }

  // 우측 % 텍스트 (showPct=true 시 바와 같은 행 배치)
  let pctSpan: HTMLSpanElement | null = null
  if (showPct) {
    const row = document.createElement('div')
    Object.assign(row.style, {
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      width: '100%',
    })
    row.appendChild(bar)
    pctSpan = document.createElement('span')
    Object.assign(pctSpan.style, {
      fontSize: '12px',
      color: color,
      whiteSpace: 'nowrap',
      minWidth: '42px',
      textAlign: 'right',
      transition: 'color 0.3s ease',
    })
    pctSpan.textContent = '0%'
    row.appendChild(pctSpan)
    return { el: row, setValue, setThreshold }
  }

  // showPctTop=true 시: % 행(우측 정렬) + 바를 세로 컨테이너로 감싸기
  if (showPctTop && pctTopRow) {
    const wrap = document.createElement('div')
    wrap.appendChild(pctTopRow)
    wrap.appendChild(bar)
    return { el: wrap, setValue, setThreshold }
  }

  return { el: bar, setValue, setThreshold }
}
