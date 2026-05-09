# -*- coding: utf-8 -*-
"""
WebSocket 수신 `trnm` 분기 -- `engine_service._handle_ws_data` 본문을 위임.
`engine_service` 모듈 객체를 인자로 받아 순환 import 없이 모듈 전역 상태를 갱신한다.
"""
from __future__ import annotations

import asyncio
import json
from types import ModuleType
from typing import Callable

from app.core.logger import get_logger
from app.services.auto_trading_effective import auto_sell_effective
from app.core.trade_mode import is_test_mode
from app.services import dry_run
from app.services.engine_account_notify import (
    notify_desktop_buy_radar_only,
    notify_desktop_index_refresh,
    notify_desktop_sector_scores,
    notify_sector_tick_single,
    notify_raw_real_data,
)
from app.services.engine_account_rest import (
    apply_last_price_to_positions_inplace,
)
from app.services.engine_trade_audit import audit_trade_decision
import app.services.engine_radar_ops as engine_radar_ops
from app.services.engine_symbol_utils import (
    _base_stk_cd,
    _format_kiwoom_reg_stk_cd,
    _real_item_stk_cd,
    _resolve_bucket_key,
)
from app.services.engine_ws_parsing import (
    _normalize_kiwoom_real_type,
    _parse_fid10_price,
    _parse_ws_fid12_to_percent,
    _ws_fid_float,
    _ws_fid_int,
    _ws_fid_key_present,
    _ws_fid_raw,
    _ws_int,
    parse_fid9081_exchange,
    parse_fid290_session,
)

logger = get_logger("engine")

# ── _wl_codes 캐시 (매 틱마다 Set 재생성 방지) ──
_wl_codes_cache: set[str] = set()
_wl_codes_layout_len: int = -1


def _get_wl_codes_cached(es: ModuleType) -> set[str]:
    """sector_stock_layout → code Set 캐시. 레이아웃 길이가 바뀔 때만 재생성."""
    global _wl_codes_cache, _wl_codes_layout_len
    cur_len = len(es._sector_stock_layout)
    if cur_len != _wl_codes_layout_len:
        _wl_codes_cache = {v for t, v in es._sector_stock_layout if t == "code"}
        _wl_codes_layout_len = cur_len
    return _wl_codes_cache


_fid14_last_log_time: float = 0.0  # 삼성전자 거래대금 로그 빈도 제한용


def _update_trade_amount_fid14(
    base_nk: str,
    amt14: int,
    es: ModuleType,
) -> int:
    """
    FID 14(누적거래대금, 백만원 단위) -- _AL 구독 시 KRX+NXT 통합값.
    키움이 내려주는 당일 누적값(백만원) -> 원 단위로 변환 후 저장.
    """
    global _fid14_last_log_time

    if amt14 <= 0:
        return es._latest_trade_amounts.get(base_nk, 0)

    amt_won = amt14 * 1_000_000
    es._latest_trade_amounts[base_nk] = amt_won  # 단일 키 직접 대입 (asyncio 원자적)

    if base_nk == "005930":
        import time as _time
        _now = _time.monotonic()
        if _now - _fid14_last_log_time >= 10.0:
            _fid14_last_log_time = _now
            logger.debug(
                "[거래대금] %s FID14(KRX+NXT통합) %s백만원",
                base_nk, f"{amt14:,}",
            )
    return amt_won


def _update_strength_buckets(
    es: ModuleType,
    nk_px: str,
    str_f: float,
    vol13: int,
) -> None:
    """KRX 단독 체결강도 갱신."""
    es._latest_strength[nk_px] = f"{str_f:.2f}"  # 단일 키 직접 대입 (asyncio 원자적)


def _log_ws_trnm_json_detail(trnm: str, data: dict) -> None:
    """REG/REAL 등 웹소켓 응답 본문을 DEBUG로 남김(과대 전문은 잘림)."""
    try:
        s = json.dumps(data, ensure_ascii=False)
        max_len = 5000
        total_len = len(s)
        if total_len > max_len:
            s = s[:max_len] + f"... (truncated, total {total_len} chars)"
        logger.debug("[WS] ◀ %s 응답 상세: %s", trnm, s)
    except Exception as e:
        logger.debug("[WS] ◀ %s 응답 상세 (repr): %r -- %s", trnm, data, e)


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
        norm = _normalize_kiwoom_real_type(msg_type)
        if norm not in ("01", "0j", "0u"):
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
        logger.debug(
            "[WS] ◀ REAL 항목[#%d] type=%r norm=%s item=%r | fid 샘플=%s",
            idx,
            msg_type,
            norm,
            iy,
            sample_s,
        )


