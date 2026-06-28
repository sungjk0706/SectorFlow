from __future__ import annotations
# -*- coding: utf-8 -*-
"""
WebSocket 수신 `trnm` 분기 -- `engine_service._handle_ws_data` 본문을 위임.
engine_state에서 직접 상태를 참조하여 순환 import 없이 모듈 전역 상태를 갱신한다.
"""

import asyncio
import json
import time

import backend.app.services.engine_state as engine_state
from backend.app.services import engine_account
from backend.app.services import engine_lifecycle
from types import ModuleType
from collections.abc import Callable

from backend.app.core.logger import get_logger
from backend.app.services.auto_trading_effective import auto_sell_effective
from backend.app.core.trade_mode import is_test_mode
from backend.app.services import dry_run
from backend.app.services.engine_account_notify import (
    notify_raw_real_data,
)
from backend.app.services.engine_account_rest import (
    apply_last_price_to_positions_inplace,
    recalc_broker_totals_from_positions,
)
import backend.app.services.engine_radar_ops as engine_radar_ops
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    _real_item_stk_cd,
    _resolve_bucket_key,
)
from backend.app.services.engine_ws_parsing import (
    _normalize_real_type,
    _parse_fid10_price,
    parse_change_rate_to_percent,
    _ws_fid_float,
    _ws_fid_int,
    _ws_fid_key_present,
    _ws_fid_raw,
    parse_fid9081_exchange,
    parse_fid290_session,
)

logger = get_logger("engine")

# ── _wl_codes 캐시 (매 틱마다 Set 재생성 방지) ──
_wl_codes_cache: set[str] = set()
_wl_codes_layout_len: int = -1

# ── LIVE 전환 조건 강화: symbol별 필수 필드 캐시 ──
_realtime_required_fields_cache: dict[str, dict] = {}  # {symbol: {"price": bool, "change": bool, "volume": bool}}
_realtime_first_tick_ts_map: dict[str, int] = {}  # {symbol: timestamp (ms)}


def _get_wl_codes_cached() -> set[str]:
    """sector_stock_layout → code Set 캐시. 레이아웃 길이가 바뀔 때만 재생성."""
    global _wl_codes_cache, _wl_codes_layout_len
    cur_len = len(engine_state._integrated_system_settings_cache["sector_stock_layout"])
    if cur_len != _wl_codes_layout_len:
        _wl_codes_cache = {v for t, v in engine_state._integrated_system_settings_cache["sector_stock_layout"] if t == "code"}
        _wl_codes_layout_len = cur_len
    return _wl_codes_cache








def _update_trade_amount_fid14(
    base_nk: str,
    amt14: int,
) -> int:
    """
    FID 14(누적거래대금, 백만원 단위) -- _AL 구독 시 KRX+NXT 통합값.
    키움이 내려주는 당일 누적값(백만원) -> 원 단위로 변환 후 반환.
    저장하지 않고 순간 계산만 수행.
    """
    if amt14 <= 0:
        return 0

    amt_won = amt14 * 1_000_000
    return amt_won


def _update_strength_buckets(
    nk_px: str,
    str_f: float,
    vol13: int,
) -> None:
    """KRX 단독 체결강도 갱신.
    저장하지 않고 순간 계산만 수행.
    """
    pass


def _log_ws_trnm_json_detail(trnm: str, data: dict) -> None:
    """REG/REAL 등 웹소켓 응답 본문을 DEBUG로 남김(과대 전문은 잘림)."""
    try:
        s = json.dumps(data, ensure_ascii=False)
        max_len = 5000
        total_len = len(s)
        if total_len > max_len:
            s = s[:max_len] + f"... (truncated, total {total_len} chars)"
    except Exception as e:
        pass


def _log_real_data_items_preview(data: dict) -> None:
    """REAL data 배열에서 type 01·02만 골라 item·FID 키/값 샘플을 INFO로 출력."""
    real_data = data.get("data")
    if isinstance(real_data, list):
        items = real_data
    elif isinstance(real_data, dict):
        items = [real_data]
    else:
        items = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        msg_type = item.get("type")
        norm = _normalize_real_type(msg_type)
        if norm not in ("01", "0j"):
            continue
        iy = item.get("item")
        vals = item.get("values", {})
        if not isinstance(vals, dict):
            vals = {}
        keys = list(vals.keys())[:48]
        sample = {k: vals[k] for k in keys}
        try:
            sample_s = json.dumps(sample, ensure_ascii=False)
        except Exception:
            sample_s = str(sample)


