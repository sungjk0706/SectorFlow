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
    is_nxt_premarket_window,
    is_nxt_aftermarket_window,
    calc_timebased_market_phase,
    is_nxt_only_window,
    get_nxt_trde_tp,
    is_krx_after_hours,
    get_market_phase,
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
    _on_krx_after_hours_start,
    _on_ws_subscribe_start,
    _on_ws_subscribe_end,
    _fire_confirmed_download,
    _on_confirmed_download,
    _fire_ws_disconnect_only,
    _ws_disconnect_only,
    _init_ws_subscribe_state,
    _trigger_reg_pipeline,
    _trigger_unreg_all,
    _do_unreg_all,
    _seconds_until_hm,
    _on_auto_trade_transition,
    _on_midnight,
    schedule_midnight_timer,
    _freeze_krx_amt29_baseline,
    _apply_detail_to_entry,
    start_daily_time_scheduler,
    stop_daily_time_scheduler,
    schedule_ws_subscribe_timers,
    schedule_auto_trade_timers,
    retry_pipeline_catchup_after_bootstrap,
    _market_phase_periodic_loop,
    _start_market_phase_periodic_task,
    _stop_market_phase_periodic_task,
    _MARKET_PHASE_PERIODIC_INTERVAL,
    _on_realtime_fields_reset,
    _check_prestart_triggers,
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_premarket_window() is True

    def test_regular_market_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_premarket_window() is False

    def test_prep_gap_returns_false(self):
        """정규장 준비(거래 없음) 구간은 프리마켓에서 제외."""
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "정규장 준비"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_premarket_window() is False

    def test_holiday_returns_false(self):
        """휴장일 — calc_timebased_market_phase가 '휴장일' 페이즈 산정."""
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "휴장일"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_premarket_window() is False

    def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": ""}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_premarket_window() is False


# ── is_nxt_aftermarket_window ─────────────────────────────────────────────────

class TestIsNxtAftermarketWindow:
    """market_phase 기반 판별 — state.market_phase를 mock하여 검증."""

    def test_aftermarket_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "애프터마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_aftermarket_window() is True

    def test_aftermarket_sustained_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "애프터마켓 지속"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_aftermarket_window() is True

    def test_single_price_gap_returns_false(self):
        """단일가 매매(일괄 체결) 구간은 애프터마켓에서 제외."""
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "단일가 매매"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_aftermarket_window() is False

    def test_market_closed_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": "장마감"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_aftermarket_window() is False

    def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"nxt": ""}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
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
            assert result["krx"] == "시간외 단일가"
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_only_window() is True

    def test_krx_active_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_only_window() is False

    def test_nxt_inactive_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "장마감"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_only_window() is False

    def test_empty_krx_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "애프터마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_only_window() is False

    def test_opening_auction_nxt_prep_returns_true(self):
        """08:50~09:00 구간: KRX 시가 동시호가(비활성) + NXT 정규장 준비(활성) → True."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_only_window() is True

    def test_settle_nxt_single_price_returns_true(self):
        """15:30~15:40 구간: KRX 체결 정산(비활성) + NXT 단일가 매매(활성) → True."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "체결 정산", "nxt": "단일가 매매"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_nxt_only_window() is True


# ── get_nxt_trde_tp ───────────────────────────────────────────────────────────

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


# ── is_krx_after_hours ────────────────────────────────────────────────────────

class TestIsKrxAfterHours:
    """market_phase 기반 판별 — state.market_phase를 mock하여 검증."""

    def test_settle_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "체결 정산"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is True

    def test_after_hours_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장후 시간외"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is True

    def test_single_price_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시간외 단일가"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is True

    def test_close_none_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장 종료"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is True

    def test_regular_market_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is False

    def test_market_closed_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is False

    def test_holiday_returns_false(self):
        """휴장일 — calc_timebased_market_phase가 '휴장일' 페이즈 산정."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is False

    def test_empty_krx_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": ""}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            assert is_krx_after_hours() is False


# ── get_market_phase ──────────────────────────────────────────────────────────

class TestGetMarketPhase:
    def test_returns_copy_with_krx_nxt(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result["krx"] == "정규장"
            assert result["nxt"] == "메인마켓"
            assert result["is_nxt_only"] is False

    def test_includes_krx_alert(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓", "krx_alert": "테스트"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result["krx_alert"] == "테스트"
            assert result["is_nxt_only"] is False

    def test_empty_krx_logs_error(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result["krx"] == ""
            assert result["is_nxt_only"] is False

    def test_is_nxt_only_true_when_krx_inactive_nxt_active(self):
        """KRX 비활성 + NXT 활성 구간 → is_nxt_only=True 파생 (P10 SSOT)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "애프터마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result["is_nxt_only"] is True


