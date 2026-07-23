# -*- coding: utf-8 -*-
"""
WebSocket 수신 `trnm` 분기 -- `engine_service._handle_ws_data` 본문을 위임.
engine_state에서 직접 상태를 참조하여 순환 import 없이 모듈 전역 상태를 갱신한다.
"""
from __future__ import annotations
import time
import backend.app.services.engine_state as engine_state
from backend.app.services import engine_account
import logging
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    _real_item_stk_cd,
)

logger = logging.getLogger(__name__)

# ── _wl_codes 캐시 (매 틱마다 Set 재생성 방지) ──
_wl_codes_cache: set[str] = set()
_wl_codes_layout_len: int = -1


def _get_wl_codes_cached() -> set[str]:
    """sector_stock_layout → code Set 캐시. 레이아웃 길이가 바뀔 때만 재생성."""
    global _wl_codes_cache, _wl_codes_layout_len
    cur_len = len(engine_state.state.integrated_system_settings_cache["sector_stock_layout"])
    if cur_len != _wl_codes_layout_len:
        _wl_codes_cache = {v for t, v in engine_state.state.integrated_system_settings_cache["sector_stock_layout"] if t == "code"}
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
        engine_state.state.login_ok = True
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
                if norm in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[norm].pop("_subscribed", None)
                logger.warning(
                    "[연결] REG 응답 건수한도(105110) -- 즉시 재시도하지 않음 item=%s (응답 본문 기준)",
                    norm,
                )
            elif rc not in ("0", "00", ""):
                if norm in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[norm].pop("_subscribed", None)
    finally:
        engine_state._notify_reg_ack(return_code=rc)


def _check_realtime_latency(_ts: int) -> None:
    """실시간 체결 처리 지연 측정 — 50ms 경고, 200ms 초과 시 자동매매 중단 플래그."""
    elapsed = int(time.time() * 1000) - _ts
    if elapsed >= 200:
        logger.error("[체결지연] 처리 시간 %sms → 자동매매 중단 플래그 설정", elapsed)
        engine_state.state.realtime_latency_exceeded = True
    else:
        # 지연 회복: 플래그 단일 소유자(이 함수)가 직접 해제 — 원칙 17(플래그 단일 소스)
        if engine_state.state.realtime_latency_exceeded:
            logger.info("[체결지연] 처리 시간 %sms → 지연 회복, 자동매매 재개", elapsed)
            engine_state.state.realtime_latency_exceeded = False
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
    # P25 격리된 실패: 체결 콜백/잔고 갱신 예외 시에도 지연 측정은 유지하고 함수는 정상 반환.
    # 호출자(pipeline_compute._dispatch_real_item)의 per-item try/except(B2-03-03)와 다단계 방어.
    try:
        if engine_state.state.auto_trade:
            await engine_state.state.auto_trade.on_fill_update(raw_cd, side, unex, engine_state.state.access_token)

        # [근본해결] 부분 체결(unex > 0) 포함 모든 체결 발생 시 즉시 계좌 상태 반영
        await engine_account._on_fill_after_ws()
    except Exception as e:
        logger.warning("[매매] 체결 콜백/잔고 갱신 오류 (계속): %s", e, exc_info=True)

    _check_realtime_latency(_ts)


async def _handle_real_balance(item: dict, vals: dict) -> None:
    """04/80 잔고 처리 — 실시간 잔고 변동 반영."""
    # REAL 04는 flat 구조 -- FID가 values 안이 아닌 item 루트에 직접 위치
    # item 자체를 vals로 사용 (키움 공식 답변 확인)
    # P25 격리된 실패: 잔고 반영 예외 시 호출자로 전파 차단. 형제 item 처리 유지.
    try:
        await engine_account._apply_balance_realtime(item, item)
    except Exception as e:
        logger.warning("[계좌] 실시간 잔고 반영 오류 (계속): %s", e, exc_info=True)


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
# 안 D(하이브리드): JIF push를 1순위 장 상태 소스로 사용, 시간 기반(_broadcast_market_phase)이 보완.
# JIF 장 상태 전환 코드(11/21/31/41/51/52/54/55/56/57/58) → _apply_market_phase()로 페이즈 갱신.
# JIF 서킷브레이커 코드(61~71) → krx_alert 갱신 + 자동매매 임시중단/재개 (기존 로직 유지).
# 카운트다운 코드(22~25, 42~44, A2~A5 등)는 페이즈 전환 아님 → _JIF_IGNORE_CODES에서 무시 (P24).
# 카운트다운 표시는 프론트엔드가 페이즈명 + 현재 시각으로 자체 계산 (P24 단순성).

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

