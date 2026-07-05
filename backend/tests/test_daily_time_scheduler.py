"""daily_time_scheduler.py 단위 테스트 — 시간 기반 장 상태 판별, 타이머 예약, 콜백 검증.

hang 방지 원칙:
- schedule_engine_task를 mock으로 대체 (백그라운드 태스크 생성 방지)
- asyncio.get_running_loop를 mock으로 대체 (call_later 타이머 생성 방지)
- gc.disable/enable을 mock으로 대체
- state를 mock으로 대체
"""
from __future__ import annotations

import asyncio
import gc
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.daily_time_scheduler import (
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
    _on_krx_market_open,
    _on_krx_after_hours_start,
    _on_ws_subscribe_start,
    _on_ws_subscribe_end,
    _fire_ws_subscribe_end,
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
)
import backend.app.services.daily_time_scheduler as scheduler_mod


def _make_kst(h: int, m: int, weekday: int = 0) -> datetime:
    """Create a KST datetime at given hour:minute with given weekday (0=Mon)."""
    base = datetime(2025, 1, 6, h, m, 0, tzinfo=KST)  # 2025-01-06 is Monday
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
    def test_weekend_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 30, weekday=5)):
            assert is_nxt_premarket_window() is False

    def test_holiday_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False):
            assert is_nxt_premarket_window() is False

    def test_in_window_returns_true(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(8, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_nxt_premarket_window() is True

    def test_before_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_nxt_premarket_window() is False

    def test_after_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_nxt_premarket_window() is False


# ── is_nxt_aftermarket_window ─────────────────────────────────────────────────

class TestIsNxtAftermarketWindow:
    def test_in_window_returns_true(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0)):
            assert is_nxt_aftermarket_window() is True

    def test_before_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 20)):
            assert is_nxt_aftermarket_window() is False

    def test_after_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 30)):
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
            assert result["krx"] == "장전 동시호가"
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
            assert result["krx"] == "장후 동시호가"
            assert result["nxt"] == "휴식"

    def test_after_hours(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 35)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장후 시간외"
            assert result["nxt"] == "애프터마켓"

    def test_single_price(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(15, 50)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "시간외 단일가"
            assert result["nxt"] == "애프터마켓"

    def test_market_closed(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = calc_timebased_market_phase()
            assert result["krx"] == "장마감"
            assert result["nxt"] == "장마감"


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
    def test_in_window_returns_true(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_krx_after_hours() is True

    def test_weekend_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0, weekday=5)):
            assert is_krx_after_hours() is False

    def test_holiday_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(16, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False):
            assert is_krx_after_hours() is False

    def test_before_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(14, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_krx_after_hours() is False

    def test_after_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 30)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_krx_after_hours() is False

    def test_with_explicit_now(self):
        now = _make_kst(16, 0)
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            assert is_krx_after_hours(now) is True


# ── get_market_phase ──────────────────────────────────────────────────────────

class TestGetMarketPhase:
    def test_returns_copy_with_krx_nxt(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result == {"krx": "정규장", "nxt": "메인마켓"}

    def test_includes_krx_alert(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓", "krx_alert": "테스트"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result["krx_alert"] == "테스트"

    def test_empty_krx_logs_error(self):
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "", "nxt": "메인마켓"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            result = get_market_phase()
            assert result["krx"] == ""


# ── is_ws_subscribe_window ────────────────────────────────────────────────────

class TestIsWsSubscribeWindow:
    @pytest.mark.asyncio
    async def test_weekend_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0, weekday=5)):
            result = await is_ws_subscribe_window({"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True})
            assert result is False

    @pytest.mark.asyncio
    async def test_holiday_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=False):
            result = await is_ws_subscribe_window({"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True})
            assert result is False

    @pytest.mark.asyncio
    async def test_ws_subscribe_off_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = await is_ws_subscribe_window({"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": False})
            assert result is False

    @pytest.mark.asyncio
    async def test_in_window_returns_true(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = await is_ws_subscribe_window({"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True})
            assert result is True

    @pytest.mark.asyncio
    async def test_outside_window_returns_false(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = await is_ws_subscribe_window({"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True})
            assert result is False

    @pytest.mark.asyncio
    async def test_empty_settings_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.services.daily_time_scheduler.state", mock_state):
            with pytest.raises(RuntimeError, match="settings cache not initialized"):
                await is_ws_subscribe_window(None)


# ── is_edit_window_open ───────────────────────────────────────────────────────

class TestIsEditWindowOpen:
    @pytest.mark.asyncio
    async def test_ws_window_closed_edit_open(self):
        settings = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True}
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(7, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = await is_edit_window_open(settings)
            assert result is True

    @pytest.mark.asyncio
    async def test_ws_window_open_edit_closed(self):
        settings = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True}
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            result = await is_edit_window_open(settings)
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
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task") as mock_sched:
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
        mock_state.market_phase = {"krx": "", "nxt": ""}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task") as mock_sched:
            _broadcast_market_phase()
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"
            mock_sched.assert_called_once()

    def test_exception_does_not_raise(self):
        with patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", side_effect=Exception("boom")):
            _broadcast_market_phase()


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
    async def test_trading_day_recomputes(self):
        with patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(9, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"):
            await _on_krx_market_open()
            mock_recompute.assert_awaited_once()

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
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"), \
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
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler._broadcast_market_phase"), \
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


# ── _fire_ws_subscribe_end / _fire_confirmed_download / _fire_ws_disconnect_only ──

class TestFireWrappers:
    def test_fire_ws_subscribe_end_schedules(self):
        with patch("backend.app.services.daily_time_scheduler.schedule_engine_task") as mock_sched:
            _fire_ws_subscribe_end()
            mock_sched.assert_called_once()

    def test_fire_confirmed_download_schedules(self):
        with patch("backend.app.services.daily_time_scheduler.schedule_engine_task") as mock_sched:
            _fire_confirmed_download()
            mock_sched.assert_called_once()

    def test_fire_ws_disconnect_only_schedules(self):
        with patch("backend.app.services.daily_time_scheduler.schedule_engine_task") as mock_sched:
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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True}
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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "ws_subscribe_on": True}
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
             patch("backend.app.services.daily_time_scheduler.schedule_engine_task") as mock_sched:
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
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.send_message = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.unsubscribe_stocks = AsyncMock(return_value=True)
        mock_cm.get_connector.return_value = mock_ws
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
             patch("backend.app.services.engine_lifecycle.schedule_engine_task"):
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
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            await stop_daily_time_scheduler()
            for h in auto_handles:
                h.cancel.assert_called_once()
            for h in ws_handles:
                h.cancel.assert_called_once()
            midnight_handle.cancel.assert_called_once()
            assert mock_state.midnight_timer_handle is None

    @pytest.mark.asyncio
    async def test_no_timers_no_error(self):
        mock_state = MagicMock()
        mock_state.auto_trade_timer_handles = []
        mock_state.ws_subscribe_timer_handles = []
        mock_state.midnight_timer_handle = None
        with patch("backend.app.services.daily_time_scheduler.state", mock_state):
            await stop_daily_time_scheduler()


# ── start_daily_time_scheduler ────────────────────────────────────────────────

class TestStartDailyTimeScheduler:
    @pytest.mark.asyncio
    async def test_initializes_and_schedules(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"time_scheduler_on": False}
        mock_state.market_phase = {}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._apply_auto_toggle_on_startup", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.calc_timebased_market_phase", return_value={"krx": "정규장", "nxt": "메인마켓"}), \
             patch("backend.app.services.daily_time_scheduler.schedule_auto_trade_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_ws_subscribe_timers", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.schedule_midnight_timer"), \
             patch("backend.app.services.daily_time_scheduler._init_ws_subscribe_state", new_callable=AsyncMock):
            await start_daily_time_scheduler()
            assert mock_state.market_phase["krx"] == "정규장"
            assert mock_state.market_phase["nxt"] == "메인마켓"

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
            "ws_subscribe_start": "08:00",
            "ws_subscribe_end": "20:00",
            "confirmed_download_time": "20:40",
        }
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(6, 0)):
            await schedule_ws_subscribe_timers(settings)
            existing_handle.cancel.assert_called_once()
            assert len(mock_state.ws_subscribe_timer_handles) > 0

    @pytest.mark.asyncio
    async def test_no_loop_skips(self):
        mock_state = MagicMock()
        mock_state.ws_subscribe_timer_handles = []
        settings = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "confirmed_download_time": "20:40"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            await schedule_ws_subscribe_timers(settings)


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
        mock_state.integrated_system_settings_cache = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "confirmed_download_time": "20:40"}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(10, 0)), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()

    @pytest.mark.asyncio
    async def test_disconnected_before_download_time_returns(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "confirmed_download_time": "20:40"}
        mock_state.master_stocks_cache = {}
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(20, 10)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()

    @pytest.mark.asyncio
    async def test_disconnected_cache_outdated_triggers_fetch(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "confirmed_download_time": "20:40"}
        mock_state.master_stocks_cache = {"005930": {"date": "20250105"}}
        mock_state.confirmed_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.daily_time_scheduler._fire_unified_confirmed_fetch") as mock_fire:
            await retry_pipeline_catchup_after_bootstrap()
            mock_fire.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnected_cache_today_sets_done(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"ws_subscribe_start": "08:00", "ws_subscribe_end": "20:00", "confirmed_download_time": "20:40"}
        mock_state.master_stocks_cache = {"005930": {"date": "20250106"}}
        mock_state.confirmed_done = False
        with patch("backend.app.services.daily_time_scheduler.state", mock_state), \
             patch("backend.app.services.daily_time_scheduler._kst_now", return_value=_make_kst(21, 0)), \
             patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.is_trading_day", return_value=True):
            await retry_pipeline_catchup_after_bootstrap()
            assert mock_state.confirmed_done is True