def _handle_login(data: dict) -> None:
    if str(data.get("return_code", "")) == "0":
        engine_state.state.login_ok = True
        engine_state._notify_reg_ack()
        # LOGIN 성공 → 구독 파이프라인 트리거 (구독 구간 내이면 REG 자동 시작)
        try:
            from backend.app.services.daily_time_scheduler import _trigger_reg_pipeline
            _trigger_reg_pipeline()
        except Exception as e:
            logger.warning("[연결] REG 파이프라인 트리거 실패: %s", e, exc_info=True)


def _reg_response_item_val(row: dict) -> str | None:
    """키움 REG/UNREG 응답 data[] -- item 정본(문자열 또는 단일 요소 배열)."""
    v = row.get("item")
    if v is None:
        return None
    if isinstance(v, list):
        if not v:
            return None
        x = v[0]
        s = str(x).strip() if x is not None else ""
        return s if s else None
    s = str(v).strip()
    return s if s else None


def _reg_data_rows(d: dict) -> list[dict]:
    raw = d.get("data")
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _handle_reg(data: dict) -> None:
    """
    키움: 응답 순서 ≠ 요청 순서 -- FIFO 매칭 금지. data[] 각 객체의 item·type·grp_no로 처리.
    trnm REG / UNREG 동일 구조.
    """
    d = data if isinstance(data, dict) else {}
    rc = str(d.get("return_code", "")).strip()
    trnm = str(d.get("trnm", "REG") or "REG")
    rows = _reg_data_rows(d)
    msg = str(d.get("return_msg", ""))[:160]
    try:
        ok_rc = rc in ("0", "00", "")
        for row in rows:
            item_val = _reg_response_item_val(row)
            typ = row.get("type")
            grp = row.get("grp_no")
            if trnm in ("UNREG", "REMOVE"):
                continue


            norm = _base_stk_cd(item_val) if item_val else ""
            if not norm:
                continue
            if rc == "105110":
                if norm in engine_state._master_stocks_cache:
                    engine_state._master_stocks_cache[norm].pop("_subscribed", None)
                logger.warning(
                    "[WS] REG 응답 건수한도(105110) -- 즉시 재시도하지 않음 item=%s (응답 본문 기준)",
                    norm,
                )
                try:
                    asyncio.get_running_loop().create_task(
                        engine_lifecycle._delayed_resubscribe_stock_after_rate_limit(norm)
                    )
                except RuntimeError as e:
                    logger.warning("[재구독] 루프 미실행 %s: %s", norm, e)
            elif rc not in ("0", "00", ""):
                if norm in engine_state._master_stocks_cache:
                    engine_state._master_stocks_cache[norm].pop("_subscribed", None)
        if engine_state._REG_REAL_DEBUG_EXTRA_LOG and rows:
            _log_ws_trnm_json_detail(trnm, d if d else {"_raw": data})
    finally:
        engine_state._notify_reg_ack(return_code=rc)


