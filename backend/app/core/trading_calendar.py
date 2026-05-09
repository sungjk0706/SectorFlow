# -*- coding: utf-8 -*-
"""
KRX 영업일 판별 유틸 -- holidays 라이브러리 + 주말 판단.

사용처:
- 직전 영업일 계산 (캐시 날짜 태그, REST API qry_dt 등)
- 최근 N영업일 목록 생성 (일별 요약 등)

holidays 라이브러리는 설/추석/대체공휴일 등 음력 기반 공휴일도
알고리즘으로 자동 계산하므로 연도 변경 시 수동 업데이트 불필요.
임시공휴일(대통령 지정 등)만 라이브러리 업데이트로 반영.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import holidays

_KST = timezone(timedelta(hours=9))


@lru_cache(maxsize=8)
def _kr_holidays(year: int) -> holidays.HolidayBase:
    """해당 연도 한국 공휴일 dict. lru_cache로 연도별 1회만 생성."""
    return holidays.KR(years=year)


def is_krx_holiday(d: date) -> bool:
    """주말 또는 한국 공휴일이면 True. 근로자의 날(5/1) 포함."""
    if d.weekday() >= 5:  # 토(5), 일(6)
        return True
    # 근로자의 날 (5월 1일) - KRX 휴장일
    if d.month == 5 and d.day == 1:
        return True
    return d in _kr_holidays(d.year)


def prev_business_date(from_date: date | None = None) -> date:
    """
    from_date 직전 영업일 반환.
    from_date가 None이면 오늘(KST) 기준.
    from_date 자체가 영업일이어도 그 전날부터 탐색.
    최대 10일 뒤로 탐색 (연휴 + 주말 최대 조합 대응).
    """
    if from_date is None:
        from_date = datetime.now(_KST).date()
    d = from_date - timedelta(days=1)
    for _ in range(10):
        if not is_krx_holiday(d):
            return d
        d -= timedelta(days=1)
    # 10일 내 영업일 못 찾으면 단순 -1일 폴백 (사실상 발생 불가)
    return from_date - timedelta(days=1)


def prev_business_date_str(from_yyyymmdd: str | None = None) -> str:
    """YYYYMMDD 문자열 버전. None이면 오늘(KST) 기준."""
    if from_yyyymmdd:
        d = datetime.strptime(from_yyyymmdd, "%Y%m%d").date()
    else:
        d = datetime.now(_KST).date()
    return prev_business_date(d).strftime("%Y%m%d")


def kst_today() -> date:
    """오늘 날짜 (KST)."""
    return datetime.now(_KST).date()


def kst_today_str() -> str:
    """오늘 날짜 YYYYMMDD (KST)."""
    return kst_today().strftime("%Y%m%d")


# ── NXT 장마감(20:00) 기준 거래일 ────────────────────────────────────────────
_NXT_CLOSE_HOUR = 20  # NXT 장마감 시각 (KST)


def _next_business_date(from_date: date) -> date:
    """from_date 다음 영업일 반환. 최대 10일 앞으로 탐색."""
    d = from_date + timedelta(days=1)
    for _ in range(10):
        if not is_krx_holiday(d):
            return d
        d += timedelta(days=1)
    return from_date + timedelta(days=1)


def current_trading_date() -> date:
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
        return _next_business_date(today)

    # 20:00 이전 → 오늘이 거래일이면 오늘, 아니면 다음 거래일
    if not is_krx_holiday(today):
        return today
    return _next_business_date(today)


def current_trading_date_str() -> str:
    """현재 거래일 YYYYMMDD 문자열."""
    return current_trading_date().strftime("%Y%m%d")


def is_cache_valid(cached_date_str: str) -> bool:
    """
    확정 데이터 캐시 유효성 판정 (공통 함수).

    규칙: 캐시 날짜의 다음 거래일 NXT 장마감(20:00 KST)까지 유효.

    예시:
      - 월 캐시 → 화 20:00까지 유효
      - 금 캐시 → 월 20:00까지 유효 (주말 건너뜀)
      - 연휴 전날 캐시 → 연휴 후 첫 거래일 20:00까지 유효
    """
    if not cached_date_str:
        return False
    try:
        cached_date = datetime.strptime(cached_date_str, "%Y%m%d").date()
        next_biz = _next_business_date(cached_date)
        now = datetime.now(_KST)
        expiry = datetime(
            next_biz.year, next_biz.month, next_biz.day,
            _NXT_CLOSE_HOUR, 0, tzinfo=_KST,
        )
        return now < expiry
    except (ValueError, TypeError):
        return False


def recent_business_days(days: int, from_date: date | None = None) -> list[date]:
    """
    from_date 포함 과거 방향으로 최근 N영업일 리스트 반환 (오래된 순).
    from_date가 None이면 오늘(KST) 기준.
    from_date가 비영업일이면 직전 영업일부터 카운트.
    """
    if from_date is None:
        from_date = kst_today()
    result: list[date] = []
    d = from_date
    # from_date가 비영업일이면 직전 영업일로 이동
    while is_krx_holiday(d):
        d -= timedelta(days=1)
    result.append(d)
    while len(result) < days:
        d -= timedelta(days=1)
        if not is_krx_holiday(d):
            result.append(d)
    result.reverse()
    return result