def _handle_login(data: dict, es: ModuleType) -> None:
    if str(data.get("return_code", "")) == "0":
        es._login_ok = True
        es._notify_reg_ack()
        es._cancel_price_trace_delayed_task()
        # LOGIN 성공 → 구독 파이프라인 트리거 (구독 구간 내이면 REG 자동 시작)
        try:
            from app.services.daily_time_scheduler import _trigger_reg_pipeline
            _trigger_reg_pipeline(es)
        except Exception:
            pass


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


def _handle_reg(data: dict, es: ModuleType) -> None:
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
        if not rows:
            logger.debug(
                "[WS] ◀ %s 응답 data 없음 return_code=%r msg=%s",
                trnm,
                rc,
                msg,
            )
        ok_rc = rc in ("0", "00", "")
        for row in rows:
            item_val = _reg_response_item_val(row)
            typ = row.get("type")
            grp = row.get("grp_no")
            if trnm in ("UNREG", "REMOVE"):
                if item_val:
                    logger.debug(
                        "[UNREG·종목] ◀ item=%s type=%r grp=%r return_code=%r 해제OK=%s msg=%s",
                        item_val,
                        typ,
                        grp,
                        rc,
                        ok_rc,
                        msg,
                    )
                else:
                    logger.debug(
                        "[UNREG·조건/계좌] ◀ type=%r grp=%r return_code=%r item=%r 해제OK=%s msg=%s",
                        typ,
                        grp,
                        rc,
                        item_val,
                        ok_rc,
                        msg,
                    )
                continue

            if item_val:
                logger.debug(
                    "[REG·종목] 응답 item=%s type=%r grp=%r return_code=%r 서버등록OK=%s msg=%s",
                    item_val,
                    typ,
                    grp,
                    rc,
                    ok_rc,
                    msg,
                )
            else:
                logger.debug(
                    "[REG·계좌/조건] 응답 type=%r grp=%r return_code=%r item=%r msg=%s",
                    typ,
                    grp,
                    rc,
                    item_val,
                    msg,
                )

            norm = _format_kiwoom_reg_stk_cd(item_val) if item_val else ""
            if not norm:
                continue
            if rc == "105110":
                es._subscribed_stocks.discard(norm)
                logger.warning(
                    "[WS] REG 응답 건수한도(105110) -- 즉시 재시도하지 않음 item=%s (응답 본문 기준)",
                    norm,
                )
                try:
                    asyncio.get_running_loop().create_task(
                        es._delayed_resubscribe_stock_after_rate_limit(norm)
                    )
                except RuntimeError:
                    pass
            elif rc not in ("0", "00", ""):
                es._subscribed_stocks.discard(norm)
        if es._REG_REAL_DEBUG_EXTRA_LOG and rows:
            _log_ws_trnm_json_detail(trnm, d if d else {"_raw": data})
    finally:
        es._notify_reg_ack(return_code=rc)


