"""engine_sector_confirm.py 단위 테스트 — 업종 재계산 이벤트 기반 증분 갱신."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.tests._mock_helpers import swallow_coro_side_effect
from backend.app.domain.models import SectorScore
from backend.app.services.engine_sector_confirm import (
    request_sector_recompute,
    has_dirty_sectors,
    clear_dirty_sectors,
    extract_guard_pass_codes,
    are_buy_targets_changed,
    extract_buy_target_page_codes,
    are_buy_target_page_codes_changed,
    are_buy_target_page_codes_aligned,
    cancel_sector_recompute,
    cancel_recompute_timer,
    _dirty_codes,
    _flush_sector_recompute_impl,
    _full_recompute,
    sync_dynamic_subscriptions,
    _PENDING_UNREG_TIMERS,
    _extract_cutoff_map,
    _extract_top_n_sectors,
    detect_buy_target_events,
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


# ── 매수 후보 페이지 downstream 코드 집합 비교 ───────────────────────

class TestBuyTargetPageCodes:
    def test_none_summary_returns_empty(self):
        assert extract_buy_target_page_codes(None) == set()

    def test_extracts_buy_and_blocked_targets(self):
        summary = MagicMock()
        summary.buy_targets = [_make_buy_target("005930")]
        summary.blocked_targets = [_make_buy_target("005931", guard_pass=False)]

        assert extract_buy_target_page_codes(summary) == {"005930", "005931"}

    def test_rank_only_change_is_unchanged(self):
        previous = MagicMock()
        previous.buy_targets = [_make_buy_target("005930")]
        previous.blocked_targets = []
        current = MagicMock()
        current.buy_targets = [_make_buy_target("005930")]
        current.blocked_targets = []

        assert are_buy_target_page_codes_changed(previous, current) is False

    def test_added_blocked_target_is_changed(self):
        previous = MagicMock()
        previous.buy_targets = [_make_buy_target("005930")]
        previous.blocked_targets = []
        current = MagicMock()
        current.buy_targets = [_make_buy_target("005930")]
        current.blocked_targets = [_make_buy_target("005931", guard_pass=False)]

        assert are_buy_target_page_codes_changed(previous, current) is True


# ── 호환용 함수 ─────────────────────────────────────────────────────

class TestCompatFunctions:
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

    def test_batch_already_pending_skips_call_soon(self):
        """_UNREG_BATCH_PENDING=True → call_soon 스킵 (L345->exit)."""
        import backend.app.services.engine_sector_confirm as mod
        from backend.app.services.engine_sector_confirm import _on_unreg_timer, _UNREG_READY_CODES, _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()
        _UNREG_READY_CODES.clear()
        _PENDING_UNREG_TIMERS["005930"] = MagicMock()
        original_batch_pending = mod._UNREG_BATCH_PENDING
        mod._UNREG_BATCH_PENDING = True
        try:
            _on_unreg_timer("005930")
            # batch already pending → if not _UNREG_BATCH_PENDING False → call_soon 스킵
            assert "005930" in _UNREG_READY_CODES
        finally:
            mod._UNREG_BATCH_PENDING = original_batch_pending
            _PENDING_UNREG_TIMERS.clear()
            _UNREG_READY_CODES.clear()

    @pytest.mark.asyncio
    async def test_with_loop_calls_call_soon(self):
        """이벤트 루프 있는 환경 — call_soon 호출 (L349)."""
        import backend.app.services.engine_sector_confirm as mod
        from backend.app.services.engine_sector_confirm import _on_unreg_timer, _UNREG_READY_CODES, _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()
        _UNREG_READY_CODES.clear()
        mod._UNREG_BATCH_PENDING = False
        mock_loop = MagicMock()
        with patch("backend.app.services.engine_sector_confirm.asyncio.get_running_loop", return_value=mock_loop):
            _on_unreg_timer("005930")
            mock_loop.call_soon.assert_called_once()
        assert "005930" in _UNREG_READY_CODES
        mod._UNREG_BATCH_PENDING = False
        _PENDING_UNREG_TIMERS.clear()
        _UNREG_READY_CODES.clear()


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

    def test_with_subscribed_codes(self):
        """구독 중인 종목 해지 — DYNAMIC_UNREG + 캐시 정리 + schedule_engine_task (L374-398).
        put_nowait 부작용으로 1개 종목 캐시에서 제거 → L389 False 분기 커버."""
        import backend.app.services.engine_sector_confirm as mod
        from backend.app.services.engine_sector_confirm import _flush_unreg_batch, _UNREG_READY_CODES
        _UNREG_READY_CODES.clear()
        _UNREG_READY_CODES.add("005930")
        _UNREG_READY_CODES.add("005935")
        mock_queue = MagicMock()
        mock_cache = {
            "005930": {"_subscribed_dynamic": True, "order_ratio": 0.5, "program_net_buy": 1000},
            "005935": {"_subscribed_dynamic": True, "order_ratio": 0.3, "program_net_buy": 500},
        }

        def put_side_effect(*args):
            # put_nowait 호출 후 캐시에서 005935 제거 (비동기 환경에서 캐시 변경 시뮬레이션)
            mock_cache.pop("005935", None)

        mock_queue.put_nowait.side_effect = put_side_effect
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task", side_effect=swallow_coro_side_effect) as mock_schedule, \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update"):
            mock_state.master_stocks_cache = mock_cache
            _flush_unreg_batch()
            # DYNAMIC_UNREG 큐 발행 (L374-383)
            mock_queue.put_nowait.assert_called_once()
            payload = mock_queue.put_nowait.call_args[0][0]
            assert payload[2]["type"] == "DYNAMIC_UNREG"
            # 캐시 엔트리 정리 — 005930만 정리 (L389-393)
            assert "_subscribed_dynamic" not in mock_cache["005930"]
            assert "order_ratio" not in mock_cache["005930"]
            assert "program_net_buy" not in mock_cache["005930"]
            # 005935는 put_side_effect로 캐시에서 제거됨 → L389 False 분기
            assert "005935" not in mock_cache
            # schedule_engine_task 호출 (L396-398)
            mock_schedule.assert_called_once()
        _UNREG_READY_CODES.clear()
        mod._UNREG_BATCH_PENDING = False

    def test_queue_put_failure_logged(self):
        """큐 발행 실패 — except 로깅, 캐시 정리는 계속 수행 (L384-385)."""
        import backend.app.services.engine_sector_confirm as mod
        from backend.app.services.engine_sector_confirm import _flush_unreg_batch, _UNREG_READY_CODES
        _UNREG_READY_CODES.clear()
        _UNREG_READY_CODES.add("005930")
        mock_queue = MagicMock()
        mock_queue.put_nowait.side_effect = Exception("queue full")
        mock_cache = {
            "005930": {"_subscribed_dynamic": True, "order_ratio": 0.5, "program_net_buy": 1000},
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task", side_effect=swallow_coro_side_effect), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update"):
            mock_state.master_stocks_cache = mock_cache
            # 예외 없이 종료 (except 핸들러가 로깅만 수행)
            _flush_unreg_batch()
            # 캐시 정리는 큐 실패와 무관하게 수행됨 (L389-393)
            assert "_subscribed_dynamic" not in mock_cache["005930"]
            assert "order_ratio" not in mock_cache["005930"]
            assert "program_net_buy" not in mock_cache["005930"]
        _UNREG_READY_CODES.clear()
        mod._UNREG_BATCH_PENDING = False


# ── _flush_sector_recompute_impl ───────────────────────────────────

def _make_sector_score(sector_name, rise_ratio=0.5, final_score=0.0):
    """테스트용 SectorScore 생성 (실제 객체 — calculate_bonus_scores 실행 가능)."""
    return SectorScore(
        sector=sector_name,
        total=3,
        rise_count=int(rise_ratio * 3),
        rise_ratio=rise_ratio,
        avg_change_rate=1.0,
        avg_trade_amount=1_000_000_000,
        rank=0,
        stocks=[],
        final_score=final_score,
    )


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
        with patch("backend.app.services.engine_state.state") as mock_state, \
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
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={"005930": ""})):
            mock_state.sector_summary_cache = mock_cache
            await _flush_sector_recompute_impl()
            # notify 호출 없이 종료

    @pytest.mark.asyncio
    async def test_incremental_happy_path(self):
        """증분 재계산 정상 경로 — merge + 업종 점수 전송 + 이벤트 발행 (SEDA 2단계)."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("자동차", rise_ratio=0.3)
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []

        new_sector = _make_sector_score("반도체", rise_ratio=0.8)
        mock_buy_target_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930", "005935"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체", "005935": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체", "005935": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[new_sector])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores") as mock_bonus, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()) as mock_notify_scores, \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            mock_bonus.assert_called_once()
            mock_notify_scores.assert_called_once()
            mock_state.sector_summary_ready_event.set.assert_called_once()
            # 캐시는 existing 객체 그대로 유지 (sectors만 merged로 교체)
            assert mock_state.sector_summary_cache == mock_cache
            # 새 업종(반도체)이 추가되어 merged에 포함
            assert any(sc.sector == "반도체" for sc in mock_cache.sectors)

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

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930", "005935"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체", "005935": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체", "005935": "반도체"},
                 {"005930": "반도체", "005935": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[existing_sector])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()
            assert mock_state.sector_summary_cache == mock_result

    @pytest.mark.asyncio
    async def test_min_rise_ratio_cutoff(self):
        """min_rise_ratio > 0 → 상승비율 미만 업종 is_cutoff_passed=False (L164-173)."""
        request_sector_recompute("005930")
        pass_sector = _make_sector_score("반도체", rise_ratio=0.8)
        fail_sector = _make_sector_score("자동차", rise_ratio=0.2)
        mock_cache = MagicMock()
        mock_cache.sectors = [fail_sector]
        mock_cache.buy_targets = []
        mock_result = MagicMock()
        mock_result.sectors = [pass_sector, fail_sector]
        mock_result.buy_targets = []

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[pass_sector])), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 50.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            assert pass_sector.is_cutoff_passed is True
            assert pass_sector.rank == 1
            assert fail_sector.is_cutoff_passed is False

    @pytest.mark.asyncio
    async def test_buy_targets_changed_triggers_event_publish(self):
        """통과/탈락 전환 감지 → 매수후보 갱신 큐에 이벤트 발행 (SEDA 2단계).

        기존: buy_targets 변경 → sync_dynamic_subscriptions + buy_evaluate
        신규: 통과/탈락 전환 감지 → 매수후보 갱신 큐에 이벤트 put
        """
        request_sector_recompute("005930")
        # 기존: 자동차 통과, 반도체 탈락
        existing_pass = _make_sector_score("자동차", rise_ratio=0.8)
        existing_pass.is_cutoff_passed = True
        existing_fail = _make_sector_score("반도체", rise_ratio=0.1)
        existing_fail.is_cutoff_passed = False
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_pass, existing_fail]
        mock_cache.buy_targets = []

        # 신규: 자동차 탈락, 반도체 통과 (통과/탈락 전환)
        new_pass = _make_sector_score("반도체", rise_ratio=0.9)
        new_pass.is_cutoff_passed = True
        new_fail = _make_sector_score("자동차", rise_ratio=0.05)
        new_fail.is_cutoff_passed = False
        mock_buy_target_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[new_pass, new_fail])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            # 매수후보 갱신 큐에 이벤트 발행 확인
            assert mock_buy_target_queue.put_nowait.call_count >= 1
            # 화면 전송(notify_buy_targets_update)·구독 갱신·매수 평가 큐는 호출되지 않음
            # (매수후보 갱신 루프 3단계로 이관)

    @pytest.mark.asyncio
    async def test_no_event_no_queue_publish(self):
        """통과/탈락·상위 N개 변동 없음 → 매수후보 갱신 큐에 발행 안 함 (SEDA 2단계).

        업종 점수만 변하고 통과/탈락 상태·상위 N개 순위가 불변이면 이벤트 없음.
        """
        request_sector_recompute("005930")
        # 기존: 반도체 통과 (상위 N개 내)
        existing_sector = _make_sector_score("반도체", rise_ratio=0.8)
        existing_sector.is_cutoff_passed = True
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []

        # 신규: 반도체 여전히 통과 (점수만 약간 변동, 상태 불변)
        new_sector = _make_sector_score("반도체", rise_ratio=0.85)
        new_sector.is_cutoff_passed = True
        mock_buy_target_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[new_sector])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            # 이벤트 없음 → 매수후보 갱신 큐에 발행 안 함
            mock_buy_target_queue.put_nowait.assert_not_called()

    @pytest.mark.asyncio
    async def test_stock_set_change_publishes_reconcile_event(self):
        """업종 상태 불변이어도 종목 집합 변경 시 후보 재동기화 이벤트 발행."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("반도체", rise_ratio=0.8)
        existing_sector.is_cutoff_passed = True
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = [_make_buy_target("005931")]
        mock_cache.blocked_targets = []

        new_sector = _make_sector_score("반도체", rise_ratio=0.85)
        new_sector.is_cutoff_passed = True
        new_sector.stocks = [MagicMock(code="005930")]
        mock_buy_target_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={"005930": "반도체"})), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[new_sector])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

        payloads = [call.args[0] for call in mock_buy_target_queue.put_nowait.call_args_list]
        assert {payload["action"] for payload in payloads} == {"reconcile"}

    @pytest.mark.asyncio
    async def test_exception_logged(self):
        """try 블록 내 예외 시 로깅만 수행 (L208-209)."""
        request_sector_recompute("005930")
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(side_effect=Exception("test error"))):
            mock_state.sector_summary_cache = MagicMock()
            mock_state.sector_summary_cache.sectors = []
            # 예외가 raise되지 않음
            await _flush_sector_recompute_impl()

    @pytest.mark.asyncio
    async def test_auto_trade_state_accepted(self):
        """state.auto_trade가 None이 아닌 경우에도 증분 재계산 정상 수행 (SEDA 2단계).

        기존: build_buy_targets_from_settings에 bought_today_codes 전달 검증
        신규: auto_trade 설정 시에도 증분 재계산·이벤트 감지 정상 수행
        (bought_today_codes 전달은 3단계 매수후보 갱신 루프로 이관)
        """
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("반도체", rise_ratio=0.8)
        existing_sector.is_cutoff_passed = True
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []

        new_sector = _make_sector_score("반도체", rise_ratio=0.85)
        new_sector.is_cutoff_passed = True
        mock_buy_target_queue = MagicMock()

        mock_auto_trade = MagicMock()
        mock_auto_trade._bought_today = {"005940": True}

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},
                 {"005930": "반도체"},
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[new_sector])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = mock_auto_trade
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()

            # 통과 유지·상위 N개 불변 → 이벤트 없음 → 큐 발행 안 함
            mock_buy_target_queue.put_nowait.assert_not_called()
            mock_state.sector_summary_ready_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_dirty_codes_for_calc_empty(self):
        """dirty_codes_for_calc가 빈 경우 → new_map = {} (L143).
        dirty 종목의 업종이 all_codes에 없는 경우."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("반도체")
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []
        mock_buy_target_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["000660"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"000660": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "반도체"},   # dirty codes → sectors
                 {"000660": "자동차"},   # all_codes → sectors (000660 not in 반도체)
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()
            # dirty_codes_for_calc = [] (000660 not in 반도체) → new_map = {} (L143)
            # 캐시는 existing 객체 유지 (sectors만 merged로 교체)
            assert mock_state.sector_summary_cache == mock_cache

    @pytest.mark.asyncio
    async def test_sector_disappeared_from_new_map(self):
        """dirty 업종이 new_map에 없는 경우 → replacement None, 업종 제외 (L150->147).
        compute_sector_scores가 빈 결과 반환 → 기존 업종 제외."""
        request_sector_recompute("005930")
        existing_sector = _make_sector_score("자동차")
        mock_cache = MagicMock()
        mock_cache.sectors = [existing_sector]
        mock_cache.buy_targets = []
        mock_buy_target_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(side_effect=[
                 {"005930": "자동차"},   # dirty codes → sectors
                 {"005930": "자동차"},   # all_codes → sectors
             ])), \
             patch("backend.app.domain.sector_calculator.compute_sector_scores", new=AsyncMock(return_value=[])), \
             patch("backend.app.domain.sector_score.calculate_bonus_scores"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=mock_buy_target_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
                "sector_max_targets": 3,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _flush_sector_recompute_impl()
            # compute_sector_scores returns [] → new_map = {} (L141)
            # "자동차" in dirty_sectors → replacement = None → excluded (L150->147)
            # 캐시는 existing 객체 유지 (sectors만 merged로 교체 — 자동차 제외됨)
            assert mock_state.sector_summary_cache == mock_cache
            assert all(sc.sector != "자동차" for sc in mock_cache.sectors)


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

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_summary)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()) as mock_notify_scores, \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()) as mock_notify_targets, \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()) as mock_page_refresh, \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=True), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.core_queues.get_order_queue") as mock_get_queue:
            mock_state.sector_summary_cache = None
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _full_recompute()

            assert mock_state.sector_summary_cache == mock_result
            mock_notify_scores.assert_called_once()
            mock_notify_targets.assert_called_once()
            mock_page_refresh.assert_awaited_once()
            mock_sync.assert_called_once()
            mock_get_queue.return_value.put_nowait.assert_called_once_with({"type": "buy_evaluate"})
            mock_state.sector_summary_ready_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_prev_cache_targets_unchanged_skips_sync(self):
        """이전 캐시 존재 + buy_targets 미변경 → sync 스킵, evaluate는 호출 (분리)."""
        mock_summary = MagicMock()
        mock_summary.sectors = []
        mock_result = MagicMock()
        mock_result.sectors = []
        mock_result.buy_targets = []
        prev_cache = MagicMock()
        prev_cache.buy_targets = []

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_summary)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.core_queues.get_order_queue") as mock_get_queue:
            mock_state.sector_summary_cache = prev_cache
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
            }
            mock_state.auto_trade = None
            mock_state.sector_summary_ready_event = MagicMock()

            await _full_recompute()

            # sync는 buy_targets 미변경 시 스킵
            mock_sync.assert_not_called()
            # 매수 후보 평가 요청은 are_buy_targets_changed와 분리 — 업종 점수 변동 시 항상 큐에 put
            mock_get_queue.return_value.put_nowait.assert_called_once_with({"type": "buy_evaluate"})

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

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "master_stocks_cache": {}, "sector_map": {"005930": "반도체"},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_summary)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_result) as mock_build, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.core_queues.get_order_queue"):
            mock_state.sector_summary_cache = None
            mock_state.integrated_system_settings_cache = {
                "sector_min_trade_amt": 0.0,
                "sector_min_rise_ratio_pct": 0.0,
                "sector_bonus_rise_ratio_slider": 0,
                "sector_bonus_relative_strength_slider": 0,
                "sector_bonus_trade_amount_slider": 0,
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
        from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            sync_dynamic_subscriptions([bt])
            mock_queue.put_nowait.assert_called_once()
            payload = mock_queue.put_nowait.call_args[0][0]
            assert payload[2]["type"] == "DYNAMIC_REG"
            assert "005930" in payload[2]["payload"]["codes"]
        _PENDING_REG_CODES.clear()

    def test_queue_put_failure_logged(self):
        """큐 발행 실패 시 로깅만 수행 (L308-309)."""
        from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        mock_queue.put_nowait.side_effect = Exception("queue full")
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            # 예외 없이 종료
            sync_dynamic_subscriptions([bt])
        # 큐 발행 실패 시 대기 세트에 추가되지 않음
        assert "005930" not in _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()

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
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            sync_dynamic_subscriptions([bt])
            # 005930이 복귀 → 타이머 취소
            mock_timer.cancel.assert_called_once()
            assert "005930" not in _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()

    def test_pending_reg_codes_set_when_reg_queued(self):
        """DYNAMIC_REG 큐 발행 시 _pending_reg_codes에 추가 — 구독 전 플래그 설정 안 함 (P10 SSOT).

        _subscribed_dynamic은 구독 완료 후 pipeline_compute DYNAMIC_REG 처리에서만 설정됨.
        sync_dynamic_subscriptions는 _pending_reg_codes에만 추적.
        """
        from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()
        bt = _make_buy_target("005930", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            mock_state.connector_manager = mock_ws
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {
                "005930": {},
            }
            sync_dynamic_subscriptions([bt])
            # 대기 세트에 추가됨
            assert "005930" in _PENDING_REG_CODES
            # 구독 전이므로 _subscribed_dynamic은 설정되지 않음 (P22 정합성)
            assert "_subscribed_dynamic" not in mock_state.master_stocks_cache["005930"]
        _PENDING_REG_CODES.clear()

    @pytest.mark.asyncio
    async def test_returned_codes_multiple_cancels_timers(self):
        """복귀한 종목 3개 (타이머 있음 2개, None 1개) — 루프 2회차 + timer falsy 분기 (L331->329)."""
        bt1 = _make_buy_target("005930", guard_pass=True)
        bt2 = _make_buy_target("005935", guard_pass=True)
        bt3 = _make_buy_target("005940", guard_pass=True)
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_queue = MagicMock()
        mock_loop = MagicMock()
        mock_timer1 = MagicMock()
        mock_timer2 = MagicMock()
        mock_loop.call_later.return_value = mock_timer1
        _PENDING_UNREG_TIMERS.clear()
        _PENDING_UNREG_TIMERS["005930"] = mock_timer1
        _PENDING_UNREG_TIMERS["005935"] = mock_timer2
        _PENDING_UNREG_TIMERS["005940"] = None  # timer already cancelled/None
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue), \
             patch("backend.app.services.engine_sector_confirm.asyncio.get_running_loop", return_value=mock_loop):
            mock_state.connector_manager = mock_ws
            mock_state.login_ok = True
            mock_state.master_stocks_cache = {}
            sync_dynamic_subscriptions([bt1, bt2, bt3])
            # 005930, 005935 타이머 취소
            mock_timer1.cancel.assert_called_once()
            mock_timer2.cancel.assert_called_once()
            # 005940는 timer None → 취소 안 함 (L331->329)
            assert "005930" not in _PENDING_UNREG_TIMERS
            assert "005935" not in _PENDING_UNREG_TIMERS
            assert "005940" not in _PENDING_UNREG_TIMERS
        _PENDING_UNREG_TIMERS.clear()


# ── 매수후보 갱신 이벤트 감지 (SEDA 2단계) ──────────────────────────

class TestExtractCutoffMap:
    """_extract_cutoff_map — 업종별 통과/탈락 맵 추출."""

    def test_empty_sectors(self):
        assert _extract_cutoff_map([]) == {}
        assert _extract_cutoff_map(None) == {}

    def test_passed_sectors(self):
        s1 = _make_sector_score("반도체")
        s1.is_cutoff_passed = True
        s2 = _make_sector_score("자동차")
        s2.is_cutoff_passed = True
        result = _extract_cutoff_map([s1, s2])
        assert result == {"반도체": True, "자동차": True}

    def test_mixed_pass_fail(self):
        s1 = _make_sector_score("반도체")
        s1.is_cutoff_passed = True
        s2 = _make_sector_score("자동차")
        s2.is_cutoff_passed = False
        result = _extract_cutoff_map([s1, s2])
        assert result == {"반도체": True, "자동차": False}

    def test_default_passed_when_attr_missing(self):
        """is_cutoff_passed 속성이 없으면 기본값 True."""
        s = MagicMock()
        s.sector = "반도체"
        # is_cutoff_passed 속성 명시적 설정 안 함 → getattr 기본값 True
        del s.is_cutoff_passed
        result = _extract_cutoff_map([s])
        assert result == {"반도체": True}


class TestExtractTopNSectors:
    """_extract_top_n_sectors — 통과 업종 중 상위 N개 추출."""

    def test_empty_sectors(self):
        assert _extract_top_n_sectors([], 3) == set()
        assert _extract_top_n_sectors(None, 3) == set()

    def test_max_sectors_zero(self):
        s1 = _make_sector_score("반도체")
        s1.is_cutoff_passed = True
        assert _extract_top_n_sectors([s1], 0) == set()

    def test_all_passed_within_n(self):
        s1 = _make_sector_score("반도체")
        s1.is_cutoff_passed = True
        s2 = _make_sector_score("자동차")
        s2.is_cutoff_passed = True
        result = _extract_top_n_sectors([s1, s2], 3)
        assert result == {"반도체", "자동차"}

    def test_only_passed_sectors(self):
        """탈락 업종은 상위 N개에서 제외."""
        s1 = _make_sector_score("반도체")
        s1.is_cutoff_passed = True
        s2 = _make_sector_score("자동차")
        s2.is_cutoff_passed = False
        s3 = _make_sector_score("철강")
        s3.is_cutoff_passed = True
        result = _extract_top_n_sectors([s1, s2, s3], 3)
        assert result == {"반도체", "철강"}

    def test_limit_to_n(self):
        """통과 업종이 N개 초과 시 앞의 N개만."""
        sectors = []
        for name in ["반도체", "자동차", "철강", "화학", "의약"]:
            s = _make_sector_score(name)
            s.is_cutoff_passed = True
            sectors.append(s)
        result = _extract_top_n_sectors(sectors, 3)
        # 정렬 순서대로 앞의 3개 (final_score 내림차순 가정)
        assert len(result) == 3


class TestBuyTargetPageCodeAlignment:
    def test_detects_stale_stock_when_sector_status_is_unchanged(self):
        """업종 상태가 같아도 종목 목록이 바뀌면 후보 불일치로 감지."""
        summary = MagicMock()
        summary.buy_targets = [_make_buy_target("005931")]
        summary.blocked_targets = []
        current_sector = _make_sector_score("반도체")
        current_sector.is_cutoff_passed = True
        current_sector.stocks = [MagicMock(code="005930")]

        assert are_buy_target_page_codes_aligned(
            summary,
            [current_sector],
            max_sectors=3,
        ) is False

    def test_accepts_current_selected_sector_stocks(self):
        """현재 선택 업종 종목과 후보 목록이 같으면 불일치 아님."""
        summary = MagicMock()
        summary.buy_targets = [_make_buy_target("005930")]
        summary.blocked_targets = []
        current_sector = _make_sector_score("반도체")
        current_sector.is_cutoff_passed = True
        current_sector.stocks = [MagicMock(code="005930")]

        assert are_buy_target_page_codes_aligned(
            summary,
            [current_sector],
            max_sectors=3,
        ) is True


class TestDetectBuyTargetEvents:
    """detect_buy_target_events — 통과/탈락 전환 + 상위 N개 진입/이탈 감지."""

    def test_no_change_no_events(self):
        """상태 불변 → 이벤트 없음."""
        prev_cutoff = {"반도체": True, "자동차": False}
        new_cutoff = {"반도체": True, "자동차": False}
        prev_top_n = {"반도체"}
        new_top_n = {"반도체"}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, prev_top_n, new_top_n)
        assert events == []

    def test_pass_to_fail_cutoff_out(self):
        """통과→탈락 전환 → remove 이벤트 (cutoff_out)."""
        prev_cutoff = {"반도체": True}
        new_cutoff = {"반도체": False}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, set(), set())
        assert len(events) == 1
        assert events[0]["sector"] == "반도체"
        assert events[0]["action"] == "remove"
        assert events[0]["reason"] == "cutoff_out"

    def test_fail_to_pass_cutoff_in(self):
        """탈락→통과 전환 → add 이벤트 (cutoff_in)."""
        prev_cutoff = {"자동차": False}
        new_cutoff = {"자동차": True}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, set(), {"자동차"})
        assert len(events) == 1
        assert events[0]["sector"] == "자동차"
        assert events[0]["action"] == "add"
        assert events[0]["reason"] == "cutoff_in"

    def test_top_n_entry(self):
        """상위 N개 진입 (통과 유지하면서 순위 경계 진입) → add 이벤트 (top_n_in)."""
        prev_cutoff = {"반도체": True, "자동차": True, "철강": True}
        new_cutoff = {"반도체": True, "자동차": True, "철강": True}
        # 철강이 상위 N개에 새로 진입
        prev_top_n = {"반도체", "자동차"}
        new_top_n = {"반도체", "자동차", "철강"}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, prev_top_n, new_top_n)
        assert len(events) == 1
        assert events[0]["sector"] == "철강"
        assert events[0]["action"] == "add"
        assert events[0]["reason"] == "top_n_in"

    def test_top_n_exit(self):
        """상위 N개 이탈 (통과 유지하면서 순위 경계 이탈) → remove 이벤트 (top_n_out)."""
        prev_cutoff = {"반도체": True, "자동차": True, "철강": True}
        new_cutoff = {"반도체": True, "자동차": True, "철강": True}
        # 철강이 상위 N개에서 이탈
        prev_top_n = {"반도체", "자동차", "철강"}
        new_top_n = {"반도체", "자동차"}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, prev_top_n, new_top_n)
        assert len(events) == 1
        assert events[0]["sector"] == "철강"
        assert events[0]["action"] == "remove"
        assert events[0]["reason"] == "top_n_out"

    def test_new_sector_appears(self):
        """신규 업종 등장 (이전에 없던 업종이 통과로 등장) → add 이벤트 (cutoff_in)."""
        prev_cutoff = {"반도체": True}
        new_cutoff = {"반도체": True, "자동차": True}
        prev_top_n = {"반도체"}
        new_top_n = {"반도체", "자동차"}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, prev_top_n, new_top_n)
        # 자동차: 이전 False(기본값) → 신규 True → cutoff_in
        # 자동차: 상위 N개 진입이지만 cutoff_in으로 이미 감지됨 → top_n_in 중복 안 함
        assert len(events) == 1
        assert events[0]["sector"] == "자동차"
        assert events[0]["reason"] == "cutoff_in"

    def test_sector_disappears(self):
        """업종 사라짐 (이전 통과 → 신규에 없음) → remove 이벤트 (cutoff_out)."""
        prev_cutoff = {"반도체": True, "자동차": True}
        new_cutoff = {"반도체": True}
        prev_top_n = {"반도체", "자동차"}
        new_top_n = {"반도체"}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, prev_top_n, new_top_n)
        # 자동차: 이전 True → 신규 False(기본값) → cutoff_out
        assert len(events) == 1
        assert events[0]["sector"] == "자동차"
        assert events[0]["reason"] == "cutoff_out"

    def test_multiple_events(self):
        """여러 이벤트 동시 발생."""
        prev_cutoff = {"반도체": True, "자동차": False, "철강": True}
        new_cutoff = {"반도체": False, "자동차": True, "철강": True}
        # 반도체: 통과→탈락 (cutoff_out)
        # 자동차: 탈락→통과 (cutoff_in), 상위 N개 진입이지만 cutoff_in으로 감지
        # 철강: 통과 유지, 상위 N개 유지 → 이벤트 없음
        prev_top_n = {"반도체", "철강"}
        new_top_n = {"자동차", "철강"}
        events = detect_buy_target_events(prev_cutoff, new_cutoff, prev_top_n, new_top_n)
        actions = {(e["sector"], e["action"], e["reason"]) for e in events}
        assert ("반도체", "remove", "cutoff_out") in actions
        assert ("자동차", "add", "cutoff_in") in actions
        # 철강은 통과 유지 + 상위 N개 유지 → 이벤트 없음
        assert not any(e["sector"] == "철강" for e in events)


