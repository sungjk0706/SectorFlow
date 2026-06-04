from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
초고속 연산 엔진 (Compute Engine) - 파이프라인 아키텍처 Step 3

tick_queue에서 데이터를 꺼내어 연산 수행:
- 업종 점수 계산
- 체결강도 업데이트
- 매수/매도 타점 도달 여부 판단
- 결과를 order_queue 또는 broadcast_queue로 전송
"""

import asyncio
import time
from types import ModuleType

from backend.app.core.logger import get_logger
from backend.app.services.core_queues import (
    get_tick_queue,
    get_order_queue,
    get_broadcast_queue,
    get_control_queue,
)

logger = get_logger("pipeline_compute")

_compute_task: Optional[asyncio.Task] = None
_sector_recompute_task: Optional[asyncio.Task] = None
_compute_running: bool = False
_sector_recompute_dirty: bool = False

# 실시간데이터 필드 키 목록 (engine_snapshot._REALTIME_FIELDS와 동일)
# ws_subscribe_start 시점에 _reset_realtime_fields()가 이 필드들을 None으로 초기화한다.
# None이 아닌 값 = 실시간 틱 또는 장마감 후 확정 데이터가 수신된 것을 의미.
_REALTIME_CHECK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength", "high_price")


def _has_any_realtime_data(entry: dict) -> bool:
    """종목 캐시 엔트리에 실시간데이터 필드가 1개라도 채워져 있는지 확인.

    ws_subscribe_start 시점에 _reset_realtime_fields()가 모든 필드를 None으로 초기화하므로,
    None이 아닌 값이 존재한다는 것은 실시간 틱 또는 확정 데이터가 수신되었음을 의미.
    """
    return any(entry.get(f) is not None for f in _REALTIME_CHECK_FIELDS)


async def start_compute_loop(es: ModuleType) -> None:
    """Compute Engine 루프 시작."""
    global _compute_task, _compute_running, _sector_recompute_task

    if _compute_running:
        logger.warning("[Compute] 이미 실행 중")
        return

    _compute_running = True
    _compute_task = asyncio.get_running_loop().create_task(_compute_loop_impl(es))
    _sector_recompute_task = asyncio.get_running_loop().create_task(_sector_recompute_loop_impl(es, get_broadcast_queue()))
    logger.debug("[Compute] 루프 시작")


async def stop_compute_loop() -> None:
    """Compute Engine 루프 종료."""
    global _compute_running, _compute_task, _sector_recompute_task

    _compute_running = False
    if _sector_recompute_task:
        _sector_recompute_task.cancel()
        try:
            await _sector_recompute_task
        except asyncio.CancelledError:
            pass
    if _compute_task:
        _compute_task.cancel()
        try:
            await _compute_task
        except asyncio.CancelledError:
            pass
    logger.debug("[Compute] 루프 종료")


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
                # P0-1: PriorityQueue 전환 - 튜플 언패킹 적용 (우선순위, 데이터)
                try:
                    _, _, control_signal = control_queue.get_nowait()
                    await _process_control_signal(control_signal, es, broadcast_queue)
                    control_queue.task_done()
                except asyncio.QueueEmpty:
                    pass  # 제어 신호 없음, 정상 흐름 계속

                # tick_queue에서 데이터 꺼내기 (Python dict 메모리 참조 직통)
                data = await tick_queue.get()

                # data 자체가 딕셔너리(REAL 데이터 등)이므로 직접 전달
                # 큐에 여러 이벤트가 리스트로 올 경우를 대비한 방어 로직
                parsed_events = [data] if isinstance(data, dict) else data

                # 파싱된 각 이벤트를 순차적으로 연산 로직에 전달
                for event in parsed_events:
                    try:
                        # 연산 수신 (engine_service의 연산 로직 이관)
                        await _process_tick_data(event, es, order_queue, broadcast_queue)
                    except Exception as e:
                        logger.error("[Compute] 이벤트 처리 예외 (계속): %s", e, exc_info=True)

                tick_queue.task_done()

                # P0-1: 틱 폭주 시 이벤트 루프 고갈 방지 - 협력적 멀티태스킹 (Yielding)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Compute] 처리 예외 (계속): %s", e, exc_info=True)
    finally:
        _compute_running = False
        logger.debug("[Compute] 루프 종료")


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
                es._integrated_system_settings_cache[key] = payload.get(key)

        logger.info("[Compute] 설정값 업데이트 완료 - changed_keys=%s", changed_keys)
        
        # 설정(거래모드, 증권사 등) 변경에 따라 Header 상태 갱신
        from backend.app.services.engine_account_notify import notify_desktop_header_refresh
        notify_desktop_header_refresh()

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
            await es.recompute_sector_summary_now()

        # UI 업데이트
        summary_data = es.get_sector_scores_snapshot()
        if summary_data:
            # summary_data는 tuple[list[dict], int]이므로 첫 번째 요소만 사용
            scores_list, _ = summary_data
            await broadcast_queue.put({
                "type": "sector_scores",
                "data": {"scores": scores_list},  # dict로 감싸서 전송
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

            # 0B/01 체결 처리 (주식 현재가)
            if msg_type in ("0B", "01"):
                await _handle_real_01_tick(item, vals, es, order_queue, broadcast_queue)
            # 0D 호가 처리 (호가 잔량 테이블)
            elif msg_type == "0D":
                await _handle_real_0d_tick(item, vals, es, broadcast_queue)

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

        # UI 프론트엔드로 RAW 틱 데이터 브로드캐스트 (Gateway 파이프라인으로 전송)
        item["item"] = raw_cd
        import time
        item["_ts"] = int(time.time() * 1000)
        try:
            broadcast_queue.put_nowait({"type": "real-data", "data": item})
        except asyncio.QueueFull:
            pass

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
async def _handle_real_0d_tick(
    item: dict,
    vals: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    0D 호가 틱 처리 (호가 잔량 테이블).

    Args:
        item: 틱 아이템
        vals: 틱 값
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd, _format_kiwoom_reg_stk_cd
        from backend.app.services.engine_ws_dispatch import _ws_fid_int
        from backend.app.services.engine_account_notify import notify_orderbook_update

        # 종목코드 추출
        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return

        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        bid = _ws_fid_int(vals, "125", 0)  # 총 매수호가잔량
        ask = _ws_fid_int(vals, "121", 0)  # 총 매도호가잔량

        if bid < 0 or ask < 0:
            return

        # 호가잔량 캐시 삭제로 저장 로직 제거
        # 매수후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송
        if es._master_stocks_cache.get(nk, {}).get("_subscribed_0d", False):
            notify_orderbook_update(nk, bid, ask)

    except Exception as e:
        logger.error("[Compute] 0D 틱 처리 예외: %s", e, exc_info=True)


async def _check_sector_recompute_needed(
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    업종 점수 재계산 필요 여부 확인.
    (스로틀링 최적화: 계산 로직을 백그라운드 루프로 분리하고 깃발만 꽂음)
    """
    global _sector_recompute_dirty
    _sector_recompute_dirty = True


