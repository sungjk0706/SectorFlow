# -*- coding: utf-8 -*-
"""
time_scheduler_on + KST 시각에 따른 자동매매 허용 여부 변화 감지.

장마감 후 확정 데이터 갱신:
- 5일 평균 거래대금 캐시 롤링 갱신
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.core.logger import get_logger

logger = get_logger("engine")

KST = timezone(timedelta(hours=9))

# 장마감 갱신 플래그 -- 당일 1회
_avg_amt_5d_refresh_done: bool = False
_last_reset_date: str = ""

# 장마감 캐시 파이프라인 플래그 -- 당일 1회
_krx_remove_done: bool = False        # 16:01 KRX 장마감 구독해지 완료
_confirmed_done: bool = False         # 20:30 통합 확정 조회 완료

# 장외 지수 폴링 -- 이벤트 타이머 기반
_index_poll_timer_handle = None  # asyncio.TimerHandle
_INDEX_POLL_INTERVAL_SEC: float = 60.0

# 0J REAL 수신 플래그 -- 첫 0J 수신 시 폴링 자동 중단
_0j_real_receiving: bool = False



# ── NXT 거래 시간대 (키움증권 공식 답변 기준) ─────────────────────────────────
NXT_PREMARKET_START  = (8,  0)   # 08:00
NXT_PREMARKET_END    = (9,  0)   # 09:00
NXT_AFTERMARKET_START = (15, 30)  # 15:30
NXT_AFTERMARKET_END   = (18,  0)  # 18:00


def is_nxt_premarket_window() -> bool:
    """현재 시각이 NXT 프리마켓 구간(08:00~09:00)인지 판단."""
    now = _kst_now()
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
    from app.core.trading_calendar import is_krx_holiday
    if now is None:
        now = _kst_now()
    today = now.date()
    if today.weekday() >= 5:
        return False
    if is_krx_holiday(today):
        return False
    h, m = now.hour, now.minute
    t = h * 60 + m
    return 930 <= t < 1200  # 15:30 <= time < 20:00


def get_market_phase(now: datetime | None = None) -> dict:
    """
    현재 KRX/NXT 장 상태 반환 (시간대별 상세 상태).
    반환값: {"krx": 상태문자열, "nxt": 상태문자열}
    """
    from app.core.trading_calendar import is_krx_holiday
    if now is None:
        now = _kst_now()
    today = now.date()
    if today.weekday() >= 5 or is_krx_holiday(today):
        return {"krx": "휴장일", "nxt": "휴장일"}
    t = now.hour * 60 + now.minute
    
    # KRX 상태
    if t < 510:  # ~08:30
        krx_status = "장개시전"
    elif t < 540:  # 08:30~09:00 (장전 동시호가)
        krx_status = "장전 동시호가"
    elif t < 930:  # 09:00~15:30 (정규장)
        krx_status = "정규장"
    elif t < 950:  # 15:30~15:50 (장후 시간외)
        krx_status = "장후 시간외"
    elif t < 1080:  # 15:50~18:00 (시간외 단일가)
        krx_status = "시간외 단일가"
    else:  # 18:00~
        krx_status = "장마감"
    
    # NXT 상태
    if t < 480:  # ~08:00
        nxt_status = "장개시전"
    elif t < 530:  # 08:00~08:50 (프리마켓)
        nxt_status = "프리마켓"
    elif t < 920:  # 08:50~15:20 (메인마켓)
        nxt_status = "메인마켓"
    elif t < 930:  # 15:20~15:30 (휴식)
        nxt_status = "휴식"
    elif t < 1200:  # 15:30~20:00 (애프터마켓)
        nxt_status = "애프터마켓"
    else:  # 20:00~
        nxt_status = "장마감"
    
    return {"krx": krx_status, "nxt": nxt_status}


def _kst_now() -> datetime:
    return datetime.now(KST)


def _parse_hm(hm_str: str) -> tuple[int, int]:
    """'HH:MM' 문자열 -> (hour, minute). 파싱 실패 시 (0, 0)."""
    try:
        parts = str(hm_str or "").strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def is_ws_subscribe_window(settings: dict | None = None) -> bool:
    """
    현재 시각이 웹소켓 구독 허용 구간인지 판단.
    조건: KRX 영업일(평일 + 공휴일 아님) AND 구독 시간 구간 내
    구독 구간 = ws_subscribe_start ~ ws_subscribe_end (사용자 설정, 기본값 07:50~20:00)
    settings 미전달 시 settings.json에서 직접 읽음.
    """
    # ── 영업일 판단: 주말은 항상 차단, 공휴일은 holiday_guard_on 설정에 따라 ──
    from app.core.trading_calendar import is_krx_holiday
    now = _kst_now()
    today = now.date()
    # 주말은 무조건 차단
    if today.weekday() >= 5:
        return False

    if not settings:
        try:
            from app.core.settings_file import load_settings
            settings = load_settings()
        except Exception:
            return True  # 설정 읽기 실패 시 구독 허용

    # 공휴일 가드: ON이면 공휴일 차단, OFF면 공휴일에도 허용
    if bool(settings.get("holiday_guard_on", True)):
        if is_krx_holiday(today):
            return False

    # WS 구독 마스터 스위치: OFF면 구독 차단
    if not bool(settings.get("ws_subscribe_on", True)):
        return False

    ws_start = str(settings.get("ws_subscribe_start") or "07:50")
    ws_end = str(settings.get("ws_subscribe_end") or "20:00")

    sh, sm = _parse_hm(ws_start)
    eh, em = _parse_hm(ws_end)

    now_total = now.hour * 60 + now.minute

    start_total = sh * 60 + sm
    end_total = eh * 60 + em

    return start_total <= now_total <= end_total


def is_edit_window_open(settings: dict | None = None) -> bool:
    """수정 허용 시간대 판단(업종 커스텀 등).
    허용: NOT is_ws_subscribe_window().
    WS 구독 구간 밖이면 편집 가능 (프론트 computeEditWindowOpenByTime과 동일 기준)."""
    if not settings:
        try:
            from app.core.settings_file import load_settings
            settings = load_settings()
        except Exception:
            settings = {}
    return not is_ws_subscribe_window(settings)


# ── call_later 기반 WS 구독 구간 타이머 ─────────────────────────────────────
_ws_subscribe_timer_handles: list = []  # asyncio.TimerHandle 목록
_ws_subscribe_window_active: bool | None = None  # 현재 WS 구독 구간 상태

# ── 지수 확정 데이터 캐시 ────────────────────────────────────────────────────
_INDEX_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "index_cache.json"

# ── 업종 시세 확정 데이터 캐시 ────────────────────────────────────────────────
_INDUSTRY_INDEX_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "industry_index_cache.json"


def save_index_cache(engine_service) -> None:
    """WS 구독 종료 시점에 _latest_index(코스피·코스닥 지수)를 캐시 파일로 저장하는 함수."""
    try:
        latest_index: dict = getattr(engine_service, "_latest_index", {})
        if not latest_index:
            logger.debug("[지수저장데이터] 저장할 지수 데이터 없음 -- 생략")
            return
        _INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_INDEX_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(latest_index, f, ensure_ascii=False)
        logger.info("[지수저장데이터] 확정 데이터 저장 완료 -- %s", {k: f"{v.get('price', 0):.2f}" for k, v in latest_index.items()})
    except Exception as e:
        logger.warning("[지수저장데이터] 저장 실패: %s", e)


def load_index_cache(engine_service) -> bool:
    """캐시 파일에서 지수 데이터를 읽어 _latest_index에 로드하는 함수. 성공 시 True 반환."""
    try:
        if not _INDEX_CACHE_PATH.exists():
            return False
        with open(_INDEX_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data:
            return False
        latest_index: dict = getattr(engine_service, "_latest_index", {})
        latest_index.update(data)
        logger.info("[지수저장데이터] 확정 데이터 로드 완료 -- %s", {k: f"{v.get('price', 0):.2f}" for k, v in data.items()})
        return True
    except Exception as e:
        logger.warning("[지수저장데이터] 로드 실패: %s", e)
        return False


def save_industry_index_cache(engine_service) -> None:
    """WS 구독 종료 시점에 _latest_industry_index(업종별 등락률·거래대금)를 캐시 파일로 저장하는 함수."""
    try:
        latest: dict = getattr(engine_service, "_latest_industry_index", {})
        if not latest:
            logger.debug("[업종저장데이터] 저장할 업종 시세 데이터 없음 -- 생략")
            return
        _INDUSTRY_INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_INDUSTRY_INDEX_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False)
        logger.info("[업종저장데이터] 확정 데이터 저장 완료 -- %d개 업종", len(latest))
    except Exception as e:
        logger.warning("[업종저장데이터] 저장 실패: %s", e)


def load_industry_index_cache(engine_service) -> bool:
    """캐시 파일에서 업종 시세 데이터를 읽어 _latest_industry_index에 로드하는 함수. 성공 시 True 반환."""
    try:
        if not _INDUSTRY_INDEX_CACHE_PATH.exists():
            return False
        with open(_INDUSTRY_INDEX_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data:
            return False
        latest: dict = getattr(engine_service, "_latest_industry_index", {})
        latest.update(data)
        logger.info("[업종저장데이터] 확정 데이터 로드 완료 -- %d개 업종", len(data))
        return True
    except Exception as e:
        logger.warning("[업종저장데이터] 로드 실패: %s", e)
        return False


def _run_avg_amt_5d_refresh(engine_service) -> None:
    """장마감 후 확정된 당일 1일봉 거래대금을 받아서 5일 평균을 계산하고 캐시 파일에 저장하는 함수."""
    global _avg_amt_5d_refresh_done
    if getattr(engine_service, '_avg_amt_refresh_running', False):
        logger.info("[타이머] 5일 평균 갱신 이미 진행 중 -- 생략")
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(engine_service.refresh_avg_amt_5d_cache())
        _avg_amt_5d_refresh_done = True
        logger.info("[타이머] 5일 평균 거래대금 저장데이터 갱신 요청 완료")
    except Exception as e:
        logger.warning("[타이머] 5일 평균 거래대금 갱신 실패: %s", e)


def _on_krx_after_hours_start() -> None:
    """15:30 전환 콜백 — 업종 종합점수 재계산 + WS 브로드캐스트 + market-phase 이벤트 전송.

    NOTE: KRX 장마감 구독해지는 16:01 예약(_on_krx_after_hours_remove)으로 이동됨.
    시간외 단일가(15:40~16:00) 0B 데이터를 끝까지 수신한 후 해지하기 위함.
    """
    try:
        from app.core.trading_calendar import is_krx_holiday
        today = _kst_now().date()
        if today.weekday() >= 5 or is_krx_holiday(today):
            return
        logger.info("[타이머] KRX 장외 시간대 진입 (15:30) -- 업종 종합점수 재계산 + 실시간 화면전송")
        from app.services.engine_service import recompute_sector_summary_now
        from app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_desktop_sector_stocks_refresh,
            _broadcast,
        )
        loop = asyncio.get_running_loop()
        recompute_sector_summary_now()
        notify_desktop_sector_scores(force=True)
        notify_desktop_sector_stocks_refresh()
        _broadcast("market-phase", get_market_phase())
    except Exception as e:
        logger.warning("[타이머] KRX 장외 전환 콜백 오류: %s", e)


def _on_krx_after_hours_remove() -> None:
    """16:01 예약 — KRX 장마감 구독해지.

    KRX 시간외 단일가 종료(16:00) 직후 실행:
    KRX 단독 종목(nxt_enable=False) WS 구독 해지 (remove_krx_only_stocks)
    """
    global _krx_remove_done
    try:
        from app.core.trading_calendar import is_krx_holiday
        today = _kst_now().date()
        if today.weekday() >= 5 or is_krx_holiday(today):
            return
        if not _krx_remove_done:
            _krx_remove_done = True
            loop = asyncio.get_running_loop()
            loop.create_task(_do_krx_after_hours_remove())
    except Exception as e:
        logger.warning("[타이머] 16:01 KRX 장마감 구독해지 예약 오류: %s", e)


async def _do_krx_after_hours_remove() -> None:
    """16:01 비동기 헬퍼 — KRX 장마감 구독해지."""
    global _krx_remove_done
    try:
        from app.core.trading_calendar import is_krx_holiday
        today = _kst_now().date()
        if today.weekday() >= 5 or is_krx_holiday(today):
            return
        from app.services import engine_service as es

        # KRX 단독 종목 장마감 구독해지
        from app.services.market_close_pipeline import remove_krx_only_stocks
        result = await remove_krx_only_stocks(es)
        if result.get("skipped"):
            _krx_remove_done = False
            logger.info("[파이프라인] KRX 장마감 구독해지 생략 — 플래그 복원 (앱준비 후 재시도 가능)")
        else:
            logger.info("[파이프라인] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목", result.get("removed", 0), result.get("failed", 0))
    except Exception as e:
        _krx_remove_done = False
        logger.warning("[파이프라인] KRX 장마감 구독해지 오류 — 플래그 복원: %s", e)


def _fire_unified_confirmed_fetch() -> None:
    """20:30 통합 확정 조회 시작 함수.

    _confirmed_done 플래그 체크 → 이미 완료면 스킵.
    fetch_unified_confirmed_data(es) 비동기 태스크 생성.
    성공 시 _confirmed_done = True, 실패 시 _confirmed_done = False로 복원.
    """
    global _confirmed_done
    try:
        if _confirmed_done:
            logger.info("[파이프라인] 통합 확정 조회 이미 완료 — 생략")
            return
        _confirmed_done = True
        loop = asyncio.get_running_loop()
        loop.create_task(_do_unified_confirmed_fetch())
    except Exception as e:
        logger.warning("[파이프라인] 20:30 통합 확정 조회 시작 오류: %s", e)


async def _do_unified_confirmed_fetch() -> None:
    """20:30 통합 확정 조회 비동기 헬퍼."""
    global _confirmed_done
    try:
        from app.services import engine_service as es
        # TODO: fetch_unified_confirmed_data()는 Task 3.4에서 구현 예정
        from app.services.market_close_pipeline import fetch_unified_confirmed_data
        await fetch_unified_confirmed_data(es)
        _confirmed_done = True
        logger.info("[파이프라인] 20:30 통합 확정 조회 완료")
    except Exception as e:
        _confirmed_done = False
        logger.warning("[파이프라인] 20:30 통합 확정 조회 실패 — 플래그 복원: %s", e)
        try:
            from app.services import engine_service as es2
            es2._confirmed_refresh_running = False
            es2._confirmed_refresh_message = ""
        except Exception:
            pass



# _fire_krx_confirmed_fetch / _fire_nxt_confirmed_fetch / _run_post_confirmed_pipeline
# → 제거됨 (Task 3.1). 통합 확정 조회는 market_close_pipeline.py에서 수행.


def retry_pipeline_catchup_after_bootstrap() -> None:
    """부트스트랩 완료 후 미실행 파이프라인 catch-up 재시도.

    기동 시 WS/REST 미준비로 스킵된 작업을 부트스트랩 완료 후 재실행한다.
    캐시가 유효하면(다음 거래일 20:00까지) REST 조회를 스킵한다.
    
    재시도 기간: 20:30 ~ 다음 거래일 ws_subscribe_start 시간까지
    """
    global _confirmed_done
    t = _kst_now().hour * 60 + _kst_now().minute

    # 사용자 설정의 ws_subscribe_start 시간 로드
    try:
        from app.core.settings_file import load_settings
        _settings = load_settings()
        ws_start = str(_settings.get("ws_subscribe_start") or "07:50")
        sh, sm = _parse_hm(ws_start)
        ws_start_minutes = sh * 60 + sm
    except Exception:
        ws_start_minutes = 470  # 기본값 07:50

    # 5개 캐시 모두 유효해야 확정 조회 완료로 간주 → REST 스킵
    # 하나라도 None(만료)이면 확정 데이터 조회 실행
    from app.core.sector_stock_cache import load_snapshot_cache, load_stock_name_cache, load_market_map_cache
    from app.core.industry_map import load_eligible_stocks_cache
    from app.core.avg_amt_cache import load_avg_amt_cache
    from app.services import engine_service

    _snap = load_snapshot_cache()
    _stock_name = load_stock_name_cache()
    _eligible_stocks = load_eligible_stocks_cache()
    _market_map = load_market_map_cache()
    _avg_amt = load_avg_amt_cache()

    _expired = []
    if _snap is None:
        _expired.append("snapshot")
    if _stock_name is None:
        _expired.append("stock_name")
    if _eligible_stocks is None:
        _expired.append("industry_map")
    if _market_map is None:
        _expired.append("market_map")
    if _avg_amt is None:
        _expired.append("avg_amt")

    if not _expired:
        # 모든 캐시 유효 — 종목 수 부족 검사
        _snap_count = len(_snap)
        _filter_count = len(getattr(engine_service, "_filtered_sector_codes", None) or set())
        if _filter_count > 0 and _snap_count < _filter_count * 0.5:
            logger.info("[데이터동기화중] 확정데이터 저장데이터 종목 부족 (%d/%d) — 확정 데이터 조회 실행", _snap_count, _filter_count)
            _fire_unified_confirmed_fetch()
            return
        else:
            # 20:30 이후 + 캐시 날짜가 다음 거래일과 불일치 → 확정 갱신 미완료
            # 재시도 기간: 20:30 ~ 다음 거래일 ws_subscribe_start 시간까지
            unified_past = t >= 1230 or t < ws_start_minutes
            if unified_past:
                from app.core.trading_calendar import current_trading_date_str
                # snapshot 캐시 date로 확정 갱신 완료 여부 판별
                from app.core.sector_stock_cache import SNAPSHOT_CACHE_PATH
                import json as _json
                try:
                    _raw = _json.loads(SNAPSHOT_CACHE_PATH.read_text(encoding="utf-8"))
                    _cached_date = _raw.get("date", "")
                except Exception:
                    _cached_date = ""
                if _cached_date != current_trading_date_str():
                    logger.info("[데이터동기화중] 20:30 이후 + 확정 갱신 미완료 (cached=%s, expected=%s) — 통합 확정 조회 실행", _cached_date, current_trading_date_str())
                    _fire_unified_confirmed_fetch()
                    return
            _confirmed_done = True
            logger.info("[데이터동기화중] 저장데이터 유효 (%d종목) — 재조회 생략", _snap_count)
            return
    else:
        logger.info("[데이터동기화중] 만료된 저장데이터 발견: %s", ", ".join(_expired))

    # 이벤트 루프가 필요한 경로: 개별 갱신
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    # ── 캐시별 개별 갱신 분기 ──────────────────────────────────────────
    # 핵심 4개 캐시 (ka10099 + ka10086 의존)
    _core_expired = [c for c in _expired if c != "avg_amt"]
    # avg_amt (ka10081 독립)
    _avg_amt_expired = "avg_amt" in _expired

    # 재시도 기간: 20:30 ~ 다음 거래일 ws_subscribe_start 시간까지
    unified_past = t >= 1230 or t < ws_start_minutes

    # 1) 핵심 캐시 만료 → 통합 확정 조회 (ka10099 + ka10086)
    if _core_expired and unified_past and not _confirmed_done:
        logger.info("[데이터동기화중] 핵심 저장데이터 만료 (%s) — 통합 확정 조회 실행", ", ".join(_core_expired))
        _fire_unified_confirmed_fetch()
    elif _core_expired and not unified_past:
        logger.info("[데이터동기화중] 핵심 저장데이터 만료 (%s) — ws_subscribe_start(%02d:%02d) 이전이라 대기", ", ".join(_core_expired), ws_start_minutes // 60, ws_start_minutes % 60)
    elif not _core_expired:
        # 핵심 캐시 모두 유효 → 확정 조회 완료로 간주
        _confirmed_done = True

    # 2) avg_amt만 만료 → 5일봉 재구축만 트리거 (ka10081)
    if _avg_amt_expired:
        logger.info("[데이터동기화중] 5일거래대금평균/고가 저장데이터 만료 — 5일챠트 재구축 트리거")
        try:
            engine_service._avg_amt_needs_bg_refresh = True
            engine_service._broadcast_avg_amt_progress(0, 0, status="cache_deleted")
            loop.create_task(engine_service.refresh_avg_amt_5d_cache())
        except Exception as e:
            logger.warning("[데이터동기화중] 5일챠트 재구축 트리거 실패: %s", e)


def _broadcast_market_phase() -> None:
    """market-phase WS 이벤트 브로드캐스트 (08:00, 09:00, 20:00 전환 시점)."""
    try:
        from app.services.engine_account_notify import _broadcast
        phase = get_market_phase()
        _broadcast("market-phase", phase)
        logger.info("[타이머] market-phase 화면전송: %s", phase)
    except Exception as e:
        logger.warning("[타이머] market-phase 화면전송 오류: %s", e)


def _apply_auto_toggle_on_startup(settings: dict) -> None:
    """앱 기동 시 거래일/시간 기준으로 자동매매·WS구독을 자동 ON/OFF.
    - 거래일 + ws_subscribe_start~end 구간 내 → ON
    - 비거래일 or 구독 구간 밖 → OFF
    settings.json 저장 + 프론트 알림까지 수행."""
    from app.core.trading_calendar import is_krx_holiday, kst_today
    from app.core.settings_file import update_settings

    today = kst_today()
    holiday_guard = bool(settings.get("holiday_guard_on", True))
    is_holiday = is_krx_holiday(today)

    # 거래일 판별: holiday_guard_on이 OFF면 공휴일도 허용
    is_trade_day = not (holiday_guard and is_holiday)

    # 시간 구간 판별: ws_subscribe_on 제외하고 시간만 확인
    _dummy = {**settings, "ws_subscribe_on": True}
    in_time_window = is_ws_subscribe_window(_dummy)

    should_be_on = is_trade_day and in_time_window

    on_or_off = should_be_on
    keys = {
        "time_scheduler_on": on_or_off,
        "auto_buy_on": on_or_off,
        "auto_sell_on": on_or_off,
        "ws_subscribe_on": on_or_off,
        "auto_off_by_holiday": False,
    }
    try:
        update_settings(keys)
        settings.update(keys)
        logger.info(
            "[자동토글] 기동 판별 -- 거래일=%s, 시간구간=%s → 자동매매/WS구독 %s",
            is_trade_day, in_time_window, "ON" if on_or_off else "OFF",
        )
        try:
            from app.services.engine_account_notify import (
                notify_desktop_header_refresh,
                notify_desktop_settings_toggled,
            )
            notify_desktop_header_refresh()
            notify_desktop_settings_toggled()
        except Exception:
            pass
    except Exception as e:
        logger.warning("[자동토글] 기동 판별 저장 실패: %s", e)


def _restore_from_holiday_flag(settings: dict) -> bool:
    """auto_off_by_holiday 플래그가 있으면 자동매매/WS구독을 ON으로 복원하고 플래그 삭제.
    복원이 실행되면 True 반환."""
    if not bool(settings.get("auto_off_by_holiday", False)):
        return False
    on_keys = {
        "time_scheduler_on": True,
        "auto_buy_on": True,
        "auto_sell_on": True,
        "ws_subscribe_on": True,
        "auto_off_by_holiday": False,
    }
    try:
        from app.core.settings_file import update_settings
        update_settings(on_keys)
        settings.update(on_keys)
        logger.info("[공휴일가드] 거래일 시작 -- 자동매매/WS구독 자동 복원 (auto_off_by_holiday 해제)")
        try:
            from app.services.engine_account_notify import (
                notify_desktop_header_refresh,
                notify_desktop_settings_toggled,
            )
            notify_desktop_header_refresh()
            notify_desktop_settings_toggled()
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warning("[공휴일가드] 자동 복원 실패: %s", e)
        return False


async def _on_ws_subscribe_start() -> None:
    """WS 구독 시작 시각이 되면 자동 실행 -- WS 연결 + 실시간 데이터 수신을 시작하는 함수."""
    global _ws_subscribe_window_active, _0j_real_receiving
    try:
        from app.core.trading_calendar import is_krx_holiday
        today = _kst_now().date()
        # 주말/공휴일이면 스킵
        if today.weekday() >= 5:
            return
        from app.services import engine_service
        settings = getattr(engine_service, "_settings_cache", None) or {}
        if bool(settings.get("holiday_guard_on", True)):
            if is_krx_holiday(today):
                return
        # 공휴일 강제 OFF 플래그가 있으면 자동 복원 후 진행
        _restore_from_holiday_flag(settings)
        # WS 구독 마스터 스위치 OFF면 스킵
        if not bool(settings.get("ws_subscribe_on", True)):
            return
        _ws_subscribe_window_active = True
        # 0J REAL 플래그 초기화 (새 구독 사이클 시작)
        _0j_real_receiving = False
        # ── 실시간 필드 초기화 (전일 확정 데이터 제거) ──
        logger.info("[타이머] 실시간 구독 시작 -- 실시간 필드 초기화 시작")
        loop = asyncio.get_running_loop()
        loop.create_task(engine_service._reset_realtime_fields())
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        import app.services.engine_account_notify as _an
        _an._prev_scores_cache = []
        engine_service._sector_summary_cache = None
        engine_service._invalidate_sector_stocks_cache()
        # market-phase WS 브로드캐스트 (WS 구독 시작 = 08:00 또는 09:00 전환 시점)
        from app.services.engine_account_notify import _broadcast
        _broadcast("market-phase", get_market_phase())
        # WS 구독 시작 시점 → 폴링 즉시 시작 (0J REAL 수신되면 자동 중단)
        _start_index_poll_timer()
        # ── WS 연결 상태 확인 및 REG 파이프라인 실행 ──
        ws = getattr(engine_service, "_connector_manager", None) or getattr(engine_service, "_kiwoom_connector", None)
        if ws and ws.is_connected():
            logger.info("[타이머] 실시간 구독 구간 진입 -- REG 파이프라인 시작")
            _trigger_reg_pipeline(engine_service)
        else:
            logger.info("[타이머] 실시간 구독 구간 진입 -- 연결되지 않음, 연결 시도")
            try:
                from app.core.connector_manager import ConnectorManager
                settings = engine_service._get_settings()
                _mgr = ConnectorManager(settings)
                _mgr.set_message_callback(engine_service._kiwoom_message_handler)
                await _mgr.connect_all()
                engine_service._connector_manager = _mgr
                engine_service._kiwoom_connector = _mgr.get_connector("kiwoom")
                logger.info("[타이머] 실시간 연결 완료 -- REG 파이프라인 시작")
                _trigger_reg_pipeline(engine_service)
            except Exception as e:
                logger.error("[타이머] 실시간 연결 실패: %s", e)
    except Exception as e:
        logger.warning("[타이머] 실시간 구독 시작 콜백 오류: %s", e)


async def _on_ws_subscribe_end() -> None:
    """WS 구독 종료 시각이 되면 자동 실행 -- 실시간 수신 중단 + WS 연결 해제 + 섹터 재계산을 순서대로 하는 함수."""
    global _ws_subscribe_window_active, _avg_amt_5d_refresh_done, _0j_real_receiving
    try:
        from app.services import engine_service
        _ws_subscribe_window_active = False
        _0j_real_receiving = False
        # 지수 폴링 타이머 중지 (WS 구독 종료 → 폴링 구간도 끝)
        _stop_index_poll_timer()
        # WS 종료 콜백 진입 시 갱신 플래그 초기화 (새 사이클 시작)
        _avg_amt_5d_refresh_done = False
        logger.info("[타이머] 실시간 구독 구간 종료 -- 구독 해지 + 실시간 연결 해제")
        _trigger_unreg_all(engine_service)
        # 구독 상태 전체 false + WS 브로드캐스트
        from app.services.ws_subscribe_control import _set_status
        _set_status(index=False, quote=False)
        # ── 자동매매·WS구독 토글 OFF 저장 (종료 시각 도달) ──
        try:
            from app.core.settings_file import update_settings
            off_keys = {
                "time_scheduler_on": False,
                "auto_buy_on": False,
                "auto_sell_on": False,
                "ws_subscribe_on": False,
            }
            update_settings(off_keys)
            _cache = getattr(engine_service, "_settings_cache", None)
            if isinstance(_cache, dict):
                _cache.update(off_keys)
            logger.info("[자동토글] 구독 종료 시각 도달 -- 자동매매/WS구독 OFF 저장")
            from app.services.engine_account_notify import (
                notify_desktop_header_refresh,
                notify_desktop_settings_toggled,
            )
            notify_desktop_header_refresh()
            notify_desktop_settings_toggled()
        except Exception as _e:
            logger.warning("[자동토글] 구독 종료 OFF 저장 실패: %s", _e)
        # ── WS 연결 해제 ──
        ws = getattr(engine_service, "_connector_manager", None) or getattr(engine_service, "_kiwoom_connector", None)
        if ws and ws.is_connected():
            await ws.disconnect() if hasattr(ws, "disconnect") and not hasattr(ws, "disconnect_all") else await ws.disconnect_all() if hasattr(ws, "disconnect_all") else None
            logger.info("[타이머] WS 소켓 연결 해제 완료")
        engine_service._broadcast_engine_ws()
        # ── 지수 확정 데이터 캐시 저장 (WS 종료 시점 1회) ──
        save_index_cache(engine_service)
    except Exception as e:
        logger.warning("[타이머] 실시간 구독 종료 콜백 오류: %s", e)


def _fire_ws_subscribe_end() -> None:
    """call_later 콜백용 동기 래퍼 -- 비동기 _on_ws_subscribe_end()를 태스크로 감싸서 실행하는 함수."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_on_ws_subscribe_end())
    except RuntimeError:
        pass


