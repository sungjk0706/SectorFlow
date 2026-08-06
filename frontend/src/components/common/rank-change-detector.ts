/**
 * 공통 순위 변동 감지 도구 — "바뀐 업종 중 순위가 바뀐 것이 있는가?" 판정.
 *
 * 업종순위 패널(sector-ranking-list.ts)과 업종별 종목 시세 패널(sector-stock.ts)이
 * 같은 판정 로직을 공유하도록 추출 (W11 표현 통일 · W12 중복 제거).
 *
 * 판정 기준은 백엔드가 보내는 delta 정보(changed_sectors)를 그대로 사용 —
 * 프론트가 새로 판단 로직을 만들지 않음 (W3 SSOT — 백엔드가 변경 감지의 단일 소스).
 *
 * 관련 원칙: W3(SSOT) · W4(단계 간 정합성) · W11(표현 통일) · W12(중복 제거)
 */

import type { SectorScoreRow } from '../../types'

/** 순위 변동 감지 도구 인터페이스 — reset/detect 두 동작만 노출. */
export interface RankChangeDetector {
  /** 이전 업종별 순위 맵 재구축 — 전체 갱신 후 호출하여 다음 감지 기준 갱신. */
  reset: (scores: SectorScoreRow[]) => void
  /** rank 변동 감지 — changed_sectors 중 하나라도 이전 순위와 다르거나 새 업종이면 true. */
  detect: (changedSectors: string[], currentScores: SectorScoreRow[]) => boolean
}

/**
 * 순위 변동 감지 도구 생성.
 * 각 패널이 자신의 인스턴스를 갖고 같은 로직을 공유 (W11 표현 통일).
 * @returns reset/detect 인터페이스
 */
export function createRankChangeDetector(): RankChangeDetector {
  let prevRanks = new Map<string, number>()

  function reset(scores: SectorScoreRow[]): void {
    prevRanks = new Map()
    for (const s of scores) prevRanks.set(s.sector, s.rank)
  }

  function detect(changedSectors: string[], currentScores: SectorScoreRow[]): boolean {
    const currentMap = new Map<string, number>()
    for (const s of currentScores) currentMap.set(s.sector, s.rank)
    for (const sector of changedSectors) {
      const prevRank = prevRanks.get(sector)
      const currentRank = currentMap.get(sector)
      if (prevRank === undefined || currentRank === undefined || prevRank !== currentRank) {
        return true
      }
    }
    return false
  }

  return { reset, detect }
}
