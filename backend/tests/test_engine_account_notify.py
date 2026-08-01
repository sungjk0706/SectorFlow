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
    _rebuild_positions_cache,
    _rebuild_layout_cache,
    broadcast_engine_status_ws,
    notify_desktop_header_refresh,
    notify_program_update,
    notify_index_data,
    notify_buy_targets_update,
    _BUY_TARGET_CMP_KEYS,
    _BUY_TARGET_REALTIME_KEYS,
    _next_revision,
    get_freshness,
    get_freshness_snapshot,
    _broadcast,
)
from backend.app.services.engine_account_broadcast import (
    _build_lightweight_payload_for_profit_overview,
    _broadcast_account_to_pages,
)


# ── WS/HTTP 최신성 계약 ─────────────────────────────────────────────────────────

class TestFreshnessContract:
    def test_revision_is_monotonic_per_group(self):
        before = get_freshness("account")["revision"]
        revision = _next_revision("account")
        assert revision == before + 1
        assert get_freshness("account") == {"group": "account", "revision": revision}
        assert get_freshness("sector_scores")["revision"] == 0

    def test_initial_snapshot_exposes_all_groups(self):
        snapshot = get_freshness_snapshot()
        assert set(snapshot) == {"account", "buy_targets", "sector_scores", "sector_stocks", "trade_history"}
        assert all(meta["group"] == group for group, meta in snapshot.items())

    @pytest.mark.asyncio
    async def test_ws_payload_contains_server_freshness_metadata(self):
        with patch("backend.app.web.ws_manager.ws_manager") as manager:
            manager.broadcast = AsyncMock()
            await _broadcast("sector-scores", {"scores": []}, group="sector_scores")
        payload = manager.broadcast.await_args.args[1]
        assert payload["freshness"]["group"] == "sector_scores"
        assert isinstance(payload["freshness"]["revision"], int)


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


# ── _pos_equal ────────────────────────────────────────────────────────────────────

