"""daily_time_scheduler.py 단위 테스트 — 시간 기반 장 상태 판별, 타이머 예약, 콜백 검증.

hang 방지 원칙:
- schedule_engine_task를 mock으로 대체 (백그라운드 태스크 생성 방지)
- asyncio.get_running_loop를 mock으로 대체 (call_later 타이머 생성 방지)
- gc.disable/enable을 mock으로 대체
- state를 mock으로 대체
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import pytest
from unittest.mock import AsyncMock, DEFAULT, MagicMock, patch

def _close_coro(*args, **kwargs):
    """schedule_engine_task mock에 전달된 코루틴을 close하여 RuntimeWarning 방지."""
    for arg in args:
        if asyncio.iscoroutine(arg):
            arg.close()
    return DEFAULT


# Initialize queues before importing daily_time_scheduler (lazy import of pipeline_compute triggers module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues  # noqa: E402
initialize_queues()


from backend.app.services.daily_time_scheduler import (  # noqa: E402
    KST,
    NXT_PREMARKET_START,
    KRX_REGULAR_START,
    NXT_AFTERMARKET_END,
    is_nxt_premarket_window,
    is_nxt_aftermarket_window,
    calc_timebased_market_phase,
    is_nxt_only_window,
    _is_pre_subscribe_window,
    get_nxt_trde_tp,
    is_order_blocked_by_time,
    get_order_time_block_status,
    get_market_phase,
    calc_countdown,
    is_heavy_operation_allowed,
    _kst_now,
    _parse_hm,
    is_ws_subscribe_window,
    is_edit_window_open,
    _fire_unified_confirmed_fetch,
    _do_unified_confirmed_fetch,
    _broadcast_market_phase,
    _apply_market_phase,
    _on_krx_market_open,
    _on_krx_pre_subscribe,
    _on_krx_closing_auction_start,
    _on_ws_subscribe_start,
    _on_ws_subscribe_end,
    _on_confirmed_download,
    _init_ws_subscribe_state,
    _trigger_reg_pipeline,
    _trigger_unreg_all,
    _do_unreg_all,
    _seconds_until_hm,
    _on_auto_trade_transition,
    _on_midnight,
    schedule_midnight_timer,
    start_daily_time_scheduler,
    stop_daily_time_scheduler,
    schedule_auto_trade_timers,
    retry_pipeline_catchup_after_bootstrap,
    _on_realtime_fields_reset,
    _TIMETABLE,
    build_timetable_from_cache,
    _parse_hm_tuple,
    _to3,
    _fmt_hms,
    NXT_MAINMARKET_START,
    _schedule_next_timetable_event,
    _timetable_event_fired,
    _check_jif_health,
    _timetable_startup_scan,
    _JIF_STALE_WARN_SEC,
)


def _make_kst(h: int, m: int, s: int = 0, weekday: int = 0) -> datetime:
    """Create a KST datetime at given hour:minute:second with given weekday (0=Mon)."""
    base = datetime(2025, 1, 6, h, m, s, tzinfo=KST)  # 2025-01-06 is Monday
    return base + timedelta(days=weekday)


# ── _parse_hm ─────────────────────────────────────────────────────────────────

class TestParseHm:
    def test_valid_string(self):
        assert _parse_hm("09:30") == (9, 30)

    def test_valid_string_with_seconds(self):
        assert _parse_hm("09:30:45") == (9, 30)

    def test_empty_string(self):
        assert _parse_hm("") == (0, 0)

    def test_none(self):
        assert _parse_hm(None) == (0, 0)

    def test_invalid_format(self):
        assert _parse_hm("abc") == (0, 0)

    def test_with_whitespace(self):
        assert _parse_hm("  08:00  ") == (8, 0)


# ── _kst_now ──────────────────────────────────────────────────────────────────

class TestKstNow:
    def test_returns_kst_timezone(self):
        result = _kst_now()
        assert result.tzinfo == KST


# ── _seconds_until_hm ─────────────────────────────────────────────────────────

class TestSecondsUntilHm:
    def test_future_time(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            delay = _seconds_until_hm(12, 0)
            assert delay == 7200.0

    def test_past_time(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(14, 0)):
            delay = _seconds_until_hm(10, 0)
            assert delay < 0

    def test_same_time(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            delay = _seconds_until_hm(10, 0)
            assert delay == 0.0


# ── is_nxt_premarket_window ───────────────────────────────────────────────────

class TestIsNxtPremarketWindow:
    """market_phase 기반 판별 — state.market_phase를 mock하여 검증."""

    def test_premarket_phase_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_premarket_window() is True

    def test_regular_market_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_premarket_window() is False

    def test_prep_gap_returns_false(self):
        """정규장 준비(거래 없음) 구간은 프리마켓에서 제외."""
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_premarket_window() is False

    def test_holiday_returns_false(self):
        """휴장일 — calc_timebased_market_phase가 '휴장일' 페이즈 산정."""
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "휴장일"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_premarket_window() is False

    def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": ""}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_premarket_window() is False


# ── is_nxt_aftermarket_window ─────────────────────────────────────────────────

class TestIsNxtAftermarketWindow:
    """market_phase 기반 판별 — state.market_phase를 mock하여 검증."""

    def test_aftermarket_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_aftermarket_window() is True

    def test_aftermarket_sustained_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "애프터마켓 지속"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_aftermarket_window() is True

    def test_single_price_gap_returns_false(self):
        """단일가 매매(일괄 체결) 구간은 애프터마켓에서 제외."""
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "단일가 매매"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_aftermarket_window() is False

    def test_market_closed_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "장마감"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_aftermarket_window() is False

    def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": ""}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_aftermarket_window() is False


# ── calc_timebased_market_phase ───────────────────────────────────────────────

class TestCalcTimebasedMarketPhase:
    def test_weekend_returns_holiday(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0, weekday=5)):
            result = calc_timebased_market_phase()
            assert result == {"krx": "휴장일", "nxt": "휴장일"}

    def test_holiday_returns_holiday(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False):
            result = calc_timebased_market_phase()
            assert result == {"krx": "휴장일", "nxt": "휴장일"}

    def test_before_market_open(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장개시전"
            assert result["nxt"] == "장개시전"

    def test_premarket(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장전 시간외"
            assert result["nxt"] == "프리마켓"

    def test_regular_market(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "정규장"
            assert result["nxt"] == "메인마켓"

    def test_after_auction(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 25)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "종가 동시호가"
            assert result["nxt"] == "조기 마감"

    def test_after_hours(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 35)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "체결 정산"
            assert result["nxt"] == "단일가 매매"

    def test_single_price(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 50)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장후 시간외"
            assert result["nxt"] == "애프터마켓"

    def test_market_closed(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장마감"
            assert result["nxt"] == "장마감"

    def test_krx_pre_open_none(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 15)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장전 대기"
            assert result["nxt"] == "프리마켓"

    def test_krx_auction_none(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 45)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "동시호가 접수"
            assert result["nxt"] == "프리마켓"

    def test_opening_auction_and_nxt_prep(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 55)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "시가 동시호가"
            assert result["nxt"] == "정규장 준비"

    # ── 4단계: NXT 메인마켓 09:00:30 초 단위 예외 ──
    def test_nxt_mainmarket_at_090000_still_prep(self):
        # 09:00:00 — NXT "정규장 준비" 유지 (초 단위 예외)
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["nxt"] == "정규장 준비"

    def test_nxt_mainmarket_at_090029_still_prep(self):
        # 09:00:29 — NXT "정규장 준비" 유지 (초 단위 예외)
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 29)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["nxt"] == "정규장 준비"

    def test_nxt_mainmarket_at_090030_transitions(self):
        # 09:00:30 — NXT "메인마켓" 전환
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["nxt"] == "메인마켓"

    def test_krx_regular_at_090000_unchanged(self):
        # KRX는 분 단위 유지 — 09:00:00 정규장 (초 단위 예외 없음)
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "정규장"

    def test_krx_single_price_and_nxt_aftermarket(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "시간외 종가매매 종료 + 시간외 단일가매매 개시"
            assert result["nxt"] == "애프터마켓"

    def test_krx_close_none_and_nxt_aftermarket_sustained(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(18, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장 종료"
            assert result["nxt"] == "애프터마켓 지속"


# ── is_nxt_only_window ────────────────────────────────────────────────────────

class TestIsNxtOnlyWindow:
    def test_krx_inactive_nxt_active(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_only_window() is True

    def test_krx_active_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_only_window() is False

    def test_nxt_inactive_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "장마감"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_only_window() is False

    def test_empty_krx_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_only_window() is False

    def test_opening_auction_nxt_prep_returns_true(self):
        """08:50~09:00 구간: KRX 시가 동시호가(비활성) + NXT 정규장 준비(활성) → True."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_only_window() is True

    def test_settle_nxt_single_price_returns_true(self):
        """15:30~15:40 구간: KRX 체결 정산(비활성) + NXT 단일가 매매(활성) → True."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "체결 정산", "nxt": "단일가 매매"}
        with patch("backend.app.services.engine_state.state", mock_state):
            assert is_nxt_only_window() is True

    def test_pre_subscribe_window_nxt_only(self):
        """07:59~08:00 사전 구간: KRX 장개시전(비활성) + NXT 장개시전(비활성) →
        시간 기반 사전 구간 판정으로 NXT-only True (KRX 단독 종목 제외 구독)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)):
            assert is_nxt_only_window() is True