async def _handle_real_01(
    item: dict, vals: dict, raw_type_upper: str, is_0b_tick: bool,
) -> None:
    """0B/01 체결 처리.

    캐시 업데이트는 engine_service._handle_market_tick_event에서 수신 후 처리.
    """
    # LIVE 전환 조건 강화: symbol별 필수 필드 캐시 확인 + 타임아웃
    if engine_state._get_realtime_state() == "WAITING_FIRST_TICK":
        raw_cd = _real_item_stk_cd(item, vals)
        if raw_cd:
            nk_px = _base_stk_cd(raw_cd)
            
            # symbol별 최초 tick 수신 timestamp 기록
            global _realtime_first_tick_ts_map
            if nk_px not in _realtime_first_tick_ts_map:
                _realtime_first_tick_ts_map[nk_px] = int(time.time() * 1000)
            
            # 필수 필드 캐시 초기화
            if nk_px not in _realtime_required_fields_cache:
                _realtime_required_fields_cache[nk_px] = {"price": False, "change": False, "volume": False}
            
            # 필수 필드 채워짐 확인
            last_px = _parse_fid10_price(vals)
            if last_px > 0:
                _realtime_required_fields_cache[nk_px]["price"] = True
            if _ws_fid_key_present(vals, "11"):
                _realtime_required_fields_cache[nk_px]["change"] = True
            if is_0b_tick and _ws_fid_key_present(vals, "14"):
                _realtime_required_fields_cache[nk_px]["volume"] = True
            
            # 모든 필수 필드가 채워졌거나 1000ms 경과 시 LIVE 전환
            required = _realtime_required_fields_cache[nk_px]
            current_ts = int(time.time() * 1000)
            elapsed = current_ts - _realtime_first_tick_ts_map[nk_px]
            
            if (required["price"] and required["change"] and required["volume"]) or (elapsed > 1000):
                # 최소 1개 종목의 필수 필드가 모두 채워지거나 1000ms 경과 시 LIVE 전환
                engine_state._set_realtime_state("LIVE")
                # 캐시 초기화 (최초 1회만 실행)
                _realtime_required_fields_cache.clear()
                _realtime_first_tick_ts_map.clear()
    
    _ws_receive_timestamp = int(time.time() * 1000)
    _ts = _ws_receive_timestamp
    _need_sector_tick = False
    raw_cd = _real_item_stk_cd(item, vals)
    last_px = _parse_fid10_price(vals)
    if not raw_cd or last_px <= 0:
        _check_realtime_latency(_ts)
        return
    nk_px = _base_stk_cd(raw_cd)
    _exch = parse_fid9081_exchange(vals)
    _session = parse_fid290_session(vals)
    _exch_label = {"1": "KRX", "2": "NXT"}.get(_exch, "")
    raw_cd_for_bucket = raw_cd
    pend = {}
    diff = _ws_fid_int(vals, "11", 0) if _ws_fid_key_present(vals, "11") else 0
    rate = parse_change_rate_to_percent(_ws_fid_raw(vals, "12")) if _ws_fid_key_present(vals, "12") else 0.0
    sign = str(_ws_fid_raw(vals, "25") or "3").strip() if _ws_fid_key_present(vals, "25") else "3"
    sv228 = _ws_fid_raw(vals, "228")
    strength = str(sv228).strip() if sv228 is not None and str(sv228).strip() != "" else "-"
    _base_nk_14 = _base_stk_cd(raw_cd_for_bucket)
    if is_0b_tick and _ws_fid_key_present(vals, "14"):
        _amt14 = abs(_ws_fid_int(vals, "14", 0))
        _total14 = _update_trade_amount_fid14(_base_nk_14, _amt14)
        _need_sector_tick = True
    else:
        _total14 = 0

    nk_px_base = _base_stk_cd(raw_cd)
    if is_0b_tick and strength != "-":
        try:
            _update_strength_buckets(nk_px, float(strength), abs(_ws_fid_int(vals, "13", 0)))
        except (ValueError, TypeError) as e:
            logger.warning("[체결강도] %s 파싱 실패 strength=%r: %s", nk_px, strength, e)
    engine_radar_ops.apply_real01_volume_amount_to_radar_rows(
        raw_cd_for_bucket, vals, {},  # _latest_trade_amounts 대신 빈 dict 전달
        {},  # 빈 dict 전달
        is_0b_tick=is_0b_tick,
    )  # lock 불필요 — 순차 처리 + GIL 원자적
        # bid_depth, ask_depth 업데이트 제거 (사용처 없음)
    # 보유종목 현재가 반영 — 평가손익·수익률 실시간 재계산 + broadcast (0.5s coalescing)
    if is_test_mode(engine_state._integrated_system_settings_cache):
        _price_hit = await dry_run.update_price(nk_px, last_px)
        if _price_hit:
            _dr_pos = await dry_run.get_position(nk_px)
            if _dr_pos:
                _dr_pos["change"] = diff
                _dr_pos["change_rate"] = rate
    else:
        _price_hit = apply_last_price_to_positions_inplace(engine_state._positions, raw_cd_for_bucket, last_px)
        if _price_hit:
            engine_state.state.broker_rest_totals = recalc_broker_totals_from_positions(
                engine_state.state.positions, engine_state.state.broker_rest_totals
            )
    if _price_hit:
        await engine_account._refresh_account_snapshot_meta()
        engine_account._broadcast_account(reason="price_tick")
    if _price_hit and engine_state._auto_trade and auto_sell_effective(engine_state._integrated_system_settings_cache) and engine_state._access_token:
        if is_test_mode(engine_state._integrated_system_settings_cache):
            _pos = await dry_run.get_position(nk_px)
            if _pos:
                await engine_state._auto_trade.check_sell_conditions([_pos], engine_state._integrated_system_settings_cache, engine_state._access_token)
        else:
            _matched = [p for p in engine_state._positions if _base_stk_cd(str(p.get("stk_cd", "") or "")) == nk_px]
            if _matched:
                await engine_state._auto_trade.check_sell_conditions(_matched, engine_state._integrated_system_settings_cache, engine_state._access_token)
    if pend_key:
        # notify_desktop_buy_radar_only()
        _need_sector_tick = True
    else:
        _wl_codes = _get_wl_codes_cached()
        if nk_px in _wl_codes:
            if is_0b_tick and _ws_fid_key_present(vals, "14"):
                _amt14_wl = abs(_ws_fid_int(vals, "14", 0))
                _update_trade_amount_fid14(nk_px, _amt14_wl)
            if is_0b_tick and _ws_fid_key_present(vals, "228"):
                sv = _ws_fid_raw(vals, "228")
                if sv is not None and str(sv).strip():
                    try:
                        _update_strength_buckets(nk_px, float(str(sv).strip()), abs(_ws_fid_int(vals, "13", 0)))
                    except (ValueError, TypeError) as e:
                        logger.warning("[체결강도WL] %s 파싱 실패 sv=%r: %s", nk_px, sv, e)
            # notify_desktop_buy_radar_only()
            _need_sector_tick = True

    # [근본해결] 선택적 전송 제거
    # if _need_sector_tick:
    #     notify_sector_tick_single(...)

    # ── 현재가 직통 전송 (price_pass_through_queue) ──
    # sector-scores compute 루프(200ms 주기)를 우회하여
    # 현재가 변동 시점에 즉시 프론트엔드로 전송
    try:
        from backend.app.services.core_queues import get_price_pass_through_queue
        from backend.app.core.sector_mapping import get_merged_sector

        pq = get_price_pass_through_queue()
        sector = get_merged_sector(raw_cd)
        price_tick_data = {
            "code": nk_px,
            "raw_code": raw_cd,
            "price": last_px,
            "change": diff,
            "change_rate": rate,
            "sector": sector,
            "timestamp": int(time.time() * 1000),
        }
        try:
            pq.put_nowait(price_tick_data)
        except asyncio.QueueFull:
            # 큐가 가득 찼으면 가장 오래된 데이터를 버리고 재시도
            try:
                pq.get_nowait()
                pq.put_nowait(price_tick_data)
            except asyncio.QueueEmpty:
                pass
    except Exception:
        pass  # 직통 전송 실패는 치명적 에러가 아님

    _check_realtime_latency(_ts)


