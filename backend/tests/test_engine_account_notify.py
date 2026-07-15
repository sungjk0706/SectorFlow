"""engine_account_notify.py 단위 테스트 — delta 계산·캐시 관리·필터링 순수 함수 검증.

WS 브로드캐스트가 필요한 async 함수는 ws_manager를 mock하여 검증.
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from backend.app.services.engine_account_notify import (
    NotificationCache,
    notify_cache,
    _pos_equal,
    _snap_equal,
    _compute_position_delta,
    init_sent_caches,
    _is_relevant_code,
    _rebuild_positions_cache,
    _rebuild_layout_cache,
    _build_lightweight_payload_for_profit_overview,
    notify_raw_real_data,
    broadcast_engine_status_ws,
    notify_ws_subscribe_status,
    notify_program_update,
)


# ── NotificationCache ────────────────────────────────────────────────────────────

class TestNotificationCache:
    def test_init_defaults(self):
        c = NotificationCache()
        assert c.position_sent == {}
        assert c.snapshot_sent == {}
        assert c.prev_scores == []
        assert c.prev_sector_stock_codes == set()
        assert c.prev_sent == {}
        assert c.prev_buy_targets_map is None
        assert c.positions_code_set == set()
        assert c.layout_code_set == set()
        assert c.buy_targets_code_set == set()
        assert c.prev_receive_rate is None

    def test_clear_all(self):
        c = NotificationCache()
        c.position_sent = {"005930": {}}
        c.snapshot_sent = {"deposit": 100}
        c.prev_scores = [{"sector": "A"}]
        c.prev_sector_stock_codes = {"005930"}
        c.prev_sent = {"005930": {}}
        c.prev_buy_targets_map = {"005930": {}}
        c.positions_code_set = {"005930"}
        c.layout_code_set = {"005930"}
        c.buy_targets_code_set = {"005930"}
        c.prev_receive_rate = 0.95
        c.clear_all()
        assert c.position_sent == {}
        assert c.snapshot_sent == {}
        assert c.prev_scores == []
        assert c.prev_sector_stock_codes == set()
        assert c.prev_sent == {}
        assert c.prev_buy_targets_map is None
        assert c.positions_code_set == set()
        assert c.layout_code_set == set()
        assert c.buy_targets_code_set == set()
        assert c.prev_receive_rate is None


# ── _pos_equal ────────────────────────────────────────────────────────────────────

class TestPosEqual:
    def test_identical(self):
        a = {"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "buy_price": 70000,
             "avg_price": 70000, "cur_price": 80000, "pnl_amount": 100000, "pnl_rate": 14.29}
        assert _pos_equal(a, dict(a)) is True

    def test_different_price(self):
        a = {"stk_cd": "005930", "qty": 10, "cur_price": 80000}
        b = {"stk_cd": "005930", "qty": 10, "cur_price": 81000}
        assert _pos_equal(a, b) is False

    def test_extra_fields_ignored(self):
        a = {"stk_cd": "005930", "qty": 10, "extra": "ignored"}
        b = {"stk_cd": "005930", "qty": 10, "extra": "different"}
        assert _pos_equal(a, b) is True

    def test_missing_key_treated_as_none(self):
        a = {"stk_cd": "005930", "qty": 10}
        b = {"stk_cd": "005930", "qty": 10, "cur_price": 80000}
        assert _pos_equal(a, b) is False


# ── _snap_equal ───────────────────────────────────────────────────────────────────

class TestSnapEqual:
    def test_identical(self):
        a = {"deposit": 5000000, "orderable": 4000000, "accumulated_investment": 5000000,
             "total_buy_amount": 700000, "total_eval_amount": 800000, "total_pnl": 100000, "total_pnl_rate": 14.29}
        assert _snap_equal(a, dict(a)) is True

    def test_different_deposit(self):
        a = {"deposit": 5000000}
        b = {"deposit": 6000000}
        assert _snap_equal(a, b) is False

    def test_extra_fields_ignored(self):
        a = {"deposit": 5000000, "extra": "a"}
        b = {"deposit": 5000000, "extra": "b"}
        assert _snap_equal(a, b) is True


# ── _compute_position_delta ───────────────────────────────────────────────────────

class TestComputePositionDelta:
    def test_empty_current_empty_cache(self):
        notify_cache.position_sent = {}
        changed, removed = _compute_position_delta([])
        assert changed == []
        assert removed == []

    def test_new_position(self):
        notify_cache.position_sent = {}
        changed, removed = _compute_position_delta([{"stk_cd": "005930", "qty": 10}])
        assert len(changed) == 1
        assert changed[0]["stk_cd"] == "005930"
        assert removed == []

    def test_unchanged_position(self):
        notify_cache.position_sent = {"005930": {"stk_cd": "005930", "qty": 10, "cur_price": 80000}}
        changed, removed = _compute_position_delta([{"stk_cd": "005930", "qty": 10, "cur_price": 80000}])
        assert changed == []
        assert removed == []

    def test_changed_position(self):
        notify_cache.position_sent = {"005930": {"stk_cd": "005930", "qty": 10, "cur_price": 80000}}
        changed, removed = _compute_position_delta([{"stk_cd": "005930", "qty": 10, "cur_price": 81000}])
        assert len(changed) == 1
        assert removed == []

    def test_removed_position(self):
        notify_cache.position_sent = {"005930": {"stk_cd": "005930", "qty": 10}}
        changed, removed = _compute_position_delta([])
        assert changed == []
        assert removed == ["005930"]

    def test_mixed(self):
        notify_cache.position_sent = {
            "005930": {"stk_cd": "005930", "qty": 10, "cur_price": 80000},
            "000660": {"stk_cd": "000660", "qty": 5, "cur_price": 100000},
        }
        current = [
            {"stk_cd": "005930", "qty": 10, "cur_price": 81000},  # changed
            {"stk_cd": "035420", "qty": 20, "cur_price": 50000},  # new
        ]
        changed, removed = _compute_position_delta(current)
        assert len(changed) == 2
        changed_codes = {c["stk_cd"] for c in changed}
        assert changed_codes == {"005930", "035420"}
        assert removed == ["000660"]


# ── init_sent_caches ──────────────────────────────────────────────────────────────

class TestInitSentCaches:
    def test_init(self):
        notify_cache.clear_all()
        sector_stocks = [{"code": "005930"}, {"code": "000660"}]
        positions = [{"stk_cd": "005930", "qty": 10}, {"stk_cd": "000660", "qty": 5}]
        snapshot = {"deposit": 5000000}
        init_sent_caches(sector_stocks, positions, snapshot)
        assert notify_cache.prev_sector_stock_codes == {"005930", "000660"}
        assert "005930" in notify_cache.position_sent
        assert "000660" in notify_cache.position_sent
        assert notify_cache.snapshot_sent == snapshot
        assert notify_cache.prev_scores == []
        assert notify_cache.prev_buy_targets_map is None
        assert "005930" in notify_cache.positions_code_set
        assert "000660" in notify_cache.positions_code_set

    def test_empty_positions(self):
        notify_cache.clear_all()
        init_sent_caches([], [], {})
        assert notify_cache.position_sent == {}
        assert notify_cache.positions_code_set == set()


# ── _is_relevant_code ─────────────────────────────────────────────────────────────

class TestIsRelevantCode:
    def test_in_positions(self):
        notify_cache.positions_code_set = {"005930"}
        notify_cache.layout_code_set = set()
        notify_cache.buy_targets_code_set = set()
        assert _is_relevant_code("005930") is True

    def test_in_layout(self):
        notify_cache.positions_code_set = set()
        notify_cache.layout_code_set = {"000660"}
        notify_cache.buy_targets_code_set = set()
        assert _is_relevant_code("000660") is True

    def test_in_buy_targets(self):
        notify_cache.positions_code_set = set()
        notify_cache.layout_code_set = set()
        notify_cache.buy_targets_code_set = {"035420"}
        assert _is_relevant_code("035420") is True

    def test_not_relevant(self):
        notify_cache.positions_code_set = set()
        notify_cache.layout_code_set = set()
        notify_cache.buy_targets_code_set = set()
        assert _is_relevant_code("999999") is False


# ── _rebuild_positions_cache ──────────────────────────────────────────────────────

class TestRebuildPositionsCache:
    def test_basic(self):
        positions = [{"stk_cd": "005930"}, {"stk_cd": "000660_AL"}]
        _rebuild_positions_cache(positions)
        assert notify_cache.positions_code_set == {"005930", "000660"}

    def test_empty(self):
        _rebuild_positions_cache([])
        assert notify_cache.positions_code_set == set()

    def test_skips_empty_code(self):
        positions = [{"stk_cd": ""}, {"stk_cd": "005930"}]
        _rebuild_positions_cache(positions)
        assert notify_cache.positions_code_set == {"005930"}


# ── _rebuild_layout_cache ──────────────────────────────────────────────────────────

class TestRebuildLayoutCache:
    def test_basic(self):
        layout = [("code", "005930"), ("name", "삼성전자"), ("code", "000660")]
        _rebuild_layout_cache(layout)
        assert notify_cache.layout_code_set == {"005930", "000660"}

    def test_empty(self):
        notify_cache.layout_code_set = {"005930"}
        _rebuild_layout_cache([])
        assert notify_cache.layout_code_set == set()

    def test_skips_non_code(self):
        layout = [("code", "005930"), ("name", "삼성전자"), ("code", "")]
        _rebuild_layout_cache(layout)
        assert notify_cache.layout_code_set == {"005930"}


# ── _build_lightweight_payload_for_profit_overview ────────────────────────────────

class TestBuildLightweightPayload:
    def test_basic(self):
        snapshot = {
            "deposit": 5000000, "orderable": 4000000, "accumulated_investment": 5000000,
            "initial_deposit": 5000000, "total_buy_amount": 700000, "total_eval_amount": 800000,
            "total_pnl": 100000, "total_pnl_rate": 14.29, "position_count": 2,
        }
        changed = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "cur_price": 80000,
                     "pnl_amount": 100000, "pnl_rate": 14.29, "eval_amount": 800000, "extra": "ignored"}]
        removed = ["000660"]
        result = _build_lightweight_payload_for_profit_overview(snapshot, changed, removed)
        assert result["snapshot"]["deposit"] == 5000000
        assert result["snapshot"]["total_eval_amount"] == 800000
        assert "total_buy_amount" not in result["snapshot"]
        assert result["position_count"] == 2
        assert len(result["changed_positions"]) == 1
        pos = result["changed_positions"][0]
        assert "stk_cd" in pos
        assert "extra" not in pos
        assert result["removed_codes"] == ["000660"]


# ── notify_raw_real_data (ws_manager mock) ────────────────────────────────────────

class TestNotifyRawRealData:
    @pytest.mark.asyncio
    async def test_valid_item(self):
        notify_cache.positions_code_set = {"005930"}
        notify_cache.layout_code_set = set()
        notify_cache.buy_targets_code_set = set()
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            item = {"item": "005930", "values": {"9001": "005930"}}
            await notify_raw_real_data(item)
            mock_bc.assert_awaited_once()
            assert mock_bc.call_args.args[0] == "real-data"

    @pytest.mark.asyncio
    async def test_not_relevant_skipped(self):
        notify_cache.positions_code_set = set()
        notify_cache.layout_code_set = set()
        notify_cache.buy_targets_code_set = set()
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            item = {"item": "999999", "values": {"9001": "999999"}}
            await notify_raw_real_data(item)
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_item_skipped(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await notify_raw_real_data(None)
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_dict_item_skipped(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await notify_raw_real_data("not_dict")
            mock_bc.assert_not_awaited()


# ── broadcast_engine_status_ws ────────────────────────────────────────────────────

class TestBroadcastEngineStatusWs:
    @pytest.mark.asyncio
    async def test_adds_v_key(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_engine_status_ws({"connected": True})
            mock_bc.assert_awaited_once()
            payload = mock_bc.call_args.args[1]
            assert payload["_v"] == 1
            assert payload["connected"] is True

    @pytest.mark.asyncio
    async def test_preserves_existing_v(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_engine_status_ws({"_v": 2, "connected": False})
            payload = mock_bc.call_args.args[1]
            assert payload["_v"] == 2


# ── notify_ws_subscribe_status ────────────────────────────────────────────────────

class TestNotifyWsSubscribeStatus:
    @pytest.mark.asyncio
    async def test_basic(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await notify_ws_subscribe_status({"status": "ok"})
            mock_bc.assert_awaited_once()
            payload = mock_bc.call_args.args[1]
            assert payload["_v"] == 1
            assert payload["status"] == "ok"


# ── notify_program_update ──────────────────────────────────────────────────────────

class TestNotifyProgramUpdate:
    @pytest.mark.asyncio
    async def test_basic(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await notify_program_update("005930", 100000)
            mock_bc.assert_awaited_once()
            payload = mock_bc.call_args.args[1]
            assert payload["code"] == "005930"
            assert payload["net_buy"] == 100000
