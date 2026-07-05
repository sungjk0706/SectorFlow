# -*- coding: utf-8 -*-
"""
time_scheduler_on + KST 시각에 따른 자동매매 허용 여부 변화 감지.

장마감 후 확정 데이터 갱신:
- 5일 평균 거래대금 캐시 롤링 갱신
"""
from __future__ import annotations
import asyncio
import gc
from datetime import datetime, timezone, timedelta
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state
from backend.app.services.engine_lifecycle import schedule_engine_task
logger = get_logger("engine")

KST = timezone(timedelta(hours=9))



# ── KRX 거래 시간대 ─────────────────────────────────────────────────────────
KRX_PREMARKET_START   = (8,  0)    # 08:00 장전 동시호가 시작
KRX_REGULAR_START     = (9,  0)    # 09:00 정규장 시작
KRX_REGULAR_END       = (15, 20)   # 15:20 정규장 종료 → 장후 동시호가
KRX_AFTER_AUCTION_END = (15, 30)   # 15:30 장후 동시호가 종료 → 장후 시간외
KRX_AFTER_HOURS_END   = (15, 40)   # 15:40 장후 시간외 종료 → 시간외 단일가
KRX_SINGLE_PRICE_END  = (16, 0)    # 16:00 시간외 단일가 종료 → 장마감

# ── NXT 거래 시간대 (증권사 공식 답변 기준) ─────────────────────────────────
NXT_PREMARKET_START   = (8,  0)    # 08:00 프리마켓 시작
NXT_PREMARKET_END     = (9,  0)    # 09:00 프리마켓 종료 → 메인마켓
NXT_MAINMARKET_END    = (15, 20)   # 15:20 메인마켓 종료 → 휴식
NXT_BREAK_END         = (15, 30)   # 15:30 휴식 종료 → 애프터마켓
NXT_AFTERMARKET_START = (15, 30)   # 15:30 애프터마켓 시작
NXT_AFTERMARKET_END   = (20, 0)    # 20:00 애프터마켓 종료 → 장마감


def is_nxt_premarket_window() -> bool:
    """현재 시각이 NXT 프리마켓 구간(08:00~09:00)인지 판단.
    거래일(평일 + 공휴일 아님) AND 08:00 <= KST < 09:00 → True."""
    from backend.app.core.trading_calendar import is_trading_day
    now = _kst_now()
    today = now.date()
    if today.weekday() >= 5:
        return False
    if not is_trading_day(today):
        return False
    t = now.hour * 60 + now.minute
    s = NXT_PREMARKET_START[0] * 60 + NXT_PREMARKET_START[1]
    e = NXT_PREMARKET_END[0] * 60 + NXT_PREMARKET_END[1]
    return s <= t < e


def is_nxt_aftermarket_window() -> bool:
    """현재 시각이 NXT 애프터마켓 구간(15:30~20:00)인지 판단."""
    now = _kst_now()
    t = now.hour * 60 + now.minute
    s = NXT_AFTERMARKET_START[0] * 60 + NXT_AFTERMARKET_START[1]
    e = NXT_AFTERMARKET_END[0] * 60 + NXT_AFTERMARKET_END[1]
    return s <= t < e


def calc_timebased_market_phase() -> dict:
    """현재 KST 시각 기반으로 KRX/NXT 장 상태를 산정하여 반환.

    market_phase의 SSOT로 사용되며, 거래일 판별 포함.
    반환: {"krx": str, "nxt": str}

    시간대별 상태 정의:
      KRX:
        00:00~08:00  장개시전
        08:00~09:00  장전 동시호가
        09:00~15:20  정규장
        15:20~15:30  장후 동시호가
        15:30~15:40  장후 시간외
        15:40~16:00  시간외 단일가
        16:00~24:00  장마감
      NXT:
        00:00~08:00  장개시전
        08:00~09:00  프리마켓
        09:00~15:20  메인마켓
        15:20~15:30  휴식
        15:30~20:00  애프터마켓
        20:00~24:00  장마감
    """
    from backend.app.core.trading_calendar import is_trading_day

    now = _kst_now()
    today = now.date()
    t = now.hour * 60 + now.minute

    if today.weekday() >= 5 or not is_trading_day(today):
        return {"krx": "휴장일", "nxt": "휴장일"}

    def _m(hm: tuple[int, int]) -> int:
        return hm[0] * 60 + hm[1]

    # ── KRX ──
    if t < _m(KRX_PREMARKET_START):
        krx = "장개시전"
    elif t < _m(KRX_REGULAR_START):
        krx = "장전 동시호가"
    elif t < _m(KRX_REGULAR_END):
        krx = "정규장"
    elif t < _m(KRX_AFTER_AUCTION_END):
        krx = "장후 동시호가"
    elif t < _m(KRX_AFTER_HOURS_END):
        krx = "장후 시간외"
    elif t < _m(KRX_SINGLE_PRICE_END):
        krx = "시간외 단일가"
    else:
        krx = "장마감"

    # ── NXT ──
    if t < _m(NXT_PREMARKET_START):
        nxt = "장개시전"
    elif t < _m(NXT_PREMARKET_END):
        nxt = "프리마켓"
    elif t < _m(NXT_MAINMARKET_END):
        nxt = "메인마켓"
    elif t < _m(NXT_BREAK_END):
        nxt = "휴식"
    elif t < _m(NXT_AFTERMARKET_END):
        nxt = "애프터마켓"
    else:
        nxt = "장마감"

    return {"krx": krx, "nxt": nxt}


KRX_INACTIVE_PHASES = frozenset({
    "장개시전", "장전 동시호가", "장마감", "장후 시간외", "시간외 단일가", "휴장일",
})

