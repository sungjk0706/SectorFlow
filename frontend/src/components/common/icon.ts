/**
 * 공통 SVG 아이콘 도우미 — Lucide 아이콘 라이브러리 기반 (P23 일관성, P24 단순성).
 *
 * 화면 전체 이모지를 크로스 플랫폼 선 스타일 SVG 아이콘으로 통일.
 * 맥·윈도우 양쪽에서 동일한 아이콘 모양으로 렌더링 (이모지 운영체제별 차이 해결).
 *
 * 사용: createIcon('bar-chart', { size: 16 }) → SVGElement 반환
 * 색상: stroke="currentColor" 기본값 → 부모 글자색 자동 상속
 *      별도 색상 지정 시 options.color 사용
 */

import { createElement } from 'lucide'
import {
  BarChart3, Wallet, TrendingDown, TrendingUp, ClipboardList,
  Tag, Search, Settings, Newspaper, Activity, Package, Pin,
  Check, X, TriangleAlert, Info, Download, CircleCheck, CircleX, Trash2,
} from 'lucide'
import type { IconNode } from 'lucide'

const ICON_MAP = {
  'bar-chart': BarChart3,
  'wallet': Wallet,
  'trending-down': TrendingDown,
  'trending-up': TrendingUp,
  'clipboard-list': ClipboardList,
  'tag': Tag,
  'search': Search,
  'settings': Settings,
  'newspaper': Newspaper,
  'activity': Activity,
  'package': Package,
  'pin': Pin,
  'check': Check,
  'x': X,
  'alert-triangle': TriangleAlert,
  'info': Info,
  'download': Download,
  'circle-check': CircleCheck,
  'circle-x': CircleX,
  'trash-2': Trash2,
} as const

export type IconName = keyof typeof ICON_MAP

export interface IconOptions {
  size?: number
  color?: string
  strokeWidth?: number
}

/**
 * SVG 아이콘 요소 생성.
 * @param name 아이콘 이름 (ICON_MAP 키)
 * @param options size=16 기본, color 미지정 시 부모 글자색 상속(currentColor)
 * @returns SVGElement — DOM에 appendChild로 추가
 */
export function createIcon(name: IconName, options?: IconOptions): SVGElement {
  const iconNode: IconNode = ICON_MAP[name]
  const size = options?.size ?? 16
  const customAttrs: Record<string, string | number> = {
    width: size,
    height: size,
  }
  if (options?.color) customAttrs.stroke = options.color
  if (options?.strokeWidth != null) customAttrs['stroke-width'] = options.strokeWidth
  return createElement(iconNode, customAttrs)
}