class TestPosEqual:
    def test_identical(self):
        a = {"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10,
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


# ── _broadcast_account_to_pages — 페이지별 이벤트 분리 (P23) ──────────────────────

class TestBroadcastAccountToPages:
    """account-update / account-summary-update 이벤트 분리 전송 검증 (P23 일관성)."""

    @pytest.mark.asyncio
    async def test_profit_overview_only_sends_summary_update(self):
        """수익현황만 활성 → account-summary-update 경량화 이벤트 전송."""
        from unittest.mock import MagicMock
        with patch("backend.app.services.engine_account_broadcast._safe_broadcast", new_callable=AsyncMock) as mock_safe, \
             patch("backend.app.web.ws_manager.ws_manager") as mock_wsm:
            mock_wsm.get_active_pages = MagicMock(return_value={"profit-overview"})
            mock_wm_broadcast = AsyncMock()
            mock_wsm.broadcast_to_pages = mock_wm_broadcast
            changed = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "cur_price": 80000}]
            snapshot = {"deposit": 5000000, "total_eval_amount": 800000, "position_count": 1}
            await _broadcast_account_to_pages(changed, [], snapshot, {"profit-overview"})
            # account-summary-update 전송 검증
            assert mock_wm_broadcast.await_count == 1
            event_name = mock_wm_broadcast.call_args.args[0]
            assert event_name == "account-summary-update"
            target_pages = mock_wm_broadcast.call_args.args[2]
            assert target_pages == {"profit-overview"}
            # account-update 폴백 미호출
            mock_safe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sell_position_active_sends_account_update(self):
        """매도포지션 활성 → account-update 전체 payload 이벤트 전송."""
        from unittest.mock import MagicMock
        with patch("backend.app.services.engine_account_broadcast._safe_broadcast", new_callable=AsyncMock) as mock_safe, \
             patch("backend.app.web.ws_manager.ws_manager") as mock_wsm:
            mock_wsm.get_active_pages = MagicMock(return_value={"sell-position"})
            mock_wm_broadcast = AsyncMock()
            mock_wsm.broadcast_to_pages = mock_wm_broadcast
            changed = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "cur_price": 80000, "pnl_rate": 5.2}]
            snapshot = {"deposit": 5000000, "total_eval_amount": 800000, "position_count": 1}
            await _broadcast_account_to_pages(changed, [], snapshot, {"sell-position"})
            assert mock_wm_broadcast.await_count == 1
            event_name = mock_wm_broadcast.call_args.args[0]
            assert event_name == "account-update"
            target_pages = mock_wm_broadcast.call_args.args[2]
            assert target_pages == {"sell-position"}
            mock_safe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_both_pages_active_sends_account_update(self):
        """두 페이지 모두 활성 → account-update 전체 payload (수익현황도 전체 수신)."""
        from unittest.mock import MagicMock
        with patch("backend.app.services.engine_account_broadcast._safe_broadcast", new_callable=AsyncMock) as mock_safe, \
             patch("backend.app.web.ws_manager.ws_manager") as mock_wsm:
            mock_wsm.get_active_pages = MagicMock(return_value={"profit-overview", "sell-position"})
            mock_wm_broadcast = AsyncMock()
            mock_wsm.broadcast_to_pages = mock_wm_broadcast
            changed = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "cur_price": 80000}]
            snapshot = {"deposit": 5000000, "total_eval_amount": 800000, "position_count": 1}
            await _broadcast_account_to_pages(changed, [], snapshot, {"profit-overview", "sell-position"})
            assert mock_wm_broadcast.await_count == 1
            event_name = mock_wm_broadcast.call_args.args[0]
            assert event_name == "account-update"
            target_pages = mock_wm_broadcast.call_args.args[2]
            assert target_pages == {"sell-position", "profit-overview"}
            mock_safe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_active_page_fallback_account_update(self):
        """활성 페이지 없음 → account-update 전체 payload 폴백 (_safe_broadcast)."""
        from unittest.mock import MagicMock
        with patch("backend.app.services.engine_account_broadcast._safe_broadcast", new_callable=AsyncMock) as mock_safe, \
             patch("backend.app.web.ws_manager.ws_manager") as mock_wsm:
            mock_wsm.get_active_pages = MagicMock(return_value=set())
            mock_wm_broadcast = AsyncMock()
            mock_wsm.broadcast_to_pages = mock_wm_broadcast
            changed = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "cur_price": 80000}]
            snapshot = {"deposit": 5000000, "total_eval_amount": 800000, "position_count": 1}
            await _broadcast_account_to_pages(changed, [], snapshot, set())
            mock_wm_broadcast.assert_not_awaited()
            mock_safe.assert_awaited_once()
            event_name = mock_safe.call_args.args[0]
            assert event_name == "account-update"


# ── broadcast_engine_status_ws ────────────────────────────────────────────────────

class TestBroadcastEngineStatusWs:
    @pytest.mark.asyncio
    async def test_adds_v_key(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_engine_status_ws({"connected": True})
            mock_bc.assert_awaited_once()
            event_name = mock_bc.call_args.args[0]
            payload = mock_bc.call_args.args[1]
            assert event_name == "engine-status"
            assert payload["_v"] == 1
            assert payload["connected"] is True

    @pytest.mark.asyncio
    async def test_preserves_existing_v(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_engine_status_ws({"_v": 2, "connected": False})
            event_name = mock_bc.call_args.args[0]
            payload = mock_bc.call_args.args[1]
            assert event_name == "engine-status"
            assert payload["_v"] == 2


# ── notify_desktop_header_refresh ────────────────────────────────────────────────

class TestNotifyDesktopHeaderRefresh:
    """notify_desktop_header_refresh — 엔진 상태 변경 시 engine-status 이벤트 전송 검증."""

    @pytest.mark.asyncio
    async def test_broadcasts_engine_status_event(self):
        """엔진 상태 변경 → engine-status 이벤트 브로드캐스트."""
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True, "broker_statuses": {"ls": {"token_valid": True}}}):
            await notify_desktop_header_refresh()
            mock_bc.assert_awaited_once()
            event_name = mock_bc.call_args.args[0]
            payload = mock_bc.call_args.args[1]
            assert event_name == "engine-status"
            assert payload["_v"] == 1
            assert payload["running"] is True
            assert payload["broker_statuses"] == {"ls": {"token_valid": True}}


# ── notify_index_data ────────────────────────────────────────────────────────────