NXT_ACTIVE_PHASES = frozenset({
    "프리마켓", "메인마켓", "애프터마켓",
})


def is_nxt_only_window() -> bool:
    """현재 장 상태가 NXT-only 거래 구간인지 판단 (KRX 비활성 + NXT 활성).

    SSOT: engine_state.market_phase에서 읽어 판단.
    market_phase는 시간 기반 스케줄러가 갱신하므로 빈 문자열이면 안 됨.
    """
    mp = state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[is_nxt_only_window] market_phase에 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화가 누락되었을 수 있음", krx, nxt)
        return False
    return krx in KRX_INACTIVE_PHASES and nxt in NXT_ACTIVE_PHASES


def get_nxt_trde_tp(base_trde_tp: str = "3") -> str:
    """
    현재 시간대에 맞는 NXT trde_tp 반환.
    - 프리마켓(08:00~09:00): 'P'
    - 애프터마켓(15:30~20:00): 'U'
    - 정규장: base_trde_tp 그대로 (지정가=1, 시장가=3 -- KRX와 동일)
    """
    if is_nxt_premarket_window():
        return "P"
    if is_nxt_aftermarket_window():
        return "U"
    return base_trde_tp


def is_krx_after_hours(now: datetime | None = None) -> bool:
    """
    현재 시각이 KRX 장외 시간대(15:30~20:00)인지 판별.
    - 영업일(평일 + 공휴일 아님) AND 15:30 <= KST < 20:00 → True
    - 그 외 → False
    """
    from backend.app.core.trading_calendar import is_trading_day
    if now is None:
        now = _kst_now()
    today = now.date()
    if today.weekday() >= 5:
        return False
    if not is_trading_day(today):
        return False
    h, m = now.hour, now.minute
    t = h * 60 + m
    return 930 <= t < 1200  # 15:30 <= time < 20:00


def get_market_phase() -> dict:
    """현재 KRX/NXT 장 상태 반환 (순수 읽기).

    SSOT: engine_state.market_phase에서 읽어 복사본 반환.
    market_phase는 시간 기반 스케줄러가 갱신하므로 빈 문자열이면 안 됨.
    """
    mp = state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[get_market_phase] market_phase에 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화가 누락되었을 수 있음", krx, nxt)
    phase: dict = {"krx": krx, "nxt": nxt}
    if mp.get("krx_alert"):
        phase["krx_alert"] = mp["krx_alert"]
    return phase


async def is_heavy_operation_allowed(now: datetime | None = None) -> bool:
    """
    대량 다운로드 및 무거운 배치 연산 허용 여부 반환.
    - 실시간 연결 구간(ws_subscribe_start ~ ws_subscribe_end): 차단 (False)
    - 그 외 시간: 허용 (True)
    """
    if now is None:
        now = _kst_now()
    
    # 실시간 연결 구간이면 무거운 작업 차단
    if await is_ws_subscribe_window():
        return False
    
    # 실시간 연결 구간 외면 허용
    return True


def _kst_now() -> datetime:
    return datetime.now(KST)


def _parse_hm(hm_str: str) -> tuple[int, int]:
    """'HH:MM' 문자열 -> (hour, minute). 파싱 실패 시 (0, 0)."""
    try:
        parts = str(hm_str or "").strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        logger.warning("[타이머] 시간 파싱 실패 (hm_str=%r)", hm_str, exc_info=True)
        return 0, 0


async def is_ws_subscribe_window(settings: dict | None = None) -> bool:
    """
    현재 시각이 웹소켓 구독 허용 구간인지 판단.
    조건: KRX 영업일(평일 + 공휴일 아님) AND 구독 시간 구간 내
    구독 구간 = ws_subscribe_start ~ ws_subscribe_end (사용자 설정, 기본값 07:50~20:00)
    settings 미전달 시 settings.json에서 직접 읽음.
    """
    # ── 영업일 판단: 주말·공휴일 항상 차단 ──
    from backend.app.core.trading_calendar import is_trading_day
    now = _kst_now()
    today = now.date()
    # 주말은 무조건 차단
    if today.weekday() >= 5:
        return False

    if settings is None:
        settings = state.integrated_system_settings_cache
    if not settings:
        raise RuntimeError("settings cache not initialized")

    # 공휴일 차단
    if not is_trading_day(today):
        return False

    # WS 구독 마스터 스위치: OFF면 구독 차단
    if not bool(settings.get("ws_subscribe_on", True)):
        return False

    ws_start = str(settings["ws_subscribe_start"])
    ws_end = str(settings["ws_subscribe_end"])

    sh, sm = _parse_hm(ws_start)
    eh, em = _parse_hm(ws_end)

    now_total = now.hour * 60 + now.minute

    start_total = sh * 60 + sm
    end_total = eh * 60 + em

    return start_total <= now_total <= end_total


async def is_edit_window_open(settings: dict | None = None) -> bool:
    """수정 허용 시간대 판단(업종 커스텀 등).
    허용: NOT is_ws_subscribe_window().
    WS 구독 구간 밖이면 편집 가능 (프론트 computeEditWindowOpenByTime과 동일 기준)."""
    if settings is None:
        settings = state.integrated_system_settings_cache
    if not settings:
        raise RuntimeError("settings cache not initialized")
    return not await is_ws_subscribe_window(settings)


# ── call_later 기반 WS 구독 구간 타이머 ─────────────────────────────────────






