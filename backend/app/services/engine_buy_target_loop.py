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


async def _process_buy_target_events(events: list[dict]) -> None:
    """매수후보 갱신 이벤트 배치 처리 — 증분 갱신 + 캐시 갱신 + 매수 요청 전달 + 후속 처리.

    순서 (설계서 결정 5·6·7):
      1. 증분 갱신 (변경 업종 종목만 추가/제거 + 재정렬)
      2. 캐시 갱신 (_set_sector_summary 단일 쓰기 경로 — P10 SSOT)
      3. 매수 요청을 주문 큐에 전달 (결정 6 — A안, 기존 order_queue 재사용)
      4. 후속 처리 — 기존 매니저 함수 직접 호출 (결정 7, P5 준수):
         - notify_buy_targets_update (화면 전송 — delta 비교 후 변경 시만)
         - _refresh_buy_target_page_subscriptions (페이지 구독 — 코드 집합 변동 시만)
         - sync_dynamic_subscriptions (동적 구독 — guard_pass 집합 변동 시만)
    """
    from backend.app.services import engine_state, engine_account
    from backend.app.domain.buy_filter import apply_incremental_buy_target_update
    from backend.app.services.engine_initial_data import _set_sector_summary
    from backend.app.services.engine_account_notify import notify_buy_targets_update
    from backend.app.services.engine_sector_confirm import (
        _refresh_buy_target_page_subscriptions,
        are_buy_target_page_codes_changed,
        sync_dynamic_subscriptions,
        are_buy_targets_changed,
        _build_prev_targets_map,
    )
    from backend.app.services.core_queues import get_order_queue

    existing = engine_state.state.sector_summary_cache
    if not existing:
        logger.warning("[매수후보루프] 캐시 없음 — 증분 갱신 스킵 (콜드 스타트 대기)")
        return

    settings = engine_state.state.integrated_system_settings_cache
    _held = await engine_account.get_held_codes()
    _bought_today: set[str] = set()
    if engine_state.state.auto_trade is not None:
        _bought_today = set(engine_state.state.auto_trade._bought_today.keys())

    # 이전 buy_targets·캐시 (후속 처리 비교용)
    prev_targets = existing.buy_targets
    prev_cache = existing

    # 1. 증분 갱신 — 변경 업종 종목만 추가/제거 + 재정렬 (설계서 결정 3·4)
    new_summary = apply_incremental_buy_target_update(
        existing,
        events,
        settings,
        held_codes=_held,
        bought_today_codes=_bought_today,
        prev_targets_map=_build_prev_targets_map(existing),
    )

    # 2. 캐시 갱신 — 단일 쓰기 경로 (P10 SSOT)
    _set_sector_summary(new_summary, "engine_buy_target_loop.incremental_update")

    # 3. 매수 요청을 주문 큐에 전달 (결정 6 — A안)
    #    매수후보 갱신 시에만 매수 평가 요청 → 필터 상태 불변 시 불필요한 매수 시도 없음
    try:
        get_order_queue().put_nowait({"type": "buy_evaluate"})
    except asyncio.QueueFull:
        # W1 무한 쌓기 방지 — 가득 시 경고 로그 + 드롭 (W8 폴백 금지, 명시적 드롭)
        logger.warning("[매수후보루프] 주문 큐 가득 참 — 매수 후보 평가 요청 드롭")

    # 4. 후속 처리 — 기존 매니저 함수 직접 호출 (결정 7, P5 준수 — 관찰자/콜백 미사용)
    # 4-1. 화면 전송 — notify_buy_targets_update 내부에서 delta 비교 후 변경 시만 전송
    await notify_buy_targets_update()

    # 4-2. 페이지 구독 갱신 — 종목 코드 집합 변동 시만 (기존 are_buy_target_page_codes_changed 로직)
    if are_buy_target_page_codes_changed(prev_cache, new_summary):
        await _refresh_buy_target_page_subscriptions("매수후보 갱신 루프 — 페이지 구독 갱신")

    # 4-3. 동적 구독 갱신 — guard_pass 종목 집합 변동 시만 (기존 are_buy_targets_changed 로직)
    if are_buy_targets_changed(prev_targets, new_summary.buy_targets):
        sync_dynamic_subscriptions(new_summary.buy_targets)

    logger.debug("[매수후보루프] 이벤트 %d건 처리 완료", len(events))


async def _buy_target_loop_impl() -> None:
    """매수후보 갱신 루프 구현 — buy_target_update_queue에서 이벤트를 꺼내 처리.

    큐에서 이벤트를 하나 꺼낸 후, 큐에 쌓인 추가 이벤트를 모두 꺼내 배치 처리.
    여러 업종 변경을 한 번에 증분 갱신하여 효율성 확보.
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

            # 배치 수집 — 큐에 쌓인 추가 이벤트를 모두 꺼냄 (한 번에 증분 갱신)
            events: list[dict] = [event]
            while True:
                try:
                    events.append(buy_target_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            try:
                # 증분 갱신 + 캐시 갱신 + 매수 요청 전달 + 후속 처리
                await _process_buy_target_events(events)
            except Exception as e:
                # W9 격리된 실패 — 개별 이벤트 배치 예외가 루프 전체 중단 유도 금지
                logger.error("[매수후보루프] 이벤트 처리 오류 (계속): %s", e, exc_info=True)

            # task_done — 배치의 각 이벤트에 대해 호출
            for _ in events:
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
