from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
초고속 연산 엔진 (Compute Engine) - 파이프라인 아키텍처 Step 3

tick_queue에서 데이터를 꺼내어 연산 수행:
- 업종 점수 계산
- 체결강도 업데이트
- 매수/매도 타점 도달 여부 판단
- 결과를 broadcast_queue로 전송
"""

import asyncio
import time
from types import ModuleType

# 0.3초 배치 재계산을 위한 더티 코드 셋 추가
_dirty_codes: set[str] = set()

# 수신율 추적
_current_receive_rate: dict = {"received": 0, "total": 0, "pct": 0.0}
_receive_rate_dirty: bool = False
# 누적 수신 종목 세트 — _reset_realtime_fields()에 의해 초기화되지 않음
# 한 번 수신된 종목은 앱 종료까지 수신된 것으로 유지되어 수신율이 0%로 강하하지 않음
_received_codes: set[str] = set()


async def _send_receive_rate(receive_rate: dict) -> None:
    """수신율 전송 단일 진입점 (단일 소스 진리 원칙 준수)."""
    await broadcast_queue.put({
        "type": "receive-rate",
        "data": {
            "pct": receive_rate["pct"],
            "received": receive_rate["received"],
            "total": receive_rate["total"]
        }
    })

from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state
from backend.app.services.core_queues import (
    get_tick_queue,
    get_broadcast_queue,
    get_control_queue,
)

logger = get_logger("pipeline_compute")

# 전역 큐 할당 (메모리 상주)
broadcast_queue = get_broadcast_queue()

_compute_task: Optional[asyncio.Task] = None
_sector_recompute_task: Optional[asyncio.Task] = None
_compute_running: bool = False

# 업종순위 계산 수신율 체크 필드
# 업종순위는 상승률과 거래대금만으로 결정되므로 상승률(change_rate)과 거래대금(trade_amount)만 체크
# ws_subscribe_start 시점에 _reset_realtime_fields()가 이 필드들을 None으로 초기화한다.
# None이 아닌 값 = 실시간 틱 또는 장마감 후 확정 데이터가 수신된 것을 의미.
_REALTIME_CHECK_FIELDS = ("change_rate", "trade_amount")


def _has_any_realtime_data(entry: dict) -> bool:
    """종목 캐시 엔트리에 실시간데이터 필드가 1개라도 채워져 있는지 확인.

    ws_subscribe_start 시점에 _reset_realtime_fields()가 모든 필드를 None으로 초기화하므로,
    None이 아닌 값이 존재한다는 것은 실시간 틱 또는 확정 데이터가 수신되었음을 의미.
    """
    return any(entry.get(f) is not None for f in _REALTIME_CHECK_FIELDS)


async def _calculate_receive_rate(es: ModuleType) -> None:
    """수신율 계산 (배치 처리 — Phase 1/Phase 2 루프에서 호출).

    _received_codes는 per-tick O(1)으로 추가되므로 여기서는 계산만 수행.
    """
    global _current_receive_rate

    try:
        inputs = await es.get_sector_summary_inputs()
        all_codes = inputs.get("all_codes", [])
        total_count = len(all_codes)

        if total_count == 0:
            return

        all_codes_set = set(all_codes)
        received_count = len(_received_codes & all_codes_set)
        current_pct = received_count / total_count * 100 if total_count > 0 else 0.0

        _current_receive_rate = {"received": received_count, "total": total_count, "pct": current_pct}

    except Exception as e:
        logger.error("[Compute] 수신율 계산 예외: %s", e, exc_info=True)


def get_current_receive_rate() -> dict:
    """현재 수신율 반환 (notify_desktop_sector_scores에서 사용)."""
    global _current_receive_rate
    return dict(_current_receive_rate)


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
    broadcast_queue = get_broadcast_queue()
    control_queue = get_control_queue()

    try:
        while _compute_running:
            try:
                # tick_queue 대기 (0.5초 timeout — 틱 없는 시간에도 control 신호 처리)
                try:
                    data = await asyncio.wait_for(tick_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    data = None

                # control_queue non-blocking 드레인
                while True:
                    try:
                        _, _, control_signal = control_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    await _process_control_signal(control_signal, es, broadcast_queue)
                    control_queue.task_done()

                # tick_queue 데이터 처리
                if data is not None:
                    tick_queue.task_done()

                    # data 자체가 딕셔너리(REAL 데이터 등)이므로 직접 전달
                    # 큐에 여러 이벤트가 리스트로 올 경우를 대비한 방어 로직
                    parsed_events = [data] if isinstance(data, dict) else data

                    # 파싱된 각 이벤트를 순차적으로 연산 로직에 전달
                    for event in parsed_events:
                        try:
                            await _process_tick_data(event, es, broadcast_queue)
                        except Exception as e:
                            logger.error("[Compute] 이벤트 처리 예외 (계속): %s", e, exc_info=True)

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
        elif signal_type == "sector_recompute":
            # 실시간 틱 기반 업종순위 개별 종목 증분 업데이트 신호 처리
            code = signal.get("code")
            if code:
                from backend.app.services.engine_sector_confirm import request_sector_recompute
                request_sector_recompute(code)
        elif signal_type == "DYNAMIC_REG":
            from backend.app.services.engine_ws import subscribe_dynamic_data
            from backend.app.services.engine_state import state
            codes = payload.get("codes", [])
            await subscribe_dynamic_data(codes)
            # _subscribed_dynamic 플래그 설정
            for cd in codes:
                if cd in state.master_stocks_cache:
                    state.master_stocks_cache[cd]["_subscribed_dynamic"] = True
        elif signal_type == "DYNAMIC_UNREG":
            from backend.app.services.engine_ws import unsubscribe_dynamic_data
            from backend.app.services.engine_state import state
            codes = payload.get("codes", [])
            await unsubscribe_dynamic_data(codes)
            # _subscribed_dynamic 플래그 제거
            for cd in codes:
                if cd in state.master_stocks_cache:
                    state.master_stocks_cache[cd].pop("_subscribed_dynamic", None)
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
    # 캐시 직접 업데이트 제거 - 단일 소스 진리 원칙 준수
    # DB에서 캐시 갱신은 settings.py → apply_settings_change → refresh_engine_integrated_system_settings_cache 경로만 사용
    logger.info("[Compute] 설정 변경 처리 - 캐시 업데이트는 settings.py에서 DB 로드로 수행됨")
    
    # 설정(투자모드, 증권사 등) 변경에 따라 Header 상태 갱신
    from backend.app.services.engine_account_notify import notify_desktop_header_refresh
    notify_desktop_header_refresh()


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
        # 업종순위 재계산 — recompute_sector_summary_now 내부에서 notify_desktop_sector_scores(force=True) 호출됨
        await es.recompute_sector_summary_now()

        logger.info("[Compute] 업종순위 재계산 완료")

    except Exception as e:
        logger.error("[Compute] 업종순위 재계산 예외: %s", e, exc_info=True)


async def _process_tick_data(
    data: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    틱 데이터 처리 - 연산 로직 이관.

    Args:
        data: 틱 데이터 (dict)
        es: engine_service 모듈 (전역 상태 접근용)
        broadcast_queue: UI 전송 큐
    """
    # Step 3: engine_service의 연산 로직 이관
    # 1. 틱 데이터 파싱 및 캐시 업데이트
    trnm = data.get("trnm")
    if trnm == "REAL":
        await _handle_real_tick(data, es, broadcast_queue)


