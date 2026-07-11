# -*- coding: utf-8 -*-
"""
WebSocket 수신 `trnm` 분기 -- `engine_service._handle_ws_data` 본문을 위임.
engine_state에서 직접 상태를 참조하여 순환 import 없이 모듈 전역 상태를 갱신한다.
"""
from __future__ import annotations
import asyncio
import json
import time
import backend.app.services.engine_state as engine_state
from backend.app.services.engine_state import state
from backend.app.services import engine_account
import logging
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    _real_item_stk_cd,
)
from backend.app.services.engine_ws_parsing import (
    _parse_fid10_price,
    parse_change_rate_to_percent,
    _ws_fid_int,
    _ws_fid_key_present,
    _ws_fid_raw,
)

logger = logging.getLogger(__name__)

# ── _wl_codes 캐시 (매 틱마다 Set 재생성 방지) ──
_wl_codes_cache: set[str] = set()
_wl_codes_layout_len: int = -1


def _get_wl_codes_cached() -> set[str]:
    """sector_stock_layout → code Set 캐시. 레이아웃 길이가 바뀔 때만 재생성."""
    global _wl_codes_cache, _wl_codes_layout_len
    cur_len = len(state.integrated_system_settings_cache["sector_stock_layout"])
    if cur_len != _wl_codes_layout_len:
        _wl_codes_cache = {v for t, v in state.integrated_system_settings_cache["sector_stock_layout"] if t == "code"}
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
        logger.warning("[시스템] 문자열 truncation 실패: %s", e)



def _handle_login(data: dict) -> None:
    if str(data.get("return_code", "")) == "0":
        state.login_ok = True
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
    try:
        for row in rows:
            item_val = _reg_response_item_val(row)
            if trnm in ("UNREG", "REMOVE"):
                continue


            norm = _base_stk_cd(item_val) if item_val else ""
            if not norm:
                continue
            if rc == "105110":
                if norm in state.master_stocks_cache:
                    state.master_stocks_cache[norm].pop("_subscribed", None)
                logger.warning(
                    "[연결] REG 응답 건수한도(105110) -- 즉시 재시도하지 않음 item=%s (응답 본문 기준)",
                    norm,
                )
            elif rc not in ("0", "00", ""):
                if norm in state.master_stocks_cache:
                    state.master_stocks_cache[norm].pop("_subscribed", None)
        if state.REG_REAL_DEBUG_EXTRA_LOG and rows:
            _log_ws_trnm_json_detail(trnm, d if d else {"_raw": data})
    finally:
        engine_state._notify_reg_ack(return_code=rc)


def _check_realtime_latency(_ts: int) -> None:
    """실시간 체결 처리 지연 측정 — 50ms 경고, 200ms 초과 시 자동매매 중단 플래그."""
    elapsed = int(time.time() * 1000) - _ts
    if elapsed >= 200:
        logger.error("[체결지연] 처리 시간 %sms → 자동매매 중단 플래그 설정", elapsed)
        state.realtime_latency_exceeded = True
    else:
        # 지연 회복: 플래그 단일 소유자(이 함수)가 직접 해제 — 원칙 17(플래그 단일 소스)
        if state.realtime_latency_exceeded:
            logger.info("[체결지연] 처리 시간 %sms → 지연 회복, 자동매매 재개", elapsed)
            state.realtime_latency_exceeded = False
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
        logger.warning("[매매] %s 파싱 실패 902=%r: %s", raw_cd, vals.get("902"), e)
        unex = 0
    if state.auto_trade:
        await state.auto_trade.on_fill_update(raw_cd, side, unex, state.access_token)

    # [근본해결] 부분 체결(unex > 0) 포함 모든 체결 발생 시 즉시 계좌 상태 반영
    await engine_account._on_fill_after_ws()

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
                        pq.put_nowait(price_tick_data)
        except Exception as e:
            logger.warning("[연결] price_pass_through 전송 실패 (code=%s): %s", raw_cd, e)

    _check_realtime_latency(_ts)


async def _handle_real_balance(item: dict, vals: dict) -> None:
    """04/80 잔고 처리 — 실시간 잔고 변동 반영."""
    # REAL 04는 flat 구조 -- FID가 values 안이 아닌 item 루트에 직접 위치
    # item 자체를 vals로 사용 (키움 공식 답변 확인)
    await engine_account._apply_balance_realtime(item, item)