# ── JIF 장 상태 전환 맵 (jangubun 1/2 = KRX) ──
# 서킷브레이커(61~71)는 _JSTATUS_KRX_ALERT에서 처리, 여기서는 장 상태 전환만.
# 페이즈명은 calc_timebased_market_phase()의 페이즈명과 동일 (P23 용어 통일).
_JIF_PHASE_MAP_KRX: dict[str, str] = {
    "11": "동시호가 접수",      # 장전동시호가개시 (08:40)
    "21": "정규장",             # 장시작 (09:00)
    "31": "종가 동시호가",      # 장후동시호가개시 (15:20)
    "41": "체결 정산",          # 장마감 (15:30)
    "51": "장후 시간외",        # 시간외종가매매개시 (15:40)
    "52": "시간외 종가매매 종료 + 시간외 단일가매매 개시",      # 시간외종가매매종료+단일가개시 (16:00)
    "54": "장 종료",            # 시간외단일가매매종료 (18:00)
}

# ── JIF 장 상태 전환 맵 (jangubun 6 = NXT) ──
_JIF_PHASE_MAP_NXT: dict[str, str] = {
    "55": "프리마켓",           # 프리마켓 개시 (08:00)
    "57": "정규장 준비",        # 프리마켓 마감 (08:50)
    "21": "메인마켓",           # 장시작 (09:00)
    "31": "조기 마감",          # 장후동시호가개시 (15:20)
    "41": "단일가 매매",        # 장마감 (15:30)
    "56": "애프터마켓",         # 에프터마켓 개시 (15:40)
    "58": "장마감",             # 에프터마켓 마감 (20:00)
}

# ── JIF 카운트다운 코드 → (라벨, 남은초) 매핑 (API 문서 기준 — P10 SSOT) ──
# 출처: docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt 112-144줄
# KRX 장마감은 5분전(44)이 최대 — 10분전 코드 없음 (설계 문서 3.2 오류 바로잡기 적용).
# NXT 프리마켓/에프터마켓 장마감(C/D)도 5분전이 최대 — 10분전 코드 없음.
_JIF_COUNTDOWN_KRX: dict[str, tuple[str, int]] = {
    # 장개시 카운트다운 (→ 09:00) — 현재 페이즈가 "시가 동시호가"일 때
    "25": ("정규장 장개시", 600),   # 10분전 (08:50)
    "24": ("정규장 장개시", 300),   # 5분전  (08:55)
    "23": ("정규장 장개시", 60),    # 1분전  (08:59)
    "22": ("정규장 장개시", 10),    # 10초전 (08:59:50)
    # 장마감 카운트다운 (→ 15:20, 종가동시호가 개시) — 현재 페이즈가 "정규장"일 때
    # API 문서 기준: 44=5분전(최대), 10분전 코드 없음
    "44": ("정규장 장마감", 300),   # 5분전  (15:15)
    "43": ("정규장 장마감", 60),    # 1분전  (15:19)
    "42": ("정규장 장마감", 10),    # 10초전 (15:19:50)
}

_JIF_COUNTDOWN_NXT: dict[str, tuple[str, int]] = {
    # 프리마켓 장개시 (→ 08:00)
    "A5": ("프리마켓 장개시", 600),  # 10분전
    "A4": ("프리마켓 장개시", 300),  # 5분전
    "A3": ("프리마켓 장개시", 60),   # 1분전
    "A2": ("프리마켓 장개시", 10),   # 10초전
    # 프리마켓 장마감 (→ 08:50) — 5분전이 최대
    "C4": ("프리마켓 장마감", 300),  # 5분전
    "C3": ("프리마켓 장마감", 60),   # 1분전
    "C2": ("프리마켓 장마감", 10),   # 10초전
    # 에프터마켓 장개시 (→ 15:40)
    "B5": ("에프터마켓 장개시", 600),  # 10분전
    "B4": ("에프터마켓 장개시", 300),  # 5분전
    "B3": ("에프터마켓 장개시", 60),   # 1분전
    "B2": ("에프터마켓 장개시", 10),   # 10초전
    # 에프터마켓 장마감 (→ 20:00) — 5분전이 최대
    "D4": ("에프터마켓 장마감", 300),  # 5분전
    "D3": ("에프터마켓 장마감", 60),   # 1분전
    "D2": ("에프터마켓 장마감", 10),   # 10초전
}

# ── JIF 무시 코드 (카운트다운 코드는 _JIF_COUNTDOWN_*에서 처리하므로 제외) ──
# "53"(사용안함)만 남김 — 페이즈 전환도 카운트다운도 아닌 미사용 코드.
_JIF_IGNORE_CODES: frozenset[str] = frozenset({
    "53",                             # 사용안함
})


