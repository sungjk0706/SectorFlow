"""page_subscription_targets.py 2세션 테스트 — 활성 연결 갱신·초기 스냅샷·재연결.

태스크 2세션(백엔드 전달·재연결) 8절 요구사항 검증.
ws_manager diff 갱신·자료 화면 스냅샷·원본 변경 시 활성 연결 갱신·재연결 복구.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.page_subscription_targets import (
    page_targets,
    ALLOWED_PAGE_KEYS,
    STOCK_SUBSCRIPTION_PAGES,
    PAGE_SECTOR_RANKING,
    PAGE_BUY_TARGET,
    PAGE_SELL_POSITION,
    PAGE_PROFIT_OVERVIEW,
    PAGE_PROFIT_DETAIL,
    PAGE_STOCK_CLASSIFICATION,
    PAGE_STOCK_DETAIL,
    PAGE_SETTINGS,
    handle_page_active,
    refresh_active_connections,
    _build_data_page_snapshot,
)


# ── 공통 fixture ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_registry():
    """각 테스트 전 저장소 초기화 — 상태 누출 방지."""
    page_targets.reset()
    yield
    page_targets.reset()


def _mock_state(**overrides):
    """engine_state.state mock 생성."""
    mock = MagicMock()
    mock.master_stocks_cache = overrides.get("master_stocks_cache", {"005930": {"name": "삼성전자"}})
    mock.sector_summary_cache = overrides.get("sector_summary_cache", None)
    mock.integrated_system_settings_cache = overrides.get(
        "integrated_system_settings_cache", {"trade_mode": "test"}
    )
    mock.account_rest_bootstrapped = overrides.get("account_rest_bootstrapped", False)
    mock.sector_summary_ready_event = overrides.get(
        "sector_summary_ready_event", MagicMock(is_set=MagicMock(return_value=True))
    )
    return mock


def _make_ws():
    """WebSocket mock 생성."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


# ── 1. 페이지 이름만으로 종목 실시간 4화면 활성화 ──────────────────────────