async def _on_krx_market_open() -> None:
    """09:00 KRX 정규장 진입 콜백 — 업종 종합점수 재계산 + WS 브로드캐스트.

    NXT 프리마켓(08:00~09:00)에는 NXT-enabled 종목만 업종 점수에 포함되었으므로,
    09:00 KRX 정규장 진입 시 전체 종목을 포함하도록 재계산 필요.
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        logger.info("[타이머] KRX 정규장 진입 (09:00) -- 업종 종합점수 재계산 (NXT-only → 전체 종목)")
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_desktop_sector_stocks_refresh,
        )
        await recompute_sector_summary_now()
        await notify_desktop_sector_scores(force=True)
        await notify_desktop_sector_stocks_refresh()
        _broadcast_market_phase()
    except Exception as e:
        logger.warning("[타이머] KRX 정규장 진입 콜백 오류: %s", e, exc_info=True)


async def _on_krx_after_hours_start() -> None:
    """15:30 전환 콜백 — 업종 종합점수 재계산 + KRX 단독 종목 구독해지 + WS 브로드캐스트.

    KRX 정규장 마감(15:30) 시점에 KRX 단독 종목(nxt_enable=False) WS 구독 해지.
    NXT-enabled 종목은 NXT 거래(20:00까지)가 가능하므로 구독 유지.
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        logger.info("[타이머] KRX 장외 시간대 진입 (15:30) -- 업종 종합점수 재계산 + KRX 단독 종목 구독해지")
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_desktop_sector_stocks_refresh,
        )
        await recompute_sector_summary_now()
        await notify_desktop_sector_scores(force=True)
        await notify_desktop_sector_stocks_refresh()
        _broadcast_market_phase()

        # KRX 단독 종목 장마감 구독해지
        if not state.krx_remove_done:
            state.krx_remove_done = True
            from backend.app.services.market_close_pipeline import remove_krx_only_stocks
            result = await remove_krx_only_stocks()
            if result.get("skipped"):
                state.krx_remove_done = False
                logger.debug("[타이머] KRX 장마감 구독해지 생략 — 플래그 복원 (앱준비 후 재시도 가능)")
            else:
                logger.info("[타이머] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목", result.get("removed", 0), result.get("failed", 0))
    except Exception as e:
        state.krx_remove_done = False
        logger.warning("[타이머] KRX 장외 전환 콜백 오류: %s", e, exc_info=True)


def _fire_unified_confirmed_fetch() -> None:
    """ws_subscribe_end 도달 또는 부트스트랩 catch-up 시 확정 조회 트리거 함수.

    confirmed_done 플래그 체크 → 이미 완료면 스킵.
    fetch_unified_confirmed_data(es) 비동기 태스크 생성.
    성공 시 confirmed_done = True, 실패 시 confirmed_done = False로 복원.
    """
    try:
        if state.confirmed_done:
            return
        state.confirmed_done = True
        schedule_engine_task(_do_unified_confirmed_fetch(), context="통합 확정 조회")
    except Exception as e:
        logger.warning("[타이머] 통합 확정 조회 시작 오류: %s", e, exc_info=True)


async def _do_unified_confirmed_fetch() -> None:
    """통합 확정 조회 비동기 헬퍼."""
    try:
        from backend.app.services.market_close_pipeline import fetch_unified_confirmed_data
        await fetch_unified_confirmed_data()
        state.confirmed_done = True
        logger.info("[타이머] 통합 확정 조회 완료")
    except Exception as e:
        state.confirmed_done = False
        logger.warning("[타이머] 통합 확정 조회 실패 — 플래그 복원: %s", e, exc_info=True)
        try:
            state.confirmed_refresh_running_confirmed = False
            state.confirmed_refresh_message = ""
        except Exception as _e:
            logger.warning("[데이터] 플래그 복원 실패: %s", _e, exc_info=True)


async def retry_pipeline_catchup_after_bootstrap() -> None:
    """부트스트랩 완료 후 미실행 파이프라인 catch-up 재시도.

    기동 시 WS/REST 미준비로 스킵된 작업을 부트스트랩 완료 후 재실행한다.
    
    데이터 무결성 및 단일 진실 공급원(Single Source of Truth) 원칙에 따라,
    단절 구간(ws_subscribe_end ~ 다음날 ws_subscribe_start) 기동 시 
    메모리에 로드된 DB 데이터의 유효 기한(date)을 엄격히 판별하여 누락된 확정 다운로드를 수행한다.
    """
    t = _kst_now().hour * 60 + _kst_now().minute

    # 사용자 설정의 ws_subscribe_start / ws_subscribe_end 시간 로드
    _settings = state.integrated_system_settings_cache
    ws_start = str(_settings["ws_subscribe_start"])
    ws_end   = str(_settings["ws_subscribe_end"])
    sh, sm = _parse_hm(ws_start)
    eh, em = _parse_hm(ws_end)
    ws_start_minutes = sh * 60 + sm
    ws_end_minutes   = eh * 60 + em

    # 마스터 캐시에서 데이터 유효기간(date) 추출
    _cached_date_str = ""
    if len(state.master_stocks_cache) > 0:
        all_stocks = state.master_stocks_cache.copy()
        _first_stock = next(iter(all_stocks.values()))
        _cached_date_str = _first_stock.get("date", "")

    from backend.app.core.trading_calendar import get_current_trading_day_str
    _current_trading_day = get_current_trading_day_str()
    _cache_is_today = (_cached_date_str == _current_trading_day)

    # ── 판단: 단절 구간 (ws_subscribe_end ~ 다음날 ws_subscribe_start) ──
    unified_past = t > ws_end_minutes or t < ws_start_minutes

    if unified_past:
        confirmed_dl_str = str(_settings["confirmed_download_time"])[:5]
        cdl_h, cdl_m = _parse_hm(confirmed_dl_str)
        confirmed_dl_minutes = cdl_h * 60 + cdl_m

        if t < confirmed_dl_minutes:
            logger.info(
                "[타이머] 단절 구간 기동 — 확정 다운로드 시각(%s) 이전 — 타이머 대기 (캐시=%s, 현재 거래일=%s)",
                confirmed_dl_str, _cached_date_str, _current_trading_day
            )
            return

        if not _cache_is_today and not state.confirmed_done:
            logger.info(
                "[타이머] 단절 구간 기동 — 캐시 날짜(%s) ≠ 현재 거래일(%s) → 확정 데이터 자동 다운로드 트리거",
                _cached_date_str or "없음", _current_trading_day
            )
            _fire_unified_confirmed_fetch()
            return

        logger.info(
            "[타이머] 단절 구간 기동 — 캐시(%s) = 현재 거래일(%s) 확정 다운로드 시각 경과 (스킵)",
            _cached_date_str, _current_trading_day
        )
        state.confirmed_done = True
        return
    else:
        # 실시간 연결 구간 (ws_subscribe_start ~ ws_subscribe_end)
        # 이 구간에서는 실시간 틱 데이터가 캐시를 채우므로 확정 다운로드를 하지 않음
        logger.debug("[타이머] 실시간 연결 구간 기동 — 실시간 틱 수신 중이므로 다운로드 대기/스킵")
        return