class TestNotifyIndexData:
    """notify_index_data — 캐시 갱신 + WS 브로드캐스트 검증 (P10 SSOT)."""

    @pytest.mark.asyncio
    async def test_updates_cache_and_broadcasts(self):
        """정상 틱: 캐시 갱신 + index-data 브로드캐스트 (broker_statuses 미포함 — engine-status 분리)."""
        from backend.app.services import engine_state
        engine_state.state.index_data_cache.clear()
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc:
            await notify_index_data("001", "2500.5", "10.5", "0.5", "2")
            # 캐시 갱신 검증
            assert engine_state.state.index_data_cache["001"] == {
                "jisu": "2500.5", "sign": "2", "change": "10.5", "drate": "0.5",
            }
            # 브로드캐스트 검증
            mock_bc.assert_awaited_once()
            event_name = mock_bc.call_args.args[0]
            payload = mock_bc.call_args.args[1]
            assert event_name == "index-data"
            assert payload["upcode"] == "001"
            assert payload["jisu"] == "2500.5"
            assert "broker_statuses" not in payload
        engine_state.state.index_data_cache.clear()

    @pytest.mark.asyncio
    async def test_overwrites_cache_on_new_tick(self):
        """새 틱 수신 시 기존 캐시 덮어쓰기 (종목 현재가와 동일 패턴)."""
        from backend.app.services import engine_state
        engine_state.state.index_data_cache.clear()
        engine_state.state.index_data_cache["001"] = {
            "jisu": "2400", "sign": "4", "change": "-10", "drate": "-0.4",
        }
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock):
            await notify_index_data("001", "2500.5", "10.5", "0.5", "2")
            assert engine_state.state.index_data_cache["001"]["jisu"] == "2500.5"
            assert engine_state.state.index_data_cache["001"]["sign"] == "2"
        engine_state.state.index_data_cache.clear()


# ── notify_program_update ──────────────────────────────────────────────────────────

class TestNotifyProgramUpdate:
    @pytest.mark.asyncio
    async def test_basic(self):
        """프로그램 순매수 변경 시 구독 페이지에 master-cache-delta 전송 (마스터 캐시 단일 시세 소스)."""
        with patch("backend.app.web.ws_manager.ws_manager") as mock_wsm:
            mock_wsm.broadcast_to_code_subscribers = AsyncMock()
            await notify_program_update("005930", 100000)
            mock_wsm.broadcast_to_code_subscribers.assert_awaited_once()
            call = mock_wsm.broadcast_to_code_subscribers.call_args
            assert call.args[0] == "master-cache-delta"
            payload = call.args[1]
            assert payload["code"] == "005930"
            assert payload["fields"]["program_net_buy"] == 100000
            assert call.args[2] == "005930"


# ── notify_cache 경쟁 조건 시나리오 (세션 6 — _initialized 가드로 결함 해소) ────────
# 본 클래스는 notify_cache가 전역 싱글톤이므로 다중 WS 연결이 동시에 초기화될 때
# delta 기준점 덮어쓰기가 발생하는지를 시나리오로 고정한다.
# 세션 5에서 결함을 고정했고, 세션 6에서 _initialized 플래그 멱등성 가드로 해소.
# 시나리오 2·3·4는 결함 해소 단정으로 갱신되었으며, 시나리오 1·5는 양호 경로 유지.