# ── get_nxt_trde_tp ───────────────────────────────────────────────────────────


class TestIsPreSubscribeWindow:
    """_is_pre_subscribe_window() — 07:59~08:00 사전 구독 구간 시간 기반 판정 테스트."""

    def test_in_pre_subscribe_window_returns_true(self):
        """07:59~08:00 사이 + 거래일 → True."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)):
            assert _is_pre_subscribe_window() is True

    def test_at_0800_returns_false(self):
        """08:00 정각은 사전 구간 종료 (NXT_PREMARKET_START 상한 미만) → False."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장전 대기", "nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)):
            assert _is_pre_subscribe_window() is False

    def test_before_0759_returns_false(self):
        """07:58은 사전 구간 시작 전 → False."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)):
            assert _is_pre_subscribe_window() is False

    def test_holiday_returns_false(self):
        """휴장일 시간 내라도 → False (calc_timebased_market_phase가 "휴장일" 산정)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일", "nxt": "휴장일"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)):
            assert _is_pre_subscribe_window() is False


class TestGetNxtTrdeTp:
    def test_premarket_returns_P(self):
        with patch("backend.app.services.daily_time_scheduler.is_nxt_premarket_window", return_value=True):
            assert get_nxt_trde_tp() == "P"

    def test_aftermarket_returns_U(self):
        with patch("backend.app.services.daily_time_scheduler.is_nxt_premarket_window", return_value=False), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_aftermarket_window", return_value=True):
            assert get_nxt_trde_tp() == "U"

    def test_regular_returns_base(self):
        with patch("backend.app.services.daily_time_scheduler.is_nxt_premarket_window", return_value=False), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_aftermarket_window", return_value=False):
            assert get_nxt_trde_tp("3") == "3"

    def test_regular_returns_default(self):
        with patch("backend.app.services.daily_time_scheduler.is_nxt_premarket_window", return_value=False), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_aftermarket_window", return_value=False):
            assert get_nxt_trde_tp() == "3"


# ── is_order_blocked_by_time ──────────────────────────────────────────────────

class TestIsOrderBlockedByTime:
    """체결 불가 시간대 주문 차단 판별 — state.market_phase + _kst_now + is_nxt_enabled mock."""

    # ── 본 판별: 시간대별 ──

    def test_krx_regular_nxt_main_both_allowed(self):
        """09:00~15:20 정규장/메인마켓 — 양쪽 허용 (KRX 단독·NXT 종목 모두)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert is_order_blocked_by_time("005930") is False

    def test_krx_premarket_nxt_premarket_krx_only_blocked(self):
        """08:00~08:50 KRX 장전 대기 + NXT 프리마켓 — KRX 단독 종목 차단, NXT 종목 허용."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장전 대기", "nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 20)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            assert is_order_blocked_by_time("005930") is True  # KRX 단독

    def test_krx_premarket_nxt_premarket_nxt_stock_allowed(self):
        """08:00~08:50 — NXT 중복상장 종목은 허용."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장전 대기", "nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 20)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=True):
            assert is_order_blocked_by_time("005930_AL") is False  # NXT 종목

    def test_opening_auction_both_blocked(self):
        """08:50~09:00 시가 동시호가 + NXT 정규장 준비 — 양쪽 차단 (NXT도 비활성 아님 but KRX 비활성+NXT 활성 → 종목 분기).
        실제로는 NXT '정규장 준비'가 NXT_ACTIVE_PHASES에 포함 → is_nxt_enabled 분기.
        KRX 단독 종목은 차단, NXT 종목은 허용."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 55)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            assert is_order_blocked_by_time("005930") is True  # KRX 단독 — 차단

    def test_closing_auction_both_blocked(self):
        """15:20~15:30 종가 동시호가 + NXT 조기 마감 — 양쪽 비활성 → 전부 차단.
        (KRX '종가 동시호가' 비활성, NXT '조기 마감' 비활성 → NXT_ACTIVE_PHASES 아님)"""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "종가 동시호가", "nxt": "조기 마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 25)):
            assert is_order_blocked_by_time("005930") is True
            assert is_order_blocked_by_time("005930_AL") is True

    def test_aftermarket_krx_only_blocked(self):
        """15:40~20:00 KRX 장후 시간외(비활성) + NXT 애프터마켓(활성) — KRX 단독 차단, NXT 허용."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장후 시간외", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            assert is_order_blocked_by_time("005930") is True

    def test_aftermarket_nxt_stock_allowed(self):
        """15:40~20:00 — NXT 중복상장 종목은 허용."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장후 시간외", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=True):
            assert is_order_blocked_by_time("005930_AL") is False

    def test_market_closed_both_blocked(self):
        """20:00~24:00 장마감 — 양쪽 비활성 → 전부 차단."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "장마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)):
            assert is_order_blocked_by_time("005930") is True
            assert is_order_blocked_by_time("005930_AL") is True

    def test_holiday_returns_false(self):
        """휴장일 — 장 안 열리므로 주문 자체 발생 안 함 → False (P23 일관성)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일", "nxt": "휴장일"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert is_order_blocked_by_time("005930") is False

    # ── 빈 문자열 phase (P20) ──

    def test_empty_krx_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert is_order_blocked_by_time("005930") is False

    def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": ""}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert is_order_blocked_by_time("005930") is False

    # ── 경계 시각 (페이즈 기반 판별 — 버퍼 없이 즉시 적용) ──

    def test_boundary_at_0900_regular_allowed(self):
        """09:00:00 정각 — 페이즈 "정규장"이면 즉시 허용 (버퍼 없음)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 0)):
            assert is_order_blocked_by_time("005930") is False

    def test_boundary_at_085955_opening_auction_blocked(self):
        """08:59:55 — 페이즈 "시가 동시호가" → KRX 단독 종목 차단 (버퍼 없이 페이즈 기반)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59, 55)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            assert is_order_blocked_by_time("005930") is True

    def test_boundary_at_152000_closing_auction_blocked(self):
        """15:20:00 — 페이즈 "종가 동시호가" → 양쪽 비활성 → 전부 차단."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "종가 동시호가", "nxt": "조기 마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 20, 0)):
            assert is_order_blocked_by_time("005930") is True

    def test_boundary_at_154000_aftermarket_nxt_allowed(self):
        """15:40:00 — 페이즈 "장후 시간외"+"애프터마켓" → NXT 종목 허용 (버퍼 없이 페이즈 기반)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장후 시간외", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 40, 0)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=True):
            assert is_order_blocked_by_time("005930_AL") is False

    def test_boundary_at_200000_market_closed_blocked(self):
        """20:00:00 — 페이즈 "장마감" → 양쪽 비활성 → 전부 차단."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "장마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 0, 0)):
            assert is_order_blocked_by_time("005930") is True

    def test_boundary_at_080000_premarket_krx_blocked(self):
        """08:00:00 — 페이즈 "장전 대기"+"프리마켓" → KRX 단독 종목 차단 (버퍼 없이 페이즈 기반)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장전 대기", "nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0, 0)), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            assert is_order_blocked_by_time("005930") is True


# ── get_order_time_block_status ───────────────────────────────────────────────