def _broadcast_market_phase() -> None:
    """market-phase WS 이벤트 브로드캐스트 (08:00, 09:00, 20:00 전환 시점).

    state.market_phase를 시간 기반 최신값으로 갱신 후 브로드캐스트.
    SSOT: state.market_phase가 항상 현재 시각 기반 상태를 반영하도록 보장.
    """
    try:
        from backend.app.services.engine_account_notify import _broadcast
        fresh = calc_timebased_market_phase()
        state.market_phase["krx"] = fresh["krx"]
        state.market_phase["nxt"] = fresh["nxt"]
        phase = get_market_phase()
        schedule_engine_task(_broadcast("market-phase", phase), context="market-phase 브로드캐스트")
    except Exception as e:
        logger.warning("[타이머] market-phase 화면전송 오류: %s", e, exc_info=True)


async def _apply_auto_toggle_on_startup(settings: dict) -> None:
    """앱 기동/자정 시 거래일 판별 — 설정값은 사용자만 쓰고, 실행 제어는 런타임 게이트가 담당.
    ws_subscribe_on 등 설정값을 강제 변경하지 않음 (원칙 10 SSOT, 원칙 20 폴백 금지).
    거래일 판별 결과를 로깅하고 UI 갱신 알림만 수행."""
    from backend.app.core.trading_calendar import is_trading_day, get_kst_today

    is_trade_day = is_trading_day(get_kst_today())

    now = _kst_now()
    now_minutes = now.hour * 60 + now.minute
    ws_start = str(settings["ws_subscribe_start"])
    ws_end = str(settings["ws_subscribe_end"])
    sh, sm = _parse_hm(ws_start)
    eh, em = _parse_hm(ws_end)
    start_total = sh * 60 + sm
    end_total = eh * 60 + em

    in_time_window = start_total <= now_minutes <= end_total

    logger.debug(
        "[타이머] 기동 판별 -- 거래일=%s, 시간구간내=%s (설정값 미변경)",
        is_trade_day, in_time_window,
    )
    try:
        from backend.app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
    except Exception as e:
        logger.warning("[데이터] 화면전송 실패: %s", e, exc_info=True)


async def _on_ws_subscribe_start() -> None:
    """WS 구독 시작 시각이 되면 자동 실행 -- WS 연결 + 실시간 데이터 수신을 시작하는 함수."""
    try:
        # 장중 GC 비활성화 (HFT 지연 방지)
        gc.disable()
        logger.info("[타이머] 장중 GC 비활성화 완료 (HFT 지연 방지)")
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        # 주말/공휴일이면 스킵
        if today.weekday() >= 5:
            return
        settings = state.integrated_system_settings_cache
        if not is_trading_day(today):
            return
        # ws_subscribe_on=False면 사용자 수동 모드 — 자동 연결 스킵
        if not bool(settings.get("ws_subscribe_on", False)):
            logger.info("[타이머] ws_subscribe_on=False — 자동 연결 스킵 (수동 모드)")
            return
        state.ws_subscribe_window_active = True
        # ── 실시간 필드 초기화 (전일 확정 데이터 제거) ──
        logger.info("[RESET CALL] from _on_ws_subscribe_start")
        logger.info("[타이머] 실시간 구독 시작 -- 실시간 필드 초기화 시작")
        from backend.app.services.engine_snapshot import _reset_realtime_fields
        await _reset_realtime_fields()
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        from backend.app.services.engine_account_notify import notify_cache
        notify_cache.prev_scores = []
        state.sector_summary_cache = None
        # market-phase WS 브로드캐스트 (WS 구독 시작 = 08:00 또는 09:00 전환 시점)
        _broadcast_market_phase()
        # ── WS 연결은 engine_loop의 구간 감지 루프가 담당 → 이벤트 통지 ──
        state.ws_window_changed_event.set()
        logger.info("[타이머] 실시간 구독 구간 진입 -- engine_loop에 WS 연결 통지")
    except Exception as e:
        logger.warning("[타이머] 실시간 구독 시작 콜백 오류: %s", e, exc_info=True)