class TestNotifyCacheConcurrencyScenarios:
    """세션 6 — notify_cache 전역 싱글톤 경쟁 조건 5개 시나리오 (_initialized 가드 적용)."""

    def test_scenario_1_single_connection_init_sets_delta_baseline(self):
        """시나리오 1: 단일 연결 초기화 → delta 기준점 정상 설정.

        양호 경로. init_sent_caches가 sector_stocks/positions/snapshot을
        전달받아 notify_cache의 delta 기준점을 일관되게 설정하는지 확인.
        """
        notify_cache.clear_all()
        sector_stocks = [{"code": "005930"}, {"code": "000660"}]
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}]
        snapshot = {"deposit": 5000000, "orderable": 4000000}
        init_sent_caches(sector_stocks, positions, snapshot)

        # delta 기준점이 모두 설정되었는지 검증
        assert notify_cache.prev_sector_stock_codes == {"005930", "000660"}
        assert notify_cache.position_sent["005930"]["cur_price"] == 80000
        assert notify_cache.snapshot_sent == snapshot
        # 초기화 직후 delta 캐시는 비어 있어야 함 (다음 전송이 전체 데이터 기준)
        assert notify_cache.prev_scores == []
        assert notify_cache.prev_buy_targets_map is None
        # 세션 6: _initialized 플래그가 True로 설정되어 후속 init 스킵 가드 활성화
        assert notify_cache._initialized is True

        # delta 계산이 기준점 기준으로 동작하는지 확인 (변경 없음 → 빈 delta)
        changed, removed = _compute_position_delta(positions)
        assert changed == []
        assert removed == []

    def test_scenario_2_second_connection_init_skipped_baseline_preserved(self):
        """시나리오 2: 다중 연결 동시 초기화 → 두 번째 init_sent_caches 스킵, 첫 번째 기준점 유지.

        세션 6 해소: _initialized 플래그 멱등성 가드로 두 번째 init이 no-op.
        연결 A 기준점이 그대로 유지되어 덮어쓰기 경쟁으로 인한 false positive delta 방지 (P22).
        """
        notify_cache.clear_all()

        # 연결 A 초기화 — 보유 2종목, snapshot 잔고 500만
        init_sent_caches(
            [{"code": "005930"}, {"code": "000660"}],
            [{"stk_cd": "005930", "qty": 10, "cur_price": 80000},
             {"stk_cd": "000660", "qty": 5, "cur_price": 100000}],
            {"deposit": 5000000, "orderable": 4000000},
        )
        baseline_a_positions = dict(notify_cache.position_sent)
        baseline_a_snapshot = dict(notify_cache.snapshot_sent)
        baseline_a_sector_codes = set(notify_cache.prev_sector_stock_codes)
        assert notify_cache._initialized is True

        # 연결 B 초기화 시도 — 보유 1종목(다른 종목), snapshot 잔고 300만
        init_sent_caches(
            [{"code": "035420"}],
            [{"stk_cd": "035420", "qty": 20, "cur_price": 50000}],
            {"deposit": 3000000, "orderable": 2500000},
        )

        # 연결 A 기준점이 그대로 유지되는지 검증 (세션 6 해소 단정)
        assert notify_cache.position_sent == baseline_a_positions
        assert "005930" in notify_cache.position_sent
        assert "000660" in notify_cache.position_sent
        assert "035420" not in notify_cache.position_sent
        assert notify_cache.snapshot_sent == baseline_a_snapshot
        assert notify_cache.prev_sector_stock_codes == baseline_a_sector_codes
        assert notify_cache.prev_sector_stock_codes == {"005930", "000660"}
        assert notify_cache._initialized is True

    def test_scenario_3_existing_connection_delta_uses_preserved_baseline(self):
        """시나리오 3: 기존 연결 delta 동작 중 새 연결 초기화 → 기존 연결 다음 delta가 정상 기준점에서 계산.

        세션 6 해소: 시나리오 2의 _initialized 가드로 연결 B의 init이 스킵되므로
        연결 A 기준점이 유지된다. 연결 A가 자신의 보유 종목(변동 없음)으로 delta를
        계산하면 false positive 없이 빈 delta가 나온다 (P22 정합성 보장).
        """
        notify_cache.clear_all()

        # 연결 A 기준점 — 보유 2종목
        positions_a = [{"stk_cd": "005930", "qty": 10, "cur_price": 80000},
                       {"stk_cd": "000660", "qty": 5, "cur_price": 100000}]
        init_sent_caches([{"code": "005930"}, {"code": "000660"}], positions_a,
                         {"deposit": 5000000})

        # 연결 B 초기화 시도 — 보유 1종목(005930만). _initialized=True이므로 스킵.
        init_sent_caches([{"code": "005930"}],
                         [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}],
                         {"deposit": 3000000})

        # 연결 A가 자신의 보유 종목(2종목 그대로)으로 delta를 계산하면?
        # 세션 6 해소: 기준점이 연결 A 그대로 유지되므로 변경 없음 → 빈 delta.
        changed, removed = _compute_position_delta(positions_a)
        assert changed == []
        assert removed == []

    def test_scenario_4_reset_realtime_fields_clears_baseline_and_reinit_restores(self):
        """시나리오 4: _reset_realtime_fields → clear_all() 전역 초기화 + _initialized 리셋 + 재초기화 정상.

        engine_initial_data._reset_realtime_fields가 notify_cache.clear_all()을 호출하여
        모든 delta 기준점을 초기화한다. 본 시점은 엔진 전체 재초기화(장마감·개시 등)이므로
        다중 연결 동시 초기화 정상 (P25 격리 — 한 연결 실패가 다른 연결 블로킹하지 않음).
        세션 6 해소: clear_all이 _initialized=False로 리셋 → 다음 init_sent_caches가
        정상 재설정. clear_all 직후 첫 delta는 full snapshot으로 전송되어 정합성 보장.
        """
        notify_cache.clear_all()
        # 기존 연결들이 delta 기준점을 가지고 있었다고 가정
        init_sent_caches([{"code": "005930"}, {"code": "000660"}],
                         [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}],
                         {"deposit": 5000000})
        assert notify_cache.position_sent != {}
        assert notify_cache.prev_sector_stock_codes != set()
        assert notify_cache.snapshot_sent != {}
        assert notify_cache._initialized is True

        # _reset_realtime_fields 내부의 clear_all() 호출 재현
        notify_cache.clear_all()

        # 모든 delta 기준점이 초기화되었는지 검증
        assert notify_cache.position_sent == {}
        assert notify_cache.snapshot_sent == {}
        assert notify_cache.prev_scores == []
        assert notify_cache.prev_sector_stock_codes == set()
        assert notify_cache.prev_sent == {}
        assert notify_cache.prev_buy_targets_map is None
        assert notify_cache.positions_code_set == set()
        assert notify_cache.layout_code_set == set()
        assert notify_cache.buy_targets_code_set == set()
        # 세션 6 해소: _initialized=False 리셋 → 다음 init이 정상 재설정 가능
        assert notify_cache._initialized is False

        # clear_all 직후 delta 계산 시 전체가 changed로 나오는 것은 정상 —
        # 첫 delta는 full snapshot으로 전송되어 정합성 보장 (P25 격리).
        changed, removed = _compute_position_delta(
            [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}]
        )
        assert len(changed) == 1
        assert changed[0]["stk_cd"] == "005930"

        # 세션 6 해소: clear_all 이후 init_sent_caches가 정상 재설정하는지 검증
        init_sent_caches([{"code": "005930"}, {"code": "000660"}],
                         [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}],
                         {"deposit": 5000000})
        assert notify_cache._initialized is True
        assert "005930" in notify_cache.position_sent
        assert notify_cache.prev_sector_stock_codes == {"005930", "000660"}
        # 재설정 후 동일 positions로 delta 계산 시 변경 없음 → 정상 복귀
        changed, removed = _compute_position_delta(
            [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}]
        )
        assert changed == []
        assert removed == []

    @pytest.mark.asyncio
    async def test_scenario_5_register_initial_data_does_not_touch_notify_cache(self):
        """시나리오 5: WSManager.register → _send_initial_data_on_connect는 notify_cache 건드리지 않음 (양호 경로).

        ws_manager._send_initial_data_on_connect는 buy-targets-update 단건 전송만
        수행하고 notify_cache의 delta 기준점을 변경하지 않는다.
        본 경로는 P25 격리 관점에서 양호하며, 세션 6 수정 시 유지되어야 함.
        """
        notify_cache.clear_all()
        # 기존 연결이 delta 기준점을 가지고 있었다고 가정
        init_sent_caches([{"code": "005930"}],
                         [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}],
                         {"deposit": 5000000})
        baseline_positions = dict(notify_cache.position_sent)
        baseline_snapshot = dict(notify_cache.snapshot_sent)
        baseline_sector_codes = set(notify_cache.prev_sector_stock_codes)
        baseline_buy_targets_map = notify_cache.prev_buy_targets_map

        # WSManager.register → _send_initial_data_on_connect 호출 재현
        from backend.app.web.ws_manager import WSManager
        from unittest.mock import MagicMock
        manager = WSManager()
        ws_mock = MagicMock()
        ws_mock.send_text = AsyncMock()

        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   new_callable=AsyncMock, return_value=[{"code": "005930"}]):
            await manager._send_initial_data_on_connect(ws_mock)

        # notify_cache delta 기준점이 변경되지 않았는지 검증 (양호 경로)
        assert notify_cache.position_sent == baseline_positions
        assert notify_cache.snapshot_sent == baseline_snapshot
        assert notify_cache.prev_sector_stock_codes == baseline_sector_codes
        assert notify_cache.prev_buy_targets_map is baseline_buy_targets_map
        # 세션 6: _initialized 플래그도 유지되어야 함 (register 경로는 init 건드리지 않음)
        assert notify_cache._initialized is True

        # buy-targets-update 단건 전송은 수행되었는지 확인
        ws_mock.send_text.assert_awaited_once()


