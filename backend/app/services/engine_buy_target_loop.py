# -*- coding: utf-8 -*-
"""
매수후보 갱신 루프 (Buy Target Update Loop) - 업종순위 단계에서 매수후보 갱신을 분리.

buy_target_update_queue에서 매수후보 갱신 이벤트를 꺼내 순차 처리:
- 통과→탈락 전환 업종 → 해당 업종 종목을 매수후보에서 제거
- 탈락→통과 전환 업종 → 해당 업종 종목을 매수후보에 추가
- 상위 N개 진입/이탈 업종 → 진입 업종 종목 추가, 이탈 업종 종목 제거

업종순위 재계산 루프가 매수후보 갱신(화면 전송·구독 갱신 포함)에 블록되지 않도록
갱신 이벤트를 큐에 넣고 즉시 다음 계산으로 넘어가며, 본 루프가 큐에서 순차 소비.
예외 시 개별 이벤트 격리 (에러 로깅 + continue).

1단계: 골격만 추가. 루프 내부 실제 증분 갱신 로직은 3단계에서 구현.
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

# ── 매수후보 갱신 루프 상태 ───────────────────────────────────────────────────
_buy_target_task: Optional[asyncio.Task] = None
_buy_target_running: bool = False

# 루프 대기 timeout — stop 신호 감지용 (이벤트 없을 때 주기적으로 루프 조건 재확인)
_BUY_TARGET_LOOP_TIMEOUT = 1.0


async def _buy_target_loop_impl() -> None:
    """매수후보 갱신 루프 구현 — buy_target_update_queue에서 이벤트를 꺼내 처리.

    1단계: 골격만. 이벤트 소비 후 task_done()만 수행. 실제 증분 갱신 로직은 3단계에서 구현.
    """
    from backend.app.services.core_queues import get_buy_target_update_queue

    buy_target_queue = get_buy_target_update_queue()

    while _buy_target_running:
        try:
            try:
                event = await asyncio.wait_for(
                    buy_target_queue.get(), timeout=_BUY_TARGET_LOOP_TIMEOUT
                )
            except asyncio.TimeoutError:
                # 이벤트 없음 — stop 신호 감지 후 재대기
                await asyncio.sleep(0)
                continue

            try:
                # 1단계: 골격만 — 실제 증분 갱신 로직은 3단계에서 구현
                # 3단계에서 event 페이로드(변경 업종 정보·종목 리스트·이벤트 종류) 기반 증분 갱신 + 화면 전송·구독 갱신·매수 평가 큐 적재 수행
                logger.debug("[매수후보루프] 이벤트 수신 (1단계 골격 — 처리 로직 미구현): %s", event)
            except Exception as e:
                # W9 격리된 실패 — 개별 이벤트 예외가 루프 전체 중단 유도 금지
                logger.error("[매수후보루프] 이벤트 처리 오류 (계속): %s", e, exc_info=True)

            try:
                buy_target_queue.task_done()
            except ValueError:
                # task_done 카운터 불일치 시 무시 (격리된 실패)
                pass

            # W1 — 이벤트 루프 양보
            await asyncio.sleep(0)

        except asyncio.CancelledError:
            logger.info("[매수후보루프] 취소 신호 수신 — 종료")
            raise
        except Exception as e:
            # 루프 프레임 자체 예외 — 로깅 후 계속 (W9)
            logger.error("[매수후보루프] 루프 프레임 오류 (계속): %s", e, exc_info=True)
            await asyncio.sleep(0)


async def start_buy_target_loop() -> None:
    """매수후보 갱신 루프 시작 (엔진 기동 시 호출)."""
    global _buy_target_task, _buy_target_running

    if _buy_target_running:
        logger.warning("[매수후보루프] 이미 실행 중")
        return

    _buy_target_running = True
    _buy_target_task = asyncio.get_running_loop().create_task(_buy_target_loop_impl())
    _buy_target_task.add_done_callback(_on_buy_target_loop_done)
    logger.info("[매수후보루프] 시작")


def _on_buy_target_loop_done(task: asyncio.Task) -> None:
    """매수후보 갱신 루프 종료 콜백 — cancel된 경우 CancelledError 무시, 실제 예외만 로깅."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("[매수후보루프] 루프 작업 실패: %s", exc)


async def stop_buy_target_loop() -> None:
    """매수후보 갱신 루프 종료 (엔진 정지 시 호출)."""
    global _buy_target_running, _buy_target_task

    _buy_target_running = False
    if _buy_target_task:
        _buy_target_task.cancel()
        try:
            await _buy_target_task
        except asyncio.CancelledError:
            pass
        _buy_target_task = None
    logger.info("[매수후보루프] 종료")
