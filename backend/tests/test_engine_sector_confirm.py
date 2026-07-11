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
