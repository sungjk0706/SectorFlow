from __future__ import annotations
# -*- coding: utf-8 -*-
"""
time_scheduler_on + KST 시각에 따른 자동매매 허용 여부 변화 감지.

장마감 후 확정 데이터 갱신:
- 5일 평균 거래대금 캐시 롤링 갱신
"""

import asyncio
import gc
from datetime import datetime, timezone, timedelta

from backend.app.core.logger import get_logger
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS
from backend.app.services.engine_state import state

logger = get_logger("engine")

KST = timezone(timedelta(hours=9))



# ── NXT 거래 시간대 (증권사 공식 답변 기준) ─────────────────────────────────
NXT_PREMARKET_START  = (8,  0)   # 08:00
NXT_PREMARKET_END    = (9,  0)   # 09:00
NXT_AFTERMARKET_START = (15, 30)  # 15:30
NXT_AFTERMARKET_END   = (18,  0)  # 18:00


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
    """현재 시각이 NXT 애프터마켓 구간(15:30~18:00)인지 판단."""
    now = _kst_now()
    t = now.hour * 60 + now.minute
    s = NXT_AFTERMARKET_START[0] * 60 + NXT_AFTERMARKET_START[1]
    e = NXT_AFTERMARKET_END[0] * 60 + NXT_AFTERMARKET_END[1]
    return s <= t < e


KRX_INACTIVE_PHASES = frozenset({
    "장개시전", "장전 동시호가", "장마감", "장후 시간외", "시간외 단일가", "휴장일",
})

NXT_ACTIVE_PHASES = frozenset({
    "프리마켓", "메인마켓", "애프터마켓",
})


def is_nxt_only_window() -> bool:
    """현재 장 상태가 NXT-only 거래 구간인지 판단 (KRX 비활성 + NXT 활성).

    SSOT: engine_state.market_phase (JIF 수신값) 기반으로 판단.
    JIF 미수신 시 False 반환 — 시세도 없으므로 필터링 의미 없음.
    """
    mp = state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        return False
    return krx in KRX_INACTIVE_PHASES and nxt in NXT_ACTIVE_PHASES


def get_nxt_trde_tp(base_trde_tp: str = "3") -> str:
    """
    현재 시간대에 맞는 NXT trde_tp 반환.
    - 프리마켓(08:00~09:00): 'P'
    - 애프터마켓(15:30~18:00): 'U'
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
    JIF 미수신 시 빈 문자열 반환 — 시세도 없으므로 fallback 무의미.
    """
    mp = state.market_phase
    phase: dict = {"krx": mp.get("krx", ""), "nxt": mp.get("nxt", "")}
    if mp.get("krx_alert"):
        phase["krx_alert"] = mp["krx_alert"]
    if mp.get("krx_countdown"):
        phase["krx_countdown"] = mp["krx_countdown"]
    if mp.get("nxt_countdown"):
        phase["nxt_countdown"] = mp["nxt_countdown"]
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
    # ── 영업일 판단: 주말은 항상 차단, 공휴일은 holiday_guard_on 설정에 따라 ──
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

    # 공휴일 가드: ON이면 공휴일 차단, OFF면 공휴일에도 허용
    if bool(settings.get("holiday_guard_on", True)):
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
        from backend.app.services.engine_service import recompute_sector_summary_now
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_desktop_sector_stocks_refresh,
            _broadcast,
        )
        await recompute_sector_summary_now()
        notify_desktop_sector_scores(force=True)
        await notify_desktop_sector_stocks_refresh()
        _broadcast("market-phase", get_market_phase())
    except Exception as e:
        logger.warning("[타이머] KRX 정규장 진입 콜백 오류: %s", e, exc_info=True)


