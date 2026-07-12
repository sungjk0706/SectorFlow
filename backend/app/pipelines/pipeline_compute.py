# -*- coding: utf-8 -*-
"""
초고속 연산 엔진 (Compute Engine) - 파이프라인 아키텍처 Step 3

tick_queue에서 데이터를 꺼내어 연산 수행:
- 업종 점수 계산
- 체결강도 업데이트
- 매수/매도 타점 도달 여부 판단
- 결과를 broadcast_queue로 전송
"""
from __future__ import annotations
from typing import Optional
import asyncio
import time
import logging
from backend.app.services.engine_state import state
from backend.app.services.engine_ws_dispatch import _check_realtime_latency
from backend.app.services.core_queues import (
    get_tick_queue,
    get_broadcast_queue,
    get_control_queue,
)

logger = logging.getLogger(__name__)

# 전역 큐 할당 (메모리 상주)
broadcast_queue = get_broadcast_queue()

_current_receive_rate: dict = {"received": 0, "total": 0, "pct": 0.0}
_receive_rate_dirty: bool = False

# 누적 수신 종목 세트 — _reset_realtime_fields()에 의해 초기화되지 않음
# 한 번 수신된 종목은 앱 종료까지 수신된 것으로 유지되어 수신율이 0%로 강하하지 않음
_received_codes: set[str] = set()

# ── 업종순위 수신율 임계값 게이트 (단일 소스 진리) ──
# WS 구독 구간 진입 시 False로 리셋 → Phase 1 루프에서 임계값 통과 시 True로 전환.
# 비-WS 구간(확정 데이터 기반)은 기본값 True로 항상 허용.
# notify_desktop_sector_scores() 및 초기 스냅샷 전송이 이 플래그를 참조하여
# 임계값 미달 시 sector-scores 프론트엔드 전송을 차단함.
_sector_threshold_passed: bool = True


def is_sector_threshold_passed() -> bool:
    """업종순위 수신율 임계값 통과 여부 (단일 소스 진리).

    WS 구독 구간 내에서는 Phase 1 루프가 임계값 도달 시 True로 전환.
    비-WS 구간에서는 항상 True (확정 데이터 기반이므로 수신율 게이트 불필요).
    """
    return _sector_threshold_passed


def reset_sector_threshold() -> None:
    """임계값 게이트 리셋 — WS 구독 시작 시 호출.

    _on_ws_subscribe_start() / _init_ws_subscribe_state()에서 호출되어
    새 구독 세션 시작 시 임계값 게이트를 활성화함.
    """
    global _sector_threshold_passed
    _sector_threshold_passed = False


def mark_sector_threshold_passed() -> None:
    """임계값 통과 표시 — Phase 1 통과 또는 WS 구독 종료 시 호출.

    Phase 1 루프에서 임계값 도달 시 호출되어 이후 sector-scores 전송을 허용함.
    _on_ws_subscribe_end()에서도 호출되어 장마감 후 확정 데이터 기반 전송을 허용함.
    """
    global _sector_threshold_passed
    _sector_threshold_passed = True


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


async def _calculate_receive_rate() -> None:
    """수신율 계산 (배치 처리 — Phase 1/Phase 2 루프에서 호출).

    _received_codes는 per-tick O(1)으로 추가되므로 여기서는 계산만 수행.
    """
    global _current_receive_rate

    try:
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        inputs = await get_sector_summary_inputs()
        all_codes = inputs.get("all_codes", [])
        total_count = len(all_codes)

        if total_count == 0:
            return

        all_codes_set = set(all_codes)
        received_count = len(_received_codes & all_codes_set)
        current_pct = received_count / total_count * 100 if total_count > 0 else 0.0

        _current_receive_rate = {"received": received_count, "total": total_count, "pct": current_pct}

    except Exception as e:
        logger.error("[연산] 수신율 계산 오류: %s", e, exc_info=True)


def get_current_receive_rate() -> dict:
    """현재 수신율 반환 (notify_desktop_sector_scores에서 사용)."""
    global _current_receive_rate
    return dict(_current_receive_rate)