def _apply_jif_phase(*, krx: str | None = None, nxt: str | None = None) -> None:
    """JIF 수신 시 장 상태를 갱신하고 부작용을 트리거.

    JIF는 KRX(jangubun 1/2) 또는 NXT(jangubun 6) 개별적으로 push하므로
    한 번에 한쪽만 갱신. 다른 쪽은 기존 state.market_phase 값 유지 (P10 SSOT).
    실제 갱신·브로드캐스트·부작용 트리거는 daily_time_scheduler._apply_market_phase()에 위임.
    """
    mp = engine_state.state.market_phase
    new_phase = {
        "krx": krx if krx is not None else mp.get("krx", ""),
        "nxt": nxt if nxt is not None else mp.get("nxt", ""),
    }
    from backend.app.services.daily_time_scheduler import _apply_market_phase
    _apply_market_phase(new_phase)


async def _handle_jif(data: dict) -> None:
    """JIF 장운영정보 수신 → 장 상태 전환 + 서킷브레이커/사이드카 alert 처리.

    안 D(하이브리드): JIF push를 1순위 장 상태 소스로 사용 (P10 SSOT, P16 살아있는 경로).
    카운트다운 표시는 프론트엔드가 페이즈명 + 현재 시각으로 자체 계산 (P24 단순성).

    jangubun 1/2(코스피/코스닥):
      - jstatus 11/21/31/41/51/52/54 → KRX 페이즈 전환 (_apply_jif_phase) + override 초기화
      - jstatus 22~25/42~44 → KRX 카운트다운 (override 저장 + 브로드캐스트)
      - jstatus 61~71 → krx_alert(서킷브레이커/사이드카) + 자동매매 임시중단/재개
    jangubun 6(NXT):
      - jstatus 55/57/21/31/41/56/58 → NXT 페이즈 전환 (_apply_jif_phase) + override 초기화
      - jstatus A2~A5/B2~B5/C2~C4/D2~D4 → NXT 카운트다운 (override 저장 + 브로드캐스트)
    "53"(사용안함)만 _JIF_IGNORE_CODES에서 무시.
    """
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return

    # ── JIF 수신 시각 기록 (타임테이블 헬스체크용) ──
    from backend.app.services.daily_time_scheduler import _kst_now
    now = _kst_now()
    engine_state.state.last_jif_received_at = now

    # 임시 INFO 로그 — 런타임 JIF 수신 코드 검증용 (2단계). 검증 후 INFO→DEBUG 조정 예정.
    logger.info("[연결] JIF 수신: jangubun=%s, jstatus=%s", jangubun, jstatus)

    # "53"(사용안함)만 무시 — 카운트다운 코드는 아래에서 처리
    if jstatus in _JIF_IGNORE_CODES:
        return

    # ── 카운트다운 코드 처리 (override 저장 + 브로드캐스트, P10 SSOT · P16 살아있는 경로) ──
    # jangubun 1/2 = KRX, 6 = NXT. 매핑 테이블에서 (라벨, remaining_sec) 조회.
    countdown_entry: tuple[str, int] | None = None
    countdown_market: str | None = None
    if jangubun in ("1", "2"):
        countdown_entry = _JIF_COUNTDOWN_KRX.get(jstatus)
        countdown_market = "krx"
    elif jangubun == "6":
        countdown_entry = _JIF_COUNTDOWN_NXT.get(jstatus)
        countdown_market = "nxt"

    if countdown_entry is not None and countdown_market is not None:
        label, remaining_sec = countdown_entry
        from datetime import timedelta
        expires_at = now + timedelta(seconds=remaining_sec + 5)  # 여유 5초
        override = {"label": label, "remaining_sec": remaining_sec, "expires_at": expires_at}
        if countdown_market == "krx":
            engine_state.state.krx_countdown_override = override
        else:
            engine_state.state.nxt_countdown_override = override
        from backend.app.services.daily_time_scheduler import get_market_phase
        from backend.app.services.engine_account_notify import _broadcast
        await _broadcast("market-phase", get_market_phase())
        logger.info("[연결] JIF 카운트다운 수신: %s %s초 전 (override 저장)", label, remaining_sec)
        return  # 카운트다운 코드는 페이즈 전환/CB 아님 → 여기서 종료

    # ── 장 상태 전환 처리 (안 D — JIF 1순위) ──
    # 페이즈 전환 시 해당 시장 override 초기화 — 이전 카운트다운 만료 처리 (P10 SSOT).
    if jangubun in ("1", "2"):
        new_krx = _JIF_PHASE_MAP_KRX.get(jstatus)
        if new_krx:
            engine_state.state.krx_countdown_override = None
            _apply_jif_phase(krx=new_krx)
    elif jangubun == "6":
        new_nxt = _JIF_PHASE_MAP_NXT.get(jstatus)
        if new_nxt:
            engine_state.state.nxt_countdown_override = None
            _apply_jif_phase(nxt=new_nxt)

    # ── 서킷브레이커/사이드카 처리 (기존 로직 유지) ──
    from backend.app.services.engine_account_notify import _broadcast

    if jangubun in ("1", "2"):
        mp = engine_state.state.market_phase

        alert = _JSTATUS_KRX_ALERT.get(jstatus, "__no_change__")
        if alert == "__no_change__":
            return
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