async def _on_krx_after_hours_start() -> None:
    """15:30 전환 콜백 — 업종 종합점수 재계산 + WS 브로드캐스트 + market-phase 이벤트 전송.

    NOTE: KRX 장마감 구독해지는 16:01 예약(_on_krx_after_hours_remove)으로 이동됨.
    시간외 단일가(15:40~16:00) 0B 데이터를 끝까지 수신한 후 해지하기 위함.
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        logger.info("[타이머] KRX 장외 시간대 진입 (15:30) -- 업종 종합점수 재계산 + 실시간 화면전송")
        from backend.app.services.engine_service import recompute_sector_summary_now
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_desktop_sector_stocks_refresh,
            _broadcast,
        )
        await recompute_sector_summary_now()
        notify_desktop_sector_scores(force=True)
        await notify_desktop_sector_stocks_refresh()
        _broadcast("market-phase", get_market_phase())
    except Exception as e:
        logger.warning("[타이머] KRX 장외 전환 콜백 오류: %s", e, exc_info=True)


def _on_krx_after_hours_remove() -> None:
    """16:01 예약 — KRX 장마감 구독해지.

    KRX 시간외 단일가 종료(16:00) 직후 실행:
    KRX 단독 종목(nxt_enable=False) WS 구독 해지 (remove_krx_only_stocks)
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        if not state.krx_remove_done:
            state.krx_remove_done = True
            loop = asyncio.get_running_loop()
            loop.create_task(_do_krx_after_hours_remove())
    except Exception as e:
        logger.warning("[타이머] 16:01 KRX 장마감 구독해지 예약 오류: %s", e, exc_info=True)


async def _do_krx_after_hours_remove() -> None:
    """16:01 비동기 헬퍼 — KRX 장마감 구독해지."""
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        from backend.app.services import engine_service as es

        # KRX 단독 종목 장마감 구독해지
        from backend.app.services.market_close_pipeline import remove_krx_only_stocks
        result = await remove_krx_only_stocks(es)
        if result.get("skipped"):
            state.krx_remove_done = False
            logger.debug("[타이머] KRX 장마감 구독해지 생략 — 플래그 복원 (앱준비 후 재시도 가능)")
        else:
            logger.info("[타이머] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목", result.get("removed", 0), result.get("failed", 0))
    except Exception as e:
        state.krx_remove_done = False
        logger.warning("[타이머] KRX 장마감 구독해지 오류 — 플래그 복원: %s", e, exc_info=True)


def _fire_unified_confirmed_fetch() -> None:
    """ws_subscribe_end 도달 또는 부트스트랩 catch-up 시 확정 조회 트리거 함수.

    confirmed_done 플래그 체크 → 이미 완료면 스킵.
    fetch_unified_confirmed_data(es) 비동기 태스크 생성.
    성공 시 confirmed_done = True, 실패 시 confirmed_done = False로 복원.
    """
    try:
        if state.confirmed_done:
            logger.debug("[타이머] 통합 확정 조회 이미 완료 — 생략")
            return
        state.confirmed_done = True
        loop = asyncio.get_running_loop()
        loop.create_task(_do_unified_confirmed_fetch())
    except Exception as e:
        logger.warning("[타이머] 통합 확정 조회 시작 오류: %s", e, exc_info=True)


async def _do_unified_confirmed_fetch() -> None:
    """통합 확정 조회 비동기 헬퍼."""
    try:
        from backend.app.services import engine_service as es
        from backend.app.services.market_close_pipeline import fetch_unified_confirmed_data
        await fetch_unified_confirmed_data(es)
        state.confirmed_done = True
        logger.info("[타이머] 통합 확정 조회 완료")
    except Exception as e:
        state.confirmed_done = False
        logger.warning("[타이머] 통합 확정 조회 실패 — 플래그 복원: %s", e, exc_info=True)
        try:
            from backend.app.services import engine_service as es2
            es2._confirmed_refresh_running_confirmed = False
            es2._confirmed_refresh_message = ""
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

    from backend.app.core.trading_calendar import is_cache_valid
    _master_cache_ok = is_cache_valid(_cached_date_str, ws_subscribe_start=ws_start)

    # ── 판단: 단절 구간 (ws_subscribe_end ~ 다음날 ws_subscribe_start) ──
    unified_past = t > ws_end_minutes or t < ws_start_minutes

    if unified_past:
        if not _master_cache_ok and not state.confirmed_done:
            logger.info(
                "[타이머] 단절 구간 기동 — 저장된 데이터(%s) 만료됨 → 확정 데이터 자동 다운로드 트리거",
                _cached_date_str or "없음"
            )
            _fire_unified_confirmed_fetch()
            return
        else:
            logger.debug("[타이머] 단절 구간 기동 — 저장된 데이터(%s) 유효함 (스킵)", _cached_date_str)
            state.confirmed_done = True
            return
    else:
        # 실시간 연결 구간 (ws_subscribe_start ~ ws_subscribe_end)
        # 이 구간에서는 실시간 틱 데이터가 캐시를 채우므로 확정 다운로드를 하지 않음
        logger.debug("[타이머] 실시간 연결 구간 기동 — 실시간 틱 수신 중이므로 다운로드 대기/스킵")
        return




