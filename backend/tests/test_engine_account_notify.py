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
    notify_program_update,
    notify_index_data,
)
from backend.app.services.engine_account_broadcast import (
    _build_lightweight_payload_for_profit_overview,
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


# ── notify_index_data ────────────────────────────────────────────────────────────

class TestNotifyIndexData:
    """notify_index_data — 캐시 갱신 + WS 브로드캐스트 검증 (P10 SSOT)."""

    @pytest.mark.asyncio
    async def test_updates_cache_and_broadcasts(self):
        """정상 틱: 캐시 갱신 + index-data 브로드캐스트."""
        from backend.app.services import engine_state
        engine_state.state.index_data_cache.clear()
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"broker_statuses": {"ls": {"token_valid": True}}}):
            await notify_index_data("001", "2500.5", "10.5", "0.5", "2")
            # 캐시 갱신 검증
            assert engine_state.state.index_data_cache["001"] == {
                "jisu": "2500.5", "sign": "2", "change": "10.5", "drate": "0.5",
            }
            # 브로드캐스트 검증
            mock_bc.assert_awaited_once()
            payload = mock_bc.call_args.args[1]
            assert payload["upcode"] == "001"
            assert payload["jisu"] == "2500.5"
            assert payload["broker_statuses"] == {"ls": {"token_valid": True}}
        engine_state.state.index_data_cache.clear()

    @pytest.mark.asyncio
    async def test_overwrites_cache_on_new_tick(self):
        """새 틱 수신 시 기존 캐시 덮어쓰기 (종목 현재가와 동일 패턴)."""
        from backend.app.services import engine_state
        engine_state.state.index_data_cache.clear()
        engine_state.state.index_data_cache["001"] = {
            "jisu": "2400", "sign": "4", "change": "-10", "drate": "-0.4",
        }
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"broker_statuses": {}}):
            await notify_index_data("001", "2500.5", "10.5", "0.5", "2")
            assert engine_state.state.index_data_cache["001"]["jisu"] == "2500.5"
            assert engine_state.state.index_data_cache["001"]["sign"] == "2"
        engine_state.state.index_data_cache.clear()


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


# ── notify_cache 경쟁 조건 시나리오 (세션 5 — 책임 경계 검증) ──────────────────────
# 본 클래스는 notify_cache가 전역 싱글톤이므로 다중 WS 연결이 동시에 초기화될 때
# delta 기준점 덮어쓰기가 발생하는지를 시나리오로 고정한다.
# 프로덕션 코드는 수정하지 않으며, 현재 구조의 책임 경계를 테스트로 문서화한다.
# 세션 6에서 연결별 캐시 분리 또는 잠금 도입 시 본 시나리오가 회귀 기준이 된다.

