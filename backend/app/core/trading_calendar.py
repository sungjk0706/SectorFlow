from __future__ import annotations
# -*- coding: utf-8 -*-
"""
KRX 거래일 판별 유틸 -- exchange_calendars XKRX 캘린더.

사용처:
- 직전 거래일 계산 (캐시 날짜 태그, REST API qry_dt 등)
- 최근 N거래일 목록 생성 (일별 요약 등)

데이터 소스:
- exchange_calendars XKRX 캘린더 (오프라인, 내장 휴일 데이터)
- 모듈 레벨 lazy singleton으로 1회 로드 후 메모리 상주
"""

from datetime import date, datetime, timedelta, timezone

from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS

_KST = timezone(timedelta(hours=9))

_xkrx = None

__all__ = [
    "_KST",
    "is_trading_day",
    "is_trading_day_with_holiday_guard",
    "get_previous_trading_day",
    "get_previous_trading_day_str",
    "get_kst_today",
    "get_kst_today_str",
    "get_current_trading_day",
    "get_current_trading_day_str",
    "is_cache_valid",
    "get_recent_trading_days",
]


def _get_xkrx():
    """XKRX 캘린더 lazy singleton (최초 호출 시 1회 생성, 이후 메모리 상주)."""
    global _xkrx
    if _xkrx is None:
        import exchange_calendars as xcals
        _xkrx = xcals.get_calendar("XKRX")
    return _xkrx


def _date_to_str(d: date) -> str:
    """date → YYYYMMDD."""
    return d.strftime("%Y%m%d")


def _str_to_date(s: str) -> date:
    """YYYYMMDD → date."""
    return datetime.strptime(s, "%Y%m%d").date()


def is_trading_day(d: date) -> bool:
    """해당 날짜가 KRX 거래일이면 True (exchange_calendars XKRX 캘린더 직접 조회)."""
    return _get_xkrx().is_session(d)


def is_trading_day_with_holiday_guard(holiday_guard_on: bool) -> bool:
    """holiday_guard_on=True면 실제 거래일만, False면 항상 True."""
    if not holiday_guard_on:
        return True
    return is_trading_day(get_kst_today())


def get_previous_trading_day(from_date: date | None = None) -> date:
    """
    from_date 직전 거래일 반환.
    from_date가 None이면 오늘(KST) 기준.
    from_date 자체가 거래일이어도 그 전날부터 탐색.
    최대 10일 뒤로 탐색 (연휴 + 주말 최대 조합 대응).
    """
    if from_date is None:
        from_date = datetime.now(_KST).date()
    d = from_date - timedelta(days=1)
    for _ in range(10):
        if is_trading_day(d):
            return d
        d -= timedelta(days=1)
    # 10일 내 거래일 못 찾으면 단순 -1일 폴백 (사실상 발생 불가)
    return from_date - timedelta(days=1)


def get_previous_trading_day_str(from_yyyymmdd: str | None = None) -> str:
    """YYYYMMDD 문자열 버전. None이면 오늘(KST) 기준."""
    if from_yyyymmdd:
        d = _str_to_date(from_yyyymmdd)
    else:
        d = datetime.now(_KST).date()
    return _date_to_str(get_previous_trading_day(d))


def get_kst_today() -> date:
    """오늘 날짜 (KST)."""
    return datetime.now(_KST).date()


def get_kst_today_str() -> str:
    """오늘 날짜 YYYYMMDD (KST)."""
    return get_kst_today().strftime("%Y%m%d")


# ── NXT 장마감(20:00) 기준 거래일 ────────────────────────────────────────────
_NXT_CLOSE_HOUR = 20  # NXT 장마감 시각 (KST)


def _next_trading_day(from_date: date) -> date:
    """from_date 다음 거래일 반환. 최대 10일 앞으로 탐색."""
    d = from_date + timedelta(days=1)
    for _ in range(10):
        if is_trading_day(d):
            return d
        d += timedelta(days=1)
    return from_date + timedelta(days=1)


def get_current_trading_day() -> date:
    """
    현재 시각 기준 '소속 거래일' 반환.

    - KST 00:00~19:59: 오늘이 거래일이면 오늘, 아니면 다음 거래일
    - KST 20:00~23:59: 다음 거래일

    예시 (2026년 기준):
      금 15:00 → 금 (장중)
      금 19:30 → 금 (NXT 장마감 전)
      금 20:01 → 월 (다음 거래일)
      토 아무때 → 월 (주말 → 다음 거래일)
      일 아무때 → 월 (주말 → 다음 거래일)
      월 00:30 → 월 (장 개시 전이지만 당일 거래일)
      설 연휴  → 연휴 후 첫 거래일
    """
    now = datetime.now(_KST)
    today = now.date()

    if now.hour >= _NXT_CLOSE_HOUR:
        # 20:00 이후 → 다음 거래일
        return _next_trading_day(today)

    # 20:00 이전 → 오늘이 거래일이면 오늘, 아니면 다음 거래일
    if is_trading_day(today):
        return today
    return _next_trading_day(today)


def get_current_trading_day_str() -> str:
    """현재 거래일 YYYYMMDD 문자열."""
    return get_current_trading_day().strftime("%Y%m%d")


def is_cache_valid(cached_date_str: str, ws_subscribe_start: str = DEFAULT_USER_SETTINGS["ws_subscribe_start"]) -> bool:
    """
    확정 데이터 캐시 유효성 판정 (공통 함수).

    규칙: 캐시 날짜의 다음 거래일 실시간 연결시작 시간(ws_subscribe_start, 기본값 09:00)까지 유효.

    예시:
      - 월 캐시 → 화 09:00까지 유효
      - 금 캐시 → 월 09:00까지 유효 (주말 건너뜀)
      - 연휴 전날 캐시 → 연휴 후 첫 거래일 09:00까지 유효
    """
    if not cached_date_str:
        return False
    try:
        cached_date = _str_to_date(cached_date_str)
        next_biz = _next_trading_day(cached_date)
        now = datetime.now(_KST)

        try:
            parts = str(ws_subscribe_start).strip().split(":")
            sh, sm = int(parts[0]), int(parts[1])
        except Exception:
            sh, sm = 9, 0

        expiry = datetime(
            next_biz.year, next_biz.month, next_biz.day,
            sh, sm, tzinfo=_KST,
        )
        return now < expiry
    except (ValueError, TypeError):
        return False


def get_recent_trading_days(days: int, from_date: date | None = None) -> list[date]:
    """
    from_date 포함 과거 방향으로 최근 N거래일 리스트 반환 (오래된 순).
    from_date가 None이면 오늘(KST) 기준.
    from_date가 비거래일이면 직전 거래일부터 카운트.
    """
    if from_date is None:
        from_date = get_kst_today()
    result: list[date] = []
    d = from_date
    # from_date가 비거래일이면 직전 거래일로 이동
    while not is_trading_day(d):
        d -= timedelta(days=1)
        # 날짜 범위 체크 (최소 1년 1월 1일)
        if d.year < 2000:
            return []
    result.append(d)
    while len(result) < days:
        d -= timedelta(days=1)
        # 날짜 범위 체크 (최소 1년 1월 1일)
        if d.year < 2000:
            break
        if is_trading_day(d):
            result.append(d)
    result.reverse()
    return result