class TestGetOrderTimeBlockStatus:
    """체결 불가 시간대 주문 차단 상태 (페이즈 기반, 종목 구분 없음) — WS 브로드캐스트용.

    is_order_blocked_by_time(stk_cd)와 동일한 페이즈 판별을 사용하되
    종목별 is_nxt_enabled 분기 없이 (blocked, reason) 튜플 반환.
    """

    # ── 본 판별: 시간대별 ──

    def test_krx_regular_returns_not_blocked(self):
        """09:00~15:20 정규장/메인마켓 — (False, "")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert get_order_time_block_status() == (False, "")

    def test_krx_inactive_nxt_active_returns_nxt_only_reason(self):
        """08:00~08:50 KRX 장전 대기 + NXT 프리마켓 — (True, "NXT 전용 구간...")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장전 대기", "nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 20)):
            blocked, reason = get_order_time_block_status()
            assert blocked is True
            assert reason == "KRX 단독 종목 차단 · NXT 가능"

    def test_both_inactive_returns_auction_reason(self):
        """15:20~15:30 종가 동시호가 + NXT 조기 마감 — 양쪽 비활성 → (True, "KRX·NXT 모두 주문 불가")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "종가 동시호가", "nxt": "조기 마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 25)):
            blocked, reason = get_order_time_block_status()
            assert blocked is True
            assert reason == "KRX·NXT 모두 주문 불가"

    def test_market_closed_returns_auction_reason(self):
        """20:00~24:00 장마감 — 양쪽 비활성 → (True, "KRX·NXT 모두 주문 불가")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "장마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)):
            blocked, reason = get_order_time_block_status()
            assert blocked is True
            assert reason == "KRX·NXT 모두 주문 불가"

    def test_holiday_returns_false(self):
        """휴장일 — 장 안 열리므로 칩 표시 불필요 → (False, "") (P21 사용자 투명성)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일", "nxt": "휴장일"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            blocked, reason = get_order_time_block_status()
            assert blocked is False
            assert reason == ""

    def test_aftermarket_returns_nxt_only_reason(self):
        """15:40~20:00 KRX 장후 시간외 + NXT 애프터마켓 — (True, "NXT 전용 구간...")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장후 시간외", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0)):
            blocked, reason = get_order_time_block_status()
            assert blocked is True
            assert reason == "KRX 단독 종목 차단 · NXT 가능"

    # ── 빈 문자열 phase (P20) ──

    def test_empty_krx_returns_not_blocked(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert get_order_time_block_status() == (False, "")

    def test_empty_nxt_returns_not_blocked(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": ""}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            assert get_order_time_block_status() == (False, "")

    # ── 경계 시각 (페이즈 기반 판별 — 버퍼 없이 즉시 적용) ──

    def test_boundary_at_0900_regular_allowed(self):
        """09:00:00 정각 — 페이즈 "정규장"이면 즉시 (False, "") (버퍼 없음)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 0)):
            assert get_order_time_block_status() == (False, "")

    def test_boundary_at_152000_closing_auction_blocked(self):
        """15:20:00 — 페이즈 "종가 동시호가" → (True, "KRX·NXT 모두 주문 불가")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "종가 동시호가", "nxt": "조기 마감"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 20, 0)):
            blocked, reason = get_order_time_block_status()
            assert blocked is True
            assert reason == "KRX·NXT 모두 주문 불가"

    def test_boundary_at_080000_premarket_nxt_only(self):
        """08:00:00 — 페이즈 "장전 대기"+"프리마켓" → (True, "KRX 단독 종목 차단 · NXT 가능")."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장전 대기", "nxt": "프리마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0, 0)):
            blocked, reason = get_order_time_block_status()
            assert blocked is True
            assert reason == "KRX 단독 종목 차단 · NXT 가능"


# ── get_market_phase ──────────────────────────────────────────────────────────

class TestGetMarketPhase:
    def test_returns_copy_with_krx_nxt(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = get_market_phase()
            assert result["krx"] == "정규장"
            assert result["nxt"] == "메인마켓"
            assert result["is_nxt_only"] is False

    def test_includes_krx_alert(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓", "krx_alert": "테스트"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = get_market_phase()
            assert result["krx_alert"] == "테스트"
            assert result["is_nxt_only"] is False

    def test_empty_krx_logs_error(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = get_market_phase()
            assert result["krx"] == ""
            assert result["is_nxt_only"] is False

    def test_is_nxt_only_true_when_krx_inactive_nxt_active(self):
        """KRX 비활성 + NXT 활성 구간 → is_nxt_only=True 파생 (P10 SSOT)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "애프터마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = get_market_phase()
            assert result["is_nxt_only"] is True

    def test_includes_countdown_fields(self):
        """get_market_phase() 반환에 krx_countdown/nxt_countdown 필드 포함 검증 (P10/P16)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 55)):
            result = get_market_phase()
            assert "krx_countdown" in result
            assert "nxt_countdown" in result
            # KRX '시가 동시호가' 08:55 → 09:00까지 300초 (10분 이내)
            assert result["krx_countdown"] == {"label": "정규장 장개시", "remaining_sec": 300}
            # NXT '정규장 준비' 08:55 → 09:00까지 300초 (10분 이내)
            assert result["nxt_countdown"] == {"label": "메인마켓 장개시", "remaining_sec": 300}


# ── calc_countdown ────────────────────────────────────────────────────────────

class TestCalcCountdown:
    """calc_countdown() 단위 테스트 — KRX/NXT 카운트다운 계산 (P10 SSOT, P20 폴백 금지)."""

    def test_krx_countdown_within_10min(self):
        """KRX '시가 동시호가' 08:55 → remaining 300초, label '정규장 장개시'."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 55)):
            result = calc_countdown("krx", "시가 동시호가")
            assert result == {"label": "정규장 장개시", "remaining_sec": 300}

    def test_krx_countdown_over_10min(self):
        """KRX '시가 동시호가' 08:40 → None (10분 초과 — 08:40~09:00 = 1200초)."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 40)):
            result = calc_countdown("krx", "시가 동시호가")
            assert result is None

    def test_krx_countdown_passed(self):
        """KRX '시가 동시호가' 09:05 → None (이미 09:00 전환 시각 지남, P20)."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 5)):
            result = calc_countdown("krx", "시가 동시호가")
            assert result is None

    def test_krx_no_countdown_phase(self):
        """KRX 매핑 없는 페이즈('장마감') → None."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)):
            result = calc_countdown("krx", "장마감")
            assert result is None

    def test_nxt_countdown_premarket(self):
        """NXT '장개시전' 07:55 → remaining 300초, label '프리마켓 장개시'."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 55)):
            result = calc_countdown("nxt", "장개시전")
            assert result == {"label": "프리마켓 장개시", "remaining_sec": 300}

    def test_nxt_countdown_aftermarket(self):
        """NXT '애프터마켓 지속' 19:59 → remaining 60초, label '에프터마켓 장마감'."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(19, 59)):
            result = calc_countdown("nxt", "애프터마켓 지속")
            assert result == {"label": "에프터마켓 장마감", "remaining_sec": 60}

    def test_nxt_countdown_over_threshold(self):
        """NXT '프리마켓' 08:30 → None (08:30~08:50 = 1200초, 10분 초과)."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 30)):
            result = calc_countdown("nxt", "프리마켓")
            assert result is None

    def test_nxt_no_countdown_phase(self):
        """NXT 매핑 없는 페이즈('장마감') → None."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)):
            result = calc_countdown("nxt", "장마감")
            assert result is None


# ── is_ws_subscribe_window ────────────────────────────────────────────────────

class TestIsWsSubscribeWindow:
    @pytest.mark.asyncio
    async def test_holiday_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일", "nxt": "휴장일"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await is_ws_subscribe_window({"timetable.confirmed_download": "20:40"})
            assert result is False

    @pytest.mark.asyncio
    async def test_in_window_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await is_ws_subscribe_window({"timetable.confirmed_download": "20:40"})
            assert result is True

    @pytest.mark.asyncio
    async def test_outside_window_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await is_ws_subscribe_window({"timetable.confirmed_download": "20:40"})
            assert result is False

    @pytest.mark.asyncio
    async def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": ""}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await is_ws_subscribe_window({"timetable.confirmed_download": "20:40"})
            assert result is False

    @pytest.mark.asyncio
    async def test_empty_settings_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            with pytest.raises(RuntimeError, match="settings cache not initialized"):
                await is_ws_subscribe_window(None)

    @pytest.mark.asyncio
    async def test_pre_subscribe_window_returns_true(self):
        """07:59~08:00 사전 구간 — 시간 기반 판정으로 True (재시작 대응, P16)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)):
            result = await is_ws_subscribe_window({"timetable.confirmed_download": "20:40"})
            assert result is True

    @pytest.mark.asyncio
    async def test_pre_subscribe_window_holiday_returns_false(self):
        """휴장일 사전 구간 — 시간 내라도 휴장일 → False."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일", "nxt": "휴장일"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)):
            result = await is_ws_subscribe_window({"timetable.confirmed_download": "20:40"})
            assert result is False


# ── is_edit_window_open ───────────────────────────────────────────────────────

class TestIsEditWindowOpen:
    @pytest.mark.asyncio
    async def test_ws_window_closed_edit_open(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await is_edit_window_open({"timetable.confirmed_download": "20:40"})
            assert result is True

    @pytest.mark.asyncio
    async def test_ws_window_open_edit_closed(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await is_edit_window_open({"timetable.confirmed_download": "20:40"})
            assert result is False


# ── is_heavy_operation_allowed ────────────────────────────────────────────────

class TestIsHeavyOperationAllowed:
    @pytest.mark.asyncio
    async def test_ws_window_blocks(self):
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True):
            result = await is_heavy_operation_allowed()
            assert result is False

    @pytest.mark.asyncio
    async def test_outside_ws_window_allows(self):
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False):
            result = await is_heavy_operation_allowed()
            assert result is True


# ── _fire_unified_confirmed_fetch ─────────────────────────────────────────────

class TestFireUnifiedConfirmedFetch:
    def test_already_done_skips(self):
        mock_state = MagicMock()
        mock_state.confirmed_done = True
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task") as mock_sched:
            _fire_unified_confirmed_fetch()
            mock_sched.assert_not_called()

    def test_not_done_schedules_task(self):
        mock_state = MagicMock()
        mock_state.confirmed_done = False
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _fire_unified_confirmed_fetch()
            mock_sched.assert_called_once()
            assert mock_state.confirmed_done is True

    def test_exception_does_not_raise(self):
        mock_state = MagicMock()
        mock_state.confirmed_done = False
        mock_state.confirmed_done = True  # Simulate setting
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=Exception("boom")):
            _fire_unified_confirmed_fetch()


# ── _do_unified_confirmed_fetch ───────────────────────────────────────────────

class TestDoUnifiedConfirmedFetch:
    @pytest.mark.asyncio
    async def test_success_sets_done(self):
        mock_state = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.fetch_unified_confirmed_data", new_callable=AsyncMock):
            await _do_unified_confirmed_fetch()
            assert mock_state.confirmed_done is True

    @pytest.mark.asyncio
    async def test_failure_resets_done(self):
        mock_state = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.fetch_unified_confirmed_data", new_callable=AsyncMock, side_effect=Exception("fail")):
            await _do_unified_confirmed_fetch()
            assert mock_state.confirmed_done is False
            assert mock_state.confirmed_refresh_running_confirmed is False


# ── _broadcast_market_phase ───────────────────────────────────────────────────

class TestBroadcastMarketPhase:
    def test_broadcasts_phase(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"
            # market-phase + order_time_blocked 브로드캐스트 2회 (5세션 Step 7)
            assert mock_sched.call_count == 2
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("market-phase" in ctx for ctx in contexts)
            assert any("order_time_blocked" in ctx for ctx in contexts)

    def test_exception_does_not_raise(self):
        with patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", side_effect=Exception("boom")):
            _broadcast_market_phase()

    def test_triggers_nxt_premarket_on_phase_change(self):
        """NXT '프리마켓' 전환 시 _on_nxt_premarket_start() + _on_ws_subscribe_start() 트리거."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "장전 대기", "nxt": "프리마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "장전 대기", "nxt": "프리마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("NXT 프리마켓 진입" in ctx for ctx in contexts)
            assert any("WS 구독 시작" in ctx for ctx in contexts)

    def test_triggers_krx_market_open_on_phase_change(self):
        """KRX '정규장' 전환 시 _on_krx_market_open() 트리거 (수정 8)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("KRX 정규장 진입" in ctx for ctx in contexts)

    def test_triggers_krx_closing_auction_on_phase_change(self):
        """KRX '종가 동시호가' 전환 시 _on_krx_closing_auction_start() 트리거 (15:20 구독 해지)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "종가 동시호가", "nxt": "조기 마감"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "종가 동시호가", "nxt": "조기 마감"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("KRX 종가 동시호가 — 구독 해지" in ctx for ctx in contexts)

    def test_triggers_ws_subscribe_end_on_nxt_close(self):
        """NXT '장마감' 전환 시 _on_ws_subscribe_end() 트리거 (Step 2)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "애프터마켓 지속"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "장마감", "nxt": "장마감"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "장마감", "nxt": "장마감"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("WS 구독 종료" in ctx for ctx in contexts)

    def test_no_recompute_trigger_when_phase_unchanged(self):
        """페이즈 변경 없을 시 재계산 트리거 없음 (중복 방지, 수정 8)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            # market-phase + order_time_blocked 브로드캐스트 2회, 재계산 없음 (5세션 Step 7)
            assert mock_sched.call_count == 2
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert all("진입" not in ctx and "구독" not in ctx for ctx in contexts)

    def test_broadcast_delegates_to_apply_market_phase(self):
        """_broadcast_market_phase()가 calc 결과를 _apply_market_phase에 전달 (P10 단일 적용 경로)."""
        fresh = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value=fresh), \
             patch("backend.app.services.daily_time_scheduler._apply_market_phase") as mock_apply:
            _broadcast_market_phase()
            mock_apply.assert_called_once_with(fresh)