def _broadcast_market_phase() -> None:
    """market-phase WS 이벤트 브로드캐스트 (08:00, 09:00, 20:00 전환 시점)."""
    try:
        from backend.app.services.engine_account_notify import _broadcast
        phase = get_market_phase()
        _broadcast("market-phase", phase)
        logger.debug("[타이머] market-phase 화면전송: %s", phase)
    except Exception as e:
        logger.warning("[타이머] market-phase 화면전송 오류: %s", e, exc_info=True)


async def _apply_auto_toggle_on_startup(settings: dict) -> None:
    """앱 기동 시 거래일/시간 기준으로 마스터·WS구독을 자동 ON/OFF.
    - 거래일 + ws_subscribe_start~end 구간 내 → 마스터/WS ON
    - 비거래일 or 구독 구간 밖 → 마스터/WS OFF
    - auto_buy_on/auto_sell_on은 사용자 수동 설정을 존중 (미접근)
    메모리 캐시만 갱신 (DB 저장 없음 — 재기동 시 재판별되므로 영속성 불필요)."""
    from backend.app.core.trading_calendar import is_trading_day_with_holiday_guard

    holiday_guard = bool(settings.get("holiday_guard_on", True))
    is_trade_day = is_trading_day_with_holiday_guard(holiday_guard)

    now = _kst_now()
    now_minutes = now.hour * 60 + now.minute
    ws_start = str(settings["ws_subscribe_start"])
    ws_end = str(settings["ws_subscribe_end"])
    sh, sm = _parse_hm(ws_start)
    eh, em = _parse_hm(ws_end)
    start_total = sh * 60 + sm
    end_total = eh * 60 + em

    in_time_window = start_total <= now_minutes <= end_total

    should_be_on = is_trade_day and in_time_window

    keys = {
        "time_scheduler_on": should_be_on,
        "ws_subscribe_on": should_be_on,
        "auto_off_by_holiday": not is_trade_day,
    }
    try:
        settings.update(keys)
        from backend.app.services import engine_state as _st
        _st.state.integrated_system_settings_cache.update(keys)
        logger.debug(
            "[타이머] 기동 판별 -- 거래일=%s → 마스터/WS구독 %s",
            is_trade_day, "ON" if should_be_on else "OFF",
        )
        try:
            from backend.app.services.engine_account_notify import (
                notify_desktop_header_refresh,
                notify_desktop_settings_toggled,
            )
            notify_desktop_header_refresh()
            await notify_desktop_settings_toggled()
        except Exception as e:
            logger.warning("[데이터] 화면전송 실패: %s", e, exc_info=True)
    except Exception as e:
        logger.warning("[타이머] 기동 판별 갱신 실패: %s", e)


