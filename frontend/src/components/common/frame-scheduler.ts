/**
 * 공통 화면주기 갱신 도구 — "한 화면 주기에 한 번만 갱신 예약" 패턴 추출.
 *
 * 각 표 엔진·페이지가 따로 구현하던 rAF 배칭 코드를 한 곳으로 모음 (W11 표현 통일).
 * 검증된 규칙을 한 번만 구현:
 *  - 이미 예약된 rAF가 있으면 추가 예약하지 않기
 *  - 콜백 실행 시점에 최신 상태 반영 (콜백이 매번 최신 값을 읽도록 설계)
 *  - FPS 제한(REFRESH_FPS) — 한 화면 주기 간격 미충족 시 재예약
 *  - destroy 시 rAF 취소 + 이후 schedule no-op
 *
 * 관련 원칙: W3(SSOT) · W9(격리된 실패) · W11(표현 통일) · W12(중복 제거)
 */

import { REFRESH_FRAME_INTERVAL } from './ui-styles'

/** 화면주기 갱신 도구 인터페이스 — schedule/cancel/destroy 세 동작만 노출. */
export interface FrameScheduler {
  /** 갱신 예약 — 이미 예약 중이면 no-op, 아니면 rAF 예약. */
  schedule: () => void
  /** 예약 중인 rAF 취소 (pending 상태만, callback은 유지). */
  cancel: () => void
  /** rAF 취소 + 이후 schedule no-op — 화면 종료 시 호출. */
  destroy: () => void
}

/**
 * 화면주기 갱신 도구 생성.
 * @param callback 갱신 본체 — 실행 시점에 최신 상태를 직접 읽도록 작성 (도구가 상태를 보관하지 않음).
 * @returns schedule/cancel/destroy 인터페이스
 */
export function createFrameScheduler(callback: () => void): FrameScheduler {
  // scheduled: "예약 중" 상태 플래그 (중복 예약 방지). rafHandle과 분리 —
  // 일부 환경(jsdom)에서 requestAnimationFrame이 콜백을 동기 실행하면
  // 콜백 내부에서 rafHandle=null 설정 후 반환값이 rafHandle을 덮어쓰는 문제를 방지.
  let scheduled = false
  let rafHandle: number | null = null
  let lastRenderTime = 0
  let destroyed = false

  function schedule(): void {
    if (destroyed) return
    if (scheduled) return
    scheduled = true
    rafHandle = requestAnimationFrame((timestamp) => {
      scheduled = false
      rafHandle = null
      if (destroyed) return
      const elapsed = timestamp - lastRenderTime
      if (elapsed < REFRESH_FRAME_INTERVAL) {
        schedule()
        return
      }
      lastRenderTime = timestamp
      callback()
    })
  }

  function cancel(): void {
    if (rafHandle !== null && rafHandle >= 0) {
      cancelAnimationFrame(rafHandle)
    }
    rafHandle = null
    scheduled = false
  }

  function destroy(): void {
    cancel()
    destroyed = true
  }

  return { schedule, cancel, destroy }
}