# ── 매수후보 갱신 루프 (engine_buy_target_loop) ──────────────────────────────

class TestProcessBuyTargetEvents:
    """_process_buy_target_events — 증분 갱신 + 캐시 갱신 + 매수 요청 전달 + 후속 처리 (3단계)."""

    @pytest.mark.asyncio
    async def test_calls_notify_and_order_queue(self):
        """이벤트 처리 후 화면 전송·매수 평가 큐 호출 (설계서 완료기준 9·10·12)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []
        mock_order_queue = MagicMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary), \
             patch("backend.app.services.engine_initial_data._set_sector_summary") as mock_set, \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()) as mock_notify, \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions"), \
             patch("backend.app.services.core_queues.get_order_queue", return_value=mock_order_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = None

            events = [{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}]
            await _process_buy_target_events(events)

            mock_set.assert_called_once()
            mock_notify.assert_awaited_once()
            mock_order_queue.put_nowait.assert_called_once_with({"type": "buy_evaluate"})

    @pytest.mark.asyncio
    async def test_page_subscription_on_codes_changed(self):
        """종목 코드 집합 변동 시 페이지 구독 갱신 호출 (설계서 완료기준 11)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []
        mock_new_summary.blocked_targets = []

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary), \
             patch("backend.app.services.engine_initial_data._set_sector_summary"), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=True) as mock_codes_changed, \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()) as mock_page_refresh, \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions"), \
             patch("backend.app.services.core_queues.get_order_queue", return_value=MagicMock()):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = None

            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

            mock_codes_changed.assert_called_once()
            mock_page_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_page_subscription_skipped_when_codes_unchanged(self):
        """종목 코드 집합 불변 시 페이지 구독 갱신 스킵 (불필요한 갱신 제거)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []
        mock_new_summary.blocked_targets = []

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary), \
             patch("backend.app.services.engine_initial_data._set_sector_summary"), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()) as mock_page_refresh, \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions"), \
             patch("backend.app.services.core_queues.get_order_queue", return_value=MagicMock()):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = None

            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

            mock_page_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_dynamic_on_guard_pass_changed(self):
        """guard_pass 종목 집합 변동 시 동적 구독 갱신 호출 (설계서 완료기준 11)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary), \
             patch("backend.app.services.engine_initial_data._set_sector_summary"), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=True) as mock_changed, \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.core_queues.get_order_queue", return_value=MagicMock()):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = None

            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

            mock_changed.assert_called_once()
            mock_sync.assert_called_once_with(mock_new_summary.buy_targets)

    @pytest.mark.asyncio
    async def test_sync_dynamic_skipped_when_guard_pass_unchanged(self):
        """guard_pass 종목 집합 불변 시 동적 구독 갱신 스킵."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary), \
             patch("backend.app.services.engine_initial_data._set_sector_summary"), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions") as mock_sync, \
             patch("backend.app.services.core_queues.get_order_queue", return_value=MagicMock()):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = None

            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

            mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_cache(self):
        """캐시 없음 시 증분 갱신 스킵 (콜드 스타트 대기 — W8 폴백 금지, 명시적 무시)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update") as mock_update, \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()) as mock_notify:
            mock_state.sector_summary_cache = None

            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

            mock_update.assert_not_called()
            mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_order_queue_full_drops_gracefully(self):
        """주문 큐 가득 시 명시적 드롭 + 로깅 (W8 폴백 금지, W1 무한 쌓기 방지)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events
        import asyncio

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []
        mock_order_queue = MagicMock()
        mock_order_queue.put_nowait.side_effect = asyncio.QueueFull()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary), \
             patch("backend.app.services.engine_initial_data._set_sector_summary"), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions"), \
             patch("backend.app.services.core_queues.get_order_queue", return_value=mock_order_queue):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = None

            # 예외 전파 없이 정상 종료 (격리된 실패)
            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

    @pytest.mark.asyncio
    async def test_bought_today_codes_passed_to_update(self):
        """auto_trade._bought_today가 증분 갱신 함수에 전달됨 (재매수 차단)."""
        from backend.app.services.engine_buy_target_loop import _process_buy_target_events

        mock_cache = MagicMock()
        mock_cache.sectors = []
        mock_cache.buy_targets = []
        mock_new_summary = MagicMock()
        mock_new_summary.buy_targets = []
        mock_auto_trade = MagicMock()
        mock_auto_trade._bought_today = {"005940": True}

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.domain.buy_filter.apply_incremental_buy_target_update", return_value=mock_new_summary) as mock_update, \
             patch("backend.app.services.engine_initial_data._set_sector_summary"), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_target_page_codes_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._refresh_buy_target_page_subscriptions", new=AsyncMock()), \
             patch("backend.app.services.engine_sector_confirm.are_buy_targets_changed", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.sync_dynamic_subscriptions"), \
             patch("backend.app.services.core_queues.get_order_queue", return_value=MagicMock()):
            mock_state.sector_summary_cache = mock_cache
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3}
            mock_state.auto_trade = mock_auto_trade

            await _process_buy_target_events([{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}])

            # apply_incremental_buy_target_update 호출 시 bought_today_codes 전달 확인
            _, kwargs = mock_update.call_args
            assert kwargs.get("bought_today_codes") == {"005940"}


class TestBuyTargetLoopConsume:
    """매수후보 갱신 루프 — 큐 소비 동작 (3단계)."""

    @pytest.mark.asyncio
    async def test_loop_consumes_events_from_queue(self):
        """루프가 큐에서 이벤트를 꺼내 _process_buy_target_events 호출 후 task_done."""
        from backend.app.services import engine_buy_target_loop as loop_mod
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]})

        processed_events: list = []

        async def fake_process(events):
            processed_events.extend(events)

        loop_mod._buy_target_running = True
        try:
            with patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=queue), \
                 patch.object(loop_mod, "_process_buy_target_events", side_effect=fake_process):
                # 루프를 짧게 실행 후 중단
                task = asyncio.create_task(loop_mod._buy_target_loop_impl())
                await asyncio.sleep(0.1)
                loop_mod._buy_target_running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                assert len(processed_events) == 1
                assert processed_events[0]["sector"] == "자동차"
                assert queue.empty()  # 큐에서 꺼냄
        finally:
            loop_mod._buy_target_running = False

    @pytest.mark.asyncio
    async def test_loop_batches_multiple_events(self):
        """큐에 쌓인 여러 이벤트를 한 번에 배치 처리."""
        from backend.app.services import engine_buy_target_loop as loop_mod
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]})
        queue.put_nowait({"sector": "조선", "action": "remove", "reason": "cutoff_out", "stock_codes": ["005880"]})

        batch_sizes: list = []

        async def fake_process(events):
            batch_sizes.append(len(events))

        loop_mod._buy_target_running = True
        try:
            with patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=queue), \
                 patch.object(loop_mod, "_process_buy_target_events", side_effect=fake_process):
                task = asyncio.create_task(loop_mod._buy_target_loop_impl())
                await asyncio.sleep(0.1)
                loop_mod._buy_target_running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # 2개 이벤트가 한 배치로 처리됨
                assert batch_sizes == [2]
        finally:
            loop_mod._buy_target_running = False

    @pytest.mark.asyncio
    async def test_loop_event_exception_isolated(self):
        """개별 이벤트 처리 예외 시 루프 중단 없이 계속 (W9 격리된 실패)."""
        from backend.app.services import engine_buy_target_loop as loop_mod
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]})

        call_count = 0

        async def fake_process(events):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 첫 배치 예외 후 두 번째 이벤트 추가 — 루프가 계속되는지 확인
                queue.put_nowait({"sector": "조선", "action": "add", "reason": "cutoff_in", "stock_codes": ["005880"]})
                raise RuntimeError("의도적 예외 — 격리 테스트")

        loop_mod._buy_target_running = True
        try:
            with patch("backend.app.services.core_queues.get_buy_target_update_queue", return_value=queue), \
                 patch.object(loop_mod, "_process_buy_target_events", side_effect=fake_process):
                task = asyncio.create_task(loop_mod._buy_target_loop_impl())
                await asyncio.sleep(0.2)
                loop_mod._buy_target_running = False
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # 첫 배치 예외 후에도 루프가 중단되지 않고 두 번째 배치 처리
                assert call_count >= 2
        finally:
            loop_mod._buy_target_running = False