async def _on_ws_subscribe_end() -> None:
    """WS 구독 종료 시각이 되면 자동 실행 -- 실시간 수신 중단 + WS 연결 해제 + 섹터 재계산을 순서대로 하는 함수."""
    try:
        # 장마감 후 GC 정상화 및 메모리 정리
        gc.enable()
        gc.collect()
        logger.info("[타이머] 장마감 후 GC 정상화 및 메모리 정리 완료")

        from backend.app.core.memory_monitor import start_memory_monitor, log_memory_snapshot, stop_memory_monitor
        start_memory_monitor()
        log_memory_snapshot("장마감 GC 정리 후")
        stop_memory_monitor()
        state.ws_subscribe_window_active = False
        state.confirmed_done = False  # 오후 8시 구독 종료 → 8시 30분 확정 갱신 허용
        logger.info("[타이머] 실시간 구독 구간 종료 -- 구독 해지 + 실시간 연결 해제")
        await _trigger_unreg_all()
        # 구독 상태 전체 false + WS 브로드캐스트
        from backend.app.services.ws_subscribe_control import _set_status
        _set_status(quote=False)
        # market-phase WS 브로드캐스트 (구독 종료 시각 기준 상태 반영)
        _broadcast_market_phase()
        # ── WS 연결 해제는 engine_loop의 구간 감지 루프가 담당 → 이벤트 통지 ──
        state.ws_window_changed_event.set()
        logger.info("[타이머] 실시간 구독 구간 종료 -- engine_loop에 WS 해제 통지")
        # ── 확정 데이터 다운로드는 confirmed_download_time 타이머가 별도 실행 ──
        # ws_subscribe_end와 confirmed_download_time을 분리하여
        # 증권사 확정 데이터 준비 시간을 확보 (기본값 20:40)
    except Exception as e:
        logger.warning("[타이머] 실시간 구독 종료 콜백 오류: %s", e, exc_info=True)


def _fire_ws_subscribe_end() -> None:
    """call_later 콜백용 동기 래퍼 -- 비동기 _on_ws_subscribe_end()를 태스크로 감싸서 실행하는 함수."""
    schedule_engine_task(_on_ws_subscribe_end(), context="실시간 구독 종료")


def _fire_confirmed_download() -> None:
    """call_later 콜백용 동기 래퍼 — confirmed_download_time 도달 시 확정 데이터 다운로드 트리거."""
    schedule_engine_task(_on_confirmed_download(), context="확정 데이터 다운로드")


async def _on_confirmed_download() -> None:
    """confirmed_download_time 도달 시 확정 데이터 다운로드 실행."""
    try:
        logger.info("[타이머] 확정 시세 다운로드 시각 도달 → 확정 데이터 다운로드 트리거")
        _fire_unified_confirmed_fetch()
    except Exception as e:
        logger.warning("[타이머] 확정 데이터 다운로드 콜백 오류: %s", e, exc_info=True)


def _fire_ws_disconnect_only() -> None:
    """설정 변경으로 인한 구독 해제 전용 — 구독 해제 + WS 끊기만 수행, 장마감 후처리(갱신/캐시저장) 없음."""
    schedule_engine_task(_ws_disconnect_only(), context="WS 구독 해제 전용")


async def _ws_disconnect_only() -> None:
    """구독 해제 + WS 연결 해제 요청만 수행 (장마감 후처리 제외).
    실제 WS 연결 해제는 engine_loop의 구간 감지 루프가 담당."""
    try:
        state.ws_subscribe_window_active = False
        logger.info("[타이머] 구독 구간 변경 -- 구독 해지 + engine_loop에 WS 해제 통지")
        await _trigger_unreg_all()
        from backend.app.services.ws_subscribe_control import _set_status
        _set_status(quote=False)
        state.ws_window_changed_event.set()
    except Exception as e:
        logger.warning("[타이머] 실시간 구독 해제 오류: %s", e)


