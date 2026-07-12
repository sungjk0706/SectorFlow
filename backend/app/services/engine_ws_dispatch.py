# -*- coding: utf-8 -*-
"""
WebSocket 수신 `trnm` 분기 -- `engine_service._handle_ws_data` 본문을 위임.
engine_state에서 직접 상태를 참조하여 순환 import 없이 모듈 전역 상태를 갱신한다.
"""
from __future__ import annotations
import asyncio
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


def _handle_login(data: dict) -> None:
    if str(data.get("return_code", "")) == "0":
        state.login_ok = True
        engine_state._notify_reg_ack()
        # LOGIN 성공 → 구독 파이프라인 트리거 (구독 구간 내이면 REG 자동 시작)
        try:
            from backend.app.services.daily_time_scheduler import _trigger_reg_pipeline
            _trigger_reg_pipeline()
        except Exception as e:
            logger.warning("[연결] 조회 파이프라인 트리거 실패: %s", e, exc_info=True)


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
        logger.error("[연결] 메시지 처리 오류 (메시지유형=%s): %s", data.get("trnm"), data, exc_info=True)


# ── JIF (장운영정보) 처리 ──────────────────────────────────────────────────
# market_phase(krx, nxt) 페이즈명은 시간 기반(calc_timebased_market_phase)으로 관리.
# JIF 실시간 이벤트는 휘발성 상세 라벨(krx_event/nxt_event)로 덮어씌워 표시 우선순위를 갖는다.
#   - 시계 = 지속 기준선(페이즈명), JIF = 일시적 실시간 덮어씌움(이벤트 라벨).
#   - 경계 이벤트(장시작/장마감/개시/종료 등)는 시계 전환 시점과 중복되므로 JIF에서 저장하지 않고
#     시계 페이즈 전환(_broadcast_market_phase)이 krx_event/nxt_event를 초기화하여 표시를 인계받는다.
#   - 카운트다운 이벤트(N분전/10초전)와 개시/마감 알림만 krx_event/nxt_event에 저장한다.
# 서킷브레이커/사이드카(61~71)는 krx_alert로 별도 처리 + 자동매매 임시중단/재개.

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

# KRX(jangubun 1/2) 시간대 이벤트 — 카운트다운/개시/마감 알림 (경계 21/41/51/52/54 제외)
_JSTATUS_KRX_EVENT: dict[str, str] = {
    "11": "장전 동시호가 개시",
    "22": "정규장 장개시 10초 전",
    "23": "정규장 장개시 1분 전",
    "24": "정규장 장개시 5분 전",
    "25": "정규장 장개시 10분 전",
    "31": "장후 동시호가 개시",
    "42": "정규장 장마감 10초 전",
    "43": "정규장 장마감 1분 전",
    "44": "정규장 장마감 5분 전",
}

# NXT(jangubun 6) 시간대 이벤트 — 프리마켓/메인마켓/에프터마켓 카운트다운 (경계 21/41/55/56/57/58 제외)
_JSTATUS_NXT_EVENT: dict[str, str] = {
    # 프리마켓 개시 카운트다운
    "A5": "프리마켓 장개시 10분 전",
    "A4": "프리마켓 장개시 5분 전",
    "A3": "프리마켓 장개시 1분 전",
    "A2": "프리마켓 장개시 10초 전",
    # 프리마켓 마감 카운트다운
    "C4": "프리마켓 장마감 5분 전",
    "C3": "프리마켓 장마감 1분 전",
    "C2": "프리마켓 장마감 10초 전",
    # 메인마켓 개시/마감 카운트다운
    "25": "메인마켓 장개시 10분 전",
    "24": "메인마켓 장개시 5분 전",
    "23": "메인마켓 장개시 1분 전",
    "22": "메인마켓 장개시 10초 전",
    "44": "메인마켓 장마감 5분 전",
    "43": "메인마켓 장마감 1분 전",
    "42": "메인마켓 장마감 10초 전",
    # 에프터마켓 개시 카운트다운
    "B5": "에프터마켓 장개시 10분 전",
    "B4": "에프터마켓 장개시 5분 전",
    "B3": "에프터마켓 장개시 1분 전",
    "B2": "에프터마켓 장개시 10초 전",
    # 에프터마켓 마감 카운트다운
    "D4": "에프터마켓 장마감 5분 전",
    "D3": "에프터마켓 장마감 1분 전",
    "D2": "에프터마켓 장마감 10초 전",
}