def _handle_real_01(
    item: dict, vals: dict, raw_type_upper: str, is_0b_tick: bool, es: ModuleType,
) -> None:
    """0B/01 체결 처리 — 현재가·거래대금·체결강도 갱신 + 보유종목 반영 + 자동매도 검사."""
    _need_sector_tick = False
    raw_cd = _real_item_stk_cd(item, vals)
    last_px = _parse_fid10_price(vals)
    if not raw_cd or last_px <= 0:
        logger.debug(
            "[REAL·체결] 미반영 -- 종목=%r 최종가=%s (9001/item·FID10/27/28 파싱 후에도 없음)",
            raw_cd, last_px,
        )
        return
    nk_px = _format_kiwoom_reg_stk_cd(raw_cd)
    _exch = parse_fid9081_exchange(vals)
    _session = parse_fid290_session(vals)
    _exch_label = {"1": "KRX", "2": "NXT"}.get(_exch, "")
    raw_cd_for_bucket = raw_cd
    es._latest_trade_prices[nk_px] = last_px  # 단일 키 직접 대입 (asyncio 원자적)
    es._rest_radar_quote_cache.pop(nk_px, None)  # lock 불필요 — 순차 처리 + GIL 원자적
    pend_key = _resolve_bucket_key(raw_cd_for_bucket, es._pending_stock_details)
    prev_close = _ws_fid_int(vals, "16", 0)
    pend = es._pending_stock_details.get(pend_key, {}) if pend_key else {}
    diff = _ws_fid_int(vals, "11", 0) if _ws_fid_key_present(vals, "11") else int(pend.get("change") or 0)
    rate = _parse_ws_fid12_to_percent(vals.get("12")) if _ws_fid_key_present(vals, "12") else float(pend.get("change_rate") or 0.0)
    sign = str(vals.get("25", "3")).strip() if _ws_fid_key_present(vals, "25") else str(pend.get("sign") or "3")
    sv228 = vals.get("228")
    strength = str(sv228).strip() if sv228 is not None and str(sv228).strip() != "" else "-"
    _base_nk_14 = _format_kiwoom_reg_stk_cd(_base_stk_cd(raw_cd_for_bucket))
    if is_0b_tick and _ws_fid_key_present(vals, "14"):
        _amt14 = abs(_ws_fid_int(vals, "14", 0))
        _total14 = _update_trade_amount_fid14(_base_nk_14, _amt14, es)
        _need_sector_tick = True
    else:
        _total14 = es._latest_trade_amounts.get(_base_nk_14, 0)
    # [근본해결] 선택적 전송 제거 (notify_raw_real_data가 전체 전송함)
    # es.notify_desktop_trade_price(raw_cd, last_px, change=diff, change_rate=rate, strength=strength, trade_amount=_total14)
    if pend_key and es._pending_stock_details[pend_key].get("status") in ("active", "exited"):
        # snapshot-replace: 새 dict 생성 후 참조 교체 1회
        old = es._pending_stock_details[pend_key]
        new_entry = {**old,
            "cur_price": last_px,
            "prev_close": prev_close,
            "change": diff,
            "change_rate": rate,
            "sign": sign,
            "strength": strength,
        }
        if _ws_fid_key_present(vals, "14"):
            new_entry["trade_amount"] = _total14
        es._pending_stock_details[pend_key] = new_entry  # 참조 교체 1회
        if is_0b_tick and strength != "-":
            try:
                _update_strength_buckets(es, nk_px, float(strength), abs(_ws_fid_int(vals, "13", 0)))
            except (ValueError, TypeError):
                pass
    engine_radar_ops.apply_real01_volume_amount_to_radar_rows(
        raw_cd_for_bucket, vals, es._latest_trade_amounts,
        es._pending_stock_details, is_0b_tick=is_0b_tick,
    )  # lock 불필요 — 순차 처리 + GIL 원자적
    if pend_key and es._pending_stock_details.get(pend_key, {}).get("status") == "active":
        # snapshot-replace: 새 dict 생성 후 참조 교체 1회
        old2 = es._pending_stock_details[pend_key]
        updates: dict = {}
        if _ws_fid_key_present(vals, "1030"):
            updates["bid_depth"] = _ws_fid_int(vals, "1030", 0)
        if _ws_fid_key_present(vals, "1031"):
            updates["ask_depth"] = _ws_fid_int(vals, "1031", 0)
        if updates:
            es._pending_stock_details[pend_key] = {**old2, **updates}  # 참조 교체 1회
    # 보유종목 현재가 반영 (메모리만 갱신, 계좌 broadcast 없음 — 체결/잔고 이벤트에서만 전송)
    if is_test_mode(es._settings_cache):
        _price_hit = dry_run.update_price(nk_px, last_px)
        if _price_hit:
            _dr_pos = dry_run.get_position(nk_px)
            if _dr_pos:
                _dr_pos["change"] = diff
                _dr_pos["change_rate"] = rate
    else:
        _price_hit = apply_last_price_to_positions_inplace(es._positions, raw_cd_for_bucket, last_px)
    if _price_hit and es._auto_trade and auto_sell_effective(es._settings_cache) and es._access_token:
        if is_test_mode(es._settings_cache):
            _pos = dry_run.get_position(nk_px)
            if _pos:
                es._auto_trade.check_sell_conditions([_pos], es._settings_cache, es._access_token)
        else:
            _matched = [p for p in es._positions if _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "") or "")) == nk_px]
            if _matched:
                es._auto_trade.check_sell_conditions(_matched, es._settings_cache, es._access_token)
    if pend_key:
        # notify_desktop_buy_radar_only()
        _need_sector_tick = True
        from app.services.engine_sector_confirm import recompute_sector_for_code
        recompute_sector_for_code(nk_px)
    else:
        _wl_codes = _get_wl_codes_cached(es)
        if nk_px in _wl_codes:
            if is_0b_tick and _ws_fid_key_present(vals, "14"):
                _amt14_wl = abs(_ws_fid_int(vals, "14", 0))
                _update_trade_amount_fid14(nk_px, _amt14_wl, es)
            if is_0b_tick and _ws_fid_key_present(vals, "228"):
                sv = vals.get("228")
                if sv is not None and str(sv).strip():
                    try:
                        _update_strength_buckets(es, nk_px, float(str(sv).strip()), abs(_ws_fid_int(vals, "13", 0)))
                    except (ValueError, TypeError):
                        pass
            # notify_desktop_buy_radar_only()
            _need_sector_tick = True
            from app.services.engine_sector_confirm import recompute_sector_for_code
            recompute_sector_for_code(nk_px)

    # [근본해결] 선택적 전송 제거
    # if _need_sector_tick:
    #     notify_sector_tick_single(...)