async def schedule_ws_subscribe_timers(settings: dict | None = None) -> None:
    """
    ws_subscribe_start / ws_subscribe_end 시각에 call_later 타이머를 예약한다.
    기존 타이머는 모두 취소 후 재예약.
    엔진 기동 시 + 설정 변경 시 호출.
    """

    for handle in state.ws_subscribe_timer_handles:
        handle.cancel()
    state.ws_subscribe_timer_handles.clear()

    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if not settings:
        # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = state.integrated_system_settings_cache

    ws_start_str = str(settings["ws_subscribe_start"])[:5]
    ws_end_str = str(settings["ws_subscribe_end"])[:5]

    # ※ ws_subscribe_on 상태와 무관하게 타이머는 항상 예약한다.
    # 실행 여부는 _on_ws_subscribe_start() 내부에서 판단한다.
    # (공휴일 가드가 자동으로 OFF한 경우와 사용자 수동 OFF를 여기서 구분할 수 없음)

    sh, sm = _parse_hm(ws_start_str)
    eh, em = _parse_hm(ws_end_str)

    delay_start = _seconds_until_hm(sh, sm)
    delay_end = _seconds_until_hm(eh, em)

    if delay_start > 0 and loop:
        h = loop.call_later(max(delay_start, 1), lambda: schedule_engine_task(_on_ws_subscribe_start(), context="실시간 구독 시작"))
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 실시간 구독 시작 (%s) -- %.0f초 후 예약", ws_start_str, delay_start)
    elif delay_start <= 0 and delay_end > 0 and loop:
        # 이미 구독 구간 내 — _init_ws_subscribe_state가 단일 책임으로 처리
        # 내일 ws_subscribe_start 시각에 타이머 예약 (24시간 후)
        h = loop.call_later(max(delay_start + 86400, 1), lambda: schedule_engine_task(_on_ws_subscribe_start(), context="실시간 구독 시작(내일)"))
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 실시간 구독 시작 (%s) -- 구독 구간 내 기동, 내일 예약", ws_start_str)

    if delay_end > 0 and loop:
        h = loop.call_later(max(delay_end, 1), _fire_ws_subscribe_end)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 실시간 구독 종료 (%s) -- %.0f초 후 예약", ws_end_str, delay_end)

    # ★ 09:00 KRX 정규장 진입 타이머 — NXT-only → 전체 종목 업종 재계산
    delay_krx_open = _seconds_until_hm(9, 0)
    if delay_krx_open > 0 and loop:
        def _krx_open_wrapper() -> None:
            schedule_engine_task(_on_krx_market_open(), context="KRX 정규장 진입")
        h = loop.call_later(max(delay_krx_open, 1), _krx_open_wrapper)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 정규장 진입 (09:00) -- %.0f초 후 예약", delay_krx_open)

    # ★ 15:30 KRX 장외 시간대 전환 타이머
    delay_krx_after = _seconds_until_hm(15, 30)
    if delay_krx_after > 0 and loop:
        def _krx_after_wrapper() -> None:
            schedule_engine_task(_on_krx_after_hours_start(), context="KRX 장외 전환")
        h = loop.call_later(max(delay_krx_after, 1), _krx_after_wrapper)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 장외 전환 (15:30) -- %.0f초 후 예약", delay_krx_after)

    # ★ 20:10 NXT 확정 조회 타이머 — 제거됨 (Task 3.1, 20:30 통합 확정 조회로 교체)

    # ★ 확정 시세 다운로드 타이머 — confirmed_download_time (기본값 20:40)
    # ws_subscribe_end와 분리된 별도 타이머: 증권사 확정 데이터 준비 시간 확보
    # 사용자 설정 1순위, 미설정 시 기본값 20:40
    confirmed_dl_str = str(settings["confirmed_download_time"])[:5]
    cd_h, cd_m = _parse_hm(confirmed_dl_str)
    delay_confirmed = _seconds_until_hm(cd_h, cd_m)
    if delay_confirmed > 0 and loop:
        h = loop.call_later(max(delay_confirmed, 1), _fire_confirmed_download)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 확정 시세 다운로드 (%s) -- %.0f초 후 예약", confirmed_dl_str, delay_confirmed)
    elif delay_confirmed <= 0 and loop:
        # 이미 다운로드 시간이 지났으면 부트스트랩 catch-up에서 처리
        logger.debug("[타이머] 확정 시세 다운로드 시간(%s) 이미 경과 — 부트스트랩 catch-up에서 처리", confirmed_dl_str)


    # ★ 09:00/15:30 고정 폴링 타이머 제거됨 (Task 5.1, 0J REAL 수신 여부로 자동 판단)

    # ★ market-phase 전환 시점 타이머
    # 08:00 NXT프리, 09:00 KRX정규장, 15:20 NXT메인→휴식, 15:30 KRX정규종료/NXT애프터,
    # 15:40 KRX시간외종가, 16:00 KRX시간외단일가/장마감, 20:00 NXT장마감
    for hm_h, hm_m, label in (
        (8, 0, "08:00"), (9, 0, "09:00"),
        (15, 20, "15:20"), (15, 30, "15:30"), (15, 40, "15:40"), (16, 0, "16:00"),
        (20, 0, "20:00"),
    ):
        delay_mp = _seconds_until_hm(hm_h, hm_m)
        if delay_mp > 0 and loop:
            h = loop.call_later(max(delay_mp, 1), _broadcast_market_phase)
            state.ws_subscribe_timer_handles.append(h)
            logger.debug("[타이머] market-phase 전환 (%s) -- %.0f초 후 예약", label, delay_mp)


async def _init_ws_subscribe_state() -> None:
    """
    엔진 재기동 시 현재 시각 기준으로 WS 구독 상태를 판정하고,
    WS 구독 구간 밖이면서 업종 갱신이 아직 안 됐으면 즉시 1회 갱신하는 함수.
    """
    settings = state.integrated_system_settings_cache
    if not settings or not isinstance(settings, dict):
        raise RuntimeError("settings cache not initialized")
    in_window = await is_ws_subscribe_window(settings)
    state.ws_subscribe_window_active = in_window

    if in_window:
        # 장중 GC 비활성화 (HFT 지연 방지) — _on_ws_subscribe_start와 동일
        gc.disable()
        logger.info("[타이머] 장중 GC 비활성화 완료 (HFT 지연 방지)")
        # ── 실시간 필드 초기화 (전일 확정 데이터 제거) ──
        # 캐시 로드 전이면 스킵 — engine_cache._load_caches_preboot()에서 DB 로드 후 수행
        if state.preboot_cache_loaded:
            logger.info("[RESET CALL] from _init_ws_subscribe_state")
            logger.info("[타이머] 구독 구간 내 시작 -- 실시간 필드 초기화")
            from backend.app.services.engine_snapshot import _reset_realtime_fields
            await _reset_realtime_fields()
        else:
            logger.info("[타이머] 구독 구간 내 시작 -- 실시간 필드 초기화는 캐시 로드 후 수행")
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        try:
            from backend.app.services.engine_account_notify import notify_cache
            notify_cache.prev_scores = []
            state.sector_summary_cache = None
        except Exception as e:
            logger.warning("[데이터] 캐시 초기화 실패: %s", e, exc_info=True)

        # market-phase WS 브로드캐스트 — _on_ws_subscribe_start와 동일
        _broadcast_market_phase()

        state.ws_window_changed_event.set()
        logger.info("[타이머] 구독 구간 내 시작 -- engine_loop에 WS 연결 통지")
    else:
        # 구독 상태 false + WS 브로드캐스트
        from backend.app.services.ws_subscribe_control import _set_status
        _set_status(quote=False)


def _trigger_reg_pipeline() -> None:
    """로그인 상태면 REG 파이프라인 재실행."""
    try:
        ws = state.connector_manager or state.active_connector
        if ws and ws.is_connected() and state.login_ok:
            from backend.app.services.engine_bootstrap import _login_post_pipeline
            schedule_engine_task(_login_post_pipeline(), context="REG 파이프라인 재실행")
        else:
            logger.info("[타이머] 구독 구간 진입 -- WS 미연결 상태, 연결 후 자동 구독됨")
    except Exception as e:
        logger.warning("[타이머] REG 파이프라인 트리거 오류: %s", e)