def _check_realtime_latency(_ts: int) -> None:
    """실시간 체결 처리 지연 측정 — 50ms 경고, 200ms 초과 시 자동매매 중단 플래그."""
    elapsed = int(time.time() * 1000) - _ts
    if elapsed >= 200:
        logger.error("[체결지연] 처리 시간 %sms → 자동매매 중단 플래그 설정", elapsed)
        engine_state.realtime_latency_exceeded = True
    else:
        # 지연 회복: 플래그 단일 소유자(이 함수)가 직접 해제 — 원칙 8(플래그 단일 소스)
        if engine_state.realtime_latency_exceeded:
            logger.info("[체결지연] 처리 시간 %sms → 지연 회복, 자동매매 재개", elapsed)
            engine_state.realtime_latency_exceeded = False
        if elapsed >= 50:
            logger.warning("[체결지연] 처리 시간 %sms → 50ms 초과", elapsed)


async def _handle_real_00(item: dict, vals: dict) -> None:
    """주문체결(00) 처리 — 자동매매 체결 콜백 + 잔고 갱신 트리거."""
    _ts = int(time.time() * 1000)
    raw_cd = _real_item_stk_cd(item, vals)
    side = str(vals.get("907", ""))
    try:
        unex = int(str(vals.get("902", "0")).replace(",", "").replace("+", "") or 0)
    except (ValueError, TypeError) as e:
        logger.warning("[미체결] %s 파싱 실패 902=%r: %s", raw_cd, vals.get("902"), e)
        unex = 0
    if engine_state._auto_trade:
        await engine_state._auto_trade.on_fill_update(raw_cd, side, unex, engine_state._access_token)

    # [근본해결] 부분 체결(unex > 0) 포함 모든 체결 발생 시 즉시 계좌 상태 반영
    engine_account._on_fill_after_ws()

    # ── 현재가 직통 전송 (price_pass_through_queue) ──
    # 체결도 현재가 변동을 동반하므로 동일하게 직통 전송
    if raw_cd:
        try:
            from backend.app.services.core_queues import get_price_pass_through_queue
            from backend.app.core.sector_mapping import get_merged_sector

            last_px_00 = _parse_fid10_price(vals)
            if last_px_00 > 0:
                nk_px_00 = _base_stk_cd(raw_cd)
                diff_00 = _ws_fid_int(vals, "11", 0) if _ws_fid_key_present(vals, "11") else 0
                rate_00 = parse_change_rate_to_percent(_ws_fid_raw(vals, "12")) if _ws_fid_key_present(vals, "12") else 0.0
                sector_00 = get_merged_sector(raw_cd)

                pq = get_price_pass_through_queue()
                price_tick_data = {
                    "code": nk_px_00,
                    "raw_code": raw_cd,
                    "price": last_px_00,
                    "change": diff_00,
                    "change_rate": rate_00,
                    "sector": sector_00,
                    "timestamp": int(time.time() * 1000),
                }
                try:
                    pq.put_nowait(price_tick_data)
                except asyncio.QueueFull:
                    try:
                        pq.get_nowait()
                        pq.put_nowait(price_tick_data)
                    except asyncio.QueueEmpty:
                        pass
        except Exception:
            pass  # 직통 전송 실패는 치명적 에러가 아님

    _check_realtime_latency(_ts)