async def start_compute_loop() -> None:
    """Compute Engine 루프 시작."""
    global _compute_task, _compute_running, _sector_recompute_task

    if _compute_running:
        logger.warning("[연산] 이미 실행 중")
        return

    _compute_running = True

    _compute_task = asyncio.get_running_loop().create_task(_compute_loop_impl())
    _sector_recompute_task = asyncio.get_running_loop().create_task(_sector_recompute_loop_impl(get_broadcast_queue()))


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
        _sector_recompute_task = None
    if _compute_task:
        _compute_task.cancel()
        try:
            await _compute_task
        except asyncio.CancelledError:
            pass
        _compute_task = None


_BATCH_MAX = 500


def _coalesce_batch(batch: list) -> list:
    """배치 내 동일 종목 01 틱 코얼레싱 — 최신 데이터만 유지.

    01(체결) 타입 틱은 동일 종목코드에 대해 최신 1개만 처리.
    0d, 0j, PGM 등 다른 타입은 모두 유지.
    """
    from backend.app.services.engine_ws_parsing import _normalize_real_type

    _latest_01_by_code: dict[str, dict] = {}
    other_queue_items: list[dict] = []

    for queue_item in batch:
        if not isinstance(queue_item, dict):
            other_queue_items.append(queue_item)
            continue

        trnm = queue_item.get("trnm")
        if trnm != "REAL":
            other_queue_items.append(queue_item)
            continue

        real_data = queue_item.get("data")
        if isinstance(real_data, list):
            items = real_data
        elif isinstance(real_data, dict):
            items = [real_data]
        else:
            items = []

        remaining_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            msg_type = item.get("type")
            norm_type = _normalize_real_type(msg_type)

            if norm_type == "01":
                code = str(item.get("code") or item.get("item") or "").strip()
                if code:
                    _latest_01_by_code[code] = item
                else:
                    remaining_items.append(item)
            else:
                remaining_items.append(item)

        if remaining_items:
            other_queue_items.append({"trnm": "REAL", "data": remaining_items})

    result = other_queue_items
    if _latest_01_by_code:
        result.append({"trnm": "REAL", "data": list(_latest_01_by_code.values())})

    return result


async def _compute_loop_impl() -> None:
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
                    await _process_control_signal(control_signal, broadcast_queue)
                    control_queue.task_done()

                # tick_queue 데이터 처리
                if data is not None:
                    tick_queue.task_done()

                    # 배치 드레인: 큐에 남은 데이터를 한 번에 꺼냄 (이벤트 루프 yield 최소화)
                    batch = [data]
                    while len(batch) < _BATCH_MAX:
                        try:
                            item = tick_queue.get_nowait()
                            batch.append(item)
                            tick_queue.task_done()
                        except asyncio.QueueEmpty:
                            break

                    # 동일 종목 01 틱 코얼레싱 — 최신 데이터만 유지
                    coalesced = _coalesce_batch(batch)

                    # 배치 처리 + 계좌 전송 디바운스
                    _account_broadcast_dirty = False
                    for event in coalesced:
                        try:
                            _hit = await _process_tick_data(event, broadcast_queue)
                            if _hit:
                                _account_broadcast_dirty = True
                        except Exception as e:
                            logger.error("[연산] 이벤트 처리 오류 (계속): %s", e, exc_info=True)

                    # 배치 후 계좌 전송 1회 실행
                    if _account_broadcast_dirty:
                        try:
                            from backend.app.services import engine_account
                            await engine_account._refresh_account_snapshot_meta()
                            await engine_account._broadcast_account(reason="price_tick_batch")
                        except Exception as e:
                            logger.error("[연산] 배치 계좌 전송 실패: %s", e, exc_info=True)

                # P0-1: 틱 폭주 시 이벤트 루프 고갈 방지 - 협력적 멀티태스킹 (Yielding)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[연산] 처리 오류 (계속): %s", e, exc_info=True)
    finally:
        _compute_running = False