async def _restore_from_holiday_flag(settings: dict) -> bool:
    """auto_off_by_holiday 플래그가 있으면 자동매매/WS구독을 ON으로 복원하고 플래그 삭제.
    복원이 실행되면 True 반환."""
    if not bool(settings.get("auto_off_by_holiday", False)):
        return False
    on_keys = {
        "time_scheduler_on": True,
        "ws_subscribe_on": True,
        "auto_off_by_holiday": False,
    }
    try:
        settings.update(on_keys)
        state.integrated_system_settings_cache.update(on_keys)
        logger.info("[타이머] 거래일 시작 -- 자동매매/WS구독 자동 복원 (auto_off_by_holiday 해제)")
        try:
            from backend.app.services.engine_account_notify import (
                notify_desktop_header_refresh,
                notify_desktop_settings_toggled,
            )
            notify_desktop_header_refresh()
            await notify_desktop_settings_toggled()
        except Exception as e:
            logger.warning("[데이터] 화면전송 실패: %s", e, exc_info=True)
        return True
    except Exception as e:
        logger.warning("[타이머] 자동 복원 실패: %s", e)
        return False


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
        from backend.app.services import engine_service
        settings = state.integrated_system_settings_cache
        if bool(settings.get("holiday_guard_on", True)):
            if not is_trading_day(today):
                return
        # 공휴일 강제 OFF 플래그가 있으면 자동 복원 후 진행
        await _restore_from_holiday_flag(settings)
        # ★ 구독 시작 시각 도달 → 마스터·WS구독 ON 복원
        #   (_on_ws_subscribe_end 또는 시작 전 기동으로 False가 된 값을 되돌림)
        try:
            _on_keys = {
                "time_scheduler_on": True,
                "ws_subscribe_on": True,
            }
            settings.update(_on_keys)
            state.integrated_system_settings_cache.update(_on_keys)
            try:
                from backend.app.services.engine_account_notify import (
                    notify_desktop_header_refresh,
                    notify_desktop_settings_toggled,
                )
                notify_desktop_header_refresh()
                await notify_desktop_settings_toggled()
            except Exception as e:
                logger.warning("[데이터] 화면전송 실패: %s", e, exc_info=True)
        except Exception as _e:
            logger.warning("[타이머] 자동매매 ON 복원 실패: %_e")
        state.ws_subscribe_window_active = True
        # ── 실시간 필드 초기화 (전일 확정 데이터 제거) ──
        logger.info("[RESET CALL] from _on_ws_subscribe_start")
        logger.info("[타이머] 실시간 구독 시작 -- 실시간 필드 초기화 시작")
        from backend.app.services.engine_service import _reset_realtime_fields
        await _reset_realtime_fields()
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        import backend.app.services.engine_account_notify as _an
        _an._prev_scores_cache = []
        import backend.app.services.engine_service as _es
        _es._sector_summary_cache = None
        # market-phase WS 브로드캐스트 (WS 구독 시작 = 08:00 또는 09:00 전환 시점)
        from backend.app.services.engine_account_notify import _broadcast
        _broadcast("market-phase", get_market_phase())
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

        from backend.app.core.memory_monitor import log_memory_snapshot
        log_memory_snapshot("장마감 GC 정리 후")
        from backend.app.services import engine_service
        state.ws_subscribe_window_active = False
        state.confirmed_done = False  # 오후 8시 구독 종료 → 8시 30분 확정 갱신 허용
        logger.info("[타이머] 실시간 구독 구간 종료 -- 구독 해지 + 실시간 연결 해제")
        await _trigger_unreg_all()
        # 구독 상태 전체 false + WS 브로드캐스트
        from backend.app.services.ws_subscribe_control import _set_status
        _set_status(quote=False)
        # market-phase WS 브로드캐스트 (구독 종료 시각 기준 상태 반영)
        _broadcast_market_phase()
        # ── 마스터·WS구독 토글 OFF 저장 (종료 시각 도달) ──
        try:
            off_keys = {
                "time_scheduler_on": False,
                "ws_subscribe_on": False,
            }
            state.integrated_system_settings_cache.update(off_keys)
            logger.info("[타이머] 구독 종료 시각 도달 -- 자동매매/WS구독 OFF")
            from backend.app.services.engine_account_notify import (
                notify_desktop_header_refresh,
                notify_desktop_settings_toggled,
            )
            notify_desktop_header_refresh()
            await notify_desktop_settings_toggled()
        except Exception as _e:
            logger.warning("[타이머] 구독 종료 OFF 저장 실패: %s", _e, exc_info=True)
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
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_on_ws_subscribe_end())
    except RuntimeError:
        pass