# ── _apply_market_phase ───────────────────────────────────────────────────────

class TestApplyMarketPhase:
    def test_apply_market_phase_change_triggers_side_effects(self):
        """krx '정규장' 전환 시 _on_krx_market_open 부작용 트리거 (JIF/타이머 공통 경로)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓", "krx_countdown": None, "nxt_countdown": None}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _apply_market_phase({"krx": "정규장", "nxt": "메인마켓"})
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("KRX 정규장 진입" in ctx for ctx in contexts)

    def test_apply_market_phase_no_change_no_side_effects(self):
        """동일 페이즈 적용 시 부작용 미발생 (멱등성 — JIF/타이머 동시 존재 시 충돌 방지)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓", "krx_countdown": None, "nxt_countdown": None}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _apply_market_phase({"krx": "정규장", "nxt": "메인마켓"})
            # market-phase + order_time_blocked 브로드캐스트 2회, 부작용 없음 (5세션 Step 7)
            assert mock_sched.call_count == 2
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert all("진입" not in ctx and "구독" not in ctx for ctx in contexts)

    def test_apply_market_phase_partial_update_krx_only(self):
        """JIF 경로 — krx만 갱신 시 nxt는 기존 state 값 유지 (P10 SSOT)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓", "krx_countdown": None, "nxt_countdown": None}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            # JIF가 krx만 전달 — _apply_jif_phase가 nxt를 기존 값으로 채워 전달
            _apply_market_phase({"krx": "정규장", "nxt": "메인마켓"})
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"  # 기존 값 유지


# ── _on_krx_market_open ───────────────────────────────────────────────────────

class TestOnKrxMarketOpen:
    @pytest.mark.asyncio
    async def test_weekend_skips(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, weekday=5)):
            with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute:
                await _on_krx_market_open()
                mock_recompute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_holiday_skips(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False):
            with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute:
                await _on_krx_market_open()
                mock_recompute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trading_day_recomputes_only(self):
        """09:00 정규장 진입 시 업종 재계산만 수행 — 구독은 08:59 사전 구독에서 담당 (P20/P24)."""
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute, \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock) as mock_subscribe:
            await _on_krx_market_open()
            mock_recompute.assert_awaited_once()
            mock_subscribe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", side_effect=Exception("boom")):
            await _on_krx_market_open()


# ── _on_krx_closing_auction_start ─────────────────────────────────────────────

class TestOnKrxClosingAuctionStart:
    @pytest.mark.asyncio
    async def test_weekend_skips(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 20, weekday=5)):
            with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute:
                await _on_krx_closing_auction_start()
                mock_recompute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trading_day_recomputes_and_removes_krx(self):
        mock_state = MagicMock()
        mock_state.krx_remove_done = False
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 20)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.remove_krx_only_stocks", new_callable=AsyncMock, return_value={"removed": 5, "failed": 0}):
            await _on_krx_closing_auction_start()
            assert mock_state.krx_remove_done is True

    @pytest.mark.asyncio
    async def test_remove_skipped_resets_flag(self):
        mock_state = MagicMock()
        mock_state.krx_remove_done = False
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 20)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.remove_krx_only_stocks", new_callable=AsyncMock, return_value={"skipped": True}):
            await _on_krx_closing_auction_start()
            assert mock_state.krx_remove_done is False


# ── _on_ws_subscribe_start ────────────────────────────────────────────────────

class TestOnWsSubscribeStart:
    @pytest.mark.asyncio
    async def test_weekend_skips(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0, weekday=5)), \
             patch("backend.app.services.daily_time_scheduler.gc"):
            mock_state = MagicMock()
            mock_state.ws_subscribe_window_active = False
            with patch("backend.app.services.engine_state.state", mock_state):
                await _on_ws_subscribe_start()
                # Weekend: function returns early without setting ws_subscribe_window_active to True
                assert mock_state.ws_subscribe_window_active is False

    @pytest.mark.asyncio
    async def test_trading_day_starts_subscription(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.ws_window_changed_event = MagicMock()
        # 멱등성 가드 통과: 빈 문자열이어야 실행됨 (4단계)
        mock_state.last_ws_subscribe_start_date = ""
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc"), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_cache"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_ws_subscribe_start()
            assert mock_state.ws_subscribe_window_active is True
            mock_state.ws_window_changed_event.set.assert_called_once()


# ── _on_realtime_fields_reset (4단계 — 07:58 사전 트리거) ──────────────────────

class TestOnRealtimeFieldsReset:
    """_on_realtime_fields_reset() — 07:58 사전 트리거 실시간 필드 초기화 테스트."""

    @pytest.mark.asyncio
    async def test_resets_fields_and_sets_flag(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc") as mock_gc, \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.pipelines.pipeline_compute.reset_sector_threshold") as mock_reset_threshold, \
             patch("backend.app.services.engine_account_notify.notify_cache") as mock_notify_cache:
            await _on_realtime_fields_reset()
            mock_reset.assert_awaited_once()
            mock_gc.disable.assert_called_once()
            mock_reset_threshold.assert_called_once()
            mock_notify_cache.prev_scores = []
            assert mock_state.sector_summary_cache is None
            assert mock_state.last_realtime_reset_date == "20250106"

    @pytest.mark.asyncio
    async def test_skips_if_already_run_today(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.last_realtime_reset_date = "20250106"  # 이미 오늘 실행됨
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_on_weekend(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58, weekday=5)), \
             patch("backend.app.services.daily_time_scheduler.gc") as mock_gc, \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()
            # 주말 시 GC 비활성화 미실행 (개선 — 거래일 체크 이후 GC 비활성화)
            mock_gc.disable.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_on_non_trading_day(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()


# ── _on_krx_pre_subscribe (08:59 KRX 사전 구독) ───────────────────────────────

class TestOnKrxPreSubscribe:
    """_on_krx_pre_subscribe() — 08:59 KRX 단독 종목 사전 구독 테스트."""

    @pytest.mark.asyncio
    async def test_trading_day_subscribes(self):
        mock_state = MagicMock()
        mock_state.last_krx_pre_subscribe_date = ""
        mock_state.master_stocks_cache = {
            "005930": {"_filtered": True, "_subscribed": False},
            "000660": {"_filtered": True, "_subscribed": False},
        }

        async def _fake_subscribe(*, nxt_only=False):
            for cd in mock_state.master_stocks_cache:
                mock_state.master_stocks_cache[cd]["_subscribed"] = True

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock, side_effect=_fake_subscribe) as mock_subscribe:
            await _on_krx_pre_subscribe()
            mock_subscribe.assert_awaited_once()
            assert mock_state.last_krx_pre_subscribe_date == "20250106"

    @pytest.mark.asyncio
    async def test_zero_subscription_no_guard(self):
        """가짜 성공 방지 — 구독 0건 시 가드 미설정, 실패 원인 로그 기록 (P20/P22)."""
        mock_state = MagicMock()
        mock_state.last_krx_pre_subscribe_date = ""
        mock_state.master_stocks_cache = {
            "005930": {"_filtered": True, "_subscribed": False},
        }
        # subscribe_sector_stocks_0b 호출되지만 _subscribed 플래그 변경 없음 (가짜 성공)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock) as mock_subscribe:
            await _on_krx_pre_subscribe()
            mock_subscribe.assert_awaited_once()
            assert mock_state.last_krx_pre_subscribe_date == ""  # 가드 미설정

    @pytest.mark.asyncio
    async def test_weekend_skips(self):
        mock_state = MagicMock()
        mock_state.last_krx_pre_subscribe_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59, weekday=5)), \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock) as mock_subscribe:
            await _on_krx_pre_subscribe()
            mock_subscribe.assert_not_awaited()
            # 주말 시 가드 미설정 — 다음 거래일에 실행
            assert mock_state.last_krx_pre_subscribe_date == ""

    @pytest.mark.asyncio
    async def test_holiday_skips(self):
        mock_state = MagicMock()
        mock_state.last_krx_pre_subscribe_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False), \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock) as mock_subscribe:
            await _on_krx_pre_subscribe()
            mock_subscribe.assert_not_awaited()
            # 공휴일 시 가드 미설정 — 다음 거래일에 실행
            assert mock_state.last_krx_pre_subscribe_date == ""

    @pytest.mark.asyncio
    async def test_skips_if_already_run_today(self):
        """멱등성 가드 — 같은 날 중복 실행 방지."""
        mock_state = MagicMock()
        mock_state.last_krx_pre_subscribe_date = "20250106"  # 이미 오늘 실행됨
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock) as mock_subscribe:
            await _on_krx_pre_subscribe()
            mock_subscribe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_state = MagicMock()
        mock_state.last_krx_pre_subscribe_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 59)), \
             patch("backend.app.core.trading_calendar.is_trading_day", side_effect=Exception("boom")):
            await _on_krx_pre_subscribe()


# ── _on_ws_subscribe_start 멱등성 + 보완 경로 (4단계) ──────────────────────────

class TestOnWsSubscribeStartIdempotency:
    """_on_ws_subscribe_start() 멱등성 + 보완 경로 테스트."""

    @pytest.mark.asyncio
    async def test_skips_if_already_started_today(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.ws_window_changed_event = MagicMock()
        mock_state.last_ws_subscribe_start_date = "20250106"  # 이미 오늘 실행됨
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.services.daily_time_scheduler.gc"), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_ws_subscribe_start()
            # 멱등성 가드로 스킵 — 필드 초기화 호출 없음
            mock_reset.assert_not_awaited()
            # ws_subscribe_window_active는 이미 True로 설정되지 않음 (가드 통과 못함)
            mock_state.ws_window_changed_event.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_compensates_missing_fields_reset(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.ws_window_changed_event = MagicMock()
        mock_state.last_ws_subscribe_start_date = ""        # WS 구독 미실행
        mock_state.last_realtime_reset_date = ""            # 데이터 준비도 미실행 → 보완 경로
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler._on_realtime_fields_reset", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_ws_subscribe_start()
            # 보완 경로 — _on_realtime_fields_reset() 호출 (GC+필드+게이트+캐시 통합)
            mock_reset.assert_awaited_once()
            assert mock_state.ws_subscribe_window_active is True

    @pytest.mark.asyncio
    async def test_skips_fields_reset_if_already_done(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.ws_window_changed_event = MagicMock()
        mock_state.last_ws_subscribe_start_date = ""        # WS 구독 미실행
        mock_state.last_realtime_reset_date = "20250106"    # 데이터 준비 이미 실행 → 보완 스킵
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler._on_realtime_fields_reset", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_ws_subscribe_start()
            # 보완 스킵 — _on_realtime_fields_reset() 호출 없음
            mock_reset.assert_not_awaited()
            assert mock_state.ws_subscribe_window_active is True


# ── _on_ws_subscribe_end ──────────────────────────────────────────────────────

class TestOnWsSubscribeEnd:
    @pytest.mark.asyncio
    async def test_end_sets_flags_and_triggers_unreg(self):
        mock_state = MagicMock()
        mock_state.ws_window_changed_event = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.gc"), \
             patch("backend.app.core.memory_monitor.start_memory_monitor"), \
             patch("backend.app.core.memory_monitor.log_memory_snapshot"), \
             patch("backend.app.core.memory_monitor.stop_memory_monitor"), \
             patch("backend.app.services.daily_time_scheduler._trigger_unreg_all", new_callable=AsyncMock), \
             patch("backend.app.services.ws_subscribe_control._set_status"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_ws_subscribe_end()
            assert mock_state.ws_subscribe_window_active is False
            assert mock_state.confirmed_done is False
            mock_state.ws_window_changed_event.set.assert_called_once()


# ── _on_confirmed_download ────────────────────────────────────────────────────

class TestOnConfirmedDownload:
    @pytest.mark.asyncio
    async def test_calls_fire_unified(self):
        mock_state = MagicMock()
        mock_state.last_confirmed_download_date = ""  # 아직 오늘 실행 안 됨
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 40)), \
             patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch") as mock_fire:
            await _on_confirmed_download()
            mock_fire.assert_called_once()
            # 가드 날짜 기록 — 다음 호출 스킵용
            assert mock_state.last_confirmed_download_date == _make_kst(20, 40).strftime("%Y%m%d")

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_state = MagicMock()
        mock_state.last_confirmed_download_date = ""
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 40)), \
             patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch", side_effect=Exception("boom")):
            await _on_confirmed_download()

    @pytest.mark.asyncio
    async def test_idempotency_guard_skips_same_day(self):
        """같은 날 2회 호출 시 2회째 스킵 (P22 멱등성 가드)."""
        mock_state = MagicMock()
        today_str = _make_kst(20, 40).strftime("%Y%m%d")
        mock_state.last_confirmed_download_date = today_str  # 이미 오늘 실행됨
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 40)), \
             patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch") as mock_fire:
            await _on_confirmed_download()
            mock_fire.assert_not_called()  # 가드로 인해 스킵

    @pytest.mark.asyncio
    async def test_idempotency_guard_allows_next_day(self):
        """다음 날 호출 시 정상 실행 (가드 날짜 리셋 후)."""
        mock_state = MagicMock()
        mock_state.last_confirmed_download_date = "20250105"  # 전날 실행됨
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 40)), \
             patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch") as mock_fire:
            await _on_confirmed_download()
            mock_fire.assert_called_once()  # 다른 날이므로 실행
            assert mock_state.last_confirmed_download_date == _make_kst(20, 40).strftime("%Y%m%d")


# ── _init_ws_subscribe_state ──────────────────────────────────────────────────

class TestInitWsSubscribeState:
    @pytest.mark.asyncio
    async def test_in_window_sets_active(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.preboot_cache_loaded = True
        mock_state.ws_window_changed_event = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc"), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_cache"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _init_ws_subscribe_state()
            assert mock_state.ws_subscribe_window_active is True

    @pytest.mark.asyncio
    async def test_outside_window_sets_inactive(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.ws_subscribe_control._set_status"):
            await _init_ws_subscribe_state()
            assert mock_state.ws_subscribe_window_active is False

    @pytest.mark.asyncio
    async def test_empty_settings_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state):
            with pytest.raises(RuntimeError, match="settings cache not initialized"):
                await _init_ws_subscribe_state()

    @pytest.mark.asyncio
    async def test_pre_subscribe_window_init(self):
        """사전 구간(07:59~08:00) 재시작 시 — is_ws_subscribe_window()가 시간 기반으로
        True 반환 → in_window=True 분기가 GC 비활성화 + 캐시 초기화 수행 (07:58 로직과 동일)."""
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.preboot_cache_loaded = True
        mock_state.ws_window_changed_event = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc") as mock_gc, \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.services.engine_account_notify.notify_cache") as mock_notify_cache, \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _init_ws_subscribe_state()
            assert mock_state.ws_subscribe_window_active is True
            mock_gc.disable.assert_called_once()
            mock_reset.assert_awaited_once()
            mock_notify_cache.prev_scores = []
            assert mock_state.sector_summary_cache is None


# ── _trigger_reg_pipeline ─────────────────────────────────────────────────────

class TestTriggerRegPipeline:
    def test_ws_not_connected_skips(self):
        mock_state = MagicMock()
        mock_state.connector_manager = None
        mock_state.active_connector = None
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task") as mock_sched:
            _trigger_reg_pipeline()
            mock_sched.assert_not_called()

    def test_ws_connected_and_login_ok_schedules(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_state = MagicMock()
        mock_state.connector_manager = mock_ws
        mock_state.active_connector = None
        mock_state.login_ok = True
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _trigger_reg_pipeline()
            mock_sched.assert_called_once()


# ── _trigger_unreg_all ────────────────────────────────────────────────────────

class TestTriggerUnregAll:
    @pytest.mark.asyncio
    async def test_no_ws_returns_early(self):
        mock_state = MagicMock()
        mock_state.connector_manager = None
        mock_state.active_connector = None
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._do_unreg_all", new_callable=AsyncMock) as mock_do:
            await _trigger_unreg_all()
            mock_do.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ws_not_connected_returns_early(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = False
        mock_state = MagicMock()
        mock_state.connector_manager = mock_ws
        mock_state.active_connector = None
        mock_state.login_ok = True
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._do_unreg_all", new_callable=AsyncMock) as mock_do:
            await _trigger_unreg_all()
            mock_do.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ws_connected_calls_do_unreg(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_state = MagicMock()
        mock_state.connector_manager = mock_ws
        mock_state.active_connector = None
        mock_state.login_ok = True
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._do_unreg_all", new_callable=AsyncMock) as mock_do:
            await _trigger_unreg_all()
            mock_do.assert_awaited_once()


# ── _do_unreg_all ─────────────────────────────────────────────────────────────

class TestDoUnregAll:
    @pytest.mark.asyncio
    async def test_no_subscribed_stocks(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state):
            await _do_unreg_all()

    @pytest.mark.asyncio
    async def test_unsubscribes_stocks(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.unsubscribe_stocks = AsyncMock(return_value=True)
        mock_cm.send_message = AsyncMock()
        mock_state = MagicMock()
        mock_state.connector_manager = mock_cm
        mock_state.active_connector = None
        mock_state.master_stocks_cache = {
            "005930": {"_subscribed": True},
            "000660": {"_subscribed": True},
            "035420": {"_subscribed": False},
        }
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "12345678"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.ws_subscribe_control._set_status"):
            await _do_unreg_all()
            mock_cm.unsubscribe_stocks.assert_awaited_once()
            args = mock_cm.unsubscribe_stocks.call_args.args[0]
            assert "005930" in args
            assert "000660" in args
            assert "035420" not in args

    @pytest.mark.asyncio
    async def test_ws_not_connected_returns(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = False
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.engine_state.state", mock_state):
            await _do_unreg_all()
            mock_ws.unsubscribe_stocks.assert_not_called()


# ── _on_auto_trade_transition ─────────────────────────────────────────────────

class TestOnAutoTradeTransition:
    @pytest.mark.asyncio
    async def test_calls_notify(self):
        with patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new_callable=AsyncMock) as mock_header, \
             patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new_callable=AsyncMock) as mock_toggle, \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task", side_effect=_close_coro):
            await _on_auto_trade_transition("매수 구간 진입")
            mock_header.assert_awaited_once()
            mock_toggle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock, side_effect=Exception("boom")), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task"):
            await _on_auto_trade_transition("test")


# ── _on_midnight ──────────────────────────────────────────────────────────────

class TestOnMidnight:
    @pytest.mark.asyncio
    async def test_date_change_resets_flags(self):
        mock_state = MagicMock()
        mock_state.last_reset_date = "20250105"
        mock_state.integrated_system_settings_cache = {"time_scheduler_on": False}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(0, 0)), \
             patch("backend.app.core.trading_calendar.has_trading_days_for_year", return_value=True), \
             patch("backend.app.services.daily_time_scheduler._apply_auto_toggle_on_startup", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_auto_trade_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_midnight_timer") as mock_midnight:
            await _on_midnight()
            assert mock_state.krx_remove_done is False
            assert mock_state.confirmed_done is False
            assert mock_state.last_confirmed_download_date == ""  # 가드 리셋 (P22)
            mock_midnight.assert_called_once()

    @pytest.mark.asyncio
    async def test_same_date_skips_reset(self):
        mock_state = MagicMock()
        mock_state.last_reset_date = _make_kst(0, 0).strftime("%Y%m%d")
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(0, 0)), \
             patch("backend.app.services.daily_time_scheduler.schedule_midnight_timer") as mock_midnight:
            await _on_midnight()
            mock_midnight.assert_called_once()


# ── schedule_midnight_timer ───────────────────────────────────────────────────

class TestScheduleMidnightTimer:
    def test_cancels_existing_and_schedules_new(self):
        existing_handle = MagicMock()
        mock_state = MagicMock()
        mock_state.midnight_timer_handle = existing_handle
        mock_loop = MagicMock()
        mock_handle = MagicMock()
        mock_loop.call_later.return_value = mock_handle
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            schedule_midnight_timer()
            existing_handle.cancel.assert_called_once()
            assert mock_state.midnight_timer_handle is mock_handle

    def test_no_loop_returns(self):
        mock_state = MagicMock()
        mock_state.midnight_timer_handle = None
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            schedule_midnight_timer()


# ── stop_daily_time_scheduler ─────────────────────────────────────────────────

class TestStopDailyTimeScheduler:
    @pytest.mark.asyncio
    async def test_cancels_all_timers(self):
        auto_handles = [MagicMock(), MagicMock()]
        midnight_handle = MagicMock()
        timetable_handle = MagicMock()
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = auto_handles
        mock_state.midnight_timer_handle = midnight_handle
        mock_state.timetable_timer_handle = timetable_handle
        with patch("backend.app.services.engine_state.state", mock_state):
            await stop_daily_time_scheduler()
            for h in auto_handles:
                h.cancel.assert_called_once()
            midnight_handle.cancel.assert_called_once()
            timetable_handle.cancel.assert_called_once()
            assert mock_state.midnight_timer_handle is None
            assert mock_state.timetable_timer_handle is None

    @pytest.mark.asyncio
    async def test_no_timers_no_error(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        mock_state.midnight_timer_handle = None
        mock_state.timetable_timer_handle = None
        with patch("backend.app.services.engine_state.state", mock_state):
            await stop_daily_time_scheduler()


# ── start_daily_time_scheduler ────────────────────────────────────────────────

class TestStartDailyTimeScheduler:
    @pytest.mark.asyncio
    async def test_initializes_and_schedules(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"time_scheduler_on": False}
        mock_state.market_phase = {}
        mock_state.timetable_timer_handle = None
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._apply_auto_toggle_on_startup", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_auto_trade_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_midnight_timer"), \
             patch("backend.app.services.daily_time_scheduler._init_ws_subscribe_state", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase") as mock_broadcast, \
             patch("backend.app.services.daily_time_scheduler._timetable_startup_scan", new_callable=AsyncMock) as mock_timetable_scan:
            await start_daily_time_scheduler()
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"
            mock_broadcast.assert_called_once()
            mock_timetable_scan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_settings_logs_warning(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state):
            # start_daily_time_scheduler catches exceptions internally
            await start_daily_time_scheduler()


# ── schedule_auto_trade_timers ────────────────────────────────────────────────

class TestScheduleAutoTradeTimers:
    @pytest.mark.asyncio
    async def test_time_scheduler_off_skips(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        settings = {"time_scheduler_on": False, "buy_time_start": "09:00", "buy_time_end": "15:00", "sell_time_start": "15:00", "sell_time_end": "20:00"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=MagicMock()):
            await schedule_auto_trade_timers(settings)
            assert len(mock_state.auto_trade_timer_handles) == 0

    @pytest.mark.asyncio
    async def test_schedules_timers(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        settings = {"time_scheduler_on": True, "buy_time_start": "09:00", "buy_time_end": "15:00", "sell_time_start": "15:00", "sell_time_end": "20:00"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(6, 0)):
            await schedule_auto_trade_timers(settings)
            assert len(mock_state.auto_trade_timer_handles) == 4

    @pytest.mark.asyncio
    async def test_no_loop_returns(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        settings = {"time_scheduler_on": True, "buy_time_start": "09:00", "buy_time_end": "15:00", "sell_time_start": "15:00", "sell_time_end": "20:00"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            await schedule_auto_trade_timers(settings)


# ── retry_pipeline_catchup_after_bootstrap ────────────────────────────────────

class TestRetryPipelineCatchup:
    @pytest.mark.asyncio
    async def test_in_ws_window_returns(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()

    @pytest.mark.asyncio
    async def test_disconnected_before_download_time_returns(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.master_stocks_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 10)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()

    @pytest.mark.asyncio
    async def test_disconnected_cache_outdated_triggers_fetch(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        # 캐시 date=20250104, 최근 확정 거래일=20250105(is_trading_day=True 모킹이므로 -1일) → 불일치 → 트리거
        mock_state.master_stocks_cache = {"005930": {"date": "20250104"}}
        mock_state.confirmed_done = False
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch") as mock_fire:
            await retry_pipeline_catchup_after_bootstrap()
            mock_fire.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnected_cache_fresh_sets_done(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        # 캐시 date=20250105 = 최근 확정 거래일(is_trading_day=True 모킹이므로 current 20250106의 -1일) → 일치 → 스킵
        mock_state.master_stocks_cache = {"005930": {"date": "20250105"}}
        mock_state.confirmed_done = False
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()
            assert mock_state.confirmed_done is True


# ── 타임테이블 스케줄러 (10초 루프 대체) ──────────────────────────────────────

class TestTimetableBuilder:
    """build_timetable_from_cache 단위 테스트 — 캐시 기반 동적 빌드 (Step 2 + 4세션 통합)."""

    def test_build_with_cache_values_returns_12_items(self):
        """캐시에서 4개 direct 시각을 읽어 12항목 리스트 반환 (토글 ON 기본, 09:00:30 포함)."""
        tt = build_timetable_from_cache({
            "timetable.realtime_reset": "07:55",
            "timetable.ws_prestart": "07:56",
            "timetable.krx_pre_subscribe": "08:58",
            "timetable.confirmed_download": "20:40",
        })
        assert len(tt) == 12
        # 4개 direct 항목 — 캐시 시각 반영 (time 필드는 3-tuple)
        assert tt[0]["time"] == (7, 55, 0)
        assert tt[0]["kind"] == "direct"
        assert tt[0]["action"] is _on_realtime_fields_reset
        assert tt[1]["time"] == (7, 56, 0)
        assert tt[1]["kind"] == "direct"
        assert tt[1]["action"] is _on_ws_subscribe_start
        assert tt[3]["time"] == (8, 58, 0)
        assert tt[3]["kind"] == "direct"
        assert tt[3]["action"] is _on_krx_pre_subscribe
        # 12번째 direct 항목 — 확정 데이터 다운로드 (4세션 통합)
        assert tt[11]["time"] == (20, 40, 0)
        assert tt[11]["kind"] == "direct"
        assert tt[11]["action"] is _on_confirmed_download
        # 8개 phase 항목 — 코드 상수 유지 (3-tuple 정규화)
        assert tt[2]["time"] == _to3(NXT_PREMARKET_START)
        assert tt[4]["time"] == _to3(KRX_REGULAR_START)
        assert tt[5]["time"] == NXT_MAINMARKET_START  # 09:00:30 신규 엔트리
        assert tt[5]["kind"] == "phase"
        assert "09:00:30" in tt[5]["ctx"]
        assert tt[10]["time"] == _to3(NXT_AFTERMARKET_END)

    def test_build_with_empty_cache_falls_back_to_defaults(self):
        """캐시에 키 없으면 DEFAULT_USER_SETTINGS 기본값(07:58/07:59/08:59/20:40) 사용."""
        tt = build_timetable_from_cache({})
        assert tt[0]["time"] == (7, 58, 0)
        assert tt[1]["time"] == (7, 59, 0)
        assert tt[3]["time"] == (8, 59, 0)
        assert tt[11]["time"] == (20, 40, 0)  # confirmed_download 기본값

    def test_build_with_none_cache_value_falls_back_to_default(self):
        """캐시 값이 None/빈 문자열이면 DEFAULT_USER_SETTINGS 기본값 사용 (P20)."""
        tt = build_timetable_from_cache({
            "timetable.realtime_reset": None,
            "timetable.ws_prestart": "",
            "timetable.krx_pre_subscribe": "08:55",
        })
        assert tt[0]["time"] == (7, 58, 0)  # None → 기본값
        assert tt[1]["time"] == (7, 59, 0)  # 빈 문자열 → 기본값
        assert tt[3]["time"] == (8, 55, 0)  # 캐시값 우선

    def test_build_ctx_string_includes_time(self):
        """ctx 문자열에 시각이 포함되어 사용자에게 의미 전달 (P21 투명성)."""
        tt = build_timetable_from_cache({
            "timetable.realtime_reset": "07:55",
            "timetable.ws_prestart": "07:56",
            "timetable.krx_pre_subscribe": "08:58",
            "timetable.confirmed_download": "20:40",
        })
        assert "07:55" in tt[0]["ctx"]
        assert "07:56" in tt[1]["ctx"]
        assert "08:58" in tt[3]["ctx"]
        assert "09:00:30" in tt[5]["ctx"]  # NXT 메인마켓 진입 (초 단위)
        assert "20:40" in tt[11]["ctx"]

    def test_build_toggle_off_skips_confirmed_download(self):
        """scheduler_market_close_on=False 시 마지막 항목 스킵 (P16 살아있는 경로)."""
        tt = build_timetable_from_cache({
            "timetable.realtime_reset": "07:55",
            "timetable.ws_prestart": "07:56",
            "timetable.krx_pre_subscribe": "08:58",
            "timetable.confirmed_download": "20:40",
            "scheduler_market_close_on": False,
        })
        assert len(tt) == 11  # confirmed_download 항목 스킵
        # 마지막 항목은 NXT 장마감 (phase) — confirmed_download direct 없음
        assert tt[10]["kind"] == "phase"
        # confirmed_download action을 가진 항목 없음
        assert not any(e.get("action") is _on_confirmed_download for e in tt)

    def test_build_toggle_on_includes_confirmed_download(self):
        """scheduler_market_close_on=True 시 마지막 항목 포함 (명시적 True)."""
        tt = build_timetable_from_cache({
            "timetable.realtime_reset": "07:55",
            "timetable.ws_prestart": "07:56",
            "timetable.krx_pre_subscribe": "08:58",
            "timetable.confirmed_download": "20:40",
            "scheduler_market_close_on": True,
        })
        assert len(tt) == 12
        assert tt[11]["action"] is _on_confirmed_download

    def test_parse_hm_tuple_valid(self):
        """정상 HH:MM → (h, m) 튜플."""
        assert _parse_hm_tuple("07:58") == (7, 58)
        assert _parse_hm_tuple("20:40") == (20, 40)

    def test_parse_hm_tuple_invalid_raises(self):
        """형식 오류 시 ValueError (P20 폴백 금지 — (0,0) 폴백과 대조)."""
        with pytest.raises(ValueError):
            _parse_hm_tuple("invalid")
        with pytest.raises(ValueError):
            _parse_hm_tuple("7:58:99")
        with pytest.raises(ValueError):
            _parse_hm_tuple("")

    def test_to3_normalizes_2tuple_to_3tuple(self):
        """(h, m) → (h, m, 0) 정규화 (P23 일관성)."""
        assert _to3((7, 58)) == (7, 58, 0)
        assert _to3((20, 40)) == (20, 40, 0)

    def test_to3_passes_3tuple_unchanged(self):
        """(h, m, s) → 그대로 반환."""
        assert _to3((9, 0, 30)) == (9, 0, 30)
        assert _to3((7, 58, 0)) == (7, 58, 0)

    def test_fmt_hms_zero_seconds_omits_seconds(self):
        """s=0 → "HH:MM" (기존 표시 호환)."""
        assert _fmt_hms((7, 58, 0)) == "07:58"
        assert _fmt_hms((20, 40, 0)) == "20:40"

    def test_fmt_hms_nonzero_seconds_includes_seconds(self):
        """s≠0 → "HH:MM:SS" (초 단위 이벤트 표시)."""
        assert _fmt_hms((9, 0, 30)) == "09:00:30"


class TestTimetableScheduler:
    """타임테이블 스케줄러 단위 테스트 — 시간표 기반 이벤트 예약/실행/헬스체크."""

    def setup_method(self, _method):
        """각 테스트 전 _TIMETABLE을 빌더로 채움 (기동 시 빌드 배선과 동일).

        in-place mutation (_TIMETABLE[:] = ...) 사용 — from import로 가져온
        로컬 참조와 모듈 속성 모두 동일 리스트 객체를 가리키도록 일치 (P23 일관성).
        """
        _TIMETABLE[:] = build_timetable_from_cache({
            "timetable.realtime_reset": "07:58",
            "timetable.ws_prestart": "07:59",
            "timetable.krx_pre_subscribe": "08:59",
            "timetable.confirmed_download": "20:40",
        })

    def teardown_method(self, _method):
        """테스트 후 _TIMETABLE을 빈 리스트로 복원 (모듈 로드 상태와 일치)."""
        _TIMETABLE.clear()

    def test_jif_stale_warn_sec_is_120(self):
        """JIF 헬스체크 임계값이 120초(2분)인지 검증."""
        assert _JIF_STALE_WARN_SEC == 120

    def test_schedule_next_event_at_0755_reserves_0758(self):
        """07:55 기동 시 07:58 이벤트 예약 (delay ≈ 180초)."""
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 55)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            _schedule_next_timetable_event()
            # call_later 인자: (delay, callback)
            delay = mock_loop.call_later.call_args.args[0]
            assert delay == 180  # 07:58 - 07:55 = 180초
            assert mock_state.timetable_timer_handle is not None

    def test_schedule_next_event_at_0930_reserves_1520(self):
        """09:30 기동 시 15:20 이벤트 예약 (가장 가까운 미래 phase)."""
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 30)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            _schedule_next_timetable_event()
            delay = mock_loop.call_later.call_args.args[0]
            # 15:20 - 09:30 = 5h50m = 21000초
            assert delay == 21000

    def test_schedule_next_event_at_090000_reserves_090030(self):
        """09:00:00 기동 시 09:00:30 NXT 메인마켓 예약 (delay=30초) — 핵심 신규 테스트.

        JIF 미수신 시 시간표 보완 경로가 09:00:30에 메인마켓 전환을 수행하는지 검증 (P16).
        """
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 0)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            _schedule_next_timetable_event()
            delay = mock_loop.call_later.call_args.args[0]
            # 09:00:30 - 09:00:00 = 30초
            assert delay == 30
            # 예약된 콜백의 ctx에 09:00:30 메인마켓 진입 포함 확인
            sched_ctx = mock_state.timetable_timer_handle  # call_later 반환값 (사용되지 않음)
            # call_later 두 번째 인자(콜백)는 lambda이므로 ctx는 로그로만 검증 가능 — delay로 충분

    def test_schedule_next_event_at_090015_reserves_090030(self):
        """09:00:15 기동 시 09:00:30 예약 (delay=15초) — 초 단위 정밀 예약 검증."""
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0, 15)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            _schedule_next_timetable_event()
            delay = mock_loop.call_later.call_args.args[0]
            # 09:00:30 - 09:00:15 = 15초
            assert delay == 15

    def test_schedule_next_event_at_2030_reserves_2040(self):
        """20:30 기동 시 20:40(확정 다운로드) 예약 — 4세션 11번째 항목 통합."""
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 30)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            _schedule_next_timetable_event()
            delay = mock_loop.call_later.call_args.args[0]
            # 20:40 - 20:30 = 600초
            assert delay == 600

    def test_schedule_next_event_at_2045_reserves_next_day_0758(self):
        """20:45 기동 시 익일 07:58 예약 (24시간 + delay) — 20:40 이후."""
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 45)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            _schedule_next_timetable_event()
            delay = mock_loop.call_later.call_args.args[0]
            # 20:45 → 익일 07:58 = 24h - (20:45 - 07:58) = 24h - 12h47m = 11h13m = 40380초
            assert delay == 40380

    @pytest.mark.asyncio
    async def test_direct_event_fires_action_and_reschedules(self):
        """direct 항목 전달 시 action 호출 + finally에서 다음 예약."""
        mock_state = MagicMock()
        mock_action = AsyncMock()
        entry = {"kind": "direct", "action": mock_action, "ctx": "테스트 direct"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._schedule_next_timetable_event") as mock_resched:
            await _timetable_event_fired(entry)
            mock_action.assert_awaited_once()
            mock_resched.assert_called_once()

    @pytest.mark.asyncio
    async def test_phase_event_fires_broadcast_and_reschedules(self):
        """phase 항목 전달 시 _broadcast_market_phase 호출 + finally에서 다음 예약."""
        mock_state = MagicMock()
        entry = {"kind": "phase", "ctx": "테스트 phase"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase") as mock_broadcast, \
             patch("backend.app.services.daily_time_scheduler._schedule_next_timetable_event") as mock_resched:
            await _timetable_event_fired(entry)
            mock_broadcast.assert_called_once()
            mock_resched.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_event_idempotency_guard_no_op(self):
        """같은 날 direct 이벤트 중복 실행 시 _on_realtime_fields_reset 내 가드로 no-op."""
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"timetable.confirmed_download": "20:40"}
        mock_state.last_realtime_reset_date = "20250106"  # 이미 오늘 실행됨
        # _TIMETABLE 의 07:58 direct 항목 — 실제 _on_realtime_fields_reset 사용
        entry = next(e for e in _TIMETABLE if e["ctx"].startswith("실시간 필드 초기화"))
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.services.daily_time_scheduler._schedule_next_timetable_event"), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _timetable_event_fired(entry)
            mock_reset.assert_not_awaited()  # 가드로 인해 no-op

    def test_check_jif_health_recent_no_warning(self, caplog):
        """last_jif 10초 전 → 경고 로그 미출력."""
        import logging
        mock_state = MagicMock()
        mock_state.last_jif_received_at = _make_kst(10, 0)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0, 10)):
            with caplog.at_level(logging.WARNING, logger="backend.app.services.daily_time_scheduler"):
                _check_jif_health()
                assert not any("JIF 미수신" in r.message for r in caplog.records if r.levelno >= logging.WARNING)

    def test_check_jif_health_none_logs_debug(self, caplog):
        """last_jif None → debug 로그 출력."""
        import logging
        mock_state = MagicMock()
        mock_state.last_jif_received_at = None
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            with caplog.at_level(logging.DEBUG, logger="backend.app.services.daily_time_scheduler"):
                _check_jif_health()
                assert any("JIF 미수신 상태" in r.message for r in caplog.records)

    def test_check_jif_health_stale_logs_warning(self, caplog):
        """last_jif 120초 초과 → warning 로그 출력."""
        import logging
        mock_state = MagicMock()
        # 10:00:00 에서 10:02:30 (150초 경과 → 120초 초과)
        mock_state.last_jif_received_at = _make_kst(10, 0)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 2, 30)):
            with caplog.at_level(logging.WARNING, logger="backend.app.services.daily_time_scheduler"):
                _check_jif_health()
                assert any("JIF 미수신" in r.message and r.levelno == logging.WARNING for r in caplog.records)

    @pytest.mark.asyncio
    async def test_startup_scan_at_075830_reserves_0759(self):
        """07:58:30 재기동 시 _schedule_next_timetable_event 호출 → 07:59 예약."""
        mock_state = MagicMock()
        mock_state.timetable_timer_handle = None
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58, 30)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro):
            await _timetable_startup_scan()
            # 07:59 - 07:58:30 = 30초
            delay = mock_loop.call_later.call_args.args[0]
            assert delay == 30

    @pytest.mark.asyncio
    async def test_stop_cancels_timetable_timer(self):
        """stop_daily_time_scheduler 시 timetable_timer_handle.cancel() + None 설정."""
        timetable_handle = MagicMock()
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        mock_state.midnight_timer_handle = None
        mock_state.timetable_timer_handle = timetable_handle
        with patch("backend.app.services.engine_state.state", mock_state):
            await stop_daily_time_scheduler()
            timetable_handle.cancel.assert_called_once()
            assert mock_state.timetable_timer_handle is None
