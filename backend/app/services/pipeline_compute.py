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
import time
from types import ModuleType
from typing import Optional

from backend.app.core.logger import get_logger
from backend.app.services.core_queues import (
    get_tick_queue,
    get_order_queue,
    get_broadcast_queue,
    get_control_queue,
)
from backend.protobuf import event_pb2

logger = get_logger("pipeline_compute")

_compute_task: Optional[asyncio.Task] = None
_sector_recompute_task: Optional[asyncio.Task] = None
_compute_running: bool = False
_sector_recompute_dirty: bool = False



def _parse_protobuf_batch(binary_data: bytes) -> list[dict]:
    """
    Protobuf 바이너리 배치 데이터 파싱.

    Args:
        binary_data: Protobuf 직렬화된 바이너리 데이터 (길이 접두사 + 이벤트 패킹)

    Returns:
        파싱된 이벤트 리스트 (dict 형태)
    """
    events = []
    offset = 0

    while offset < len(binary_data):
        # 길이 접두사 읽기 (4 bytes)
        if offset + 4 > len(binary_data):
            logger.warning("[Compute] Protobuf 길이 접두사 불완전")
            break

        length = int.from_bytes(binary_data[offset:offset+4], byteorder='big')
        offset += 4

        # 이벤트 데이터 읽기
        if offset + length > len(binary_data):
            logger.warning("[Compute] Protobuf 이벤트 데이터 불완전")
            break

        event_bytes = binary_data[offset:offset+length]
        offset += length

        # Protobuf 파싱
        try:
            event_proto = event_pb2.Event()
            event_proto.ParseFromString(event_bytes)

            # dict 형태로 변환
            event_dict = {
                "type": event_proto.type,
                "timestamp": event_proto.timestamp,
                "data": dict(event_proto.data),
                "latency_trace": dict(event_proto.latency_trace),
            }
            events.append(event_dict)
        except Exception as e:
            logger.error("[Compute] Protobuf 파싱 예외 (계속): %s", e, exc_info=True)

    return events


async def start_compute_loop(es: ModuleType) -> None:
    """Compute Engine 루프 시작."""
    global _compute_task, _compute_running, _sector_recompute_task

    if _compute_running:
        logger.warning("[Compute] 이미 실행 중")
        return

    _compute_running = True
    _compute_task = asyncio.get_running_loop().create_task(_compute_loop_impl(es))
    _sector_recompute_task = asyncio.get_running_loop().create_task(_sector_recompute_loop_impl(es, get_broadcast_queue()))
    logger.info("[Compute] 루프 시작")


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
                # P0-1: PriorityQueue 전환 - 튜플 언패킹 적용 (우선순위, 데이터)
                try:
                    _, _, control_signal = control_queue.get_nowait()
                    await _process_control_signal(control_signal, es, broadcast_queue)
                    control_queue.task_done()
                except asyncio.QueueEmpty:
                    pass  # 제어 신호 없음, 정상 흐름 계속

                # tick_queue에서 데이터 꺼내기 (P2-5: Protobuf 바이너리)
                data = await tick_queue.get()

                # P2-5: Protobuf 파싱
                parsed_events = _parse_protobuf_batch(data)

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

            # 0B/01 체결 처리 (주식 현재가)
            if msg_type in ("0B", "01"):
                await _handle_real_01_tick(item, vals, es, order_queue, broadcast_queue)
            # 0J 지수 처리 (업종 지수 바)
            elif msg_type == "0J":
                await _handle_real_0j_tick(item, vals, es, broadcast_queue)
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


async def _handle_real_0j_tick(
    item: dict,
    vals: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    0J 지수 틱 처리 (업종 지수 바).

    Args:
        item: 틱 아이템
        vals: 틱 값
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        from backend.app.services.daily_time_scheduler import on_0j_real_received
        from backend.app.services.engine_ws_dispatch import _ws_fid_float, _parse_ws_fid12_to_percent, _ws_fid_raw

        # 지수 폴링 중단
        on_0j_real_received()

        # 종목코드 추출
        idx_cd = str(item.get("item") or "").strip().lstrip("A")
        if not idx_cd:
            raw_item = item.get("item")
            if isinstance(raw_item, list) and raw_item:
                idx_cd = str(raw_item[0]).strip()

        # 거래소 접미사 제거
        _exch_suffix = ""
        if idx_cd:
            for sfx in ("_NX", "_AL", "_nx", "_al"):
                if idx_cd.endswith(sfx):
                    _exch_suffix = sfx
                    idx_cd = idx_cd[: -len(sfx)]
                    break

        if not (idx_cd and isinstance(vals, dict)):
            return

        # 지수 데이터 파싱
        price = _ws_fid_float(vals, "10", 0.0)
        change = _ws_fid_float(vals, "11", 0.0)
        rate = _parse_ws_fid12_to_percent(_ws_fid_raw(vals, "12"))
        sig = str(_ws_fid_raw(vals, "25") or "").strip()

        if sig in ("4", "5", "44", "45"):
            change = -abs(change)
            rate = -abs(rate)

        # 지수 캐시 업데이트
        if price != 0 or rate != 0:
            es._latest_index[idx_cd] = {
                "price": abs(price),
                "change": change,
                "rate": rate,
            }
        else:
            logger.warning("[Compute] 0J 파싱 실패 idx_cd=%s vals=%s", idx_cd, str(vals)[:200])

    except Exception as e:
        logger.error("[Compute] 0J 틱 처리 예외: %s", e, exc_info=True)


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

        # 호가 캐시 업데이트
        prev = es._orderbook_cache.get(nk)
        es._orderbook_cache[nk] = (bid, ask)

        # 매수후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송
        if prev != (bid, ask) and nk in es._subscribed_0d_stocks:
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
    """
    global _compute_running, _sector_recompute_dirty
    try:
        while _compute_running:
            try:
                if _sector_recompute_dirty:
                    # 데이터 수신율 기반 랭킹 계산 컷오프(대기) 방어 로직
                    inputs = es.get_sector_summary_inputs()
                    all_codes = inputs.get("all_codes", [])
                    trade_prices = inputs.get("trade_prices", {})
                    
                    total_count = len(all_codes)
                    received_count = sum(1 for c in all_codes if c in trade_prices)
                    
                    threshold_pct = float(es._settings_cache.get("sector_start_threshold_pct", 70.0))
                    current_pct = (received_count / total_count * 100) if total_count > 0 else 100.0
                    
                    if current_pct < threshold_pct:
                        # 1초 뒤에 다시 체크하기 위해 깃발 유지
                        logger.debug("[Compute] 업종순위 계산 대기 중 (수신율: %d/%d = %.1f%% < %.1f%%)", received_count, total_count, current_pct, threshold_pct)
                        _sector_recompute_dirty = True
                    else:
                        _sector_recompute_dirty = False
                        
                        # 업종 점수 즉시 재계산
                        es.recompute_sector_summary_now()

                        # UI 업데이트를 broadcast_queue에 전송
                        summary_data = es.get_sector_scores_snapshot()
                        if summary_data:
                            await broadcast_queue.put({
                                "type": "sector_scores",
                                "data": summary_data,
                            })
            except Exception as e:
                logger.error("[Compute] 백그라운드 업종 점수 재계산 예외: %s", e, exc_info=True)
            
            # 1초 대기 (스로틀링 주기)
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