async def _handle_jif(data: dict) -> None:
    """JIF 장운영정보 수신 → 서킷브레이커/사이드카 alert + 시간대 이벤트 라벨 갱신 + 브로드캐스트.

    jangubun 1/2(코스피/코스닥):
      - jstatus 61~71 → krx_alert(서킷브레이커/사이드카) + 자동매매 임시중단/재개.
      - jstatus 11/22~25/31/42~44 → krx_event(시간대 카운트다운/개시 알림).
    jangubun 6(NXT전용):
      - jstatus A2~A5/B2~B5/C2~C4/D2~D4/22~25/42~44 → nxt_event(프리마켓/메인/에프터마켓 카운트다운).
    경계 이벤트(21/41/51/52/54/55/56/57/58)는 시계 페이즈 전환 시점과 중복되어 저장하지 않는다.
    """
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return

    from backend.app.services.engine_account_notify import _broadcast

    # ── KRX (jangubun 1/2): 서킷브레이커/사이드카 + 시간대 이벤트 ──
    if jangubun in ("1", "2"):
        mp = engine_state.state.market_phase

        # 1) 서킷브레이커/사이드카 alert (기존 로직 유지)
        alert = _JSTATUS_KRX_ALERT.get(jstatus, "__no_change__")
        if alert != "__no_change__":
            if mp.get("krx_alert") == alert:
                return
            mp["krx_alert"] = alert
            await _broadcast("market-phase", {"krx_alert": alert})
            logger.info("[연결] 서킷브레이커/사이드카 알림 갱신: 장상태=%s → %s", jstatus, alert)

            if jstatus in _KRX_CB_ACTIVATION_CODES:
                if not engine_state.state.krx_circuit_breaker_active:
                    engine_state.state.krx_circuit_breaker_active = True
                    logger.warning("[구독] 서킷브레이커/사이드카 발동 — 자동매매 임시 중단 (장상태=%s)", jstatus)
                    _notify_krx_cb_telegram(f"🛑 [KRX] {alert} — 자동매매 임시 중단", engine_state.state.integrated_system_settings_cache)
                    await _broadcast("krx-circuit-breaker", {"active": True, "alert": alert})
            elif jstatus in _KRX_CB_RELEASE_CODES:
                if engine_state.state.krx_circuit_breaker_active:
                    engine_state.state.krx_circuit_breaker_active = False
                    logger.info("[구독] 서킷브레이커/사이드카 해제 — 자동매매 자동 재개 (장상태=%s)", jstatus)
                    _notify_krx_cb_telegram(f"✅ [KRX] {alert} — 자동매매 자동 재개", engine_state.state.integrated_system_settings_cache)
                    await _broadcast("krx-circuit-breaker", {"active": False, "alert": alert})
            return

        # 2) 시간대 이벤트 라벨 (카운트다운/개시/마감 알림)
        event = _JSTATUS_KRX_EVENT.get(jstatus)
        if event is None:
            return
        if mp.get("krx_event") == event:
            return
        mp["krx_event"] = event
        await _broadcast("market-phase", {"krx_event": event})
        logger.info("[연결] KRX 장운영 이벤트 갱신: 장상태=%s → %s", jstatus, event)
        return

    # ── NXT (jangubun 6): 시간대 이벤트 라벨 ──
    if jangubun == "6":
        mp = engine_state.state.market_phase
        event = _JSTATUS_NXT_EVENT.get(jstatus)
        if event is None:
            return
        if mp.get("nxt_event") == event:
            return
        mp["nxt_event"] = event
        await _broadcast("market-phase", {"nxt_event": event})
        logger.info("[연결] NXT 장운영 이벤트 갱신: 장상태=%s → %s", jstatus, event)
        return


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