async def handle_ws_data(data: dict) -> None:
    """비동기 호출 — LOGIN/REG/JIF 처리. REAL은 tick_queue → pipeline_compute에서 처리."""
    try:
        trnm = data.get("trnm")
        if trnm == "LOGIN":
            _handle_login(data)
        elif trnm in ("REG", "UNREG", "REMOVE"):
            _handle_reg(data)
            return
        elif trnm == "JIF":
            await _handle_jif(data)
    except Exception:
        logger.error("[연결] 메시지 처리 예외 (trnm=%s): %s", data.get("trnm"), data, exc_info=True)


# ── JIF (장운행정보) 처리 ──────────────────────────────────────────────────
# market_phase(krx, nxt)는 시간 기반(calc_timebased_market_phase)으로 관리되므로
# JIF에서는 서킷브레이커/사이드카 alert만 처리한다.

_JSTATUS_KRX_ALERT: dict[str, str | None] = {
    "61": "서킷브레이커 1단계 발동",
    "62": None,
    "63": "서킷브레이커 1단계 동시호가 종료",
    "64": "사이드카 매도 발동",
    "65": None,
    "66": "사이드카 매수 발동",
    "67": None,
    "68": "서킷브레이커 2단계 발동",
    "69": "서킷브레이커 3단계 발동, 당일 장종료",
    "70": None,
    "71": "서킷브레이커 2단계 동시호가 종료",
}

_KRX_CB_ACTIVATION_CODES: set[str] = {"61", "64", "66", "68", "69"}
_KRX_CB_RELEASE_CODES: set[str] = {"63", "71"}


async def _handle_jif(data: dict) -> None:
    """JIF 장운영정보 수신 → 서킷브레이커/사이드카 alert 갱신 + 자동매매 임시중단/재개 + 브로드캐스트.

    market_phase(krx, nxt)는 시간 기반으로 관리되므로 JIF에서 수정하지 않는다.
    KRX CB 발동 시 krx_circuit_breaker_active=True → 자동매매 임시 중단.
    KRX CB 해제 시 krx_circuit_breaker_active=False → 자동매매 자동 재개.
    """
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return

    if jangubun not in ("1", "2"):
        return

    mp = engine_state.state.market_phase
    alert = _JSTATUS_KRX_ALERT.get(jstatus, "__no_change__")
    if alert == "__no_change__":
        return

    if mp.get("krx_alert") == alert:
        return

    mp["krx_alert"] = alert
    from backend.app.services.engine_account_notify import _broadcast
    await _broadcast("market-phase", {"krx_alert": alert})
    logger.info("[연결] 서킷브레이커/사이드카 alert 갱신: jstatus=%s → %s", jstatus, alert)

    if jstatus in _KRX_CB_ACTIVATION_CODES:
        if not engine_state.state.krx_circuit_breaker_active:
            engine_state.state.krx_circuit_breaker_active = True
            logger.warning("[구독] 서킷브레이커/사이드카 발동 — 자동매매 임시 중단 (jstatus=%s)", jstatus)
            _notify_krx_cb_telegram(f"🛑 [KRX] {alert} — 자동매매 임시 중단", engine_state.state.integrated_system_settings_cache)
            await _broadcast("krx-circuit-breaker", {"active": True, "alert": alert})

    elif jstatus in _KRX_CB_RELEASE_CODES:
        if engine_state.state.krx_circuit_breaker_active:
            engine_state.state.krx_circuit_breaker_active = False
            logger.info("[구독] 서킷브레이커/사이드카 해제 — 자동매매 자동 재개 (jstatus=%s)", jstatus)
            _notify_krx_cb_telegram(f"✅ [KRX] {alert} — 자동매매 자동 재개", engine_state.state.integrated_system_settings_cache)
            await _broadcast("krx-circuit-breaker", {"active": False, "alert": alert})


def _notify_krx_cb_telegram(message: str, settings: dict | None) -> None:
    """KRX CB 알림을 NotificationWorker 큐로 전송. 예외 격리."""
    try:
        from backend.app.services.notification_worker import NotificationWorker
        NotificationWorker.get_instance().enqueue({
            "type": "telegram",
            "message": message,
            "settings": settings,
        })
    except Exception as e:
        logger.warning("[구독] 텔레그램 알림 실패: %s", e, exc_info=True)