class TestPageActiveStockSubscription:
    """코드 없이 종목 실시간 4화면 활성화 시 저장된 대상이 등록되는지."""

    async def test_sector_ranking_active_without_codes_uses_registry(self):
        """업종 순위 — codes 없이 활성화 시 저장소 대상으로 구독 등록."""
        # 저장소에 대상 미리 설정.
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["005930", "000660"]
        st.ready = True

        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": []})):
            await handle_page_active(ws, PAGE_SECTOR_RANKING, None)

        # ws_manager에 활성 페이지 설정 + 구독 코드 등록 확인.
        from backend.app.web.ws_manager import ws_manager
        assert ws_manager._client_active_page.get(ws) == PAGE_SECTOR_RANKING
        assert ws_manager._client_subscribed_codes.get(ws) == {"005930", "000660"}
        ws_manager.unregister(ws)

    async def test_buy_target_active_without_codes_uses_registry(self):
        """매수 후보 — codes 없이 활성화 시 저장소 대상으로 구독 등록."""
        st = page_targets._ensure_state(PAGE_BUY_TARGET)
        st.codes = ["A", "B"]
        st.ready = True

        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": []})):
            await handle_page_active(ws, PAGE_BUY_TARGET, None)

        from backend.app.web.ws_manager import ws_manager
        assert ws_manager._client_subscribed_codes.get(ws) == {"A", "B"}
        ws_manager.unregister(ws)

    async def test_stock_subscription_not_ready_skips_snapshot(self):
        """저장소 미준비 시 빈 스냅샷을 정상 데이터처럼 보내지 않음."""
        page_targets._ensure_state(PAGE_SECTOR_RANKING)  # ready=False 상태.

        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            await handle_page_active(ws, PAGE_SECTOR_RANKING, None)

        # 활성 페이지는 설정되지만 구독 코드는 등록되지 않음.
        from backend.app.web.ws_manager import ws_manager
        assert ws_manager._client_active_page.get(ws) == PAGE_SECTOR_RANKING
        assert ws_manager._client_subscribed_codes.get(ws) is None
        ws_manager.unregister(ws)

    async def test_codes_explicit_compatibility(self):
        """codes 명시 시 전환 기간 호환 — 저장소 무시하고 명시된 codes 사용."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["OLD"]
        st.ready = True

        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": []})):
            await handle_page_active(ws, PAGE_SECTOR_RANKING, ["NEW1", "NEW2"])

        from backend.app.web.ws_manager import ws_manager
        assert ws_manager._client_subscribed_codes.get(ws) == {"NEW1", "NEW2"}
        ws_manager.unregister(ws)


# ── 2. 자료 중심 4화면 활성화 시 자료 스냅샷 전송 ──────────────────────────

class TestPageActiveDataPages:
    """코드 없이 자료 중심 4화면 활성화 시 자료 스냅샷이 전송되는지."""

    async def test_profit_detail_snapshot_sent(self):
        """수익 상세 활성화 시 이력 초기 스냅샷 전송."""
        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data._get_trade_history_for_snapshot",
                   new=AsyncMock(return_value=[{"code": "A"}])), \
             patch("backend.app.services.engine_initial_data._get_daily_summary_for_snapshot",
                   new=AsyncMock(return_value=[])):
            await handle_page_active(ws, PAGE_PROFIT_DETAIL, None)

        # profit-detail-snapshot 이벤트 전송 확인.
        sent = ws.send_text.call_args_list
        assert any("profit-detail-snapshot" in str(c) for c in sent)

    async def test_settings_snapshot_sent(self):
        """일반 설정 활성화 시 민감 정보가 가려진 설정 스냅샷 전송."""
        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_config._mask_sensitive_settings",
                   return_value={"trade_mode": "test", "broker_app_key": "***"}):
            await handle_page_active(ws, PAGE_SETTINGS, None)

        sent = ws.send_text.call_args_list
        assert any("settings-snapshot" in str(c) for c in sent)


# ── 3. 새 연결이 이미 구독 중인 종목을 요청해도 초기 스냅샷 수신 ────────────

class TestNewConnectionGetsSnapshot:
    """다른 연결이 이미 구독 중인 종목을 새 연결이 요청해도 초기 스냅샷을 받는지."""

    async def test_second_connection_gets_snapshot(self):
        """연결 A가 종목 X를 구독 중일 때 연결 B가 같은 종목을 요청해도 스냅샷 수신."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["005930"]
        st.ready = True

        ws_a = _make_ws()
        ws_b = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": [{"code": "005930"}]})):
            await handle_page_active(ws_a, PAGE_SECTOR_RANKING, None)
            await handle_page_active(ws_b, PAGE_SECTOR_RANKING, None)

        # 두 연결 모두 스냅샷을 받아야 함.
        assert ws_a.send_text.called
        assert ws_b.send_text.called

        from backend.app.web.ws_manager import ws_manager
        ws_manager.unregister(ws_a)
        ws_manager.unregister(ws_b)


# ── 4. 대상 추가·제거 시 연결별 등록·해지 ──────────────────────────────────

class TestUpdateSubscriptionDiff:
    """ws_manager.update_subscription_diff — 추가·제거·유지 정확성."""

    def test_added_codes_returned_as_newly_subscribed(self):
        from backend.app.web.ws_manager import ws_manager
        ws = _make_ws()
        # 초기 구독 설정.
        ws_manager.subscribe_codes(ws, "test", ["A", "B"])
        # 대상 변경 — C 추가, B 제거, A 유지.
        newly, removed = ws_manager.update_subscription_diff(ws, "test", ["A", "C"])
        assert newly == {"C"}
        assert removed == {"B"}
        ws_manager.unregister(ws)

    def test_removed_codes_unsubscribed(self):
        from backend.app.web.ws_manager import ws_manager
        ws = _make_ws()
        ws_manager.subscribe_codes(ws, "test", ["A", "B"])
        newly, removed = ws_manager.update_subscription_diff(ws, "test", ["A"])
        assert newly == set()
        assert removed == {"B"}
        # B는 구독자가 없으므로 _symbol_subscribers에서 제거됨.
        assert "B" not in ws_manager._symbol_subscribers
        ws_manager.unregister(ws)

    def test_unchanged_codes_kept(self):
        from backend.app.web.ws_manager import ws_manager
        ws = _make_ws()
        ws_manager.subscribe_codes(ws, "test", ["A", "B"])
        newly, removed = ws_manager.update_subscription_diff(ws, "test", ["A", "B"])
        assert newly == set()
        assert removed == set()
        ws_manager.unregister(ws)


# ── 5. 대상 변경 없을 때 중복 스냅샷 미발생 ────────────────────────────────

