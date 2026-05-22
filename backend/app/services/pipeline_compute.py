# -*- coding: utf-8 -*-
"""
초고속 연산 엔진 (Compute Engine) - 파이프라인 아키텍처 Step 3

tick_queue에서 데이터를 꺼내어 연산 수행:
- 업종 점수 계산
- 체결강도 업데이트
- 매수/매도 타점 도달 여부 판단
- 결과를 order_queue 또는 broadcast_queue로 전송
"""
from __future__ import annotations

import asyncio
from types import ModuleType
from typing import Optional

from backend.app.core.logger import get_logger
from backend.app.services.core_queues import (
    get_tick_queue,
    get_order_queue,
    get_broadcast_queue,
    get_control_queue,
)

logger = get_logger("pipeline_compute")

_compute_task: Optional[asyncio.Task] = None
_compute_running: bool = False


async def start_compute_loop(es: ModuleType) -> None:
    """Compute Engine 루프 시작."""
    global _compute_task, _compute_running

    if _compute_running:
        logger.warning("[Compute] 이미 실행 중")
        return

    _compute_running = True
    _compute_task = asyncio.get_running_loop().create_task(_compute_loop_impl(es))
    logger.info("[Compute] 루프 시작")


async def stop_compute_loop() -> None:
    """Compute Engine 루프 종료."""
    global _compute_running, _compute_task

    _compute_running = False
    if _compute_task:
        _compute_task.cancel()
        try:
            await _compute_task
        except asyncio.CancelledError:
            pass
    logger.info("[Compute] 루프 종료")


async def _compute_loop_impl(es: ModuleType) -> None:
    """Compute Engine 루프 구현."""
    global _compute_running
    tick_queue = get_tick_queue()
    order_queue = get_order_queue()
    broadcast_queue = get_broadcast_queue()
    control_queue = get_control_queue()

    try:
        while _compute_running:
            try:
                # ── Control Queue 관문 (Step 6: 컨트롤 플레인 우회 배관 연동) ──
                # 제어 신호가 있는지 먼저 체크 (get_nowait로 비블로킹 체크)
                try:
                    control_signal = control_queue.get_nowait()
                    await _process_control_signal(control_signal, es, broadcast_queue)
                    control_queue.task_done()
                except asyncio.QueueEmpty:
                    pass  # 제어 신호 없음, 정상 흐름 계속

                # tick_queue에서 데이터 꺼내기
                data = await tick_queue.get()

                # 연산 수신 (engine_service의 연산 로직 이관)
                await _process_tick_data(data, es, order_queue, broadcast_queue)

                tick_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Compute] 처리 예외 (계속): %s", e, exc_info=True)
    finally:
        _compute_running = False
        logger.info("[Compute] 루프 종료")