def _handle_real_00(item: dict, vals: dict, es: ModuleType) -> None:
    """주문체결(00) 처리 — 자동매매 체결 콜백 + 잔고 갱신 트리거."""
    raw_cd = _real_item_stk_cd(item, vals)
    side = str(vals.get("907", ""))
    try:
        unex = int(str(vals.get("902", "0")).replace(",", "").replace("+", "") or 0)
    except (ValueError, TypeError):
        unex = 0
    if es._auto_trade:
        es._auto_trade.on_fill_update(raw_cd, side, unex, es._access_token)
    
    # [근본해결] 부분 체결(unex > 0) 포함 모든 체결 발생 시 즉시 계좌 상태 반영
    es._on_fill_after_ws()


def _handle_real_balance(item: dict, vals: dict, es: ModuleType) -> None:
    """04/80 잔고 처리 — 실시간 잔고 변동 반영."""
    # REAL 04는 flat 구조 -- FID가 values 안이 아닌 item 루트에 직접 위치
    # item 자체를 vals로 사용 (키움 공식 답변 확인)
    es._apply_balance_realtime(item, item)


def _handle_real_0j(item: dict, vals: dict, es: ModuleType) -> None:
    """업종지수(0J) 처리 — 코스피·코스닥 지수 실시간 갱신."""
    from app.services.daily_time_scheduler import on_0j_real_received
    on_0j_real_received()

    idx_cd = str(item.get("item") or "").strip().lstrip("A")
    if not idx_cd:
        raw_item = item.get("item")
        if isinstance(raw_item, list) and raw_item:
            idx_cd = str(raw_item[0]).strip()
    _exch_suffix = ""
    if idx_cd:
        for sfx in ("_NX", "_AL", "_nx", "_al"):
            if idx_cd.endswith(sfx):
                _exch_suffix = sfx
                idx_cd = idx_cd[: -len(sfx)]
                break
    if not (idx_cd and isinstance(vals, dict)):
        return
    price = _ws_fid_float(vals, "10", 0.0)
    change = _ws_fid_float(vals, "11", 0.0)
    rate = _parse_ws_fid12_to_percent(vals.get("12"))
    sig = str(vals.get("25") or "").strip()
    if sig in ("4", "5", "44", "45"):
        change = -abs(change)
        rate = -abs(rate)
    if price != 0 or rate != 0:
        es._latest_index[idx_cd] = {  # 단일 키 직접 대입 (값 자체가 새 dict)
            "price": abs(price),
            "change": change,
            "rate": rate,
        }
        logger.debug(
            "[지수] 0J REAL -- %s %.2f (전일대비 %.2f, 등락율 %.2f%%) src=%s",
            idx_cd, abs(price), change, rate,
            "NXT" if _exch_suffix else "KRX",
        )
        # [근본해결] 중복 알림 제거 (Raw 데이터가 전체 전송함)
        # notify_desktop_index_refresh()
    else:
        logger.warning(
            "[지수] 0J REAL -- %s 파싱 실패 vals=%s",
            idx_cd, str(vals)[:200],
        )