class TestNoDuplicateSnapshotOnUnchanged:
    """대상 변경이 없을 때 중복 스냅샷이 발생하지 않는지."""

    async def test_refresh_active_connections_no_change_no_snapshot(self):
        """갱신 결과 changed=False 시 활성 연결에 스냅샷 미전송."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["A"]
        st.ready = True
        st.change_no = 1

        ws = _make_ws()
        from backend.app.web.ws_manager import ws_manager
        ws_manager._clients.add(ws)
        ws_manager.set_active_page(ws, PAGE_SECTOR_RANKING)
        ws_manager.subscribe_codes(ws, PAGE_SECTOR_RANKING, ["A"])

        # 같은 대상으로 갱신 — changed=False.
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["A"]})):
            results = await refresh_active_connections("테스트", {PAGE_SECTOR_RANKING})

        assert results[PAGE_SECTOR_RANKING].changed is False
        # 스냅샷 전송 호출 없어야 함 (send_text 호출 없음).
        assert not ws.send_text.called
        ws_manager._clients.discard(ws)
        ws_manager.unregister(ws)


# ── 6. 원본 변경 시 활성 연결 갱신 ────────────────────────────────────────

class TestRefreshActiveConnections:
    """원본 변경 시 활성 연결의 대상이 자동으로 최신화되는지."""

    async def test_added_code_gets_snapshot(self):
        """대상 추가 시 추가 종목에 초기 스냅샷 전송."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["A"]
        st.ready = True
        st.change_no = 1

        ws = _make_ws()
        from backend.app.web.ws_manager import ws_manager
        ws_manager._clients.add(ws)
        ws_manager.set_active_page(ws, PAGE_SECTOR_RANKING)
        ws_manager.subscribe_codes(ws, PAGE_SECTOR_RANKING, ["A"])

        # 새 대상 — B 추가.
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["A", "B"]})), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": []})):
            results = await refresh_active_connections("테스트", {PAGE_SECTOR_RANKING})

        assert results[PAGE_SECTOR_RANKING].changed is True
        assert "B" in results[PAGE_SECTOR_RANKING].added
        # 스냅샷 전송 호출 있어야 함.
        assert ws.send_text.called
        ws_manager._clients.discard(ws)
        ws_manager.unregister(ws)

    async def test_removed_code_unsubscribed(self):
        """대상 제거 시 제거 종목은 연결에서 해지."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["A", "B"]
        st.ready = True
        st.change_no = 1

        ws = _make_ws()
        from backend.app.web.ws_manager import ws_manager
        ws_manager._clients.add(ws)
        ws_manager.set_active_page(ws, PAGE_SECTOR_RANKING)
        ws_manager.subscribe_codes(ws, PAGE_SECTOR_RANKING, ["A", "B"])

        # 새 대상 — B 제거.
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["A"]})):
            results = await refresh_active_connections("테스트", {PAGE_SECTOR_RANKING})

        assert results[PAGE_SECTOR_RANKING].changed is True
        assert "B" in results[PAGE_SECTOR_RANKING].removed
        # B는 구독 해지됨.
        assert "B" not in ws_manager._client_subscribed_codes.get(ws, set())
        ws_manager._clients.discard(ws)
        ws_manager.unregister(ws)

    async def test_no_active_clients_skips_broadcast(self):
        """활성 연결이 없으면 갱신만 수행하고 전송 생략."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["A"]
        st.ready = True
        st.change_no = 1

        # 활성 연결 없음.
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["A", "B"]})):
            results = await refresh_active_connections("테스트", {PAGE_SECTOR_RANKING})

        assert results[PAGE_SECTOR_RANKING].changed is True
        # 활성 연결 없으므로 예외 없이 완료.


# ── 7. 페이지 비활성화·연결 해제 시 구독 정리 ──────────────────────────────

class TestPageInactiveCleanup:
    """페이지 비활성화·연결 해제 시 구독이 정리되는지."""

    def test_page_inactive_clears_subscribed_codes(self):
        from backend.app.web.ws_manager import ws_manager
        ws = _make_ws()
        ws_manager.set_active_page(ws, "test")
        ws_manager.subscribe_codes(ws, "test", ["A", "B"])
        assert ws_manager._client_subscribed_codes.get(ws) == {"A", "B"}

        ws_manager.clear_active_page(ws)
        assert ws_manager._client_subscribed_codes.get(ws) is None
        assert ws_manager._client_active_page.get(ws) is None

    def test_unregister_clears_all(self):
        from backend.app.web.ws_manager import ws_manager
        ws = _make_ws()
        ws_manager.set_active_page(ws, "test")
        ws_manager.subscribe_codes(ws, "test", ["A"])
        ws_manager.unregister(ws)
        assert ws not in ws_manager._clients
        assert ws not in ws_manager._client_active_page
        assert ws not in ws_manager._client_subscribed_codes