class TestNotifyCacheConcurrencyScenarios:
    """세션 5 — notify_cache 전역 싱글톤 경쟁 조건 5개 시나리오 고정."""

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
        # 초기화 직후 delta 캐시는 비어 있어야 함 (다음 전송이 전체 스냅샷 기준)
        assert notify_cache.prev_scores == []
        assert notify_cache.prev_buy_targets_map is None

        # delta 계산이 기준점 기준으로 동작하는지 확인 (변경 없음 → 빈 delta)
        changed, removed = _compute_position_delta(positions)
        assert changed == []
        assert removed == []

    def test_scenario_2_second_connection_init_overwrites_first_baseline(self):
        """시나리오 2: 다중 연결 동시 초기화 → 두 번째 init_sent_caches가 첫 번째 기준점 덮어쓰기.

        현재 구조 결함 문서화. notify_cache는 전역 싱글톤이므로
        연결 A의 기준점을 설정한 뒤 연결 B가 init_sent_caches를 호출하면
        연결 A의 기준점이 연결 B 기준으로 교체된다.
        세션 6에서 연결별 캐시 분리 시 본 시나리오는 회귀 기준이 됨.
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

        # 연결 B 초기화 — 보유 1종목(다른 종목), snapshot 잔고 300만
        init_sent_caches(
            [{"code": "035420"}],
            [{"stk_cd": "035420", "qty": 20, "cur_price": 50000}],
            {"deposit": 3000000, "orderable": 2500000},
        )

        # 연결 A의 기준점이 연결 B 기준으로 완전히 교체되었는지 검증 (현재 구조 동작)
        assert notify_cache.position_sent != baseline_a_positions
        assert "005930" not in notify_cache.position_sent
        assert "000660" not in notify_cache.position_sent
        assert "035420" in notify_cache.position_sent
        assert notify_cache.snapshot_sent != baseline_a_snapshot
        assert notify_cache.prev_sector_stock_codes != baseline_a_sector_codes
        assert notify_cache.prev_sector_stock_codes == {"035420"}

        # 결함 문서화: 연결 A가 이후 delta를 계산하면 자신의 원래 기준점이 아닌
        # 연결 B 기준점에서 계산하게 됨 (P22 데이터 정합성 위반 가능).
        # 단, 본 시나리오는 동작 고정이며 결함 수정은 세션 6에서 수행.

    def test_scenario_3_existing_connection_delta_uses_overwritten_baseline(self):
        """시나리오 3: 기존 연결 delta 동작 중 새 연결 초기화 → 기존 연결 다음 delta가 잘못된 기준점에서 계산.

        시나리오 2의 결과를 delta 계산에 직접 반영하여 정합성 위반을 재현.
        연결 A가 보유 2종목 기준점을 가진 상태에서 연결 B가 1종목 기준점으로 덮어쓰면,
        연결 A가 이어서 delta를 계산할 때 000660이 '제거된' 것으로 잘못 감지된다.
        """
        notify_cache.clear_all()

        # 연결 A 기준점 — 보유 2종목
        positions_a = [{"stk_cd": "005930", "qty": 10, "cur_price": 80000},
                       {"stk_cd": "000660", "qty": 5, "cur_price": 100000}]
        init_sent_caches([{"code": "005930"}, {"code": "000660"}], positions_a,
                         {"deposit": 5000000})

        # 연결 B 기준점 덮어쓰기 — 보유 1종목(005930만)
        init_sent_caches([{"code": "005930"}],
                         [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}],
                         {"deposit": 3000000})

        # 연결 A가 자신의 보유 종목(2종목 그대로)으로 delta를 계산하면?
        # 실제 보유는 변동 없지만, 기준점이 연결 B 기준(1종목)으로 교체되어
        # 000660이 '새로 추가된' 것으로 잘못 감지됨 (false positive).
        changed, removed = _compute_position_delta(positions_a)
        changed_codes = {c["stk_cd"] for c in changed}
        assert "000660" in changed_codes  # 잘못된 delta — 실제로는 변경 없어야 함
        assert removed == []

        # 결함 문서화: 연결 A 입장에서는 보유 변동이 없는데도 delta가 발생.
        # P22 위반. 세션 6에서 연결별 캐시 분리 시 본 단정이 실패해야 정상.

    def test_scenario_4_reset_realtime_fields_destroys_global_baseline(self):
        """시나리오 4: _reset_realtime_fields → notify_cache.clear_all() 전역 파괴.

        engine_snapshot._reset_realtime_fields가 notify_cache.clear_all()을
        호출하여 모든 delta 기준점을 한 번에 날린다. 한 연결의 구독 시작이
        다른 연결의 delta 기준점까지 파괴하는 P25 격리 위반 가능성 문서화.
        본 시나리오는 clear_all의 전역 파괴 동작을 고정.
        """
        notify_cache.clear_all()
        # 기존 연결들이 delta 기준점을 가지고 있었다고 가정
        init_sent_caches([{"code": "005930"}, {"code": "000660"}],
                         [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}],
                         {"deposit": 5000000})
        assert notify_cache.position_sent != {}
        assert notify_cache.prev_sector_stock_codes != set()
        assert notify_cache.snapshot_sent != {}

        # _reset_realtime_fields 내부의 clear_all() 호출 재현
        notify_cache.clear_all()

        # 모든 delta 기준점이 파괴되었는지 검증
        assert notify_cache.position_sent == {}
        assert notify_cache.snapshot_sent == {}
        assert notify_cache.prev_scores == []
        assert notify_cache.prev_sector_stock_codes == set()
        assert notify_cache.prev_sent == {}
        assert notify_cache.prev_buy_targets_map is None
        assert notify_cache.positions_code_set == set()
        assert notify_cache.layout_code_set == set()
        assert notify_cache.buy_targets_code_set == set()
        assert notify_cache.prev_receive_rate is None

        # 결함 문서화: 기존 연결이 delta를 계산하면 모든 종목이 '새로 추가된' 것으로 감지.
        # clear_all 직후 delta 계산 시 전체가 changed로 나옴 (false positive).
        changed, removed = _compute_position_delta(
            [{"stk_cd": "005930", "qty": 10, "cur_price": 80000}]
        )
        assert len(changed) == 1
        assert changed[0]["stk_cd"] == "005930"

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

        # buy-targets-update 단건 전송은 수행되었는지 확인
        ws_mock.send_text.assert_awaited_once()

