from __future__ import annotations
# -*- coding: utf-8 -*-
"""
KRX 거래일 판별 유틸 -- pykrx + DB 캐시.

사용처:
- 직전 거래일 계산 (캐시 날짜 태그, REST API qry_dt 등)
- 최근 N거래일 목록 생성 (일별 요약 등)

데이터 소스:
- pykrx: 장마감 후 1회 갱신하여 DB kv_store에 저장
- DB 캐시: 거래일 판별 시 오직 DB 캐시만 조회 (가볍고 빠름)
"""

from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

# 메모리 캐시 (앱 기동 시 DB에서 로드)
_trading_days_cache: dict[int, set[str]] = {}  # {연도: {"20250101", "20250102", ...}}
_cache_loaded = False

__all__ = [
    "_KST",
    "is_trading_day",
    "get_previous_trading_day",
    "get_previous_trading_day_str",
    "get_kst_today",
    "get_kst_today_str",
    "get_current_trading_day",
    "get_current_trading_day_str",
    "is_cache_valid",
    "get_recent_trading_days",
    "refresh_trading_days_cache",
    "initialize_trading_calendar_cache",
]


def _ensure_cache_loaded() -> None:
    """DB 캐시 로드 (최초 호출 시 1회만 실행)."""
    global _cache_loaded
    if _cache_loaded:
        return

    # 캐시가 로드되지 않았으면 빈 캐시로 계속 (앱 기동 시 initialize_trading_calendar_cache 호출 필요)
    _cache_loaded = True


async def initialize_trading_calendar_cache() -> None:
    """
    앱 기동 시 호출하여 DB 캐시를 비동기로 로드.
    """
    global _cache_loaded, _trading_days_cache
    if _cache_loaded:
        return

    try:
        from backend.app.db.stock_tables import load_trading_days_cache

        data = await load_trading_days_cache()
        if data:
            for year_str, days_list in data.items():
                if year_str != "last_updated":
                    year = int(year_str)
                    _trading_days_cache[year] = set(days_list)
            _cache_loaded = True
    except Exception:
        # DB 로드 실패 시 빈 캐시로 계속 (장마감 후 갱신됨)
        _cache_loaded = True


def _date_to_str(d: date) -> str:
    """date → YYYYMMDD."""
    return d.strftime("%Y%m%d")


def _str_to_date(s: str) -> date:
    """YYYYMMDD → date."""
    return datetime.strptime(s, "%Y%m%d").date()


def is_trading_day(d: date) -> bool:
    """
    해당 날짜가 KRX 거래일이면 True.
    DB 캐시만 조회 (네트워크 요청 없음).
    """
    _ensure_cache_loaded()
    date_str = _date_to_str(d)
    return date_str in _trading_days_cache.get(d.year, set())


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


def is_cache_valid(cached_date_str: str, ws_subscribe_start: str = "07:50") -> bool:
    """
    확정 데이터 캐시 유효성 판정 (공통 함수).

    규칙: 캐시 날짜의 다음 거래일 실시간 연결시작 시간(ws_subscribe_start, 기본값 07:50)까지 유효.

    예시:
      - 월 캐시 → 화 07:50까지 유효
      - 금 캐시 → 월 07:50까지 유효 (주말 건너뜀)
      - 연휴 전날 캐시 → 연휴 후 첫 거래일 07:50까지 유효
    """
    if not cached_date_str:
        return False
    try:
        cached_date = _str_to_date(cached_date_str)
        next_biz = _next_trading_day(cached_date)
        now = datetime.now(_KST)

        try:
            parts = str(ws_subscribe_start or "07:50").strip().split(":")
            sh, sm = int(parts[0]), int(parts[1])
        except Exception:
            sh, sm = 7, 50

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


async def refresh_trading_days_cache() -> None:
    """
    exchange_calendars로 올해와 내년 KRX 거래일 목록 조회 후 DB에 저장.
    장마감 배치 파이프라인에서 호출 (비동기 함수).
    XKRX 캘린더 기반 (내장 휴일 데이터).
    """
    import exchange_calendars as xcals
    from backend.app.db.stock_tables import save_trading_days_cache

    global _trading_days_cache, _cache_loaded

    # 올해와 내년 거래일 조회
    today = get_kst_today()
    current_year = today.year
    next_year = current_year + 1

    # 캐시 초기화 (덮어쓰기)
    _trading_days_cache.clear()

    # XKRX 캘린더 로드
    xkrx = xcals.get_calendar("XKRX")

    # 캘린더의 마지막 세션 확인 (범위 초과 방지)
    last_session = xkrx.last_session.strftime("%Y%m%d")

    # 현재 연도와 다음 연도 거래일 조회
    for year in [current_year, next_year]:
        try:
            # exchange_calendars로 KRX 거래일 조회
            start_date = f"{year}0101"
            end_date = f"{year}1231"
            # end_date가 캘린더의 마지막 세션보다 늦으면 조정
            if end_date > last_session:
                end_date = last_session
            valid_days = xkrx.sessions_in_range(start_date, end_date)
            if valid_days is not None and len(valid_days) > 0:
                # DatetimeIndex에서 날짜 추출 (YYYYMMDD 형식)
                trading_days = [d.strftime("%Y%m%d") for d in valid_days]
                days_set = set(trading_days)
                _trading_days_cache[year] = days_set
        except Exception as e:
            # exchange_calendars 조회 실패 시 에러 로그 출력 후 예외 전파
            import traceback
            traceback.print_exc()
            raise

    # DB에 저장 (덮어쓰기)
    cache_data = {str(year): list(days) for year, days in _trading_days_cache.items()}
    cache_data["last_updated"] = _date_to_str(today)

    await save_trading_days_cache(cache_data)
    _cache_loaded = True
