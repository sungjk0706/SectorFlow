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
from backend.app.core.logger import log_receive_rate_progress, log_progress_end
from backend.app.services.engine_state import state
from backend.app.services.engine_ws_dispatch import _check_realtime_latency
from backend.app.services.engine_utils import LazyEvent
from backend.app.services.core_queues import (
    get_tick_queue,
    get_broadcast_queue,
    get_control_queue,
)
# 틱 핸들러·코얼레싱 — 분리 모듈 (P24 단순성). pipeline_compute 전역(state/수신세트/플래그)을
# 지연 import로 참조하므로 테스트 patch("...pipeline_compute.state") 경로가 유효.
from backend.app.pipelines.pipeline_compute_tick_handlers import (
    _coalesce_batch,
    _handle_real_0j_tick,
    _handle_real_01_tick,
    _handle_real_0d_tick,
    _handle_real_pgm_tick,
)

logger = logging.getLogger(__name__)

# 전역 큐 할당 (메모리 상주)
broadcast_queue = get_broadcast_queue()

_current_receive_rate: dict = {
    "krx": {"received": 0, "total": 0, "pct": 0.0},
    "nxt": {"received": 0, "total": 0, "pct": 0.0},
}
_receive_rate_dirty: bool = False
# 수신율 갱신 이벤트 — 틱 수신 시 set(), Phase 1 루프에서 wait() (P11 이벤트 기반, while+sleep 폴링 금지)
_receive_rate_event: LazyEvent = LazyEvent()

# 누적 수신 종목 세트 — _reset_realtime_fields()에 의해 초기화되지 않음
# 한 번 수신된 종목은 앱 종료까지 수신된 것으로 유지되어 수신율이 0%로 강하하지 않음
# KRX/NXT 분리 (P10 SSOT — nxt_enable 필드 기반, P23 일관성 — sector-stock.ts 카운트와 동일 기준):
# - _received_codes_krx: KRX 단독 상장 종목 (nxt_enable=False)
# - _received_codes_nxt: NXT 중복상장 종목 (nxt_enable=True)
_received_codes_krx: set[str] = set()
_received_codes_nxt: set[str] = set()

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
    _receive_rate_event.clear()


def mark_sector_threshold_passed() -> None:
    """임계값 통과 표시 — Phase 1 통과 또는 WS 구독 종료 시 호출.

    Phase 1 루프에서 임계값 도달 시 호출되어 이후 sector-scores 전송을 허용함.
    _on_ws_subscribe_end()에서도 호출되어 장마감 후 확정 데이터 기반 전송을 허용함.
    """
    global _sector_threshold_passed
    _sector_threshold_passed = True


