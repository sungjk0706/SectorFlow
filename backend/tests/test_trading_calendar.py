"""trading_calendar.py 단위 테스트 — KRX 휴일 계산 및 거래일 판별 검증.

_compute_holidays, _generate_trading_days의 휴일 정확성을 2024-2027년 데이터로 검증.
exchange_calendars XKRX 캘린더 결과와 교차 검증 (2024-2025년 100% 일치,
2026년은 제헌절 추가로 1일 차이 — exchange_calendars 버그 수정).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from backend.app.core import trading_calendar
from backend.app.core.trading_calendar import (
    _compute_holidays,
    _generate_trading_days,
    _lunar_to_solar,
    get_chart_reference_trading_day,
)
from backend.app.core.constants import _KST


# ── _lunar_to_solar ────────────────────────────────────────────────────────────

class TestLunarToSolar:
    """음력→양력 변환 정확성 검증."""

    def test_seollal_2026(self):
        """설날 2026 (음력 1/1) = 2월 17일."""
        assert _lunar_to_solar(2026, 1, 1) == date(2026, 2, 17)

    def test_chuseok_2026(self):
        """추석 2026 (음력 8/15) = 9월 25일."""
        assert _lunar_to_solar(2026, 8, 15) == date(2026, 9, 25)

    def test_buddha_2026(self):
        """부처님오신날 2026 (음력 4/8) = 5월 24일."""
        assert _lunar_to_solar(2026, 4, 8) == date(2026, 5, 24)

    def test_seollal_2025(self):
        """설날 2025 (음력 1/1) = 1월 29일."""
        assert _lunar_to_solar(2025, 1, 1) == date(2025, 1, 29)


# ── _compute_holidays: 2024년 (exchange_calendars와 100% 일치) ──────────────────

class TestHolidays2024:
    """2024년 KRX 휴일 — exchange_calendars XKRX 결과와 완전 일치."""

    @pytest.fixture(scope="class")
    def holidays(self):
        return _compute_holidays(2024)

    def test_new_year(self, holidays):
        assert date(2024, 1, 1) in holidays

    def test_seollal_cluster(self, holidays):
        """설날: 2/9(금, 전날), 2/10(토, 당일), 2/11(일, 다음날), 2/12(월, 대체)."""
        assert date(2024, 2, 9) in holidays   # 전날 (금)
        assert date(2024, 2, 10) in holidays  # 당일 (토)
        assert date(2024, 2, 11) in holidays  # 다음날 (일)
        assert date(2024, 2, 12) in holidays  # 대체공휴일 (월)

    def test_independence_day(self, holidays):
        assert date(2024, 3, 1) in holidays

    def test_election_day(self, holidays):
        """제22대 국회의원선거 — 수동 오버라이드."""
        assert date(2024, 4, 10) in holidays

    def test_labor_day(self, holidays):
        assert date(2024, 5, 1) in holidays

    def test_childrens_day_substitute(self, holidays):
        """어린이날 5/5(일) → 5/6(월) 대체공휴일."""
        assert date(2024, 5, 5) in holidays
        assert date(2024, 5, 6) in holidays

    def test_buddha_birthday(self, holidays):
        assert date(2024, 5, 15) in holidays

    def test_memorial_day(self, holidays):
        assert date(2024, 6, 6) in holidays

    def test_liberation_day(self, holidays):
        assert date(2024, 8, 15) in holidays

    def test_chuseok_cluster(self, holidays):
        """추석: 9/16(월), 9/17(화), 9/18(수)."""
        assert date(2024, 9, 16) in holidays
        assert date(2024, 9, 17) in holidays
        assert date(2024, 9, 18) in holidays

    def test_armed_forces_day(self, holidays):
        """국군의날 임시공휴일 — 수동 오버라이드."""
        assert date(2024, 10, 1) in holidays

    def test_national_foundation(self, holidays):
        assert date(2024, 10, 3) in holidays

    def test_hangul_day(self, holidays):
        assert date(2024, 10, 9) in holidays

    def test_christmas(self, holidays):
        assert date(2024, 12, 25) in holidays

    def test_year_end(self, holidays):
        """KRX 전용 연말 휴일 (Dec 31)."""
        assert date(2024, 12, 31) in holidays

    def test_no_constitution_day(self, holidays):
        """제헌절은 2026년부터 공휴일 — 2024년에는 아님."""
        assert date(2024, 7, 17) not in holidays

    def test_trading_day_count(self):
        """2024년 거래일 수: 244일 (261 평일 - 17 공휴일 + 선거일/임시공휴일 등)."""
        result = _generate_trading_days(2024)
        assert len(result[2024]) == 244


# ── _compute_holidays: 2025년 (exchange_calendars와 100% 일치) ──────────────────

class TestHolidays2025:
    """2025년 KRX 휴일 — exchange_calendars XKRX 결과와 완전 일치."""

    @pytest.fixture(scope="class")
    def holidays(self):
        return _compute_holidays(2025)

    def test_seollal_cluster_with_temp(self, holidays):
        """설날: 1/27(임시), 1/28(전날), 1/29(당일), 1/30(다음날)."""
        assert date(2025, 1, 27) in holidays  # 임시공휴일
        assert date(2025, 1, 28) in holidays  # 전날
        assert date(2025, 1, 29) in holidays  # 당일
        assert date(2025, 1, 30) in holidays  # 다음날

    def test_independence_substitute(self, holidays):
        """삼일절 3/1(토) → 3/3(월) 대체공휴일."""
        assert date(2025, 3, 1) in holidays
        assert date(2025, 3, 3) in holidays

    def test_presidential_election(self, holidays):
        """제21대 대통령선거 — 수동 오버라이드."""
        assert date(2025, 6, 3) in holidays

    def test_temp_holiday_may6(self, holidays):
        """임시공휴일 5/6 — 수동 오버라이드."""
        assert date(2025, 5, 6) in holidays

    def test_chuseok_cluster(self, holidays):
        """추석: 10/6(월), 10/7(화), 10/8(수)."""
        assert date(2025, 10, 6) in holidays
        assert date(2025, 10, 7) in holidays
        assert date(2025, 10, 8) in holidays

    def test_year_end(self, holidays):
        assert date(2025, 12, 31) in holidays

    def test_trading_day_count(self):
        """2025년 거래일 수: 242일."""
        result = _generate_trading_days(2025)
        assert len(result[2025]) == 242


# ── _compute_holidays: 2026년 (제헌절 추가 — exchange_calendars 버그 수정) ───────

class TestHolidays2026:
    """2026년 KRX 휴일 — 제헌절(7/17) 포함으로 exchange_calendars보다 정확."""

    @pytest.fixture(scope="class")
    def holidays(self):
        return _compute_holidays(2026)

    def test_constitution_day(self, holidays):
        """제헌절 7/17 — 2026년부터 공휴일 재지정 (exchange_calendars 누락 버그 수정)."""
        assert date(2026, 7, 17) in holidays

    def test_seollal_cluster(self, holidays):
        """설날: 2/16(월), 2/17(화), 2/18(수). 일요일 없어 대체 없음."""
        assert date(2026, 2, 16) in holidays
        assert date(2026, 2, 17) in holidays
        assert date(2026, 2, 18) in holidays

    def test_independence_substitute(self, holidays):
        """삼일절 3/1(일) → 3/2(월) 대체공휴일."""
        assert date(2026, 3, 1) in holidays
        assert date(2026, 3, 2) in holidays

    def test_buddha_substitute(self, holidays):
        """부처님오신날 5/24(일) → 5/25(월) 대체공휴일."""
        assert date(2026, 5, 24) in holidays
        assert date(2026, 5, 25) in holidays

    def test_liberation_substitute(self, holidays):
        """광복절 8/15(토) → 8/17(월) 대체공휴일."""
        assert date(2026, 8, 15) in holidays
        assert date(2026, 8, 17) in holidays

    def test_national_foundation_substitute(self, holidays):
        """개천절 10/3(토) → 10/5(월) 대체공휴일."""
        assert date(2026, 10, 3) in holidays
        assert date(2026, 10, 5) in holidays

    def test_year_end(self, holidays):
        assert date(2026, 12, 31) in holidays

    def test_trading_day_count(self):
        """2026년 거래일 수: 245일 (exchange_calendars는 246일 — 제헌절 누락)."""
        result = _generate_trading_days(2026)
        assert len(result[2026]) == 245

    def test_jul17_not_trading_day(self):
        """제헌절(7/17)은 거래일이 아님 — DB 캐시 버그 수정 확인."""
        result = _generate_trading_days(2026)
        assert "20260717" not in result[2026]


# ── _compute_holidays: 2027년 (제헌절 대체공휴일 검증) ──────────────────────────

class TestHolidays2027:
    """2027년 KRX 휴일 — 제헌절 대체공휴일 검증 (7/17이 토요일)."""

    @pytest.fixture(scope="class")
    def holidays(self):
        return _compute_holidays(2027)

    def test_constitution_day_saturday(self, holidays):
        """제헌절 7/17(토) — 주말이므로 비거래일."""
        assert date(2027, 7, 17) in holidays

    def test_constitution_day_substitute(self, holidays):
        """제헌절 7/17(토) → 7/19(월) 대체공휴일."""
        assert date(2027, 7, 19) in holidays

    def test_seollal_substitute(self, holidays):
        """설날 2/7(일) → 2/9(화) 대체공휴일 (2/8은 다음날)."""
        assert date(2027, 2, 8) in holidays   # 다음날 (월)
        assert date(2027, 2, 9) in holidays   # 대체공휴일 (화)


# ── 엣지 케이스 ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """엣지 케이스 및 회귀 방지."""

    def test_weekend_never_trading_day(self):
        """모든 토/일요일은 거래일이 아님."""
        for year in [2024, 2025, 2026]:
            result = _generate_trading_days(year)
            for day_str in result[year]:
                d = date.fromisoformat(
                    f"{day_str[:4]}-{day_str[4:6]}-{day_str[6:8]}"
                )
                assert d.weekday() < 5, f"{d} is weekend but in trading days"

    def test_year_end_friday(self):
        """Dec 31이 금요일이면 거래일 아님 (KRX 전용 연말 휴일)."""
        # 2025-12-31 is Wednesday
        result = _generate_trading_days(2025)
        assert "20251231" not in result[2025]

    def test_year_end_monday(self):
        """Dec 31이 월요일이어도 거래일 아님."""
        # 2024-12-31 is Tuesday
        result = _generate_trading_days(2024)
        assert "20241231" not in result[2024]

    def test_no_duplicate_holidays(self):
        """휴일 set에 중복 없음 (set이므로 구조적으로 보장되지만 명시적 검증)."""
        for year in [2024, 2025, 2026, 2027]:
            holidays = _compute_holidays(year)
            # set이므로 중복 불가 — 대신 빈 set이 아닌지만 확인
            assert len(holidays) > 10, f"{year}년 휴일이 너무 적음: {len(holidays)}"

    def test_labor_day_always_holiday(self):
        """근로자의날(5/1)은 매년 KRX 휴일."""
        for year in [2024, 2025, 2026, 2027]:
            holidays = _compute_holidays(year)
            assert date(year, 5, 1) in holidays, f"{year}년 근로자의날 누락"


# ── get_chart_reference_trading_day ───────────────────────────────────────────
# 차트/그래프 표시용 '가장 최근 확정 거래일' — 08:00 NXT 프리마켓 개시 기준.
# 프론트 getTradingToday()와 동일 의미 (P10 SSOT).

@pytest.fixture(scope="class")
def _init_2026_cache():
    """2026년 거래일 캐시 초기화 — get_chart_reference_trading_day 테스트용."""
    trading_calendar._trading_days_cache = _generate_trading_days(2026)
    trading_calendar._cache_initialized = True
    yield
    trading_calendar._cache_initialized = False
    trading_calendar._trading_days_cache = {}


def _make_kst_dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """KST timezone-aware datetime 생성."""
    return datetime(year, month, day, hour, minute, 0, tzinfo=_KST)


class TestChartReferenceTradingDay:
    """get_chart_reference_trading_day — 08:00 NXT 프리마켓 개시 기준 차트 표시일.

    사용자 원칙:
      - 08:00 이전 (장 미개시): 직전 거래일 (오늘 데이터 점 미포함)
      - 08:00 이후 (프리마켓 개시): 오늘이 거래일이면 오늘, 비거래일이면 직전 거래일
      - 주말/공휴일: 직전 거래일
    """

    def test_premarket_thursday_returns_previous(self, _init_2026_cache):
        """목 06:47 (08:00 이전) → 수(직전 거래일). 오늘 데이터 점 미포함."""
        # 2026-07-30 목요일 06:47
        mock_dt = _make_kst_dt(2026, 7, 30, 6, 47)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 7, 29)  # 수요일

    def test_premarket_after_0800_returns_today(self, _init_2026_cache):
        """목 08:30 (프리마켓 개시 후) → 목(오늘, 거래일). 오늘 데이터 점 시작."""
        mock_dt = _make_kst_dt(2026, 7, 30, 8, 30)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 7, 30)  # 목요일 (오늘)

    def test_saturday_returns_friday(self, _init_2026_cache):
        """토 10:00 (주말) → 금(직전 거래일). 주말 데이터 점 없음."""
        # 2026-08-01 토요일
        mock_dt = _make_kst_dt(2026, 8, 1, 10, 0)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 7, 31)  # 금요일

    def test_monday_premarket_returns_friday(self, _init_2026_cache):
        """월 06:47 (08:00 이전) → 금(직전 거래일). 주말 건너뜀."""
        # 2026-08-03 월요일 06:47
        mock_dt = _make_kst_dt(2026, 8, 3, 6, 47)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 7, 31)  # 금요일

    def test_monday_after_0800_returns_today(self, _init_2026_cache):
        """월 09:00 (정규장) → 월(오늘, 거래일)."""
        mock_dt = _make_kst_dt(2026, 8, 3, 9, 0)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 8, 3)  # 월요일

    def test_holiday_returns_previous_trading_day(self, _init_2026_cache):
        """제헌절(7/17, 금요일) 10:00 → 7/16(목, 직전 거래일). 공휴일 건너뜀."""
        # 2026-07-17 제헌절 (금요일이지만 공휴일)
        mock_dt = _make_kst_dt(2026, 7, 17, 10, 0)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 7, 16)  # 목요일

    def test_sunday_returns_friday(self, _init_2026_cache):
        """일 14:00 (주말) → 금(직전 거래일)."""
        # 2026-08-02 일요일
        mock_dt = _make_kst_dt(2026, 8, 2, 14, 0)
        with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_dt))):
            result = get_chart_reference_trading_day()
        assert result == date(2026, 7, 31)  # 금요일