async def _process_control_signal(
    signal: dict,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    제어 신호 처리 (Step 6: 컨트롤 플레인 우회 배관 연동).

    Args:
        signal: 제어 신호 (dict)
        broadcast_queue: UI 전송 큐
    """
    try:
        signal_type = signal.get("type")
        payload = signal.get("payload", {})

        if signal_type == "UPDATE_CONFIG":
            # 설정 변경 신호 처리
            await _handle_config_update(payload, broadcast_queue)
        elif signal_type == "RECOMPUTE_SECTOR":
            # 업종순위 재계산 신호 처리
            await _handle_sector_recompute(broadcast_queue)
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
            logger.warning("[연산] 알 수 없는 제어 신호: %s", signal_type)

    except Exception as e:
        logger.error("[연산] 제어 신호 처리 오류: %s", e, exc_info=True)


async def _handle_config_update(
    payload: dict,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    설정 변경 처리.

    Args:
        payload: 설정 변경 데이터
        broadcast_queue: UI 전송 큐
    """
    # 캐시 직접 업데이트 제거 - 단일 소스 진리 원칙 준수
    # DB에서 캐시 갱신은 settings.py → apply_settings_change → refresh_engine_integrated_system_settings_cache 경로만 사용
    logger.info("[연산] 설정 변경 처리 - 캐시 갱신은 settings.py에서 DB 로드로 수행됨")
    
    # 설정(투자모드, 증권사 등) 변경에 따라 Header 상태 갱신
    from backend.app.services.engine_account_notify import notify_desktop_header_refresh
    await notify_desktop_header_refresh()


async def _handle_sector_recompute(
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    업종순위 재계산 처리.

    Args:
        broadcast_queue: UI 전송 큐
    """
    try:
        # 업종순위 재계산 — recompute_sector_summary_now 내부에서 notify_desktop_sector_scores(force=True) 호출됨
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        await recompute_sector_summary_now()

        logger.info("[연산] 업종순위 재계산 완료")

    except Exception as e:
        logger.error("[연산] 업종순위 재계산 오류: %s", e, exc_info=True)


async def _process_tick_data(
    data: dict,
    broadcast_queue: asyncio.Queue,
) -> bool:
    """
    틱 데이터 처리 - 연산 로직 이관.

    Args:
        data: 틱 데이터 (dict)
        broadcast_queue: UI 전송 큐

    Returns:
        True if 보유종목 가격 갱신 발생 (계좌 전송 필요), False otherwise.
    """
    # Step 3: engine_service의 연산 로직 이관
    # 1. 틱 데이터 파싱 및 캐시 업데이트
    trnm = data.get("trnm")
    if trnm == "REAL":
        return await _handle_real_tick(data, broadcast_queue)
    return False


async def _handle_real_tick(
    data: dict,
    broadcast_queue: asyncio.Queue,
) -> bool:
    """
    REAL 틱 데이터 처리.

    Args:
        data: REAL 틱 데이터
        broadcast_queue: UI 전송 큐

    Returns:
        True if 보유종목 가격 갱신 발생 (계좌 전송 필요), False otherwise.
    """
    _account_dirty = False
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
                _hit = await _handle_real_01_tick(item, vals, broadcast_queue)
                if _hit:
                    _account_dirty = True
            # 00 주문체결 처리 (자동매매 체결 콜백 + 잔고 갱신)
            elif norm_type == "00":
                from backend.app.services.engine_ws_dispatch import _handle_real_00
                await _handle_real_00(item, vals)
            # 04/80 잔고 처리 (실시간 잔고 변동 반영)
            elif norm_type in ("04", "80"):
                from backend.app.services.engine_ws_dispatch import _handle_real_balance
                await _handle_real_balance(item, vals)
            # 0D 호가 처리 (호가 잔량 테이블)
            elif norm_type == "0d":
                await _handle_real_0d_tick(item, vals, broadcast_queue)
            # 0J 업종지수 처리 (즉시 전송, 저장 없음)
            elif norm_type == "0j":
                await _handle_real_0j_tick(item, vals)
            # PGM 프로그램 순매수 처리 (커스텀 타입)
            elif norm_type == "PGM":
                await _handle_real_pgm_tick(item, vals, broadcast_queue)

    except Exception as e:
        logger.error("[연산] 실시간 틱 처리 오류: %s", e, exc_info=True)
    return _account_dirty


async def _handle_real_0j_tick(item: dict, vals: dict) -> None:
    """0J 업종지수 틱 처리 — 저장 없이 즉시 화면에 전송."""
    upcode = str(item.get("item", "") or "").strip()
    if not upcode:
        return
    jisu = str(vals.get("10", "") or "").strip()
    change = str(vals.get("11", "") or "").strip()
    drate = str(vals.get("12", "") or "").strip()
    sign = str(vals.get("25", "") or "").strip()
    if not jisu:
        return
    from backend.app.services.engine_account_notify import notify_index_data
    await notify_index_data(upcode, jisu, change, drate, sign)


async def _handle_real_01_tick(
    item: dict,
    vals: dict,
    broadcast_queue: asyncio.Queue,
) -> bool:
    """
    0B/01 체결 틱 처리.

    Args:
        item: 틱 아이템
        vals: 틱 값
        broadcast_queue: UI 전송 큐

    Returns:
        True if 보유종목 가격 갱신 발생 (계좌 전송 필요), False otherwise.
    """
    global _received_codes, _receive_rate_dirty

    _price_hit = False
    _ts = int(time.time() * 1000)
    try:
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd, _base_stk_cd
        from backend.app.services.engine_ws_parsing import (
            _parse_fid10_price,
            parse_change_rate_to_percent,
            _ws_fid_int,
            _ws_fid_key_present,
            _ws_fid_raw,
        )
        from backend.app.services.auto_trading_effective import auto_sell_effective
        from backend.app.core.trade_mode import is_test_mode
        from backend.app.services import dry_run
        from backend.app.services.engine_account_rest import (
            apply_last_price_to_positions_inplace,
            recalc_broker_totals_from_positions,
        )
        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return False

        nk_px = _base_stk_cd(raw_cd)
        last_px = _parse_fid10_price(vals)
        is_0b_tick = str(item.get("type", "")).strip().upper() in ("0B", "01")

        if not nk_px or last_px <= 0:
            _check_realtime_latency(_ts)
            return False

        # ── 1. 화면으로 실시간 틱 데이터 전송 ──
        item["item"] = raw_cd
        item["_ts"] = _ts
        try:
            broadcast_queue.put_nowait({"type": "real-data", "data": item})
        except asyncio.QueueFull:
            logger.warning("[연산] 전송 큐 가득 참 — 화면 데이터 누락 (종목코드=%s)", raw_cd)

        # ── 2. 레이더 행 갱신 + 업종 점수 증분 재계산 트리거 ──
        if is_0b_tick and any(f in vals for f in ("10", "11", "12", "14", "17", "228")):
            from backend.app.services.engine_radar import _apply_real01_volume_amount_to_radar_rows
            _apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick)
            if nk_px:
                from backend.app.services.engine_sector_confirm import request_sector_recompute
                request_sector_recompute(nk_px)
                _received_codes.add(nk_px)
                _receive_rate_dirty = True

        # ── 3. 보유종목 현재가 반영 — 평가손익·수익률 실시간 재계산 ──
        diff = _ws_fid_int(vals, "11", 0) if _ws_fid_key_present(vals, "11") else 0
        rate = parse_change_rate_to_percent(_ws_fid_raw(vals, "12")) if _ws_fid_key_present(vals, "12") else 0.0
        _price_hit = False
        if is_test_mode(state.integrated_system_settings_cache):
            _price_hit = await dry_run.update_price(nk_px, last_px)
            if _price_hit:
                _dr_pos = await dry_run.get_position(nk_px)
                if _dr_pos:
                    _dr_pos["change"] = diff
                    _dr_pos["change_rate"] = rate
        else:
            _price_hit = apply_last_price_to_positions_inplace(state.positions, raw_cd, last_px)
            if _price_hit:
                state.broker_rest_totals = recalc_broker_totals_from_positions(
                    state.positions, state.broker_rest_totals
                )

        # ── 4. 자동매도 조건 체크 ──
        if _price_hit and state.auto_trade and auto_sell_effective(state.integrated_system_settings_cache) and state.access_token:
            if is_test_mode(state.integrated_system_settings_cache):
                _pos = await dry_run.get_position(nk_px)
                if _pos:
                    await state.auto_trade.check_sell_conditions([_pos], state.integrated_system_settings_cache, state.access_token)
            else:
                _matched = [p for p in state.positions if _base_stk_cd(str(p.get("stk_cd", "") or "")) == nk_px]
                if _matched:
                    await state.auto_trade.check_sell_conditions(_matched, state.integrated_system_settings_cache, state.access_token)

        # ── 5. 지연 측정 ──
        _check_realtime_latency(_ts)

    except Exception as e:
        logger.error("[연산] 체결 틱(0B/01) 처리 오류: %s", e, exc_info=True)
    return _price_hit


async def _handle_real_0d_tick(
    item: dict,
    vals: dict,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    0D 호가 틱 처리 (호가 잔량 테이블).

    Args:
        item: 틱 아이템
        vals: 틱 값
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

        # 매수 후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송
        cache_entry = state.master_stocks_cache.get(nk, {})
        if cache_entry.get("_subscribed_dynamic", False):
            cache_entry["order_ratio"] = [bid, ask]
            await notify_orderbook_update(nk, bid, ask)

    except Exception as e:
        logger.error("[연산] 호가 틱(0D) 처리 오류: %s", e, exc_info=True)


async def _handle_real_pgm_tick(
    item: dict,
    vals: dict,
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

        # 매수 후보 종목이면 프로그램 순매수 변경을 프론트에 즉시 전송
        cache_entry = state.master_stocks_cache.get(nk, {})
        if cache_entry.get("_subscribed_dynamic", False):
            cache_entry["program_net_buy"] = tval
            await notify_program_update(nk, tval)

    except Exception as e:
        logger.error("[연산] 프로그램 순매수 틱(PGM) 처리 오류: %s", e, exc_info=True)


async def _sector_recompute_loop_impl(broadcast_queue: asyncio.Queue) -> None:
    """
    업종순위 재계산 백그라운드 루프 (이벤트 기반).

    Phase 1 (1회): 실시간데이터 필드 수신율 임계값 대기 — 통과 후 Phase 2로 전환
    Phase 2: 0.2초 배치 재계산 루프 (틱 기반 증분 재계산)
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
                    await _calculate_receive_rate()
                    threshold_pct = float(state.integrated_system_settings_cache["sector_start_threshold_pct"])
                    current_pct = _current_receive_rate["pct"]
                    received_count = _current_receive_rate["received"]
                    total_count = _current_receive_rate["total"]

                    if total_count == 0:
                        continue

                    if received_count == 0:
                        continue

                    if current_pct >= threshold_pct:
                        logger.info(
                            "[연산] 실시간데이터 수신율 임계값 통과 (현재: %.1f%%, 임계값: %.1f%%). 업종순위 계산을 시작합니다.",
                            current_pct, threshold_pct
                        )
                        mark_sector_threshold_passed()
                        request_sector_recompute(None)  # 콜드 스타트 1회 전체 재계산
                        phase1_completed = True
                    else:
                        # 수신율 전송 (단일 진입점)
                        await _send_receive_rate(_current_receive_rate)

            except Exception as e:
                logger.error("[연산] 수신율 체크 오류: %s", e, exc_info=True)

        # Phase 2: 0.2초 배치 재계산 루프
        from backend.app.services.engine_sector_confirm import has_dirty_sectors, _flush_sector_recompute_impl
        while _compute_running:
            await asyncio.sleep(0.2)

            # 수신율 계산 및 전송 (변경 시에만) — per-tick O(n) 계산 제거, 배치 처리
            if _receive_rate_dirty:
                await _calculate_receive_rate()
                await _send_receive_rate(get_current_receive_rate())
                _receive_rate_dirty = False

            # sector-scores 전송 (delta — 변경된 업종만)
            from backend.app.services.engine_account_notify import notify_desktop_sector_scores
            await notify_desktop_sector_scores(force=False)

            if has_dirty_sectors():
                await _flush_sector_recompute_impl()

    except asyncio.CancelledError:
        logger.info("[연산] 백그라운드 업종 점수 재계산 반복 취소됨")