def _fire_ws_disconnect_only() -> None:
    """설정 변경으로 인한 구독 해제 전용 — 구독 해제 + WS 끊기만 수행, 장마감 후처리(갱신/캐시저장) 없음."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_ws_disconnect_only())
    except RuntimeError:
        pass


async def _ws_disconnect_only() -> None:
    """구독 해제 + WS 연결 해제만 수행 (장마감 후처리 제외)."""
    global _ws_subscribe_window_active
    try:
        from app.services import engine_service
        _ws_subscribe_window_active = False
        logger.info("[설정] 구독 구간 변경 -- 구독 해지 + 실시간 연결 해제")
        _trigger_unreg_all(engine_service)
        from app.services.ws_subscribe_control import _set_status
        _set_status(index=False, quote=False)
        ws = getattr(engine_service, "_connector_manager", None) or getattr(engine_service, "_kiwoom_connector", None)
        if ws and ws.is_connected():
            await ws.disconnect() if hasattr(ws, "disconnect") and not hasattr(ws, "disconnect_all") else await ws.disconnect_all() if hasattr(ws, "disconnect_all") else None
            logger.info("[설정] 실시간 소켓 연결 해제 완료")
        engine_service._broadcast_engine_ws()
    except Exception as e:
        logger.warning("[설정] 실시간 구독 해제 오류: %s", e)


def schedule_ws_subscribe_timers(settings: dict | None = None) -> None:
    """
    ws_subscribe_start / ws_subscribe_end 시각에 call_later 타이머를 예약한다.
    기존 타이머는 모두 취소 후 재예약.
    엔진 기동 시 + 설정 변경 시 호출.
    """
    global _ws_subscribe_timer_handles

    for handle in _ws_subscribe_timer_handles:
        handle.cancel()
    _ws_subscribe_timer_handles.clear()

    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if not settings:
        try:
            from app.core.settings_file import load_settings
            settings = load_settings()
        except Exception:
            return

    ws_start_str = str(settings.get("ws_subscribe_start") or "07:50")[:5]
    ws_end_str = str(settings.get("ws_subscribe_end") or "20:00")[:5]

    # ※ ws_subscribe_on 상태와 무관하게 타이머는 항상 예약한다.
    # 실행 여부는 _on_ws_subscribe_start() 내부에서 판단한다.
    # (공휴일 가드가 자동으로 OFF한 경우와 사용자 수동 OFF를 여기서 구분할 수 없음)

    sh, sm = _parse_hm(ws_start_str)
    eh, em = _parse_hm(ws_end_str)

    delay_start = _seconds_until_hm(sh, sm)
    delay_end = _seconds_until_hm(eh, em)

    if delay_start > 0 and loop:
        h = loop.call_later(max(delay_start, 1), lambda: asyncio.create_task(_on_ws_subscribe_start()))
        _ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 실시간 구독 시작 (%s) -- %.0f초 후 예약", ws_start_str, delay_start)

    if delay_end > 0 and loop:
        h = loop.call_later(max(delay_end, 1), _fire_ws_subscribe_end)
        _ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 실시간 구독 종료 (%s) -- %.0f초 후 예약", ws_end_str, delay_end)

    # ★ 15:30 KRX 장외 시간대 전환 타이머
    delay_krx_after = _seconds_until_hm(15, 30)
    if delay_krx_after > 0 and loop:
        h = loop.call_later(max(delay_krx_after, 1), _on_krx_after_hours_start)
        _ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 장외 전환 (15:30) -- %.0f초 후 예약", delay_krx_after)

    # ★ 15:40 KRX 확정 조회 타이머 — 제거됨 (Task 3.1, 16:01 KRX 스냅샷+REMOVE로 교체)

    # ★ 20:10 NXT 확정 조회 타이머 — 제거됨 (Task 3.1, 20:30 통합 확정 조회로 교체)

    # ★ 16:01 KRX 장마감 구독해지 타이머
    delay_krx_snapshot = _seconds_until_hm(16, 1)
    if delay_krx_snapshot > 0 and loop:
        h = loop.call_later(max(delay_krx_snapshot, 1), _on_krx_after_hours_remove)
        _ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] KRX 장마감 구독해지 (16:01) -- %.0f초 후 예약", delay_krx_snapshot)

    # ★ 20:30 통합 확정 조회 타이머
    delay_unified = _seconds_until_hm(20, 30)
    if delay_unified > 0 and loop:
        h = loop.call_later(max(delay_unified, 1), _fire_unified_confirmed_fetch)
        _ws_subscribe_timer_handles.append(h)
        logger.debug("[타이머] 통합 확정 조회 (20:30) -- %.0f초 후 예약", delay_unified)
    elif delay_unified <= 0:
        # 20:30 이후 기동 → retry_pipeline_catchup_after_bootstrap에서 캐시 유효성 기반으로 판단
        logger.info("[타이머] 20:30 이후 기동 — 통합 확정 조회는 앱준비 후 catch-up에서 판단")

    # ★ 09:00/15:30 고정 폴링 타이머 제거됨 (Task 5.1, 0J REAL 수신 여부로 자동 판단)

    # ★ market-phase 전환 시점 타이머 (08:00, 09:00, 20:00)
    for hm_h, hm_m, label in ((8, 0, "08:00"), (9, 0, "09:00"), (20, 0, "20:00")):
        delay_mp = _seconds_until_hm(hm_h, hm_m)
        if delay_mp > 0 and loop:
            h = loop.call_later(max(delay_mp, 1), _broadcast_market_phase)
            _ws_subscribe_timer_handles.append(h)
            logger.debug("[타이머] market-phase 전환 (%s) -- %.0f초 후 예약", label, delay_mp)


def _init_ws_subscribe_state(engine_service) -> None:
    """
    엔진 재기동 시 현재 시각 기준으로 WS 구독 상태를 판정하고,
    WS 구독 구간 밖이면서 업종 갱신이 아직 안 됐으면 즉시 1회 갱신하는 함수.
    """
    global _ws_subscribe_window_active, _0j_real_receiving
    settings = getattr(engine_service, "_settings_cache", None)
    if not settings or not isinstance(settings, dict) or "index_poll_after_close" not in settings:
        # 엔진 기동 전이라 _settings_cache가 아직 안 채워졌을 수 있음 → 파일에서 직접 읽기
        try:
            from app.core.settings_file import load_settings
            settings = load_settings()
        except Exception:
            settings = settings or {}
    in_window = is_ws_subscribe_window(settings)
    _ws_subscribe_window_active = in_window

    if in_window:
        # 0J REAL 플래그 초기화 (기동 시점에는 아직 0J 미수신)
        _0j_real_receiving = False
        # ── 실시간 필드 초기화 (전일 확정 데이터 제거) ──
        logger.info("[타임스케줄러] 구독 구간 내 시작 -- 실시간 필드 초기화")
        loop = asyncio.get_running_loop()
        loop.create_task(engine_service._reset_realtime_fields())
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        try:
            import app.services.engine_account_notify as _an
            _an._prev_scores_cache = []
            engine_service._sector_summary_cache = None
            engine_service._invalidate_sector_stocks_cache()
        except Exception:
            pass

        _trigger_reg_pipeline(engine_service)
        # 기동 시각 기준: 폴링 즉시 시작 → 0J REAL 수신되면 자동 중단
        logger.info("[타임스케줄러] 기동 시각 %02d:%02d — 폴링 시작 (0J REAL 수신 시 자동 중단)", _kst_now().hour, _kst_now().minute)
        _start_index_poll_timer()
    else:
        logger.info("[타임스케줄러] 구독 구간 외 시작")
        # 구독 상태 false + WS 브로드캐스트
        from app.services.ws_subscribe_control import _set_status
        _set_status(index=False, quote=False)
        # WS 구독 구간 밖에서 기동 → 지수 캐시 로드 (확정 데이터, 추가 API 요청 불필요)
        load_index_cache(engine_service)
        # WS 구독 구간 밖에서 기동 → 업종 시세 캐시 로드 (확정 데이터, 추가 API 요청 불필요)
        load_industry_index_cache(engine_service)


def _trigger_reg_pipeline(engine_service) -> None:
    """로그인 상태면 REG 파이프라인 재실행."""
    try:
        ws = getattr(engine_service, "_connector_manager", None) or getattr(engine_service, "_kiwoom_connector", None)
        login_ok = getattr(engine_service, "_login_ok", False)
        if ws and ws.is_connected() and login_ok:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(engine_service._login_post_pipeline())
            except RuntimeError:
                pass
        else:
            logger.info("[타임스케줄러] 구독 구간 진입 -- WS 미연결 상태, 연결 후 자동 구독됨")
    except Exception as e:
        logger.warning("[타임스케줄러] REG 파이프라인 트리거 오류: %s", e)


def _trigger_unreg_all(engine_service) -> None:
    """구독 중인 종목 전체 UNREG 전송 + WS 캐시 클리어."""
    try:
        # WS 캐시 클리어 -- 장외 시간에 REST 확정값이 우선 표시되도록
        for attr in ("_latest_trade_prices", "_latest_trade_amounts", "_latest_strength"):
            cache = getattr(engine_service, attr, None)
            if isinstance(cache, dict):
                cache.clear()
        logger.info("[타임스케줄러] WS 저장데이터 클리어 완료 (trade_prices·trade_amounts·strength)")

        import asyncio
        ws = getattr(engine_service, "_connector_manager", None) or getattr(engine_service, "_kiwoom_connector", None)
        login_ok = getattr(engine_service, "_login_ok", False)
        if not ws or not ws.is_connected() or not login_ok:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_do_unreg_all(engine_service))
        except RuntimeError:
            pass
    except Exception as e:
        logger.warning("[타임스케줄러] UNREG 트리거 오류: %s", e)


async def _do_unreg_all(engine_service) -> None:
    """구독 중인 종목 전체 REMOVE 전송 (비동기)."""
    try:
        subscribed = set(getattr(engine_service, "_subscribed_stocks", set()))
        ws = getattr(engine_service, "_connector_manager", None) or getattr(engine_service, "_kiwoom_connector", None)
        if not ws or not ws.is_connected():
            return

        all_codes = subscribed
        if not all_codes:
            logger.info("[타임스케줄러] REMOVE 대상 없음 -- 이미 구독 없음")
            return

        # grp 4(0B): 구독 중인 종목코드를 data에 포함
        from app.services.engine_symbol_utils import get_ws_subscribe_code
        codes_list = [get_ws_subscribe_code(cd) for cd in list(all_codes)]
        payload = {
            "trnm": "REMOVE",
            "grp_no": "4",
            "refresh": "0",
            "data": [{"item": codes_list, "type": ["0B"]}],
        }
        await ws.send_message(payload)

        # 계좌 실시간도 해지 (grp 10)
        acnt_no = str(
            (getattr(engine_service, "_settings_cache", None) or {}).get("kiwoom_account_no", "") or ""
        ).strip()
        if acnt_no:
            await ws.send_message({
                "trnm": "REMOVE", "grp_no": "10", "refresh": "0",
                "data": [{"item": [""], "type": ["00", "04"]}],
            })

        # 구독 상태 초기화
        subscribed.clear()
        if hasattr(engine_service, "_subscribed_stocks"):
            engine_service._subscribed_stocks.clear()

        logger.info("[타임스케줄러] REMOVE 완료 -- %d종목 구독 해지", len(codes_list))

        # ws_subscribe_control 상태 동기화 — 구독 해지 완료
        from app.services import ws_subscribe_control
        ws_subscribe_control._set_status(index=False, quote=False)
    except Exception as e:
        logger.warning("[타임스케줄러] REMOVE 전송 오류: %s", e)


# ── call_later 기반 매수/매도 시간 전환 타이머 ─────────────────────────────────
_auto_trade_timer_handles: list = []  # asyncio.TimerHandle 목록


def _seconds_until_hm(h: int, m: int) -> float:
    """현재 KST 시각에서 오늘 h:m까지 남은 초. 이미 지났으면 음수."""
    now = _kst_now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (target - now).total_seconds()


def _on_auto_trade_transition(label: str) -> None:
    """매수/매도 시간 구간 진입/이탈 시 1회 실행되는 콜백."""
    try:
        from app.services import engine_service
        from app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        logger.info("[타이머] 자동매매 시간 전환 -- %s", label)
        # 엔진 설정 캐시 갱신 (메모리만, 디스크 I/O 없음)
        loop = asyncio.get_running_loop()
        loop.create_task(engine_service.refresh_engine_settings_cache(None, use_root=True))
        notify_desktop_header_refresh()
        notify_desktop_settings_toggled()
    except Exception as e:
        logger.warning("[타이머] 자동매매 전환 콜백 오류: %s", e)


def schedule_auto_trade_timers(settings: dict | None = None) -> None:
    """
    매수/매도 시간 구간 전환 시점에 call_later 타이머를 예약한다.
    기존 타이머는 모두 취소 후 재예약.
    엔진 기동 시 + 설정 변경 시 호출.
    """
    global _auto_trade_timer_handles

    # 기존 타이머 전부 취소
    for handle in _auto_trade_timer_handles:
        handle.cancel()
    _auto_trade_timer_handles.clear()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 이벤트 루프 없으면 스킵

    if not settings:
        try:
            from app.core.settings_file import load_settings
            settings = load_settings()
        except Exception:
            return

    if not bool(settings.get("time_scheduler_on", False)):
        return  # 마스터 스위치 OFF면 타이머 불필요

    # 예약 대상 시각들: 매수 시작/종료, 매도 시작/종료
    time_points = [
        ("buy_time_start", str(settings.get("buy_time_start") or "09:00")[:5], "매수 구간 진입"),
        ("buy_time_end", str(settings.get("buy_time_end") or "15:20")[:5], "매수 구간 이탈"),
        ("sell_time_start", str(settings.get("sell_time_start") or "09:00")[:5], "매도 구간 진입"),
        ("sell_time_end", str(settings.get("sell_time_end") or "15:20")[:5], "매도 구간 이탈"),
    ]

    for key, hm_str, label in time_points:
        h, m = _parse_hm(hm_str)
        delay = _seconds_until_hm(h, m)
        if delay < 0:
            continue  # 이미 지난 시각은 스킵
        if delay < 1:
            delay = 1  # 최소 1초 (즉시 실행 방지)
        handle = loop.call_later(delay, _on_auto_trade_transition, label)
        _auto_trade_timer_handles.append(handle)
        logger.debug(
            "[타이머] %s (%s) -- %.0f초 후 예약",
            label, hm_str, delay,
        )


# ── call_later 기반 자정 날짜 변경 타이머 ─────────────────────────────────────
_midnight_timer_handle = None  # asyncio.TimerHandle


def _on_midnight() -> None:
    """자정(00:00)이 되면 자동 실행 -- 갱신 플래그를 초기화하고 당일 타이머를 새로 예약하는 함수."""
    global _last_reset_date, _avg_amt_5d_refresh_done
    global _krx_remove_done, _confirmed_done
    try:
        now = _kst_now()
        _last_reset_date = now.strftime("%Y%m%d")
        _avg_amt_5d_refresh_done = False
        _krx_remove_done = False
        _confirmed_done = False
        logger.info("[타이머] 자정 날짜 변경 -- 플래그 초기화 (%s)", _last_reset_date)

        from app.services import engine_service
        settings = getattr(engine_service, "_settings_cache", None)

        # 날짜 변경 시 거래일/시간 기준 자동 ON/OFF 판별
        if not settings:
            try:
                from app.core.settings_file import load_settings
                settings = load_settings()
            except Exception:
                settings = {}
        if settings:
            _apply_auto_toggle_on_startup(settings)

        schedule_auto_trade_timers(settings)
        schedule_ws_subscribe_timers(settings)
        # 다음날 자정 타이머도 재예약
        schedule_midnight_timer()
    except Exception as e:
        logger.warning("[타이머] 자정 콜백 오류: %s", e)


def schedule_midnight_timer() -> None:
    """다음 자정(00:00)에 call_later 타이머를 예약하는 함수. 엔진 기동 시 + 자정 콜백에서 호출."""
    global _midnight_timer_handle
    if _midnight_timer_handle is not None:
        _midnight_timer_handle.cancel()
        _midnight_timer_handle = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    delay = _seconds_until_hm(0, 0)
    if delay <= 0:
        # 이미 자정 지남 → 다음날 자정까지 (24시간 + delay)
        delay += 86400
    _midnight_timer_handle = loop.call_later(max(delay, 1), _on_midnight)
    logger.debug("[타이머] 자정 타이머 -- %.0f초 후 예약", delay)


# ── 지수 REST 폴링 이벤트 타이머 (15:30~WS구독종료, 60초 간격) ──────────────

_index_poll_start_handle = None  # 15:30 시작 예약용 TimerHandle


def _schedule_index_poll_at_1530(settings: dict | None = None) -> None:
    """15:30에 지수 폴링을 시작하는 call_later 타이머를 예약하는 함수. WS 구독 시작 콜백에서 호출."""
    global _index_poll_start_handle
    if _index_poll_start_handle is not None:
        _index_poll_start_handle.cancel()
        _index_poll_start_handle = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    delay = _seconds_until_hm(15, 30)
    if delay <= 0:
        # 이미 15:30 지남 → 즉시 시작
        _start_index_poll_timer()
        return
    _index_poll_start_handle = loop.call_later(max(delay, 1), _start_index_poll_timer)
    logger.debug("[지수폴링] 15:30 시작 타이머 -- %.0f초 후 예약", delay)


def _start_index_poll_timer() -> None:
    """60초 간격 지수 REST 폴링 반복 타이머를 시작하는 함수."""
    global _index_poll_timer_handle
    if _index_poll_timer_handle is not None:
        return  # 이미 작동 중
    if _0j_real_receiving:
        return  # 0J REAL 수신 중이면 폴링 불필요
    logger.info("[지수폴링] 60초 간격 폴링 시작")
    _do_index_poll_tick()


def _stop_index_poll_timer() -> None:
    """지수 폴링 반복 타이머를 중지하는 함수."""
    global _index_poll_timer_handle, _index_poll_start_handle
    if _index_poll_timer_handle is not None:
        _index_poll_timer_handle.cancel()
        _index_poll_timer_handle = None
    if _index_poll_start_handle is not None:
        _index_poll_start_handle.cancel()
        _index_poll_start_handle = None


def on_0j_real_received() -> None:
    """0J REAL 메시지 첫 수신 시 호출 — 폴링 즉시 중단."""
    global _0j_real_receiving
    if _0j_real_receiving:
        return  # 이미 수신 중 — 중복 처리 방지
    _0j_real_receiving = True
    logger.info("[지수폴링] 0J REAL 수신 시작 — 폴링 즉시 중단")
    _stop_index_poll_timer()


def _do_index_poll_tick() -> None:
    """60초마다 실행 -- 지수 REST 폴링 1회 실행 후 다음 타이머를 예약하는 함수."""
    global _index_poll_timer_handle
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_poll_index_ka20001_once())
    except RuntimeError:
        return
    # 다음 60초 후 재예약
    try:
        _index_poll_timer_handle = loop.call_later(_INDEX_POLL_INTERVAL_SEC, _do_index_poll_tick)
    except RuntimeError:
        _index_poll_timer_handle = None


async def _poll_index_ka20001_once() -> None:
    """ka20001 업종현재가요청으로 코스피·코스닥 지수를 1회 조회해서 _latest_index에 저장하는 함수."""
    from app.services import engine_service
    from app.core.broker_factory import get_router

    _settings = getattr(engine_service, "_settings_cache", {}) or {}
    try:
        _sector = get_router(_settings).sector
    except Exception:
        logger.debug("[지수폴링] BrokerRouter 미준비 -- 폴링 생략")
        return

    latest_index: dict = getattr(engine_service, "_latest_index", {})

    def _sync_poll():
        """코스피(001)·코스닥(101) 지수를 SectorProvider 경유로 조회."""
        import time as _time
        results = {}
        for i, (mrkt_tp, inds_cd) in enumerate((("0", "001"), ("1", "101"))):
            if i > 0:
                _time.sleep(1.0)  # API 호출 간격
            row = _sector.fetch_index(mrkt_tp, inds_cd)
            if row:
                results[inds_cd] = row
        return results

    try:
        rows = await asyncio.to_thread(_sync_poll)
        for inds_cd, row in rows.items():
            if row.get("price", 0) > 0:
                latest_index[inds_cd] = row
        if rows:
            from app.services.engine_account_notify import notify_desktop_index_refresh
            notify_desktop_index_refresh()
            logger.info("[지수폴링] ka20001 갱신 -- %s", {k: f"{v['price']:.2f}" for k, v in rows.items()})
    except Exception as e:
        logger.warning("[지수폴링] ka20001 REST 폴링 실패: %s", e)


# ── ka10001 확정 데이터 갱신 ─────────────────────────────────────────────────

def _freeze_krx_amt29_baseline(engine_service) -> None:
    pass  # KRX 단독 구조에서는 freeze 불필요 -- 호환성 유지용 stub


def _apply_detail_to_entry(entry: dict, detail: dict, *, engine_service=None, base_nk: str = "") -> None:
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
        # ka10086 확정값도 _latest_trade_amounts에 반영 (장 마감 후 UI 표시용)
        if engine_service is not None and base_nk:
            lta: dict = getattr(engine_service, "_latest_trade_amounts", {})
            lta[base_nk] = amt
    strength = detail.get("strength")
    if strength is not None:
        try:
            entry["strength"] = f"{float(strength):.2f}"
        except (ValueError, TypeError):
            pass


# ── 스케줄러 시작/중지 ────────────────────────────────────────────────────────


def _apply_holiday_guard_on_startup(settings: dict | None) -> None:
    """앱 기동 시 공휴일이면 자동매매/매수/매도/WS구독을 OFF로 저장.
    사용자가 수동으로 다시 켤 수 있음 (하드코딩 아님)."""
    if not settings:
        try:
            from app.core.settings_file import load_settings
            settings = load_settings()
        except Exception:
            return
    if not bool(settings.get("holiday_guard_on", True)):
        return

    from app.core.trading_calendar import is_krx_holiday, kst_today
    today = kst_today()
    if today.weekday() >= 5 or is_krx_holiday(today):
        off_keys = {
            "time_scheduler_on": False,
            "auto_buy_on": False,
            "auto_sell_on": False,
            "ws_subscribe_on": False,
            "auto_off_by_holiday": True,
        }
        # 이미 전부 OFF + 플래그 있으면 저장 스킵
        _already_off = all(not bool(settings.get(k, True)) for k in ("time_scheduler_on", "auto_buy_on", "auto_sell_on", "ws_subscribe_on"))
        if _already_off and bool(settings.get("auto_off_by_holiday", False)):
            return
        try:
            from app.core.settings_file import update_settings
            update_settings(off_keys)
            # 엔진 메모리 캐시도 즉시 반영
            settings.update(off_keys)
            logger.info(
                "[공휴일가드] 비거래일(%s) -- 자동매매/매수/매도/WS구독 OFF 저장 (auto_off_by_holiday=True)",
                today.isoformat(),
            )
            # WS로 프론트에 변경 알림
            try:
                from app.services.engine_account_notify import (
                    notify_desktop_header_refresh,
                    notify_desktop_settings_toggled,
                )
                notify_desktop_header_refresh()
                notify_desktop_settings_toggled()
            except Exception:
                pass
        except Exception as e:
            logger.warning("[공휴일가드] 설정 저장 실패: %s", e)


def start_daily_time_scheduler() -> None:
    """타임스케줄러를 시작하는 함수 -- 이벤트 타이머 초기 예약."""
    # 엔진 기동 시 타이머 초기 예약
    try:
        from app.services import engine_service
        settings = getattr(engine_service, "_settings_cache", None)

        # ── 기동 시 자동 ON/OFF 판별: 거래일+시간구간이면 ON, 아니면 OFF ──
        if not settings:
            try:
                from app.core.settings_file import load_settings
                settings = load_settings()
            except Exception:
                settings = {}
        if settings:
            _apply_auto_toggle_on_startup(settings)

        schedule_auto_trade_timers(settings)
        schedule_ws_subscribe_timers(settings)
        schedule_midnight_timer()
        # 현재 시각 기준 WS 구독 상태 즉시 판정 (기동 시점)
        _init_ws_subscribe_state(engine_service)
    except Exception as e:
        logger.warning("[타임스케줄러] 타이머 초기 예약 실패: %s", e)
    logger.info("[타임스케줄러] 시작 (이벤트 기반 타이머)")


async def stop_daily_time_scheduler() -> None:
    """타임스케줄러를 중지하는 함수 -- 모든 타이머 취소."""
    global _auto_trade_timer_handles, _ws_subscribe_timer_handles, _midnight_timer_handle
    # 모든 타이머 취소
    for handle in _auto_trade_timer_handles:
        handle.cancel()
    _auto_trade_timer_handles.clear()
    for handle in _ws_subscribe_timer_handles:
        handle.cancel()
    _ws_subscribe_timer_handles.clear()
    if _midnight_timer_handle is not None:
        _midnight_timer_handle.cancel()
        _midnight_timer_handle = None
    _stop_index_poll_timer()
    logger.info("[타임스케줄러] 중지")