# ── is_ws_subscribe_window ────────────────────────────────────────────────────

class TestIsWsSubscribeWindow:
    @pytest.mark.asyncio
    async def test_holiday_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "휴장일", "nxt": "휴장일"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_ws_subscribe_window({"ws_subscribe_on": True})
            assert result is False

    @pytest.mark.asyncio
    async def test_ws_subscribe_off_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_ws_subscribe_window({"ws_subscribe_on": False})
            assert result is False

    @pytest.mark.asyncio
    async def test_in_window_returns_true(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_ws_subscribe_window({"ws_subscribe_on": True})
            assert result is True

    @pytest.mark.asyncio
    async def test_outside_window_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_ws_subscribe_window({"ws_subscribe_on": True})
            assert result is False

    @pytest.mark.asyncio
    async def test_empty_nxt_returns_false(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": ""}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_ws_subscribe_window({"ws_subscribe_on": True})
            assert result is False

    @pytest.mark.asyncio
    async def test_empty_settings_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            with pytest.raises(RuntimeError, match="settings cache not initialized"):
                await is_ws_subscribe_window(None)


# ── is_edit_window_open ───────────────────────────────────────────────────────

class TestIsEditWindowOpen:
    @pytest.mark.asyncio
    async def test_ws_window_closed_edit_open(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_edit_window_open({"ws_subscribe_on": True})
            assert result is True

    @pytest.mark.asyncio
    async def test_ws_window_open_edit_closed(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = await is_edit_window_open({"ws_subscribe_on": True})
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task") as mock_sched:
            _fire_unified_confirmed_fetch()
            mock_sched.assert_not_called()

    def test_not_done_schedules_task(self):
        mock_state = MagicMock()
        mock_state.confirmed_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _fire_unified_confirmed_fetch()
            mock_sched.assert_called_once()
            assert mock_state.confirmed_done is True

    def test_exception_does_not_raise(self):
        mock_state = MagicMock()
        mock_state.confirmed_done = False
        mock_state.confirmed_done = True  # Simulate setting
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=Exception("boom")):
            _fire_unified_confirmed_fetch()


# ── _do_unified_confirmed_fetch ───────────────────────────────────────────────

class TestDoUnifiedConfirmedFetch:
    @pytest.mark.asyncio
    async def test_success_sets_done(self):
        mock_state = MagicMock()
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.fetch_unified_confirmed_data", new_callable=AsyncMock):
            await _do_unified_confirmed_fetch()
            assert mock_state.confirmed_done is True

    @pytest.mark.asyncio
    async def test_failure_resets_done(self):
        mock_state = MagicMock()
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.fetch_unified_confirmed_data", new_callable=AsyncMock, side_effect=Exception("fail")):
            await _do_unified_confirmed_fetch()
            assert mock_state.confirmed_done is False
            assert mock_state.confirmed_refresh_running_confirmed is False


# ── _broadcast_market_phase ───────────────────────────────────────────────────

class TestBroadcastMarketPhase:
    def test_broadcasts_phase(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"
            mock_sched.assert_called_once()

    def test_exception_does_not_raise(self):
        with patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", side_effect=Exception("boom")):
            _broadcast_market_phase()

    def test_triggers_nxt_premarket_on_phase_change(self):
        """NXT '프리마켓' 전환 시 _on_nxt_premarket_start() + _on_ws_subscribe_start() 트리거."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("KRX 정규장 진입" in ctx for ctx in contexts)

    def test_triggers_krx_after_hours_on_phase_change(self):
        """KRX '체결 정산' 전환 시 _on_krx_after_hours_start() 트리거 (수정 8)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "종가 동시호가", "nxt": "조기 마감"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "체결 정산", "nxt": "단일가 매매"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "체결 정산", "nxt": "단일가 매매"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            contexts = [c.kwargs.get("context", "") for c in mock_sched.call_args_list]
            assert any("KRX 장외 전환" in ctx for ctx in contexts)

    def test_triggers_ws_subscribe_end_on_nxt_close(self):
        """NXT '장마감' 전환 시 _on_ws_subscribe_end() 트리거 (Step 2)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장마감", "nxt": "애프터마켓 지속"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _broadcast_market_phase()
            assert mock_sched.call_count == 1  # 브로드캐스트만, 재계산 없음

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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _apply_market_phase({"krx": "정규장", "nxt": "메인마켓"})
            assert mock_sched.call_count == 1  # 브로드캐스트만, 부작용 없음

    def test_apply_market_phase_partial_update_krx_only(self):
        """JIF 경로 — krx만 갱신 시 nxt는 기존 state 값 유지 (P10 SSOT)."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
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
    async def test_trading_day_recomputes_and_resubscribes(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute, \
             patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock) as mock_subscribe:
            await _on_krx_market_open()
            mock_recompute.assert_awaited_once()
            mock_subscribe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", side_effect=Exception("boom")):
            await _on_krx_market_open()


# ── _on_krx_after_hours_start ─────────────────────────────────────────────────

class TestOnKrxAfterHoursStart:
    @pytest.mark.asyncio
    async def test_weekend_skips(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 30, weekday=5)):
            with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute:
                await _on_krx_after_hours_start()
                mock_recompute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trading_day_recomputes_and_removes_krx(self):
        mock_state = MagicMock()
        mock_state.krx_remove_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.remove_krx_only_stocks", new_callable=AsyncMock, return_value={"removed": 5, "failed": 0}):
            await _on_krx_after_hours_start()
            assert mock_state.krx_remove_done is True

    @pytest.mark.asyncio
    async def test_remove_skipped_resets_flag(self):
        mock_state = MagicMock()
        mock_state.krx_remove_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.remove_krx_only_stocks", new_callable=AsyncMock, return_value={"skipped": True}):
            await _on_krx_after_hours_start()
            assert mock_state.krx_remove_done is False


# ── _on_ws_subscribe_start ────────────────────────────────────────────────────

class TestOnWsSubscribeStart:
    @pytest.mark.asyncio
    async def test_weekend_skips(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0, weekday=5)), \
             patch("backend.app.services.daily_time_scheduler.gc"):
            mock_state = MagicMock()
            mock_state.ws_subscribe_window_active = False
            with patch("backend.app.services.daily_time_scheduler.state", mock_state):
                await _on_ws_subscribe_start()
                # Weekend: function returns early without setting ws_subscribe_window_active to True
                assert mock_state.ws_subscribe_window_active is False

    @pytest.mark.asyncio
    async def test_ws_subscribe_off_skips(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": False}
        mock_state.ws_subscribe_window_active = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc"):
            await _on_ws_subscribe_start()
            assert mock_state.ws_subscribe_window_active is False

    @pytest.mark.asyncio
    async def test_trading_day_starts_subscription(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.ws_window_changed_event = MagicMock()
        # 멱등성 가드 통과: 빈 문자열이어야 실행됨 (4단계)
        mock_state.last_ws_subscribe_start_date = ""
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_awaited_once()
            assert mock_state.last_realtime_reset_date == "20250106"

    @pytest.mark.asyncio
    async def test_skips_if_already_run_today(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.last_realtime_reset_date = "20250106"  # 이미 오늘 실행됨
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_on_weekend(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58, weekday=5)), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_on_non_trading_day(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_on_manual_mode(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": False}
        mock_state.last_realtime_reset_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset:
            await _on_realtime_fields_reset()
            mock_reset.assert_not_awaited()


# ── _check_prestart_triggers (4단계 — 07:58/07:59 사전 트리거 체크) ────────────

class TestCheckPrestartTriggers:
    """_check_prestart_triggers() — 07:58/07:59 사전 트리거 체크 테스트."""

    def test_triggers_fields_reset_at_0758(self):
        mock_state = MagicMock()
        mock_state.last_realtime_reset_date = ""
        mock_state.last_ws_subscribe_start_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 58)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _check_prestart_triggers()
            # 07:58 → 필드 초기화 트리거 1회 (WS 구독은 07:59 미도달 → 0회)
            assert mock_sched.call_count == 1

    def test_triggers_ws_subscribe_at_0759(self):
        mock_state = MagicMock()
        mock_state.last_realtime_reset_date = "20250106"  # 필드 초기화 이미 실행
        mock_state.last_ws_subscribe_start_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _check_prestart_triggers()
            # 07:59 → WS 구독 시작 트리거 1회 (필드 초기화는 이미 실행 → 0회)
            assert mock_sched.call_count == 1

    def test_triggers_both_at_0759_if_neither_run(self):
        mock_state = MagicMock()
        mock_state.last_realtime_reset_date = ""
        mock_state.last_ws_subscribe_start_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _check_prestart_triggers()
            # 07:59 → 필드 초기화(미실행) + WS 구독(미실행) = 2회
            assert mock_sched.call_count == 2

    def test_skips_after_0800(self):
        mock_state = MagicMock()
        mock_state.last_realtime_reset_date = ""
        mock_state.last_ws_subscribe_start_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _check_prestart_triggers()
            # 08:00 이상 — 사전 트리거 없음 (phase 변경 감지가 담당)
            mock_sched.assert_not_called()

    def test_skips_if_already_run(self):
        mock_state = MagicMock()
        mock_state.last_realtime_reset_date = "20250106"
        mock_state.last_ws_subscribe_start_date = "20250106"
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 59)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _check_prestart_triggers()
            mock_sched.assert_not_called()

    def test_skips_before_0758(self):
        mock_state = MagicMock()
        mock_state.last_realtime_reset_date = ""
        mock_state.last_ws_subscribe_start_date = ""
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 57)), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _check_prestart_triggers()
            mock_sched.assert_not_called()


# ── _on_ws_subscribe_start 멱등성 + 보완 경로 (4단계) ──────────────────────────

class TestOnWsSubscribeStartIdempotency:
    """_on_ws_subscribe_start() 멱등성 + 보완 경로 테스트."""

    @pytest.mark.asyncio
    async def test_skips_if_already_started_today(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.ws_window_changed_event = MagicMock()
        mock_state.last_ws_subscribe_start_date = "20250106"  # 이미 오늘 실행됨
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.ws_window_changed_event = MagicMock()
        mock_state.last_ws_subscribe_start_date = ""        # WS 구독 미실행
        mock_state.last_realtime_reset_date = ""            # 필드 초기화도 미실행 → 보완 경로
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc"), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.services.engine_account_notify.notify_cache"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_ws_subscribe_start()
            # 보완 경로 — 필드 초기화 실행
            mock_reset.assert_awaited_once()
            assert mock_state.ws_subscribe_window_active is True

    @pytest.mark.asyncio
    async def test_skips_fields_reset_if_already_done(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.ws_window_changed_event = MagicMock()
        mock_state.last_ws_subscribe_start_date = ""        # WS 구독 미실행
        mock_state.last_realtime_reset_date = "20250106"    # 필드 초기화 이미 실행 → 보완 스킵
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler.gc"), \
             patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.services.engine_account_notify.notify_cache"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_ws_subscribe_start()
            # 보완 스킵 — 필드 초기화 호출 없음
            mock_reset.assert_not_awaited()
            assert mock_state.ws_subscribe_window_active is True


# ── _on_ws_subscribe_end ──────────────────────────────────────────────────────

class TestOnWsSubscribeEnd:
    @pytest.mark.asyncio
    async def test_end_sets_flags_and_triggers_unreg(self):
        mock_state = MagicMock()
        mock_state.ws_window_changed_event = MagicMock()
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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


# ── _fire_confirmed_download / _fire_ws_disconnect_only ──

class TestFireWrappers:
    def test_fire_confirmed_download_schedules(self):
        with patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _fire_confirmed_download()
            mock_sched.assert_called_once()

    def test_fire_ws_disconnect_only_schedules(self):
        with patch("backend.app.services.daily_time_scheduler.schedule_engine_task", side_effect=_close_coro) as mock_sched:
            _fire_ws_disconnect_only()
            mock_sched.assert_called_once()


# ── _on_confirmed_download ────────────────────────────────────────────────────

class TestOnConfirmedDownload:
    @pytest.mark.asyncio
    async def test_calls_fire_unified(self):
        with patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch") as mock_fire:
            await _on_confirmed_download()
            mock_fire.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch", side_effect=Exception("boom")):
            await _on_confirmed_download()


# ── _ws_disconnect_only ───────────────────────────────────────────────────────

class TestWsDisconnectOnly:
    @pytest.mark.asyncio
    async def test_sets_flags_and_triggers_unreg(self):
        mock_state = MagicMock()
        mock_state.ws_window_changed_event = MagicMock()
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._trigger_unreg_all", new_callable=AsyncMock), \
             patch("backend.app.services.ws_subscribe_control._set_status"):
            await _ws_disconnect_only()
            assert mock_state.ws_subscribe_window_active is False
            mock_state.ws_window_changed_event.set.assert_called_once()


# ── _init_ws_subscribe_state ──────────────────────────────────────────────────

class TestInitWsSubscribeState:
    @pytest.mark.asyncio
    async def test_in_window_sets_active(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        mock_state.preboot_cache_loaded = True
        mock_state.ws_window_changed_event = MagicMock()
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.ws_subscribe_control._set_status"):
            await _init_ws_subscribe_state()
            assert mock_state.ws_subscribe_window_active is False

    @pytest.mark.asyncio
    async def test_empty_settings_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            with pytest.raises(RuntimeError, match="settings cache not initialized"):
                await _init_ws_subscribe_state()


# ── _trigger_reg_pipeline ─────────────────────────────────────────────────────

class TestTriggerRegPipeline:
    def test_ws_not_connected_skips(self):
        mock_state = MagicMock()
        mock_state.connector_manager = None
        mock_state.active_connector = None
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(0, 0)), \
             patch("backend.app.core.trading_calendar.has_trading_days_for_year", return_value=True), \
             patch("backend.app.services.daily_time_scheduler._apply_auto_toggle_on_startup", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_auto_trade_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_ws_subscribe_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_midnight_timer") as mock_midnight:
            await _on_midnight()
            assert mock_state.krx_remove_done is False
            assert mock_state.confirmed_done is False
            mock_midnight.assert_called_once()

    @pytest.mark.asyncio
    async def test_same_date_skips_reset(self):
        mock_state = MagicMock()
        mock_state.last_reset_date = _make_kst(0, 0).strftime("%Y%m%d")
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)):
            schedule_midnight_timer()
            existing_handle.cancel.assert_called_once()
            assert mock_state.midnight_timer_handle is mock_handle

    def test_no_loop_returns(self):
        mock_state = MagicMock()
        mock_state.midnight_timer_handle = None
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            schedule_midnight_timer()


# ── _freeze_krx_amt29_baseline ────────────────────────────────────────────────

class TestFreezeKrxAmt29Baseline:
    def test_is_noop(self):
        _freeze_krx_amt29_baseline()


# ── _apply_detail_to_entry ────────────────────────────────────────────────────

class TestApplyDetailToEntry:
    def test_applies_all_fields(self):
        entry = {}
        detail = {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "sign": "2", "trade_amount": 5000000, "strength": 85.5}
        _apply_detail_to_entry(entry, detail)
        assert entry["cur_price"] == 50000
        assert entry["change"] == 1000
        assert entry["change_rate"] == 2.0
        assert entry["sign"] == "2"
        assert entry["trade_amount"] == 5000000
        assert entry["strength"] == "85.50"

    def test_zero_price_not_overwritten(self):
        entry = {"cur_price": 60000}
        detail = {"cur_price": 0}
        _apply_detail_to_entry(entry, detail)
        assert entry["cur_price"] == 60000

    def test_zero_change_not_overwritten(self):
        entry = {"change": 500}
        detail = {"change": 0}
        _apply_detail_to_entry(entry, detail)
        assert entry["change"] == 500

    def test_sign_3_not_overwritten(self):
        entry = {"sign": "2"}
        detail = {"sign": "3"}
        _apply_detail_to_entry(entry, detail)
        assert entry["sign"] == "2"

    def test_invalid_strength_ignored(self):
        entry = {}
        detail = {"strength": "not_a_number"}
        _apply_detail_to_entry(entry, detail)
        assert "strength" not in entry

    def test_none_strength_ignored(self):
        entry = {"strength": "50.00"}
        detail = {"strength": None}
        _apply_detail_to_entry(entry, detail)
        assert entry["strength"] == "50.00"


# ── stop_daily_time_scheduler ─────────────────────────────────────────────────

class TestStopDailyTimeScheduler:
    @pytest.mark.asyncio
    async def test_cancels_all_timers(self):
        auto_handles = [MagicMock(), MagicMock()]
        ws_handles = [MagicMock()]
        midnight_handle = MagicMock()
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = auto_handles
        mock_state.ws_subscribe_timer_handles = ws_handles
        mock_state.midnight_timer_handle = midnight_handle
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._stop_market_phase_periodic_task", new_callable=AsyncMock) as mock_stop_periodic:
            await stop_daily_time_scheduler()
            for h in auto_handles:
                h.cancel.assert_called_once()
            for h in ws_handles:
                h.cancel.assert_called_once()
            midnight_handle.cancel.assert_called_once()
            assert mock_state.midnight_timer_handle is None
            mock_stop_periodic.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_timers_no_error(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        mock_state.ws_subscribe_timer_handles = []
        mock_state.midnight_timer_handle = None
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._stop_market_phase_periodic_task", new_callable=AsyncMock):
            await stop_daily_time_scheduler()


# ── start_daily_time_scheduler ────────────────────────────────────────────────

class TestStartDailyTimeScheduler:
    @pytest.mark.asyncio
    async def test_initializes_and_schedules(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"time_scheduler_on": False}
        mock_state.market_phase = {}
        mock_state.market_phase_periodic_task = None
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._apply_auto_toggle_on_startup", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_auto_trade_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_ws_subscribe_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_midnight_timer"), \
             patch("backend.app.services.daily_time_scheduler._init_ws_subscribe_state", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase") as mock_broadcast, \
             patch("backend.app.services.daily_time_scheduler._start_market_phase_periodic_task") as mock_start_periodic:
            await start_daily_time_scheduler()
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"
            mock_broadcast.assert_called_once()
            mock_start_periodic.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_settings_logs_warning(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            # start_daily_time_scheduler catches exceptions internally
            await start_daily_time_scheduler()


# ── schedule_ws_subscribe_timers ──────────────────────────────────────────────

class TestScheduleWsSubscribeTimers:
    @pytest.mark.asyncio
    async def test_cancels_existing_and_schedules(self):
        existing_handle = MagicMock()
        mock_state = MagicMock()
        mock_state.ws_subscribe_timer_handles = [existing_handle]
        mock_loop = MagicMock()
        mock_loop.call_later.return_value = MagicMock()
        settings = {
            "confirmed_download_time": "20:40",
        }
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(6, 0)):
            await schedule_ws_subscribe_timers(settings)
            existing_handle.cancel.assert_called_once()
            # 11개 market-phase 타이머 제거됨 (안 D 3단계) — confirmed_download_time 타이머 1개만 예약
            assert len(mock_state.ws_subscribe_timer_handles) == 1

    @pytest.mark.asyncio
    async def test_no_loop_skips(self):
        mock_state = MagicMock()
        mock_state.ws_subscribe_timer_handles = []
        settings = {"confirmed_download_time": "20:40"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            await schedule_ws_subscribe_timers(settings)


# ── _market_phase_periodic_loop (안 D 3단계) ──────────────────────────────────

class TestMarketPhasePeriodicLoop:
    """주기 태스크 기동/종료 + 10초 간격 실행 + 엔진 종료 시 즉시 종료 테스트."""

    def test_interval_is_10_seconds(self):
        """주기 태스크 간격이 10초(안 D 설계)인지 검증."""
        assert _MARKET_PHASE_PERIODIC_INTERVAL == 10.0

    def test_start_creates_task(self):
        mock_state = MagicMock()
        mock_state.market_phase_periodic_task = None
        mock_loop = MagicMock()
        mock_task = MagicMock()

        def _create_task_and_close_coro(coro):
            """코루틴을 close하여 RuntimeWarning 방지 (mock은 실제 스케줄하지 않음)."""
            if asyncio.iscoroutine(coro):
                coro.close()
            return mock_task

        mock_loop.create_task.side_effect = _create_task_and_close_coro
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop):
            _start_market_phase_periodic_task()
            assert mock_state.market_phase_periodic_task is mock_task

    def test_start_no_duplicate(self):
        existing_task = MagicMock()
        mock_state = MagicMock()
        mock_state.market_phase_periodic_task = existing_task
        mock_loop = MagicMock()
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop):
            _start_market_phase_periodic_task()
            # 이미 task가 있으면 재생성하지 않음
            assert mock_state.market_phase_periodic_task is existing_task
            mock_loop.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """_stop_market_phase_periodic_task() 호출 시 task 취소 + None 설정 검증."""

        class _FakeTask:
            """await 시 CancelledError를 발생시키는 fake task."""
            def __init__(self):
                self.cancel_called = False
            def cancel(self):
                self.cancel_called = True
            def __await__(self):
                if False:
                    yield  # generator protocol — 실제로는 도달하지 않음
                raise asyncio.CancelledError()

        fake_task = _FakeTask()
        mock_state = MagicMock()
        mock_state.market_phase_periodic_task = fake_task
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            await _stop_market_phase_periodic_task()
            assert fake_task.cancel_called
            assert mock_state.market_phase_periodic_task is None

    @pytest.mark.asyncio
    async def test_stop_no_task_no_error(self):
        mock_state = MagicMock()
        mock_state.market_phase_periodic_task = None
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            await _stop_market_phase_periodic_task()
            assert mock_state.market_phase_periodic_task is None

    @pytest.mark.asyncio
    async def test_loop_calls_broadcast_market_phase(self):
        """_market_phase_periodic_loop()가 _broadcast_market_phase()를 호출하는지 검증."""
        mock_state = MagicMock()
        stop_event = asyncio.Event()
        mock_state.engine_stop_event = stop_event

        def _broadcast_then_stop():
            stop_event.set()  # 1회 호출 후 종료 유도

        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._check_prestart_triggers"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase", side_effect=_broadcast_then_stop) as mock_broadcast:
            await _market_phase_periodic_loop()
            mock_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_loop_stops_on_engine_stop(self):
        """engine_stop_event.set() 시 루프 즉시 종료 검증."""
        mock_state = MagicMock()
        stop_event = asyncio.Event()
        stop_event.set()  # 즉시 종료
        mock_state.engine_stop_event = stop_event
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._check_prestart_triggers"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            # 즉시 반환되어야 함 (hang 없음)
            await asyncio.wait_for(_market_phase_periodic_loop(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_loop_continues_on_exception(self):
        """_broadcast_market_phase() 예외 시 루프 계속 실행 (다음 주기 재시도) 검증."""
        mock_state = MagicMock()
        stop_event = asyncio.Event()
        mock_state.engine_stop_event = stop_event

        call_count = 0

        def _side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("test error")
            # 2회차 호출 후 종료
            stop_event.set()

        def _wait_for_timeout(coro, **kwargs):
            """asyncio.wait_for mock — 코루틴을 close하고 TimeoutError 발생 (RuntimeWarning 방지)."""
            if asyncio.iscoroutine(coro):
                coro.close()
            raise asyncio.TimeoutError()

        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._check_prestart_triggers"), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase", side_effect=_side_effect), \
             patch("asyncio.wait_for", side_effect=_wait_for_timeout):
            await _market_phase_periodic_loop()
            assert call_count == 2  # 예외 후에도 루프 계속 실행


# ── schedule_auto_trade_timers ────────────────────────────────────────────────

class TestScheduleAutoTradeTimers:
    @pytest.mark.asyncio
    async def test_time_scheduler_off_skips(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        settings = {"time_scheduler_on": False, "buy_time_start": "09:00", "buy_time_end": "15:00", "sell_time_start": "15:00", "sell_time_end": "20:00"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(6, 0)):
            await schedule_auto_trade_timers(settings)
            assert len(mock_state.auto_trade_timer_handles) == 4

    @pytest.mark.asyncio
    async def test_no_loop_returns(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        settings = {"time_scheduler_on": True, "buy_time_start": "09:00", "buy_time_end": "15:00", "sell_time_start": "15:00", "sell_time_end": "20:00"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            await schedule_auto_trade_timers(settings)


# ── retry_pipeline_catchup_after_bootstrap ────────────────────────────────────

class TestRetryPipelineCatchup:
    @pytest.mark.asyncio
    async def test_in_ws_window_returns(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True, "confirmed_download_time": "20:40"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()

    @pytest.mark.asyncio
    async def test_disconnected_before_download_time_returns(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True, "confirmed_download_time": "20:40"}
        mock_state.master_stocks_cache = {}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 10)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()

    @pytest.mark.asyncio
    async def test_disconnected_cache_outdated_triggers_fetch(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True, "confirmed_download_time": "20:40"}
        # 캐시 date=20250104, 최근 확정 거래일=20250105(is_trading_day=True 모킹이므로 -1일) → 불일치 → 트리거
        mock_state.master_stocks_cache = {"005930": {"date": "20250104"}}
        mock_state.confirmed_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_on": True, "confirmed_download_time": "20:40"}
        # 캐시 date=20250105 = 최근 확정 거래일(is_trading_day=True 모킹이므로 current 20250106의 -1일) → 일치 → 스킵
        mock_state.master_stocks_cache = {"005930": {"date": "20250105"}}
        mock_state.confirmed_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()
            assert mock_state.confirmed_done is True
