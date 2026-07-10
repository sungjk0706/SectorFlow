# -*- coding: utf-8 -*-
"""
KRX 거래일 판별 유틸 -- DB 캐시 기반.

사용처:
- 직접 거래일 계산 (캐시 날짜 태그, REST API qry_dt 등)
- 최근 N거래일 목록 생성 (일별 요약 등)

데이터 소스:
- korean_lunar_calendar 기반 자체 휴일 계산 (연 1회 갱신 시에만 사용, 런타임 블로킹 제거)
- trading_days_cache SQLite 테이블에 연도별 거래일 저장
- 앱 기동 시 DB에서 dict[int, set[str]] 메모리 로드 (O(1) 조회)
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

_trading_days_cache: dict[int, set[str]] = {}
_cache_initialized: bool = False

__all__ = [
    "_KST",
    "is_trading_day",
    "get_previous_trading_day",
    "get_previous_trading_day_str",
    "get_kst_today",
    "get_kst_today_str",
    "get_current_trading_day",
    "get_current_trading_day_str",
    "get_recent_trading_days",
    "initialize_trading_calendar_cache",
    "refresh_trading_days_for_year",
    "has_trading_days_for_year",
]


def _date_to_str(d: date) -> str:
    """date → YYYYMMDD."""
    return d.strftime("%Y%m%d")


def _str_to_date(s: str) -> date:
    """YYYYMMDD → date."""
    return datetime.strptime(s, "%Y%m%d").date()


async def initialize_trading_calendar_cache() -> None:
    """앱 기동 시 1회 호출 — DB에서 거래일 캐시 로드.
    DB에 데이터 없으면 자체 휴일 계산으로 최초 1회 생성 후 DB 저장.
    """
    global _trading_days_cache, _cache_initialized
    if _cache_initialized:
        return
    from backend.app.db.stock_tables import load_trading_days_cache, save_trading_days_cache

    db_cache = await load_trading_days_cache()
    if db_cache is not None:
        _trading_days_cache = db_cache
        current_year = datetime.now(_KST).year
        next_year = current_year + 1
        if next_year not in _trading_days_cache:
            logger.info("[스케줄] 다음 연도(%d) 캐시 없음 — 자체 휴일 계산으로 생성", next_year)
            new_data = _generate_trading_days(next_year)
            _trading_days_cache.update(new_data)
            await save_trading_days_cache(new_data)
        _cache_initialized = True
        logger.info("[스케줄] DB 캐시 로드 완료 — %d개 연도", len(_trading_days_cache))
        return

    logger.info("[스케줄] DB 캐시 없음 — 자체 휴일 계산으로 최초 생성")
    current_year = datetime.now(_KST).year
    _trading_days_cache = _generate_trading_days(current_year)
    next_year_data = _generate_trading_days(current_year + 1)
    _trading_days_cache.update(next_year_data)
    await save_trading_days_cache(_trading_days_cache)
    _cache_initialized = True
    logger.info("[스케줄] 최초 캐시 생성 및 DB 저장 완료 — %d개 연도", len(_trading_days_cache))


# ── KRX 휴일 계산 (korean_lunar_calendar 기반) ──────────────────────────────────

# 고정 양력 공휴일 (매년 같은 날짜)
# (월, 일, 이름) — 제헌절은 2026년부터 공휴일로 재지정
_FIXED_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "신정"),
    (3, 1, "삼일절"),
    (5, 1, "근로자의날"),
    (5, 5, "어린이날"),
    (6, 6, "현충일"),
    (8, 15, "광복절"),
    (10, 3, "개천절"),
    (10, 9, "한글날"),
    (12, 25, "크리스마스"),
]

# 대체 공휴일 대상 (2021년 확대 규칙): 토/일요일 겹칠 시 다음 평일을 대체 공휴일로 지정
# 설날/추석: 일요일 겹칠 시만 대체 (별도 처리)
# 부처님오신날: 2023년부터 토/일요일 대체 적용
_SUBSTITUTE_TARGETS: set[str] = {"삼일절", "광복절", "개천절", "한글날", "어린이날"}

# 임시 공휴일 / 선거일 (알고리즘 예측 불가 — 수동 관리)
# 정부 발표 시 해당 날짜를 추가하면 됨
_MANUAL_HOLIDAYS: dict[int, set[date]] = {
    2024: {
        date(2024, 4, 10),   # 제22대 국회의원선거
        date(2024, 10, 1),   # 국군의날 임시공휴일
    },
    2025: {
        date(2025, 1, 27),   # 설날 연휴 임시공휴일
        date(2025, 5, 6),    # 임시공휴일
        date(2025, 6, 3),    # 제21대 대통령선거
    },
}


def _lunar_to_solar(year: int, lunar_month: int, lunar_day: int) -> date:
    """음력 날짜를 양력 날짜로 변환 (korean_lunar_calendar 사용)."""
    from korean_lunar_calendar import KoreanLunarCalendar
    cal = KoreanLunarCalendar()
    cal.setLunarDate(year, lunar_month, lunar_day, False)
    return date.fromisoformat(cal.SolarIsoFormat())


def _compute_holidays(year: int) -> set[date]:
    """해당 연도의 KRX 비거래일(공휴일) set 계산.

    구성:
    1. 고정 양력 휴일 (신정~크리스마스 + 제헌절 2026~)
    2. 음력 휴일 (설날 3일, 추석 3일, 부처님오신날)
    3. 대체 공휴일 (2021년 확대 규칙)
    4. KRX 전용 연말 휴일 (Dec 31, 마지막 거래일 관측)
    5. 임시 공휴일 / 선거일 (수동 오버라이드)
    """
    holidays: set[date] = set()

    # 1. 고정 양력 휴일
    for month, day, _name in _FIXED_HOLIDAYS:
        holidays.add(date(year, month, day))

    # 제헌절: 2026년부터 공휴일 재지정 (2008년~2025년은 공휴일 아님)
    if year >= 2026:
        holidays.add(date(year, 7, 17))

    # 2. 음력 휴일
    # 설날 (음력 1/1) + 전날 + 다음날
    try:
        seollal = _lunar_to_solar(year, 1, 1)
        holidays.add(seollal - timedelta(days=1))
        holidays.add(seollal)
        holidays.add(seollal + timedelta(days=1))
    except Exception:
        logger.warning("[스케줄] %d년 설날 음력 변환 실패", year)

    # 추석 (음력 8/15) + 전날 + 다음날
    try:
        chuseok = _lunar_to_solar(year, 8, 15)
        holidays.add(chuseok - timedelta(days=1))
        holidays.add(chuseok)
        holidays.add(chuseok + timedelta(days=1))
    except Exception:
        logger.warning("[스케줄] %d년 추석 음력 변환 실패", year)

    # 부처님오신날 (음력 4/8)
    try:
        buddha = _lunar_to_solar(year, 4, 8)
        holidays.add(buddha)
    except Exception:
        logger.warning("[스케줄] %d년 부처님오신날 음력 변환 실패", year)

    # 3. 대체 공휴일
    substitutes: set[date] = set()

    # 설날/추석: 3일 연휴 중 일요일이 포함되면 다음 평일을 대체 공휴일로
    for base in [seollal, chuseok]:
        if base is None:
            continue
        cluster = {base - timedelta(days=1), base, base + timedelta(days=1)}
        has_sunday = any(d.weekday() == 6 for d in cluster if d.year == year)
        if has_sunday:
            next_day = max(cluster) + timedelta(days=1)
            while next_day in holidays or next_day in substitutes or next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            substitutes.add(next_day)

    # 고정 휴일 대체 (2021년부터, 어린이날은 2014년부터)
    for month, day, name in _FIXED_HOLIDAYS:
        if name not in _SUBSTITUTE_TARGETS:
            continue
        d = date(year, month, day)
        sub = _calc_substitute(d, year, holidays, substitutes)
        if sub is not None:
            substitutes.add(sub)

    # 제헌절 대체 (2026년부터, 삼일절/광복절과 동일 규칙)
    if year >= 2026:
        d = date(year, 7, 17)
        sub = _calc_substitute(d, year, holidays, substitutes)
        if sub is not None:
            substitutes.add(sub)

    # 부처님오신날 대체 (2023년부터)
    if year >= 2023:
        try:
            buddha = _lunar_to_solar(year, 4, 8)
            sub = _calc_substitute(buddha, year, holidays, substitutes)
            if sub is not None:
                substitutes.add(sub)
        except Exception:
            pass

    holidays.update(substitutes)

    # 4. KRX 전용 연말 휴일 (Dec 31이 주말이면 그 직전 마지막 평일)
    dec31 = date(year, 12, 31)
    if dec31.weekday() >= 5:
        # 주말이면 직전 금요일을 휴일로 (이미 주말이므로 비거래일)
        d = dec31
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        holidays.add(d)
    else:
        holidays.add(dec31)

    # 5. 임시 공휴일 / 선거일 (수동 오버라이드)
    if year in _MANUAL_HOLIDAYS:
        holidays.update(_MANUAL_HOLIDAYS[year])

    return holidays


def _calc_substitute(
    holiday: date,
    year: int,
    holidays: set[date],
    substitutes: set[date],
) -> date | None:
    """대체 공휴일 계산 — 휴일이 토요일이면 월요일, 일요일이면 월요일을 대체 공휴일로 지정.
    이미 다른 휴일/대체 공휴일이거나 주말이면 다음 평일로 이동."""
    if holiday.weekday() == 5:  # Saturday
        sub = holiday + timedelta(days=2)
    elif holiday.weekday() == 6:  # Sunday
        sub = holiday + timedelta(days=1)
    else:
        return None
    while sub in holidays or sub in substitutes or sub.weekday() >= 5:
        sub += timedelta(days=1)
    return sub


def _generate_trading_days(year: int) -> dict[int, set[str]]:
    """자체 휴일 계산으로 해당 연도의 거래일 set 생성 (동기, 최초 1회 또는 연 1회 갱신 시에만 호출).
    korean_lunar_calendar 기반 — exchange_calendars 의존성 없음."""
    holidays = _compute_holidays(year)
    days_set: set[str] = set()
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            days_set.add(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    logger.info("[스케줄] 자체 계산으로 %d년 거래일 %d일 생성", year, len(days_set))
    return {year: days_set}


async def refresh_trading_days_for_year(year: int) -> None:
    """특정 연도의 거래일 캐시를 자체 휴일 계산으로 재생성 후 DB에 저장 (연 1회 갱신용)."""
    global _trading_days_cache
    from backend.app.db.stock_tables import save_trading_days_cache

    new_data = _generate_trading_days(year)
    _trading_days_cache[year] = new_data[year]
    await save_trading_days_cache({year: _trading_days_cache[year]})
    logger.info("[스케줄] %d년 거래일 캐시 갱신 완료", year)


def is_trading_day(d: date) -> bool:
    """해당 날짜가 KRX 거래일이면 True (메모리 캐시 set 조회, O(1))."""
    if not _cache_initialized:
        logger.error("[스케줄] 캐시 미초기화 — initialize_trading_calendar_cache()가 호출되지 않음")
        raise RuntimeError("trading calendar cache not initialized")
    year = d.year
    if year not in _trading_days_cache:
        logger.error("[스케줄] %d년 캐시 없음 — refresh_trading_days_for_year() 필요", year)
        raise KeyError(f"trading days cache missing for year {year}")
    return d.strftime("%Y%m%d") in _trading_days_cache[year]


def has_trading_days_for_year(year: int) -> bool:
    """해당 연도의 거래일 캐시가 메모리에 존재하는지 확인."""
    return year in _trading_days_cache


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