# ── 8. 재연결 시 페이지 이름만으로 최신 대상 복구 ──────────────────────────

class TestReconnectRecovery:
    """재연결 시 페이지 이름만으로 최신 대상이 복구되는지."""

    async def test_reconnect_uses_latest_registry_codes(self):
        """재연결 시 저장소의 최신 대상을 사용해 구독 복구."""
        # 저장소에 최신 대상 설정 (재연결 전 이미 갱신됨).
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["LATEST1", "LATEST2"]
        st.ready = True

        ws = _make_ws()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": []})):
            # 재연결 시 프론트엔드가 page-active 재전송 (codes 없음).
            await handle_page_active(ws, PAGE_SECTOR_RANKING, None)

        from backend.app.web.ws_manager import ws_manager
        # 최신 대상으로 구독 복구됨.
        assert ws_manager._client_subscribed_codes.get(ws) == {"LATEST1", "LATEST2"}
        ws_manager.unregister(ws)

    async def test_reconnect_no_stale_codes(self):
        """이전 연결의 구독 코드가 새 연결에 남지 않음."""
        st = page_targets._ensure_state(PAGE_SECTOR_RANKING)
        st.codes = ["NEW"]
        st.ready = True

        ws_old = _make_ws()
        ws_new = _make_ws()
        from backend.app.web.ws_manager import ws_manager

        # 이전 연결에서 OLD 구독.
        ws_manager.set_active_page(ws_old, PAGE_SECTOR_RANKING)
        ws_manager.subscribe_codes(ws_old, PAGE_SECTOR_RANKING, ["OLD"])

        # 이전 연결 해제.
        ws_manager.unregister(ws_old)

        # 새 연결 — 저장소의 최신 대상(NEW)만 구독.
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data.build_master_cache_snapshot",
                   new=AsyncMock(return_value={"_v": 1, "stocks": []})):
            await handle_page_active(ws_new, PAGE_SECTOR_RANKING, None)

        assert ws_manager._client_subscribed_codes.get(ws_new) == {"NEW"}
        # OLD는 이전 연결 해제로 _symbol_subscribers에서 제거됨.
        assert "OLD" not in ws_manager._symbol_subscribers
        ws_manager.unregister(ws_new)


# ── 9. 자료 화면 스냅샷 빌더 ──────────────────────────────────────────────

class TestDataPageSnapshotBuilder:
    """자료 중심 4화면 스냅샷 빌더 — 원본에서 자료 조회."""

    async def test_profit_detail_snapshot_contains_histories(self):
        """수익 상세 스냅샷 — 매수·매도 이력 + 일별 요약 포함."""
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_initial_data._get_trade_history_for_snapshot",
                   new=AsyncMock(return_value=[{"code": "A"}])), \
             patch("backend.app.services.engine_initial_data._get_daily_summary_for_snapshot",
                   new=AsyncMock(return_value=[{"date": "2026-08-01"}])):
            payload = await _build_data_page_snapshot(PAGE_PROFIT_DETAIL)
        assert "buy_history" in payload
        assert "sell_history" in payload
        assert "daily_summary" in payload

    async def test_settings_snapshot_masks_sensitive(self):
        """일반 설정 스냅샷 — 민감 정보 마스킹."""
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.services.engine_config._mask_sensitive_settings",
                   return_value={"trade_mode": "test", "broker_app_key": "***"}):
            payload = await _build_data_page_snapshot(PAGE_SETTINGS)
        assert payload["broker_app_key"] == "***"

    async def test_unsupported_page_returns_none(self):
        """지원하지 않는 페이지 키 — None 반환."""
        result = await _build_data_page_snapshot("unknown-page")
        assert result is None


# ── 10. 지원하지 않는 페이지 이름 처리 ────────────────────────────────────

class TestUnsupportedPage:
    """지원하지 않는 페이지 이름 — 기존 처리 규칙 유지."""

    async def test_unsupported_page_active_no_op(self):
        """허용되지 않은 페이지 키 — handle_page_active 아무 동작 없음."""
        ws = _make_ws()
        await handle_page_active(ws, "unknown", None)
        # 활성 페이지 설정되지 않음.
        from backend.app.web.ws_manager import ws_manager
        assert ws_manager._client_active_page.get(ws) is None