async def _handle_real_balance(item: dict, vals: dict) -> None:
    """04/80 잔고 처리 — 실시간 잔고 변동 반영."""
    # REAL 04는 flat 구조 -- FID가 values 안이 아닌 item 루트에 직접 위치
    # item 자체를 vals로 사용 (키움 공식 답변 확인)
    await engine_account._apply_balance_realtime(item, item)


def _handle_real_0d(item: dict, vals: dict) -> None:
    """0D 호가잔량 처리 — 매수잔량(FID 125)·매도잔량(FID 121) 캐시 갱신 + 매수후보 실시간 반영."""
    raw_cd = _real_item_stk_cd(item, vals)
    if not raw_cd:
        return
    nk = _base_stk_cd(raw_cd)
    bid = _ws_fid_int(vals, "125", 0)  # 총 매수호가잔량
    ask = _ws_fid_int(vals, "121", 0)  # 총 매도호가잔량
    if bid < 0 or ask < 0:
        return
    # 호가잔량 캐시 삭제로 저장 로직 제거
    # 매수후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송 (이벤트 기반)
    if engine_state._master_stocks_cache.get(nk, {}).get("_subscribed_0d", False):
        from backend.app.services.engine_account_notify import notify_orderbook_update
        notify_orderbook_update(nk, bid, ask)