async def _trigger_unreg_all() -> None:
    """구독 중인 종목 전체 UNREG 전송 + WS 캐시 클리어."""
    try:
        # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_latest_trade_prices, _latest_trade_amounts, _latest_strength)
        logger.info("[타이머] WS 저장데이터 클리어 완료 (캐시 삭제됨)")

        ws = state.connector_manager or state.active_connector
        if not ws or not ws.is_connected() or not state.login_ok:
            return
        await _do_unreg_all()
    except Exception as e:
        logger.warning("[타이머] UNREG 트리거 오류: %s", e)


async def _do_unreg_all() -> None:
    """구독 중인 종목 전체 REMOVE 전송 (비동기)."""
    try:
        all_stocks = state.master_stocks_cache.copy()
        subscribed = {cd for cd, entry in all_stocks.items() if entry.get("_subscribed", False)}
        ws = state.connector_manager or state.active_connector
        if not ws or not ws.is_connected():
            return

        all_codes = list(subscribed)
        if not all_codes:
            logger.info("[타이머] REMOVE 대상 없음 -- 이미 구독 없음")
            return

        # Broker Abstraction: subscribe_stocks / unsubscribe_stocks 추상 API 사용
        ok = await ws.unsubscribe_stocks(all_codes)

        # 키움증권일 때만 계좌 실시간도 해지 (grp 10) — kiwoom 커넥터 직접 조회
        cm = state.connector_manager
        kiwoom_conn = cm.get_connector("kiwoom") if cm else None
        if kiwoom_conn and kiwoom_conn.is_connected():
            broker_nm = str(state.integrated_system_settings_cache["broker"]).lower().strip()
            acnt_no = str(state.integrated_system_settings_cache.get(f"{broker_nm}_account_no", "") or "").strip()
            if acnt_no:
                await kiwoom_conn.send_message({
                    "trnm": "REMOVE", "grp_no": "10", "refresh": "0",
                    "data": [{"item": [""], "type": ["00", "04"]}],
                })

        # 구독 상태 초기화
        for cd in subscribed:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd].pop("_subscribed", None)

        logger.info("[타이머] REMOVE 완료 -- %d종목 구독 해지 (성공=%s)", len(all_codes), ok)

        # ws_subscribe_control 상태 동기화 — 구독 해지 완료
        from backend.app.services import ws_subscribe_control
        ws_subscribe_control._set_status(quote=False)
    except Exception as e:
        logger.warning("[타이머] REMOVE 전송 오류: %s", e)


# ── call_later 기반 매수/매도 시간 전환 타이머 ─────────────────────────────────


def _seconds_until_hm(h: int, m: int) -> float:
    """현재 KST 시각에서 오늘 h:m까지 남은 초. 이미 지났으면 음수."""
    now = _kst_now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (target - now).total_seconds()


async def _on_auto_trade_transition(label: str) -> None:
    """매수/매도 시간 구간 진입/이탈 시 1회 실행되는 콜백."""
    try:
        from backend.app.services.engine_config import refresh_engine_integrated_system_settings_cache
        from backend.app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        logger.info("[타이머] 자동매매 시간 전환 -- %s", label)
        # 엔진 설정 캐시 갱신 (메모리만, 디스크 I/O 없음)
        schedule_engine_task(refresh_engine_integrated_system_settings_cache(None, use_root=True), context="설정 캐시 갱신")
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
    except Exception as e:
        logger.warning("[타이머] 자동매매 전환 콜백 오류: %s", e)


async def schedule_auto_trade_timers(settings: dict | None = None) -> None:
    """
    매수/매도 시간 구간 전환 시점에 call_later 타이머를 예약한다.
    기존 타이머는 모두 취소 후 재예약.
    엔진 기동 시 + 설정 변경 시 호출.
    """

    # 기존 타이머 전부 취소
    for handle in state.auto_trade_timer_handles:
        handle.cancel()
    state.auto_trade_timer_handles.clear()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 이벤트 루프 없으면 스킵

    if settings is None:
        # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = state.integrated_system_settings_cache
    if not settings:
        raise RuntimeError("settings cache not initialized")

    # ws_subscribe 타이머는 time_scheduler_on과 무관하게 항상 예약 (독립 기능)
    # 매수/매도 타이머만 time_scheduler_on 체크
    if not bool(settings.get("time_scheduler_on", False)):
        return  # 마스터 스위치 OFF면 매수/매도 타이머 불필요

    # 예약 대상 시각들: 매수 시작/종료, 매도 시작/종료
    time_points = [
        ("buy_time_start", str(settings["buy_time_start"])[:5], "매수 구간 진입"),
        ("buy_time_end", str(settings["buy_time_end"])[:5], "매수 구간 이탈"),
        ("sell_time_start", str(settings["sell_time_start"])[:5], "매도 구간 진입"),
        ("sell_time_end", str(settings["sell_time_end"])[:5], "매도 구간 이탈"),
    ]

    for key, hm_str, label in time_points:
        h, m = _parse_hm(hm_str)
        delay = _seconds_until_hm(h, m)
        if delay < 0:
            continue  # 이미 지난 시각은 스킵
        if delay < 1:
            delay = 1  # 최소 1초 (즉시 실행 방지)
        handle = loop.call_later(delay, lambda: schedule_engine_task(_on_auto_trade_transition(label), context=f"자동매매 전환({label})"))
        state.auto_trade_timer_handles.append(handle)
        logger.debug(
            "[타이머] %s (%s) -- %.0f초 후 예약",
            label, hm_str, delay,
        )


