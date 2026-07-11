"""engine_sector_confirm.py 단위 테스트 — 업종 재계산 이벤트 기반 증분 갱신."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.engine_sector_confirm import (
    is_engine_running_internal,
    request_sector_recompute,
    has_dirty_sectors,
    clear_dirty_sectors,
    extract_guard_pass_codes,
    are_buy_targets_changed,
    flush_pending_recompute,
    cancel_sector_recompute,
    cancel_recompute_timer,
    _dirty_codes,
    _flush_sector_recompute_impl,
    _full_recompute,
    sync_dynamic_subscriptions,
    _PENDING_UNREG_TIMERS,
    _UNREG_READY_CODES,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_dirty_codes():
    """각 테스트 전후 _dirty_codes 초기화."""
    _dirty_codes.clear()
    yield
    _dirty_codes.clear()


@pytest.fixture(autouse=True)
def _mock_db():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield


# ── is_engine_running_internal ──────────────────────────────────────

class TestIsEngineRunningInternal:
    def test_running_true(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.running = True
            assert is_engine_running_internal() is True

    def test_running_false(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.running = False
            assert is_engine_running_internal() is False


# ── request_sector_recompute / has_dirty / clear ────────────────────

class TestDirtyCodes:
    def test_request_with_code(self):
        request_sector_recompute("005930")
        assert "005930" in _dirty_codes
        assert has_dirty_sectors() is True

    def test_request_with_none(self):
        request_sector_recompute(None)
        assert "__ALL__" in _dirty_codes
        assert has_dirty_sectors() is True

    def test_request_no_arg(self):
        request_sector_recompute()
        assert "__ALL__" in _dirty_codes

    def test_has_dirty_empty(self):
        assert has_dirty_sectors() is False

    def test_clear_dirty(self):
        request_sector_recompute("005930")
        clear_dirty_sectors()
        assert has_dirty_sectors() is False
        assert len(_dirty_codes) == 0


# ── extract_guard_pass_codes ────────────────────────────────────────

class TestExtractGuardPassCodes:
    def test_empty(self):
        assert extract_guard_pass_codes(None) == set()
        assert extract_guard_pass_codes([]) == set()

    def test_with_guard_pass(self):
        mock_bt = MagicMock()
        mock_bt.stock.code = "005930"
        mock_bt.stock.guard_pass = True

        result = extract_guard_pass_codes([mock_bt])
        assert result == {"005930"}

    def test_without_guard_pass(self):
        mock_bt = MagicMock()
        mock_bt.stock.code = "005931"
        mock_bt.stock.guard_pass = False

        result = extract_guard_pass_codes([mock_bt])
        assert result == set()

    def test_mixed(self):
        mock_bt1 = MagicMock()
        mock_bt1.stock.code = "005930"
        mock_bt1.stock.guard_pass = True

        mock_bt2 = MagicMock()
        mock_bt2.stock.code = "005931"
        mock_bt2.stock.guard_pass = False

        result = extract_guard_pass_codes([mock_bt1, mock_bt2])
        assert result == {"005930"}


# ── are_buy_targets_changed ─────────────────────────────────────────

class TestAreBuyTargetsChanged:
    def test_both_empty(self):
        assert are_buy_targets_changed([], []) is False

    def test_both_none(self):
        assert are_buy_targets_changed(None, None) is False

    def test_no_change(self):
        mock_bt1 = MagicMock()
        mock_bt1.stock.code = "005930"
        mock_bt1.stock.guard_pass = True

        mock_bt2 = MagicMock()
        mock_bt2.stock.code = "005930"
        mock_bt2.stock.guard_pass = True

        assert are_buy_targets_changed([mock_bt1], [mock_bt2]) is False

    def test_code_added(self):
        mock_bt1 = MagicMock()
        mock_bt1.stock.code = "005930"
        mock_bt1.stock.guard_pass = True

        mock_bt2 = MagicMock()
        mock_bt2.stock.code = "005930"
        mock_bt2.stock.guard_pass = True

        mock_bt3 = MagicMock()
        mock_bt3.stock.code = "005935"
        mock_bt3.stock.guard_pass = True

        assert are_buy_targets_changed([mock_bt1], [mock_bt2, mock_bt3]) is True

    def test_code_removed(self):
        mock_bt1 = MagicMock()
        mock_bt1.stock.code = "005930"
        mock_bt1.stock.guard_pass = True

        mock_bt2 = MagicMock()
        mock_bt2.stock.code = "005935"
        mock_bt2.stock.guard_pass = True

        assert are_buy_targets_changed([mock_bt1, mock_bt2], [mock_bt1]) is True

    def test_guard_pass_changed(self):
        """같은 코드지만 guard_pass가 변경된 경우."""
        mock_bt1 = MagicMock()
        mock_bt1.stock.code = "005930"
        mock_bt1.stock.guard_pass = True

        mock_bt2 = MagicMock()
        mock_bt2.stock.code = "005930"
        mock_bt2.stock.guard_pass = False

        assert are_buy_targets_changed([mock_bt1], [mock_bt2]) is True


# ── 호환용 함수 ─────────────────────────────────────────────────────

class TestCompatFunctions:
    def test_flush_pending_recompute(self):
        flush_pending_recompute()
        assert "__ALL__" in _dirty_codes

    def test_cancel_sector_recompute(self):
        request_sector_recompute("005930")
        cancel_sector_recompute()
        assert has_dirty_sectors() is False

    def test_cancel_recompute_timer(self):
        request_sector_recompute("005930")
        cancel_recompute_timer()
        assert has_dirty_sectors() is False


# ── sync_dynamic_subscriptions ──────────────────────────────────────

class TestSyncDynamicSubscriptions:
    def test_ws_not_connected_skip(self):
        """WS 미연결 시 스킵."""
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.connector_manager = None
            mock_state.active_connector = None
            mock_state.login_ok = False
            from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions
            sync_dynamic_subscriptions([])
            # 예외 없이 종료

    def test_ws_connected_no_new_codes(self):
        """WS 연결되어 있지만 새 구독 코드 없음."""
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_ws = MagicMock()
            mock_ws.is_connected.return_value = True
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions
            # buy_targets가 빈 경우
            sync_dynamic_subscriptions([])
            # 예외 없이 종료


# ── _on_unreg_timer ─────────────────────────────────────────────────

class TestOnUnregTimer:
    def test_adds_to_ready_set(self):
        from backend.app.services.engine_sector_confirm import _on_unreg_timer, _UNREG_READY_CODES, _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()
        _UNREG_READY_CODES.clear()
        # 이벤트 루프가 없는 환경에서는 RuntimeError 발생 → 스킵
        _on_unreg_timer("005930")
        # 타이머에서 제거되고 ready_set에 추가됨 (또는 루프 없음으로 스킵)
        assert "005930" not in _PENDING_UNREG_TIMERS


# ── _flush_unreg_batch ──────────────────────────────────────────────

class TestFlushUnregBatch:
    def test_empty_ready_set(self):
        """ready_set이 비어있으면 아무 작업도 수행하지 않음."""
        from backend.app.services.engine_sector_confirm import _flush_unreg_batch, _UNREG_READY_CODES
        _UNREG_READY_CODES.clear()
        _flush_unreg_batch()
        # 예외 없이 종료

    def test_with_codes_but_not_subscribed(self):
        """ready_set에 코드가 있지만 구독 중이 아닌 경우."""
        from backend.app.services.engine_sector_confirm import _flush_unreg_batch, _UNREG_READY_CODES
        _UNREG_READY_CODES.clear()
        _UNREG_READY_CODES.add("005930")
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {}
            _flush_unreg_batch()
        # 예외 없이 종료, ready_set 비워짐
        assert len(_UNREG_READY_CODES) == 0


# ── _flush_sector_recompute_impl ───────────────────────────────────

def _make_sector_score(sector_name, rise_ratio=0.5, final_score=1.0):
    """테스트용 sector score mock 생성."""
    sc = MagicMock()
    sc.sector = sector_name
    sc.rise_ratio = rise_ratio
    sc.final_score = final_score
    sc.rank = 0
    return sc


def _make_buy_target(code, guard_pass=True):
    """테스트용 buy target mock 생성."""
    bt = MagicMock()
    bt.stock.code = code
    bt.stock.guard_pass = guard_pass
    return bt


class TestFlushSectorRecomputeImpl:
    """_flush_sector_recompute_impl — 증분 재계산 메인 (L65-209)."""

    @pytest.mark.asyncio
    async def test_empty_dirty_codes_returns(self):
        """_dirty_codes가 비어있으면 즉시 return (L72-73)."""
        _dirty_codes.clear()
        await _flush_sector_recompute_impl()
        # 예외 없이 종료

    @pytest.mark.asyncio
    async def test_cold_start_calls_full_recompute(self):
        """캐시 없음(콜드 스타트) → _full_recompute 호출 (L92-94)."""
        request_sector_recompute("005930")
        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.engine_sector_confirm._full_recompute", new=AsyncMock()) as mock_full:
            mock_state.sector_summary_cache = None
            await _flush_sector_recompute_impl()
            mock_full.assert_called_once()

    @pytest.mark.asyncio
    async def test_dirty_sectors_empty_returns(self):
        """dirty_sectors가 빈 경우 즉시 return (L112-113)."""
        request_sector_recompute("005930")
        mock_cache = MagicMock()
        mock_cache.sectors = []
        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={"005930": ""})):
            mock_state.sector_summary_cache = mock_cache
            await _flush_sector_recompute_impl()
            # notify 호출 없이 종료

    @pytest.mark.asyncio
    async def test_incremental_happy_path(self):
        """증분 재계산 정상 경로 — merge + notify + event set (L102-206)."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("자동차", rise_ratio=0.3)
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []

        new_sector = _make_sector_score("반도체", rise_ratio=0.8)
        mock_result = MagicMock()
        mock_result.sectors = [existing_sector, new_sector]
        mock_result.buy_targets = []

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930", "005935"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체", "005935": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[new_sector])), \
             patch("backend.app.domain.sector_score.calculate_weighted_scores") as mock_weighted, \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()) as mock_notify_scores, \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()) as mock_notify_targets, \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            mock_weighted.assert_called_once()
            mock_notify_scores.assert_called_once()
            mock_notify_targets.assert_called_once()
            mock_state.sector_summary_ready_event.set.assert_called_once()
            assert mock_state.sector_summary_cache == mock_result

    @pytest.mark.asyncio
    async def test_all_flag_expands_to_all_codes(self):
        """__ALL__ 플래그 → all_codes로 확장 (L98-100)."""
        request_sector_recompute(None)  # adds __ALL__
        existing_sector = _make_sector_score("반도체")
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []
        mock_result = MagicMock()
        mock_result.sectors = [existing_sector]
        mock_result.buy_targets = []

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930", "005935"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체", "005935": "반도체"},
                 {"005930": "반도체", "005935": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[existing_sector])), \
             patch("backend.app.domain.sector_score.calculate_weighted_scores"), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()
            assert mock_state.sector_summary_cache == mock_result

    @pytest.mark.asyncio
    async def test_min_rise_ratio_cutoff(self):
        """min_rise_ratio > 0 → 상승비율 미만 업종 rank=0 (L164-173)."""
        request_sector_recompute("005930")
        pass_sector = _make_sector_score("반도체", rise_ratio=0.8)
        fail_sector = _make_sector_score("자동차", rise_ratio=0.2)
        mock_cache = MagicMock()
        mock_cache.sectors = [fail_sector]
        mock_cache.buy_targets = []
        mock_result = MagicMock()
        mock_result.sectors = [pass_sector, fail_sector]
        mock_result.buy_targets = []

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[pass_sector])), \
             patch("backend.app.domain.sector_score.calculate_weighted_scores"), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 50.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            assert pass_sector.rank == 1
            assert fail_sector.rank == 0

    @pytest.mark.asyncio
    async def test_buy_targets_changed_triggers_sync_and_evaluate(self):
        """buy_targets 변경 → sync_dynamic_subscriptions + evaluate_buy_candidates (L199-203)."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("반도체")
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []
        mock_result = MagicMock()
        mock_result.sectors = [existing_sector]
        mock_result.buy_targets = [_make_buy_target("005930")]

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[existing_sector])), \
             patch("backend.app.domain.sector_score.calculate_weighted_scores"), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=True), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.buy_order_executor.evaluate_buy_candidates", new=AsyncMock()) as mock_eval, \
             patch("backend.app.services.buy_order_executor._cash_insufficient", False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            mock_sync.assert_called_once()
            mock_eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_cash_insufficient_skips_evaluate(self):
        """_cash_insufficient True → evaluate_buy_candidates 스킵 (L202)."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("반도체")
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []
        mock_result = MagicMock()
        mock_result.sectors = [existing_sector]
        mock_result.buy_targets = [_make_buy_target("005930")]

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[existing_sector])), \
             patch("backend.app.domain.sector_score.calculate_weighted_scores"), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=True), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions"), \
             patch("backend.app.services.buy_order_executor.evaluate_buy_candidates", new=AsyncMock()) as mock_eval, \
             patch("backend.app.services.buy_order_executor._cash_insufficient", True):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_logged(self):
        """try 블록 내 예외 시 로깅만 수행 (L208-209)."""
        request_sector_recompute("005930")
        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(side_effect=Exception("test error"))):
            mock_state.sector_summary_cache = MagicMock()
            mock_state.sector_summary_cache.sectors = []
            # 예외가 raise되지 않음
            await _flush_sector_recompute_impl()

    @pytest.mark.asyncio
    async def test_auto_trade_provides_bought_today(self):
        """state.auto_trade가 None이 아닌 경우 _bought_today 추출 (L182-183)."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("반도체")
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []
        mock_result = MagicMock()
        mock_result.sectors = [existing_sector]
        mock_result.buy_targets = []

        mock_auto_trade = MagicMock()
        mock_auto_trade._bought_today = {"005940": True}

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[existing_sector])), \
             patch("backend.app.domain.sector_score.calculate_weighted_scores"), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result) as mock_build, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = mock_auto_trade
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            call_kwargs = mock_build.call_args
            assert call_kwargs.kwargs["bought_today_codes"] == {"005940"}


# ── _full_recompute ────────────────────────────────────────────────

class TestFullRecompute:
    """_full_recompute — 전체 재계산 (콜드 스타트) (L212-266)."""

    @pytest.mark.asyncio
    async def test_happy_path_no_prev_cache(self):
        """이전 캐시 없음 — buy_targets 변경 → sync + evaluate (L260-263)."""
        mock_summary = MagicMock()
        mock_summary.sectors = [_make_sector_score("반도체")]
        mock_result = MagicMock()
        mock_result.sectors = mock_summary.sectors
        mock_result.buy_targets = [_make_buy_target("005930")]

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_summary)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()) as mock_notify_scores, \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()) as mock_notify_targets, \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=True), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.buy_order_executor.evaluate_buy_candidates", new=AsyncMock()) as mock_eval:
            mock_state.sector_summary_cache = None
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _full_recompute()

            assert mock_state.sector_summary_cache == mock_result
            mock_notify_scores.assert_called_once()
            mock_notify_targets.assert_called_once()
            mock_sync.assert_called_once()
            mock_eval.assert_called_once()
            mock_state.sector_summary_ready_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_prev_cache_targets_unchanged_skips_sync(self):
        """이전 캐시 존재 + buy_targets 미변경 → sync/evaluate 스킵 (L260)."""
        mock_summary = MagicMock()
        mock_summary.sectors = []
        mock_result = MagicMock()
        mock_result.sectors = []
        mock_result.buy_targets = []
        prev_cache = MagicMock()
        prev_cache.buy_targets = []

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_summary)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.buy_order_executor.evaluate_buy_candidates", new=AsyncMock()) as mock_eval:
            mock_state.sector_summary_cache = prev_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _full_recompute()

            mock_sync.assert_not_called()
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_trade_provides_bought_today(self):
        """auto_trade가 None이 아닌 경우 _bought_today 추출 (L243-244)."""
        mock_summary = MagicMock()
        mock_summary.sectors = []
        mock_result = MagicMock()
        mock_result.sectors = []
        mock_result.buy_targets = []
        mock_auto_trade = MagicMock()
        mock_auto_trade._bought_today = {"005940": True}

        with patch("backend.app.services.engine_sector_confirm.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_summary)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result) as mock_build, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = None
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 0.0,
            }
            mock_state.auto_trade = mock_auto_trade
            mock_state.sector_summary_ready_event = MagicMock()

            await _full_recompute()

            call_kwargs = mock_build.call_args
            assert call_kwargs.kwargs["bought_today_codes"] == {"005940"}


# ── sync_dynamic_subscriptions — reg/unreg branches ────────────────

class TestSyncDynamicSubscriptionsReg:
    """sync_dynamic_subscriptions — 신규 구독 등록/해지 타이머 (L296-337)."""

    def test_to_reg_new_codes(self):
        """신규 구독 코드 — DYNAMIC_REG 큐 발행 (L296-310)."""
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            sync_dynamic_subscriptions([bt])
            mock_queue.put_nowait.assert_called_once()
            payload = mock_queue.put_nowait.call_args[0][0]
            assert payload[2]["type"] == "DYNAMIC_REG"
            assert "005930" in payload[2]["payload"]["codes"]

    def test_queue_put_failure_logged(self):
        """큐 발행 실패 시 로깅만 수행 (L308-309)."""
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        mock_queue.put_nowait.side_effect = Exception("queue full")
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            # 예외 없이 종료
            sync_dynamic_subscriptions([bt])

    def test_unreg_candidates_no_loop(self):
        """이벤트 루프 없는 환경 — 해지 타이머 설정 안 함 (L316-318)."""
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        _PENDING_UNREG_TIMERS.clear()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            # 기존 구독 코드가 있지만 새 buy_targets에 없음 → 해지 대상
            mock_state.master_stocks_cache = {
                "005935": {"_subscribed_dynamic": True},
            }
            sync_dynamic_subscriptions([bt])
            # 루프가 없으므로 타이머 설정 안 됨
            assert "005935" not in _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()

    @pytest.mark.asyncio
    async def test_unreg_candidates_with_loop(self):
        """이벤트 루프 있는 환경 — 해지 타이머 설정 (L319-325)."""
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        mock_loop = MagicMock()
        mock_timer = MagicMock()
        mock_loop.call_later.return_value = mock_timer
        _PENDING_UNREG_TIMERS.clear()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue), \
             patch("backend.app.services.engine_sector_confirm.asyncio.get_running_loop", return_value=mock_loop):
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {
                "005935": {"_subscribed_dynamic": True},
            }
            sync_dynamic_subscriptions([bt])
            # 005935는 해지 대상 → 타이머 설정
            assert "005935" in _PENDING_UNREG_TIMERS
            mock_loop.call_later.assert_called_once()
        _PENDING_UNREG_TIMERS.clear()

    @pytest.mark.asyncio
    async def test_returned_codes_cancels_timer(self):
        """복귀한 종목 — 타이머 취소 (L328-332)."""
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        mock_loop = MagicMock()
        mock_timer = MagicMock()
        mock_loop.call_later.return_value = mock_timer
        _PENDING_UNREG_TIMERS.clear()
        _PENDING_UNREG_TIMERS["005930"] = mock_timer
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue), \
             patch("backend.app.services.engine_sector_confirm.asyncio.get_running_loop", return_value=mock_loop):
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            sync_dynamic_subscriptions([bt])
            # 005930이 복귀 → 타이머 취소
            mock_timer.cancel.assert_called_once()
            assert "005930" not in _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()

    def test_subscribed_dynamic_set_in_cache(self):
        """prev_codes의 종목에 _subscribed_dynamic=True 설정 (L335-337)."""
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.active_connector = None
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {
                "005930": {},
            }
            sync_dynamic_subscriptions([bt])
            assert mock_state.master_stocks_cache["005930"]["_subscribed_dynamic"] is True