async def _process_control_signal(
    signal: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    제어 신호 처리 (Step 6: 컨트롤 플레인 우회 배관 연동).

    Args:
        signal: 제어 신호 (dict)
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        signal_type = signal.get("type")
        payload = signal.get("payload", {})

        if signal_type == "UPDATE_CONFIG":
            # 설정 변경 신호 처리
            await _handle_config_update(payload, es, broadcast_queue)
        elif signal_type == "RECOMPUTE_SECTOR":
            # 업종순위 재계산 신호 처리
            await _handle_sector_recompute(es, broadcast_queue)
        else:
            logger.warning("[Compute] 알 수 없는 제어 신호: %s", signal_type)

    except Exception as e:
        logger.error("[Compute] 제어 신호 처리 예외: %s", e, exc_info=True)


async def _handle_config_update(
    payload: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    설정 변경 처리.

    Args:
        payload: 설정 변경 데이터
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        # _shared_lock 획득하여 race condition 방지
        async with es._shared_lock:
            # 설정값 업데이트
            changed_keys = payload.get("changed_keys", set())
            for key in changed_keys:
                es._settings_cache[key] = payload.get(key)

        logger.info("[Compute] 설정값 업데이트 완료 - changed_keys=%s", changed_keys)

    except Exception as e:
        logger.error("[Compute] 설정 변경 처리 예외: %s", e, exc_info=True)


async def _handle_sector_recompute(
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    업종순위 재계산 처리.

    Args:
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        # _shared_lock 획득하여 race condition 방지
        async with es._shared_lock:
            # 업종순위 재계산
            es.recompute_sector_summary_now()

        # UI 업데이트
        summary_data = es.get_sector_scores_snapshot()
        if summary_data:
            await broadcast_queue.put({
                "type": "sector_scores",
                "data": summary_data,
            })

        logger.info("[Compute] 업종순위 재계산 완료")

    except Exception as e:
        logger.error("[Compute] 업종순위 재계산 예외: %s", e, exc_info=True)


async def _process_tick_data(
    data: dict,
    es: ModuleType,
    order_queue: asyncio.Queue,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    틱 데이터 처리 - 연산 로직 이관.

    Args:
        data: 틱 데이터 (dict)
        es: engine_service 모듈 (전역 상태 접근용)
        order_queue: 주문 지령 큐
        broadcast_queue: UI 전송 큐
    """
    # Step 3: engine_service의 연산 로직 이관
    # 1. 틱 데이터 파싱 및 캐시 업데이트
    trnm = data.get("trnm")
    if trnm == "REAL":
        await _handle_real_tick(data, es, order_queue, broadcast_queue)


async def _handle_real_tick(
    data: dict,
    es: ModuleType,
    order_queue: asyncio.Queue,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    REAL 틱 데이터 처리.

    Args:
        data: REAL 틱 데이터
        es: engine_service 모듈
        order_queue: 주문 지령 큐
        broadcast_queue: UI 전송 큐
    """
    # engine_service._apply_real01_volume_amount_to_radar_rows 이관
    # 실제 연산 로직은 engine_service 모듈의 전역 변수에 접근하여 수행
    try:
        # 틱 데이터 파싱
        real_data = data.get("data")
        if isinstance(real_data, list):
            items = real_data
        elif isinstance(real_data, dict):
            items = [real_data]
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            # 틱 타입 확인
            msg_type = item.get("type")
            vals = item.get("values", {})
            if not isinstance(vals, dict):
                vals = {}

            # 0B/01 체결 처리
            if msg_type in ("0B", "01"):
                await _handle_real_01_tick(item, vals, es, order_queue, broadcast_queue)

    except Exception as e:
        logger.error("[Compute] REAL 틱 처리 예외: %s", e, exc_info=True)


async def _handle_real_01_tick(
    item: dict,
    vals: dict,
    es: ModuleType,
    order_queue: asyncio.Queue,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    0B/01 체결 틱 처리.

    Args:
        item: 틱 아이템
        vals: 틱 값
        es: engine_service 모듈
        order_queue: 주문 지령 큐
        broadcast_queue: UI 전송 큐
    """
    # engine_service._apply_real01_volume_amount_to_radar_rows 이관
    try:
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd
        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd

        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return

        # FID 13·14가 있는 틱에서만 캐시 갱신
        is_0b_tick = str(item.get("type", "")).strip().upper() in ("0B", "01")
        if is_0b_tick and "14" in vals:
            # engine_service._apply_real01_volume_amount_to_radar_rows 호출
            # 전역 변수 접근을 위해 es 모듈 사용
            await es._apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick)

            # 연산 결과: 업종 점수 재계산 필요 여부 확인
            # 업종 점수 재계산이 필요하면 broadcast_queue에 전송
            await _check_sector_recompute_needed(es, broadcast_queue)

            # 연산 결과: 매수 타점 도달 여부 확인
            # 매수 타점에 도달하면 order_queue에 주문 지령 전송
            await _check_buy_target_reached(es, order_queue, broadcast_queue)

    except Exception as e:
        logger.error("[Compute] 0B/01 틱 처리 예외: %s", e, exc_info=True)


async def _check_sector_recompute_needed(
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    업종 점수 재계산 필요 여부 확인.

    Args:
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    # 업종 점수 재계산 필요 여부 확인 로직
    # 실제 재계산은 engine_service.recompute_sector_summary_now 호출
    try:
        # 업종 점수 재계산 (engine_service.recompute_sector_summary_now 이관)
        es.recompute_sector_summary_now()

        # UI 업데이트 필요 시 broadcast_queue에 전송
        summary_data = es.get_sector_scores_snapshot()
        if summary_data:
            await broadcast_queue.put({
                "type": "sector_scores",
                "data": summary_data,
            })

    except Exception as e:
        logger.error("[Compute] 업종 점수 재계산 예외: %s", e, exc_info=True)


async def _check_buy_target_reached(
    es: ModuleType,
    order_queue: asyncio.Queue,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    매수 타점 도달 여부 확인.

    Args:
        es: engine_service 모듈
        order_queue: 주문 지령 큐
        broadcast_queue: UI 전송 큐
    """
    # 매수 타점 도달 여부 확인 로직
    # 실제 매수 판단은 engine_service._try_sector_buy 호출
    try:
        # 매수 판단 (engine_service._try_sector_buy 이관)
        es._try_sector_buy()

        # 매수 타점에 도달하면 order_queue에 주문 지령 전송
        # (실제 주문 실행은 Step 4 OMS Pipeline에서 수행)
        buy_targets = es.get_buy_targets_snapshot()
        if buy_targets:
            # 매수 후보 종목이 있으면 broadcast_queue에 전송 (UI 업데이트)
            await broadcast_queue.put({
                "type": "buy_targets",
                "data": buy_targets,
            })

    except Exception as e:
        logger.error("[Compute] 매수 타점 확인 예외: %s", e, exc_info=True)