# ── notify_buy_targets_update delta 계약 (세션 8 — payload 계약 정리) ────────────
# 본 클래스는 buy-targets-update/buy-targets-delta의 payload 계약을 고정한다.
# - 초기 전송: buy-targets-update 전체 리스트 (실시간 필드·news_boost 포함)
# - delta 전송: added/changed는 정적 필드만 (실시간 필드·news_boost 제거), removed는 코드 리스트
# - changed 판정: _BUY_TARGET_CMP_KEYS(정적 필드) 기준, news_boost 제외 (news-hit 단일 전달, P10)
# - 실시간 필드·news_boost 제거: _BUY_TARGET_REALTIME_KEYS 상수 기반 (P24 중복 제거)

class TestNotifyBuyTargetsUpdate:
    """세션 8 — notify_buy_targets_update payload 계약 단위 테스트."""

    def _make_target(self, code="005930", **overrides):
        base = {
            "code": code,
            "name": "삼성전자",
            "cur_price": 70000,
            "change": 500,
            "change_rate": 0.7,
            "strength": 1.2,
            "trade_amount": 1000000,
            "market_type": "KS",
            "nxt_enable": False,
            "sector": "반도체",
            "rank": 1,
            "guard_pass": True,
            "reject_reason": "",
            "boost_score": 5.0,
            "high_5d": 75000,
            "news_boost": 0.0,
            "order_ratio": [100, 200],
            "program_net_buy": None,
        }
        base.update(overrides)
        return base

    def test_cmp_keys_excludes_realtime_and_news_boost(self):
        """_BUY_TARGET_CMP_KEYS는 실시간 필드·news_boost 제외 (news-hit 단일 전달, P10)."""
        # 실시간 필드·news_boost 모두 제외
        for k in _BUY_TARGET_REALTIME_KEYS:
            assert k not in _BUY_TARGET_CMP_KEYS
        # news_boost 제외 (news-hit 이벤트가 단일 전달 경로, P10 SSOT)
        assert "news_boost" not in _BUY_TARGET_CMP_KEYS
        assert "news_boost" in _BUY_TARGET_REALTIME_KEYS  # delta 제외 그룹 포함 (안 A)
        # 정적 필드 포함
        for k in ("rank", "boost_score", "guard_pass", "reject_reason", "order_ratio",
                  "program_net_buy", "high_5d"):
            assert k in _BUY_TARGET_CMP_KEYS

    @pytest.mark.asyncio
    async def test_initial_send_buy_targets_update_with_realtime_fields(self):
        """초기 전송(prev=None): buy-targets-update 전체 리스트 (실시간 필드 포함)."""
        targets = [self._make_target("005930"), self._make_target("000660", rank=2)]
        # notify_cache.prev_buy_targets_map을 None으로 리셋
        notify_cache.prev_buy_targets_map = None
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=targets):
                await notify_buy_targets_update()
                mock_bc.assert_awaited_once()
                event, payload = mock_bc.call_args.args
                assert event == "buy-targets-update"
                assert payload["buy_targets"] == targets
                # 실시간 필드 포함 확인
                assert payload["buy_targets"][0]["cur_price"] == 70000
                assert payload["buy_targets"][0]["change"] == 500
        finally:
            notify_cache.prev_buy_targets_map = None

    @pytest.mark.asyncio
    async def test_delta_added_excludes_realtime_fields(self):
        """delta added: 정적 필드만 전송 (실시간 필드 제거)."""
        prev_map = {"005930": self._make_target("005930")}
        notify_cache.prev_buy_targets_map = prev_map
        # 새 종목 000660 added
        new_targets = [self._make_target("005930"), self._make_target("000660", rank=2)]
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=new_targets):
                await notify_buy_targets_update()
                mock_bc.assert_awaited_once()
                event, payload = mock_bc.call_args.args
                assert event == "buy-targets-delta"
                assert len(payload["added"]) == 1
                added = payload["added"][0]
                assert added["code"] == "000660"
                # 실시간 필드 제거 확인
                for k in _BUY_TARGET_REALTIME_KEYS:
                    assert k not in added
                # 정적 필드 유지 확인
                assert added["rank"] == 2
                # news_boost는 delta에서 제외 (news-hit 단일 전달, P10)
                assert "news_boost" not in added
        finally:
            notify_cache.prev_buy_targets_map = None

    @pytest.mark.asyncio
    async def test_delta_removed_sends_code_list_only(self):
        """delta removed: 종목 코드 리스트만 전송."""
        prev_map = {"005930": self._make_target("005930"), "000660": self._make_target("000660", rank=2)}
        notify_cache.prev_buy_targets_map = prev_map
        # 000660 제거
        new_targets = [self._make_target("005930")]
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=new_targets):
                await notify_buy_targets_update()
                mock_bc.assert_awaited_once()
                event, payload = mock_bc.call_args.args
                assert event == "buy-targets-delta"
                assert payload["removed"] == ["000660"]
                assert payload["added"] == []
                assert payload["changed"] == []
        finally:
            notify_cache.prev_buy_targets_map = None

    @pytest.mark.asyncio
    async def test_delta_changed_static_field_triggers_change(self):
        """delta changed: 정적 필드(rank) 변경 시 changed 전송 (실시간 필드 제거)."""
        prev_map = {"005930": self._make_target("005930", rank=1)}
        notify_cache.prev_buy_targets_map = prev_map
        # rank 변경 (1 → 2)
        new_targets = [self._make_target("005930", rank=2)]
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=new_targets):
                await notify_buy_targets_update()
                mock_bc.assert_awaited_once()
                event, payload = mock_bc.call_args.args
                assert event == "buy-targets-delta"
                assert len(payload["changed"]) == 1
                changed = payload["changed"][0]
                assert changed["code"] == "005930"
                assert changed["rank"] == 2
                # 실시간 필드 제거 확인
                for k in _BUY_TARGET_REALTIME_KEYS:
                    assert k not in changed
        finally:
            notify_cache.prev_buy_targets_map = None

    @pytest.mark.asyncio
    async def test_delta_changed_news_boost_does_not_trigger(self):
        """delta changed: news_boost만 변경 시 changed 미전송 (news-hit 단일 전달, P10)."""
        prev_map = {"005930": self._make_target("005930", news_boost=0.0)}
        notify_cache.prev_buy_targets_map = prev_map
        # news_boost만 변경 (0.0 → 1.5), 정적 필드 모두 동일
        new_targets = [self._make_target("005930", news_boost=1.5)]
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=new_targets):
                await notify_buy_targets_update()
                # news_boost는 cmp_keys에서 제외 → changed 없음 → 전송 생략
                mock_bc.assert_not_awaited()
        finally:
            notify_cache.prev_buy_targets_map = None

    @pytest.mark.asyncio
    async def test_delta_realtime_field_change_does_not_trigger(self):
        """delta changed: 실시간 필드(cur_price)만 변경 시 changed 미전송 (틱 디스패치 담당)."""
        prev_map = {"005930": self._make_target("005930", cur_price=70000)}
        notify_cache.prev_buy_targets_map = prev_map
        # cur_price만 변경 (70000 → 71000), 정적 필드 모두 동일
        new_targets = [self._make_target("005930", cur_price=71000)]
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=new_targets):
                await notify_buy_targets_update()
                # 변경 없음 → 전송 생략
                mock_bc.assert_not_awaited()
        finally:
            notify_cache.prev_buy_targets_map = None

    @pytest.mark.asyncio
    async def test_delta_no_change_skips_broadcast(self):
        """delta: added/removed/changed 모두 없으면 전송 생략."""
        prev_map = {"005930": self._make_target("005930")}
        notify_cache.prev_buy_targets_map = prev_map
        # 동일 타겟 (정적 필드 모두 동일, 실시간 필드는 변경 가능)
        new_targets = [self._make_target("005930", cur_price=71000, change=600)]
        try:
            with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
                 patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                       new_callable=AsyncMock, return_value=new_targets):
                await notify_buy_targets_update()
                mock_bc.assert_not_awaited()
        finally:
            notify_cache.prev_buy_targets_map = None