def _handle_real_0d(item: dict, vals: dict, es: ModuleType) -> None:
    """0D 호가잔량 처리 — 매수잔량(FID 125)·매도잔량(FID 121) 캐시 갱신 + 매수후보 실시간 반영."""
    raw_cd = _real_item_stk_cd(item, vals)
    if not raw_cd:
        return
    nk = _format_kiwoom_reg_stk_cd(raw_cd)
    bid = _ws_fid_int(vals, "125", 0)  # 총 매수호가잔량
    ask = _ws_fid_int(vals, "121", 0)  # 총 매도호가잔량
    if bid < 0 or ask < 0:
        logger.debug("[0D] 파싱 실패 종목=%s bid=%s ask=%s", nk, bid, ask)
        return
    prev = es._orderbook_cache.get(nk)
    es._orderbook_cache[nk] = (bid, ask)  # 단일 키 직접 대입 (튜플은 불변)
    # 매수후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송 (이벤트 기반)
    if prev != (bid, ask) and nk in es._subscribed_0d_stocks:
        from app.services.engine_account_notify import notify_orderbook_update
        notify_orderbook_update(nk, bid, ask)



# ── REAL 타입별 디스패치 테이블 ──────────────────────────────────
# norm(정규화된 타입) → 핸들러 매핑.  01 타입은 추가 인자가 필요하므로 별도 분기.
_REAL_DISPATCH: dict[str, Callable] = {
    "00": _handle_real_00,      # 주문체결
    "04": _handle_real_balance,  # 잔고
    "80": _handle_real_balance,  # 잔고 (04와 동일 핸들러)
    "0j": _handle_real_0j,      # 업종지수
    "0d": _handle_real_0d,      # 호가잔량
}


def _handle_real(data: dict, es: ModuleType) -> None:
    """REAL 메시지 수신 — 디스패치 테이블로 타입별 핸들러 호출, 항목별 try-except 격리."""
    if es._REG_REAL_DEBUG_EXTRA_LOG:
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
        # [근본해결] 무가공 Raw 데이터 즉시 전송 (MTS 무결성 보장)
        notify_raw_real_data(item)

        try:
            msg_type = item.get("type")
            norm = _normalize_kiwoom_real_type(msg_type)
            vals = item.get("values", {})
            if not isinstance(vals, dict):
                vals = {}
            # 01 타입은 raw_type_upper·is_0b_tick 추가 인자가 필요하므로 별도 분기
            if norm == "01":
                _raw_type_upper = str(msg_type or "").strip().upper()
                _is_0b_tick = _raw_type_upper in ("0B", "01")
                _handle_real_01(item, vals, _raw_type_upper, _is_0b_tick, es)
                continue
            handler = _REAL_DISPATCH.get(norm)
            if handler is not None:
                handler(item, vals, es)
        except Exception as e:
            logger.error("[REAL] 항목 처리 예외 (계속): %s", e, exc_info=True)


async def handle_ws_data(data: dict, es: ModuleType) -> None:
    """비동기 호출 — LOGIN/REG는 직접 처리, REAL은 직접 동기 호출."""
    trnm = data.get("trnm")
    if trnm == "LOGIN":
        _handle_login(data, es)
    elif trnm in ("REG", "UNREG", "REMOVE"):
        _handle_reg(data, es)
        return
    elif trnm == "REAL":
        # REAL 시세는 동기 호출로 즉시 처리 (태스크 큐에 쌓지 않음)
        _handle_real(data, es)