def _fire_confirmed_download() -> None:
    """call_later 콜백용 동기 래퍼 — confirmed_download_time 도달 시 확정 데이터 다운로드 트리거."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_on_confirmed_download())
    except RuntimeError:
        pass


async def _on_confirmed_download() -> None:
    """confirmed_download_time 도달 시 확정 데이터 다운로드 실행."""
    try:
        logger.info("[타이머] 확정 시세 다운로드 시각 도달 → 확정 데이터 다운로드 트리거")
        _fire_unified_confirmed_fetch()
    except Exception as e:
        logger.warning("[타이머] 확정 데이터 다운로드 콜백 오류: %s", e, exc_info=True)


def _fire_ws_disconnect_only() -> None:
    """설정 변경으로 인한 구독 해제 전용 — 구독 해제 + WS 끊기만 수행, 장마감 후처리(갱신/캐시저장) 없음."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_ws_disconnect_only())
    except RuntimeError:
        pass


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
        h = loop.call_later(max(delay_start, 1), lambda: asyncio.create_task(_on_ws_subscribe_start()))
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 실시간 구독 시작 (%s) -- %.0f초 후 예약", ws_start_str, delay_start)
    elif delay_start <= 0 and delay_end > 0 and loop:
        # 이미 구독 구간 내 — _init_ws_subscribe_state가 단일 책임으로 처리
        # 내일 ws_subscribe_start 시각에 타이머 예약 (24시간 후)
        h = loop.call_later(max(delay_start + 86400, 1), lambda: asyncio.create_task(_on_ws_subscribe_start()))
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
            asyncio.create_task(_on_krx_market_open())
        h = loop.call_later(max(delay_krx_open, 1), _krx_open_wrapper)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 정규장 진입 (09:00) -- %.0f초 후 예약", delay_krx_open)

    # ★ 15:30 KRX 장외 시간대 전환 타이머
    delay_krx_after = _seconds_until_hm(15, 30)
    if delay_krx_after > 0 and loop:
        def _krx_after_wrapper() -> None:
            asyncio.create_task(_on_krx_after_hours_start())
        h = loop.call_later(max(delay_krx_after, 1), _krx_after_wrapper)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 장외 전환 (15:30) -- %.0f초 후 예약", delay_krx_after)

    # ★ 15:40 KRX 확정 조회 타이머 — 제거됨 (Task 3.1, 16:01 KRX 스냅샷+REMOVE로 교체)

    # ★ 20:10 NXT 확정 조회 타이머 — 제거됨 (Task 3.1, 20:30 통합 확정 조회로 교체)

    # ★ 16:01 KRX 장마감 구독해지 타이머
    delay_krx_snapshot = _seconds_until_hm(16, 1)
    if delay_krx_snapshot > 0 and loop:
        h = loop.call_later(max(delay_krx_snapshot, 1), _on_krx_after_hours_remove)
        state.ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 장마감 구독해지 (16:01) -- %.0f초 후 예약", delay_krx_snapshot)

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
    # 15:40 KRX시간외종가, 16:00 KRX시간외단일가, 18:00 KRX장마감, 20:00 NXT장마감
    for hm_h, hm_m, label in (
        (8, 0, "08:00"), (9, 0, "09:00"),
        (15, 20, "15:20"), (15, 30, "15:30"), (15, 40, "15:40"), (16, 0, "16:00"), (18, 0, "18:00"),
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
            from backend.app.services.engine_service import _reset_realtime_fields
            await _reset_realtime_fields()
        else:
            logger.info("[타이머] 구독 구간 내 시작 -- 실시간 필드 초기화는 캐시 로드 후 수행")
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        try:
            import backend.app.services.engine_account_notify as _an
            _an._prev_scores_cache = []
            import backend.app.services.engine_service as _es
            _es._sector_summary_cache = None
        except Exception as e:
            logger.warning("[데이터] 캐시 초기화 실패: %s", e, exc_info=True)

        # market-phase WS 브로드캐스트 — _on_ws_subscribe_start와 동일
        from backend.app.services.engine_account_notify import _broadcast
        _broadcast("market-phase", get_market_phase())

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
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                from backend.app.services.engine_bootstrap import _login_post_pipeline
                loop.create_task(_login_post_pipeline())
            except RuntimeError:
                pass
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

        # 키움증권일 때만 계좌 실시간도 해지 (grp 10)
        if ws.broker_id == "kiwoom":
            broker_nm = str(state.integrated_system_settings_cache["broker"]).lower().strip()
            acnt_no = str(state.integrated_system_settings_cache.get(f"{broker_nm}_account_no", "") or "").strip()
            if acnt_no:
                await ws.send_message({
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
        from backend.app.services import engine_service
        from backend.app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        logger.info("[타이머] 자동매매 시간 전환 -- %s", label)
        # 엔진 설정 캐시 갱신 (메모리만, 디스크 I/O 없음)
        loop = asyncio.get_running_loop()
        loop.create_task(engine_service.refresh_engine_integrated_system_settings_cache(None, use_root=True))
        notify_desktop_header_refresh()
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
        handle = loop.call_later(delay, lambda: loop.create_task(_on_auto_trade_transition(label)))
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
            from backend.app.core.trading_calendar import _trading_days_cache, refresh_trading_days_for_year
            next_year = current_year + 1
            if next_year not in _trading_days_cache:
                logger.info("[타이머] 연도 변경 — %d년 거래일 캐시 생성", next_year)
                await refresh_trading_days_for_year(next_year)

            from backend.app.services import engine_service

            # 날짜 변경 시 거래일/시간 기준 자동 ON/OFF 판별
            # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
            settings = state.integrated_system_settings_cache
            if not settings:
                raise RuntimeError("settings cache not initialized")
            await _apply_auto_toggle_on_startup(settings)

            await schedule_auto_trade_timers(settings)
            await schedule_ws_subscribe_timers(settings)
            # 다음날 자정 타이머도 재예약
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
    state.midnight_timer_handle = loop.call_later(max(delay, 1), lambda: loop.create_task(_on_midnight()))
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