# ── REAL 타입별 디스패치 테이블 ──────────────────────────────────
# norm(정규화된 타입) → 핸들러 매핑.  01 타입은 추가 인자가 필요하므로 별도 분기.
_REAL_DISPATCH: dict[str, Callable] = {
    "00": _handle_real_00,      # 주문체결
    "04": _handle_real_balance,  # 잔고
    "80": _handle_real_balance,  # 잔고 (04와 동일 핸들러)
    "0d": _handle_real_0d,      # 호가잔량
}


async def _handle_real(data: dict) -> None:
    """REAL 메시지 수신 — 데이터 타입별 분기 처리 (돈 데이터 즉시 우회, 연산 데이터 압축)."""
    if engine_state._REG_REAL_DEBUG_EXTRA_LOG:
        _log_ws_trnm_json_detail("REAL", data if isinstance(data, dict) else {"_raw": data})
        _log_real_data_items_preview(data if isinstance(data, dict) else {})
    
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
        
        # 무가공 Raw 데이터 즉시 전송 (MTS 무결성 보장)
        notify_raw_real_data(item)
        
        try:
            msg_type = item.get("type")
            norm = _normalize_real_type(msg_type)
            vals = item.get("values", {})
            if not isinstance(vals, dict):
                vals = {}
            
            # 💰 돈 데이터 - 즉시 우회 (체결, 잔고)
            if norm == "00":
                await _handle_real_00(item, vals)
            elif norm in ("04", "80"):
                await _handle_real_balance(item, vals)
            # 📊 연산 데이터 - type="0B"는 master_stocks_cache 업데이트 직접 수행
            elif norm == "0B":
                raw_type_upper = str(msg_type).upper() if msg_type else ""
                await _handle_real_01(item, vals, raw_type_upper, is_0b_tick=True)
            # 그 외 데이터는 BackendCoalescing으로 전송 (프론트엔드 전용)
            else:
                from backend.app.services.backend_coalescing import BackendCoalescing
                coalescing = BackendCoalescing.get_instance()
                try:
                    coalescing.add_raw_data(item)
                except Exception as e:
                    logger.error("[REAL] Coalescing 전송 예외 (계속): %s", e, exc_info=True)
        except Exception as e:
            logger.error("[REAL] 항목 처리 예외 (계속): %s", e, exc_info=True)


async def handle_ws_data(data: dict) -> None:
    """비동기 호출 — LOGIN/REG는 직접 처리, REAL은 직접 동기 호출."""
    try:
        trnm = data.get("trnm")
        if trnm == "LOGIN":
            _handle_login(data)
        elif trnm in ("REG", "UNREG", "REMOVE"):
            _handle_reg(data)
            return
        elif trnm == "REAL":
            # REAL 시세는 동기 호출로 즉시 처리 (태스크 큐에 쌓지 않음)
            await _handle_real(data)
    except Exception:
        logger.error("[WS] 메시지 처리 예외 (trnm=%s): %s", data.get("trnm"), data, exc_info=True)


# ── Consumer 루프 (asyncio.Queue 기반) ──────────────────────────────────────

_consumer_task: asyncio.Task | None = None
_consumer_running: bool = False


async def start_consumer_loop(queue: asyncio.Queue) -> None:
    """Consumer 루프 — 큐에서 데이터를 꺼내 handle_ws_data()로 전달."""
    global _consumer_task, _consumer_running

    if _consumer_running:
        logger.warning("[Consumer] 이미 실행 중")
        return

    _consumer_running = True
    _consumer_task = asyncio.get_running_loop().create_task(_consumer_loop_impl(queue))
    logger.info("[Consumer] 루프 시작")


async def _consumer_loop_impl(queue: asyncio.Queue) -> None:
    """Consumer 루프 구현."""
    global _consumer_running
    try:
        while _consumer_running:
            try:
                data = await queue.get()
                # 기존 방식 유지 (하위 호환)
                await handle_ws_data(data)
                queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Consumer] 처리 예외 (계속): %s", e, exc_info=True)
    finally:
        _consumer_running = False
        logger.info("[Consumer] 루프 종료")


async def stop_consumer_loop() -> None:
    """Consumer 루프 종료."""
    global _consumer_running, _consumer_task

    _consumer_running = False
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    _consumer_task = None
    logger.info("[Consumer] 루프 정지 완료")