async def _handle_real_tick(
    data: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    REAL 틱 데이터 처리.

    Args:
        data: REAL 틱 데이터
        es: engine_service 모듈
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

            # 틱 타입 확인 및 정규화 (호가잔량 "0d", 체결 "01" 등)
            msg_type = item.get("type")
            from backend.app.services.engine_ws_parsing import _normalize_real_type
            norm_type = _normalize_real_type(msg_type)
            
            vals = item.get("values", {})
            if not isinstance(vals, dict):
                vals = {}

            # 0B/01 체결 처리 (주식 현재가)
            if norm_type == "01":
                await _handle_real_01_tick(item, vals, es, broadcast_queue)
            # 0D 호가 처리 (호가 잔량 테이블)
            elif norm_type == "0d":
                await _handle_real_0d_tick(item, vals, es, broadcast_queue)
            # PGM 프로그램 순매수 처리 (커스텀 타입)
            elif norm_type == "PGM":
                await _handle_real_pgm_tick(item, vals, es, broadcast_queue)

    except Exception as e:
        logger.error("[Compute] REAL 틱 처리 예외: %s", e, exc_info=True)


async def _handle_real_01_tick(
    item: dict,
    vals: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    0B/01 체결 틱 처리.

    Args:
        item: 틱 아이템
        vals: 틱 값
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    # engine_service._apply_real01_volume_amount_to_radar_rows 이관
    try:
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd, _base_stk_cd

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

        # 현재가/등락률/대비/거래대금/고가/체결강도 FID 중 하나라도 있으면 캐시 갱신 (단일 소스 진리)
        # 기존 "14" in vals 조건은 FID 14(거래대금)가 없는 틱에서 change_rate 갱신이 누락되는 버그를 유발했음.
        is_0b_tick = str(item.get("type", "")).strip().upper() in ("0B", "01")
        if is_0b_tick and any(f in vals for f in ("10", "11", "12", "14", "17", "228")):
            # engine_service._apply_real01_volume_amount_to_radar_rows 호출
            # 전역 변수 접근을 위해 es 모듈 사용
            es._apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick)

            # 연산 결과: 틱 수신 시 해당 종목에 대한 업종 점수 증분 재계산 트리거 (이벤트 큐 대신 _dirty_codes에 추가)
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            nk = _base_stk_cd(raw_cd)
            if nk:
                global _dirty_codes, _received_codes, _receive_rate_dirty
                _dirty_codes.add(nk)
                _received_codes.add(nk)
                _receive_rate_dirty = True


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
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd, _base_stk_cd
        from backend.app.services.engine_ws_dispatch import _ws_fid_int
        from backend.app.services.engine_account_notify import notify_orderbook_update

        # 종목코드 추출
        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return

        nk = _base_stk_cd(raw_cd)
        bid = _ws_fid_int(vals, "125", 0)  # 총 매수호가잔량
        ask = _ws_fid_int(vals, "121", 0)  # 총 매도호가잔량

        if bid < 0 or ask < 0:
            return

        # 매수후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송
        cache_entry = state.master_stocks_cache.get(nk, {})
        if cache_entry.get("_subscribed_dynamic", False):
            cache_entry["order_ratio"] = [bid, ask]
            notify_orderbook_update(nk, bid, ask)

    except Exception as e:
        logger.error("[Compute] 0D 틱 처리 예외: %s", e, exc_info=True)


async def _handle_real_pgm_tick(
    item: dict,
    vals: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    PGM 프로그램 순매수 틱 처리.
    """
    try:
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd, _base_stk_cd
        from backend.app.services.engine_account_notify import notify_program_update

        # 종목코드 추출
        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return

        nk = _base_stk_cd(raw_cd)
        tval_str = vals.get("tval", "0")
        try:
            tval = int(tval_str)
        except ValueError:
            tval = 0

        # 매수후보 종목이면 프로그램 순매수 변경을 프론트에 즉시 전송
        cache_entry = state.master_stocks_cache.get(nk, {})
        if cache_entry.get("_subscribed_dynamic", False):
            cache_entry["program_net_buy"] = tval
            notify_program_update(nk, tval)

    except Exception as e:
        logger.error("[Compute] PGM 틱 처리 예외: %s", e, exc_info=True)


async def _sector_recompute_loop_impl(es: ModuleType, broadcast_queue: asyncio.Queue) -> None:
    """
    업종순위 재계산 백그라운드 루프 (이벤트 기반).

    Phase 1 (1회): 실시간데이터 필드 수신율 임계값 대기 — 통과 후 Phase 2로 전환
    Phase 2: 0.3초 배치 재계산 루프 (틱 기반 증분 재계산)
    """
    from backend.app.services.engine_sector_confirm import request_sector_recompute
    global _compute_running, _receive_rate_dirty
    try:
        # Phase 1: 실시간데이터 필드 수신율 임계값 대기 (1회성 스타트업 게이트)
        # 1초 타임아웃 기반: per-tick 이벤트 set 제거, 스피닝 방지
        phase1_completed = False
        while _compute_running and not phase1_completed:
            try:
                await asyncio.sleep(1.0)

                if _receive_rate_dirty:
                    await _calculate_receive_rate(es)
                    threshold_pct = float(es._integrated_system_settings_cache["sector_start_threshold_pct"])
                    current_pct = _current_receive_rate["pct"]
                    received_count = _current_receive_rate["received"]
                    total_count = _current_receive_rate["total"]

                    if total_count == 0:
                        logger.info("[Compute] 업종순위 계산 대기 중 (종목 없음 -- 부트스트랩 대기)")
                        continue

                    if received_count == 0:
                        logger.info("[Compute] 업종순위 계산 대기 중 (실시간 데이터 수신 전 -- 0/%d)", total_count)
                        continue

                    if current_pct >= threshold_pct:
                        logger.info(
                            "[Compute] 실시간데이터 수신율 임계값 통과 (현재: %.1f%%, 임계값: %.1f%%). 업종순위 계산을 시작합니다.",
                            current_pct, threshold_pct
                        )
                        request_sector_recompute(None)  # 콜드 스타트 1회 전체 재계산
                        phase1_completed = True
                    else:
                        logger.info("[Compute] 업종순위 계산 대기 중 (수신율: %d/%d = %.1f%% < %.1f%%)", received_count, total_count, current_pct, threshold_pct)
                        # 수신율 전송 (단일 진입점)
                        await _send_receive_rate(_current_receive_rate)

            except Exception as e:
                logger.error("[Compute] 수신율 체크 예외: %s", e, exc_info=True)

        # Phase 2: 0.2초 배치 재계산 루프
        while _compute_running:
            await asyncio.sleep(0.2)
            global _dirty_codes

            # 수신율 계산 및 전송 (변경 시에만) — per-tick O(n) 계산 제거, 배치 처리
            if _receive_rate_dirty:
                await _calculate_receive_rate(es)
                await _send_receive_rate(get_current_receive_rate())
                _receive_rate_dirty = False

            # sector-scores 전송 (delta — 변경된 섹터만)
            from backend.app.services.engine_account_notify import notify_desktop_sector_scores
            notify_desktop_sector_scores(force=False)
            
            if _dirty_codes:
                # 안전하게 복사 후 클리어
                codes_to_compute = set(_dirty_codes)
                _dirty_codes.clear()

                # 재계산 실행
                for code in codes_to_compute:
                    request_sector_recompute(code)

    except asyncio.CancelledError:
        logger.info("[Compute] 백그라운드 업종 점수 재계산 루프 취소됨")