async def _sector_recompute_loop_impl(es: ModuleType, broadcast_queue: asyncio.Queue) -> None:
    """
    1초 주기로 돌아가는 업종순위 재계산 스로틀(디바운스) 백그라운드 루프.
    _sector_recompute_dirty 깃발이 꽂혀 있을 때만 연산을 수행하여 CPU 부하를 극소화.

    Phase 1 (1회): 실시간데이터 필드 수신율 임계값 대기 — 통과 후 Phase 2로 전환 (반복 체크 없음)

      수신율 계산 기준:
        - ws_subscribe_start 시점에 _reset_realtime_fields()가 6개 실시간 필드를 None으로 초기화.
        - None이 아닌 필드가 1개라도 있는 종목 = 실시간 틱 또는 확정 데이터가 수신된 종목.
        - received_count == 0: 아직 아무 데이터도 없음(필드 초기화 직후) → 대기.
        - received_count >= 1: 수신율(%) 계산 시작 → N% 임계값 통과 시 Phase 2 진입.

      시나리오별 동작:
        - 장마감 후 기동: 확정 데이터가 이미 필드에 존재 → received_count > 0 → 즉시 수신율 계산
          → 임계값 통과 → 업종순위 즉시 계산 (무한루프 없음)
        - 장중 기동(ws_subscribe_start 이후): 필드 초기화 상태 → 틱 수신 시작 시
          received_count >= 1 → 수신율 계산 시작 → N% 도달 시 계산

    Phase 2 (반복): dirty 플래그 확인 → engine_sector_confirm 증분 재계산 트리거 (1초 스로틀)
    """
    from backend.app.services.engine_sector_confirm import recompute_sector_for_code
    global _compute_running, _sector_recompute_dirty
    try:
        # Phase 1: 실시간데이터 필드 수신율 임계값 대기 (1회성 스타트업 게이트)
        while _compute_running:
            try:
                inputs = await es.get_sector_summary_inputs()
                all_codes = inputs.get("all_codes", [])
                stock_details = inputs.get("stock_details", {})
                total_count = len(all_codes)

                if total_count == 0:
                    logger.info("[Compute] 업종순위 계산 대기 중 (종목 없음 -- 부트스트랩 대기)")
                    await asyncio.sleep(1.0)
                    continue

                # 실시간데이터 필드(cur_price, change_rate 등) 중 1개라도 None이 아닌 종목 카운트.
                # cur_price > 0 기준이 아닌 None 여부로 판단:
                #   - ws_subscribe_start → _reset_realtime_fields()가 모두 None으로 초기화
                #   - 실시간 틱 수신 또는 장마감 후 확정 데이터 수신 → None이 아닌 값으로 채워짐
                received_count = sum(
                    1 for entry in stock_details.values()
                    if _has_any_realtime_data(entry)
                )

                # received_count == 0: 실시간 필드가 초기화된 상태(ws_subscribe_start 직후).
                # 첫 번째 데이터(틱 또는 확정)가 수신될 때까지 대기.
                if received_count == 0:
                    logger.info("[Compute] 업종순위 계산 대기 중 (실시간 데이터 수신 전 -- 0/%d)", total_count)
                    await asyncio.sleep(1.0)
                    continue

                threshold_pct = float(es._integrated_system_settings_cache.get("sector_start_threshold_pct", 70.0))
                current_pct = received_count / total_count * 100

                if current_pct < threshold_pct:
                    logger.info("[Compute] 업종순위 계산 대기 중 (수신율: %d/%d = %.1f%% < %.1f%%)", received_count, total_count, current_pct, threshold_pct)
                    await asyncio.sleep(1.0)
                else:
                    logger.info("[Compute] 수신율 임계값 통과 (%.1f%%) — 증분 재계산 활성화", current_pct)
                    _sector_recompute_dirty = False
                    recompute_sector_for_code(None)  # 콜드 스타트 1회 전체 재계산
                    break
            except Exception as e:
                logger.error("[Compute] 수신율 체크 예외: %s", e, exc_info=True)
                await asyncio.sleep(1.0)

        # Phase 2: 1초 스로틀 증분 재계산 루프
        while _compute_running:
            try:
                if _sector_recompute_dirty:
                    _sector_recompute_dirty = False
                    recompute_sector_for_code(None)
            except Exception as e:
                logger.error("[Compute] 백그라운드 업종 점수 재계산 예외: %s", e, exc_info=True)

            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        logger.info("[Compute] 백그라운드 업종 점수 재계산 루프 취소됨")


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
        await es._try_sector_buy()

        # 매수 타점에 도달하면 order_queue에 주문 지령 전송
        # (실제 주문 실행은 Step 4 OMS Pipeline에서 수행)
        buy_targets = es.get_buy_targets_snapshot()
        if buy_targets:
            # 매수 후보 종목이 있으면 broadcast_queue에 전송 (UI 업데이트)
            await broadcast_queue.put({
                "type": "buy_targets",
                "data": {"buy_targets": buy_targets},
            })

    except Exception as e:
        logger.error("[Compute] 매수 타점 확인 예외: %s", e, exc_info=True)