# ── call_later 기반 자정 날짜 변경 타이머 ─────────────────────────────────────


async def _on_midnight() -> None:
    """자정(00:00)이 되면 자동 실행 -- 갱신 플래그를 초기화하고 당일 타이머를 새로 예약하는 함수."""
    try:
        now = _kst_now()

        if state.last_reset_date != now.strftime("%Y%m%d"):
            state.last_reset_date = now.strftime("%Y%m%d")
            state.krx_remove_done = False
            state.confirmed_done = False
            logger.info("[타이머] 자정 날짜 변경 -- 플래그 초기화 (%s)", state.last_reset_date)

            # 연도 변경 시 다음 연도 거래일 캐시 미리 생성 (블로킹 방지)
            current_year = now.year
            from backend.app.core.trading_calendar import has_trading_days_for_year, refresh_trading_days_for_year
            next_year = current_year + 1
            if not has_trading_days_for_year(next_year):
                logger.info("[타이머] 연도 변경 — %d년 거래일 캐시 생성", next_year)
                await refresh_trading_days_for_year(next_year)


            # 날짜 변경 시 거래일/시간 기준 자동 ON/OFF 판별
            # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
            settings = state.integrated_system_settings_cache
            if not settings:
                raise RuntimeError("settings cache not initialized")
            await _apply_auto_toggle_on_startup(settings)

            await schedule_auto_trade_timers(settings)
            await schedule_ws_subscribe_timers(settings)
        # 다음날 자정 타이머 재예약 (날짜 변경 여부와 무관하게 항상 수행)
        schedule_midnight_timer()
    except Exception as e:
        logger.warning("[타이머] 자정 콜백 오류: %s", e)


def schedule_midnight_timer() -> None:
    """다음 자정(00:00)에 call_later 타이머를 예약하는 함수. 엔진 기동 시 + 자정 콜백에서 호출."""
    if state.midnight_timer_handle is not None:
        state.midnight_timer_handle.cancel()
        state.midnight_timer_handle = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    delay = _seconds_until_hm(0, 0)
    if delay <= 0:
        # 이미 자정 지남 → 다음날 자정까지 (24시간 + delay)
        delay += 86400
    state.midnight_timer_handle = loop.call_later(max(delay, 1), lambda: schedule_engine_task(_on_midnight(), context="자정 날짜 변경"))
    logger.debug("[타이머] 자정 타이머 -- %.0f초 후 예약", delay)


# ── ka10001 확정 데이터 갱신 ─────────────────────────────────────────────────

def _freeze_krx_amt29_baseline() -> None:
    pass  # KRX 단독 구조에서는 freeze 불필요 -- 호환성 유지용 stub


def _apply_detail_to_entry(entry: dict, detail: dict, *, base_nk: str = "") -> None:
    """ka10086 응답 detail을 pending 행에 반영. 0값은 덮지 않음."""
    px = int(detail.get("cur_price") or 0)
    if px > 0:
        entry["cur_price"] = px
    change = int(detail.get("change") or 0)
    if change != 0:
        entry["change"] = change
    rate = float(detail.get("change_rate") or 0.0)
    if rate != 0.0:
        entry["change_rate"] = rate
    sign = str(detail.get("sign") or "").strip()
    if sign and sign != "3":
        entry["sign"] = sign
    amt = int(detail.get("trade_amount") or 0)
    if amt > 0:
        entry["trade_amount"] = amt
        # 실시간 틱 데이터 저장 제거 (장 마감 후 UI 표시용 저장 안 함)
    strength = detail.get("strength")
    if strength is not None:
        try:
            entry["strength"] = f"{float(strength):.2f}"
        except (ValueError, TypeError):
            pass


# ── 스케줄러 시작/중지 ────────────────────────────────────────────────────────


async def start_daily_time_scheduler() -> None:
    """타임스케줄러를 시작하는 함수 -- 이벤트 타이머 초기 예약."""
    # 엔진 기동 시 타이머 초기 예약
    try:
        # ── 기동 시 자동 ON/OFF 판별: 거래일+시간구간이면 ON, 아니면 OFF ──
        # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = state.integrated_system_settings_cache
        if not settings:
            raise RuntimeError("settings cache not initialized")
        await _apply_auto_toggle_on_startup(settings)

        # ── market_phase 시간 기반 초기화 (SSOT) ──
        phase = calc_timebased_market_phase()
        state.market_phase["krx"] = phase["krx"]
        state.market_phase["nxt"] = phase["nxt"]
        logger.info("[타이머] market_phase 시간 기반 초기화: krx=%s, nxt=%s", phase["krx"], phase["nxt"])

        state.last_reset_date = _kst_now().strftime("%Y%m%d")

        await schedule_auto_trade_timers(settings)
        await schedule_ws_subscribe_timers(settings)
        schedule_midnight_timer()
        # 현재 시각 기준 WS 구독 상태 즉시 판정 (기동 시점)
        await _init_ws_subscribe_state()
    except Exception as e:
        logger.warning("[타이머] 타이머 초기 예약 실패: %s", e)


async def stop_daily_time_scheduler() -> None:
    """타임스케줄러를 중지하는 함수 -- 모든 타이머 취소."""
    # 모든 타이머 취소
    for handle in state.auto_trade_timer_handles:
        handle.cancel()
    state.auto_trade_timer_handles.clear()
    for handle in state.ws_subscribe_timer_handles:
        handle.cancel()
    state.ws_subscribe_timer_handles.clear()
    if state.midnight_timer_handle is not None:
        state.midnight_timer_handle.cancel()
        state.midnight_timer_handle = None
    logger.info("[타이머] 중지")