async def _send_receive_rate(receive_rate: dict) -> None:
    """수신율 전송 단일 진입점 (단일 소스 진리 원칙 준수).

    분리 구조: {krx: {received, total, pct}, nxt: {received, total, pct}}
    """
    await broadcast_queue.put({
        "type": "receive-rate",
        "data": {
            "krx": {
                "pct": receive_rate["krx"]["pct"],
                "received": receive_rate["krx"]["received"],
                "total": receive_rate["krx"]["total"],
            },
            "nxt": {
                "pct": receive_rate["nxt"]["pct"],
                "received": receive_rate["nxt"]["received"],
                "total": receive_rate["nxt"]["total"],
            },
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

    KRX/NXT 분리 집계 (P10 SSOT — nxt_enable 필드 기반, P23 일관성 — sector-stock.ts 카운트와 동일 기준):
    - _received_codes_krx / _received_codes_nxt: 틱 수신 시 is_nxt_enabled()로 분기하여 추가.
      _reset_realtime_fields()에 의해 초기화되지 않음 — WS 구간에서 메모리가 None이 되어도 수신 이력 보존.
    - _has_any_realtime_data: 메모리 캐시의 change_rate/trade_amount가 None이 아닌 종목.
      비-WS 구간(확정 데이터)에서 _reset_realtime_fields()가 호출되지 않으므로 100% 산출.
    - 시간대별 분리 (P22 정합성 — market_phase 기반 파생):
      NXT-only 구간: krx_codes가 빈 리스트 → KRX 수신률 0/0 (비활성), NXT 수신률만 산출.
      정규장: krx_codes + nxt_codes 양쪽 분리 산출.
    """
    global _current_receive_rate

    try:
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        inputs = await get_sector_summary_inputs()
        krx_codes = inputs.get("krx_codes", [])
        nxt_codes = inputs.get("nxt_codes", [])

        krx_rate = _calc_market_receive_rate(krx_codes, _received_codes_krx)
        nxt_rate = _calc_market_receive_rate(nxt_codes, _received_codes_nxt)

        _current_receive_rate = {"krx": krx_rate, "nxt": nxt_rate}

    except Exception as e:
        logger.error("[연산] 수신율 계산 오류: %s", e, exc_info=True)


def _calc_market_receive_rate(codes: list[str], received_set: set[str]) -> dict:
    """단일 시장(KRX 또는 NXT) 수신률 계산.

    누적 수신 세트(received_set)와 메모리 캐시 필드를 결합하여 산출.
    codes가 빈 리스트인 경우(비활성 시간대) total=0, received=0, pct=0.0 반환.
    """
    total_count = len(codes)
    if total_count == 0:
        return {"received": 0, "total": 0, "pct": 0.0}

    received_count = 0
    for code in codes:
        if code in received_set:
            received_count += 1
        else:
            entry = state.master_stocks_cache.get(code)
            if entry and _has_any_realtime_data(entry):
                received_count += 1

    current_pct = received_count / total_count * 100
    return {"received": received_count, "total": total_count, "pct": current_pct}


def get_current_receive_rate() -> dict:
    """현재 수신율 반환 (notify_desktop_sector_scores, engine_snapshot, ws.py에서 사용).

    분리 구조: {krx: {received, total, pct}, nxt: {received, total, pct}}
    """
    global _current_receive_rate
    return {
        "krx": dict(_current_receive_rate["krx"]),
        "nxt": dict(_current_receive_rate["nxt"]),
    }


async def start_compute_loop() -> None:
    """Compute Engine 루프 시작."""
    global _compute_task, _compute_running, _sector_recompute_task

    if _compute_running:
        logger.warning("[연산] 이미 실행 중")
        return

    _compute_running = True

    _compute_task = asyncio.get_running_loop().create_task(_compute_loop_impl())
    _compute_task.add_done_callback(
        lambda t: logger.warning("[연산] compute 루프 작업 실패: %s", t.exception())
        if t.exception() else None
    )
    _sector_recompute_task = asyncio.get_running_loop().create_task(_sector_recompute_loop_impl(get_broadcast_queue()))
    _sector_recompute_task.add_done_callback(
        lambda t: logger.warning("[연산] 업종 재계산 루프 작업 실패: %s", t.exception())
        if t.exception() else None
    )


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


async def _drain_control_queue(control_queue: asyncio.Queue, broadcast_queue: asyncio.Queue) -> None:
    """control_queue non-blocking 드레인 — 모든 제어 신호를 즉시 처리."""
    while True:
        try:
            _, _, control_signal = control_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        await _process_control_signal(control_signal, broadcast_queue)
        control_queue.task_done()


async def _process_tick_batch(batch: list, broadcast_queue: asyncio.Queue) -> None:
    """배치 처리 + 계좌 전송 디바운스 — 코얼레싱 후 이벤트별 처리 + 1회 계좌 전송."""
    coalesced = _coalesce_batch(batch)

    _account_broadcast_dirty = False
    for event in coalesced:
        try:
            _hit = await _process_tick_data(event, broadcast_queue)
            if _hit:
                _account_broadcast_dirty = True
        except Exception as e:
            logger.error("[연산] 이벤트 처리 오류 (계속): %s", e, exc_info=True)

    if _account_broadcast_dirty:
        try:
            from backend.app.services import engine_account
            await engine_account._refresh_account_snapshot_meta()
            await engine_account._broadcast_account(reason="price_tick_batch")
        except Exception as e:
            logger.error("[연산] 배치 계좌 전송 실패: %s", e, exc_info=True)


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

                await _drain_control_queue(control_queue, broadcast_queue)

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

                    await _process_tick_batch(batch, broadcast_queue)

                # P0-1: 틱 폭주 시 이벤트 루프 고갈 방지 - 협력적 멀티태스킹 (Yielding)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[연산] 처리 오류 (계속): %s", e, exc_info=True)
    finally:
        _compute_running = False


async def _handle_dynamic_reg(payload: dict) -> None:
    """DYNAMIC_REG 제어 신호 처리 — 동적 구독 요청 + _subscribed_dynamic 플래그 갱신 (P10 SSOT, P22 정합성)."""
    from backend.app.services.engine_ws import subscribe_dynamic_data
    from backend.app.services.engine_state import state
    from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES

    codes = payload.get("codes", [])
    ok = await subscribe_dynamic_data(codes)
    if ok:
        # 구독 성공 — _subscribed_dynamic 플래그 설정 (단일 진실 소스, P10 SSOT, P22 정합성)
        for cd in codes:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd]["_subscribed_dynamic"] = True
        # 대기 세트에서 제거 — 실제 구독 완료되었으므로
        _PENDING_REG_CODES.difference_update(codes)
    else:
        # 구독 실패 — _subscribed_dynamic 미설정, _PENDING_REG_CODES 유지하여 재시도 가능 (P22)
        logger.warning("[연산] 동적 구독 실패 — %d종목 대기 세트 유지 (재시도 대상)", len(codes))


async def _handle_dynamic_unreg(payload: dict) -> None:
    """DYNAMIC_UNREG 제어 신호 처리 — 동적 구독 해지 + _subscribed_dynamic 플래그 제거."""
    from backend.app.services.engine_ws import unsubscribe_dynamic_data
    from backend.app.services.engine_state import state
    from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES

    codes = payload.get("codes", [])
    await unsubscribe_dynamic_data(codes)
    # _subscribed_dynamic 플래그 제거
    for cd in codes:
        if cd in state.master_stocks_cache:
            state.master_stocks_cache[cd].pop("_subscribed_dynamic", None)
    # 대기 세트에서도 제거 — 해지된 종목이 대기 중이었을 수 있음
    _PENDING_REG_CODES.difference_update(codes)


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
            await _handle_dynamic_reg(payload)
        elif signal_type == "DYNAMIC_UNREG":
            await _handle_dynamic_unreg(payload)
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
    logger.info("[연산] 설정 변경 처리 - 캐시 갱신은 설정 파일에서 DB 로드로 수행됨")
    
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


def _extract_real_items(real_data) -> list:
    """REAL 틱의 data 필드를 아이템 리스트로 정규화 (list/dict/기타 → list)."""
    if isinstance(real_data, list):
        return real_data
    if isinstance(real_data, dict):
        return [real_data]
    return []


async def _dispatch_real_item(item: dict, broadcast_queue: asyncio.Queue) -> bool:
    """단일 REAL 아이템을 타입별 leaf 핸들러로 분배.

    Returns: 보유종목 가격 갱신 발생 여부 (01 체결 틱만 True).
    """
    from backend.app.services.engine_ws_parsing import _normalize_real_type

    msg_type = item.get("type")
    norm_type = _normalize_real_type(msg_type)

    vals = item.get("values", {})
    if not isinstance(vals, dict):
        vals = {}

    # 0B/01 체결 처리 (주식 현재가)
    if norm_type == "01":
        return await _handle_real_01_tick(item, vals, broadcast_queue)
    # 00 주문체결 처리 (자동매매 체결 콜백 + 잔고 갱신)
    if norm_type == "00":
        from backend.app.services.engine_ws_dispatch import _handle_real_00
        await _handle_real_00(item, vals)
        return False
    # 04/80 잔고 처리 (실시간 잔고 변동 반영)
    if norm_type in ("04", "80"):
        from backend.app.services.engine_ws_dispatch import _handle_real_balance
        await _handle_real_balance(item, vals)
        return False
    # 0D 호가 처리 (호가 잔량 테이블)
    if norm_type == "0d":
        await _handle_real_0d_tick(item, vals, broadcast_queue)
        return False
    # 0J 업종지수 처리 (즉시 전송, 저장 없음)
    if norm_type == "0j":
        await _handle_real_0j_tick(item, vals)
        return False
    # PGM 프로그램 순매수 처리 (커스텀 타입)
    if norm_type == "PGM":
        await _handle_real_pgm_tick(item, vals, broadcast_queue)
        return False
    return False


async def _handle_real_tick(
    data: dict,
    broadcast_queue: asyncio.Queue,
) -> bool:
    """
    REAL 틱 데이터 처리.

    Returns: 보유종목 가격 갱신 발생 시 True (계좌 전송 필요).
    """
    _account_dirty = False
    try:
        items = _extract_real_items(data.get("data"))
        for item in items:
            if not isinstance(item, dict):
                continue
            _hit = await _dispatch_real_item(item, broadcast_queue)
            if _hit:
                _account_dirty = True
    except Exception as e:
        logger.error("[연산] 실시간 틱 처리 오류: %s", e, exc_info=True)
    return _account_dirty


def _evaluate_threshold(threshold_pct: float) -> tuple[bool, bool]:
    """임계값 판정 — 시간대별 분기 정책 (옵션 C, P21 사용자 투명성).

    Returns: (threshold_met, skip_this_round)
      - threshold_met: 임계값 통과 여부 (True 시 Phase 1 → Phase 2 전환)
      - skip_this_round: 이번 라운드 건너뜀 (종목 0건 등 비활성 상태)
    """
    from backend.app.services.daily_time_scheduler import is_nxt_only_window

    krx_rate = _current_receive_rate["krx"]
    nxt_rate = _current_receive_rate["nxt"]
    krx_pct = krx_rate["pct"]
    nxt_pct = nxt_rate["pct"]
    krx_received = krx_rate["received"]
    krx_total = krx_rate["total"]
    nxt_received = nxt_rate["received"]
    nxt_total = nxt_rate["total"]

    # 비-WS 구간: 양쪽 모두 확정 데이터 → 100% 산출 → 즉시 통과
    # WS 구간: 시간대별 분기 정책 (옵션 C)
    if is_nxt_only_window():
        # NXT-only 구간: NXT 수신률만 기준
        if nxt_total == 0 or nxt_received == 0:
            return False, True
        return nxt_pct >= threshold_pct, False
    # 정규장 또는 비-WS 구간: KRX/NXT 양쪽 모두 임계값 도달 (AND)
    # 비-WS 구간은 양쪽 모두 100%이므로 자연스럽게 통과
    if krx_total == 0 or nxt_total == 0:
        # 한쪽이라도 종목이 없으면 통과 불가 (비-WS 구간 제외 — 양쪽 모두 100%)
        # 단, 양쪽 모두 total=0인 빈 캐시 상태는 스킵
        # 한쪽만 0인 경우 — 비정상 상황이므로 대기
        return False, True
    if krx_received == 0 and nxt_received == 0:
        return False, True
    return krx_pct >= threshold_pct and nxt_pct >= threshold_pct, False


async def _phase1_wait_threshold() -> None:
    """Phase 1: 실시간데이터 필드 수신율 임계값 대기 (1회성 스타트업 게이트).

    이벤트 기반 대기 — 틱 수신 시 _receive_rate_event.set() 신호로 즉시 웨이크업 (P11).
    200ms 디바운스로 다수 틱을 코얼레싱하여 수신율 갱신 빈도를 제한.
    항상 master_stocks_cache의 change_rate, trade_amount 필드 기반으로 수신율 계산.
    WS 구독 시작 시 _reset_realtime_fields()가 필드를 None으로 초기화하므로
    비-WS 구간(확정 데이터 있음)은 100%로 즉시 통과, WS 구간은 0%에서 틱 수신시 상승.

    임계값 게이트 정책 — 옵션 C (시간대별 분기, P21 사용자 투명성):
    - NXT-only 구간(08:00~08:50, 15:40~20:00): NXT 수신률만 기준
    - 정규장(09:00~15:20): KRX/NXT 양쪽 모두 임계값 도달 시 (AND)
    - 비-WS 구간: 확정 데이터 기반이므로 양쪽 모두 100% → 즉시 통과
    """
    from backend.app.services.engine_sector_confirm import request_sector_recompute

    phase1_completed = False
    _prev_krx_received = -1
    _prev_nxt_received = -1
    while _compute_running and not phase1_completed:
        try:
            # 이벤트 대기 (틱 수신 시 신호) — P11 이벤트 기반, while+sleep 폴링 금지
            await _receive_rate_event.wait()
            _receive_rate_event.clear()
            # 디바운스: 200ms 대기로 다수 틱 코얼레싱 (수신율 갱신 빈도 제한)
            # 대기 중 새 틱이 event를 set하면 다음 반복이 즉시 웨이크업 — 신호 손실 없음
            await asyncio.sleep(0.2)

            await _calculate_receive_rate()
            threshold_pct = float(state.integrated_system_settings_cache["sector_start_threshold_pct"])
            krx_rate = _current_receive_rate["krx"]
            nxt_rate = _current_receive_rate["nxt"]
            krx_received = krx_rate["received"]
            krx_total = krx_rate["total"]
            nxt_received = nxt_rate["received"]
            nxt_total = nxt_rate["total"]
            krx_pct = krx_rate["pct"]
            nxt_pct = nxt_rate["pct"]

            threshold_met, skip = _evaluate_threshold(threshold_pct)
            if skip:
                continue

            if threshold_met:
                # 1줄 갱신 종료 — 통과 시점 info 로그가 새 줄에서 시작하도록 줄바꿈 (커서 꼬임 방지)
                log_progress_end()
                logger.info(
                    "[연산] 실시간데이터 수신율 임계값 통과 (KRX: %.1f%%, NXT: %.1f%%, 임계값: %.1f%%). 업종순위 계산을 시작합니다.",
                    krx_pct, nxt_pct, threshold_pct
                )
                mark_sector_threshold_passed()
                request_sector_recompute(None)  # 콜드 스타트 1회 전체 재계산
                phase1_completed = True
            else:
                # 수신율 전송 (단일 진입점)
                await _send_receive_rate(_current_receive_rate)
                # 수신 종목 수 증가 시에만 로그 출력 (P21 사용자 투명성)
                if krx_received != _prev_krx_received or nxt_received != _prev_nxt_received:
                    log_receive_rate_progress(
                        krx_received, krx_total, nxt_received, nxt_total,
                        threshold_pct, waiting=True,
                    )
                    _prev_krx_received = krx_received
                    _prev_nxt_received = nxt_received

        except Exception as e:
            logger.error("[연산] 수신율 체크 오류: %s", e, exc_info=True)


async def _phase2_batch_recompute_loop() -> None:
    """Phase 2: 0.2초 배치 재계산 루프 (틱 기반 증분 재계산)."""
    global _receive_rate_dirty
    from backend.app.services.engine_sector_confirm import has_dirty_sectors, _flush_sector_recompute_impl
    from backend.app.services.engine_account_notify import notify_desktop_sector_scores

    _prev_p2_krx_received = _current_receive_rate["krx"]["received"]
    _prev_p2_nxt_received = _current_receive_rate["nxt"]["received"]
    while _compute_running:
        await asyncio.sleep(0.2)

        try:
            # 수신율 계산 및 전송 (변경 시에만) — per-tick O(n) 계산 제거, 배치 처리
            if _receive_rate_dirty:
                await _calculate_receive_rate()
                await _send_receive_rate(get_current_receive_rate())
                _receive_rate_dirty = False
                # 수신 종목 수 증가 시에만 로그 출력 (P21 사용자 투명성)
                _p2_krx_received = _current_receive_rate["krx"]["received"]
                _p2_nxt_received = _current_receive_rate["nxt"]["received"]
                if _p2_krx_received != _prev_p2_krx_received or _p2_nxt_received != _prev_p2_nxt_received:
                    log_receive_rate_progress(
                        _p2_krx_received, _current_receive_rate["krx"]["total"],
                        _p2_nxt_received, _current_receive_rate["nxt"]["total"],
                        0.0, waiting=False,
                    )
                    _prev_p2_krx_received = _p2_krx_received
                    _prev_p2_nxt_received = _p2_nxt_received

            # sector-scores 전송 (delta — 변경된 업종만)
            await notify_desktop_sector_scores(force=False)

            if has_dirty_sectors():
                await _flush_sector_recompute_impl()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("[연산] Phase2 재계산 루프 오류 (계속): %s", e, exc_info=True)


async def _sector_recompute_loop_impl(broadcast_queue: asyncio.Queue) -> None:
    """
    업종순위 재계산 백그라운드 루프 (이벤트 기반).

    Phase 1 (1회): 실시간데이터 필드 수신율 임계값 대기 — 통과 후 Phase 2로 전환
    Phase 2: 0.2초 배치 재계산 루프 (틱 기반 증분 재계산)
    """
    global _compute_running
    try:
        await _phase1_wait_threshold()
        await _phase2_batch_recompute_loop()
    except asyncio.CancelledError:
        logger.info("[연산] 백그라운드 업종 점수 재계산 반복 취소됨")
    except Exception as e:
        logger.error("[연산] 업종 점수 재계산 루프 치명 오류: %s", e, exc_info=True)

