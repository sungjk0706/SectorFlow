"""Web 라우트 단위 테스트 — deps, ws_orders, ws_settings, ws_subscribe.

WebSocket 핸들러는 mock WebSocket으로 accept/register/receive_text/send_text 흐름 검증.
ws_subscribe는 POST 핸들러이므로 함수 직접 호출.
deps는 get_current_user 함수 직접 호출.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Initialize queues before any lazy import of pipeline_compute (module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues
initialize_queues()


# ── deps.py ───────────────────────────────────────────────────────────────────

class TestGetCurrentUser:
    """deps.py: get_current_user — 현재 개발 모드로 항상 'dev' 반환."""

    async def test_returns_dev_in_dev_mode(self):
        from backend.app.web.deps import get_current_user
        result = await get_current_user(credentials=None)
        assert result == "dev"

    async def test_returns_dev_with_credentials(self):
        from backend.app.web.deps import get_current_user
        mock_creds = MagicMock()
        mock_creds.credentials = "fake_token"
        result = await get_current_user(credentials=mock_creds)
        assert result == "dev"


# ── ws_orders.py ──────────────────────────────────────────────────────────────

class TestWsOrders:
    """ws_orders.py: WebSocket 체결 전용 채널."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.ws_orders import router
        assert router.prefix == "/api/ws"
        assert "websocket" in router.tags

    def test_router_has_one_route(self):
        from backend.app.web.routes.ws_orders import router
        assert len(router.routes) == 1

    async def test_ping_returns_pong(self):
        from backend.app.web.routes.ws_orders import ws_orders

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "ping"}),
            Exception("disconnect"),  # 루프 탈출용
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_orders.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            await ws_orders(ws, token="test")

        # pong 응답 확인
        sent = [json.loads(c.args[0]) for c in ws.send_text.call_args_list]
        assert {"type": "pong"} in sent

    async def test_invalid_json_ignored(self):
        from backend.app.web.routes.ws_orders import ws_orders

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            "not json{{{",
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_orders.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            await ws_orders(ws, token="test")

        ws.send_text.assert_not_called()

    async def test_non_dict_message_ignored(self):
        from backend.app.web.routes.ws_orders import ws_orders

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps(["not", "a", "dict"]),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_orders.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            await ws_orders(ws, token="test")

        ws.send_text.assert_not_called()

    async def test_websocket_disconnect_handled(self):
        from backend.app.web.routes.ws_orders import ws_orders
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_orders.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 0
            await ws_orders(ws, token="test")

        mock_mgr.unregister.assert_called_once_with(ws)

    async def test_unregister_always_called(self):
        """정상 종료든 예외든 finally에서 unregister 호출."""
        from backend.app.web.routes.ws_orders import ws_orders

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=RuntimeError("unexpected"))
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_orders.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 0
            await ws_orders(ws, token="test")

        mock_mgr.unregister.assert_called_once_with(ws)

    async def test_register_called_on_connect(self):
        from backend.app.web.routes.ws_orders import ws_orders

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=Exception("disconnect"))
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_orders.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            await ws_orders(ws, token="test")

        ws.accept.assert_called_once()
        mock_mgr.register.assert_called_once_with(ws)


# ── ws_settings.py ────────────────────────────────────────────────────────────

class TestWsSettings:
    """ws_settings.py: WebSocket 설정/진행률 전용 채널."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.ws_settings import router
        assert router.prefix == "/api/ws"
        assert "websocket" in router.tags

    def test_router_has_one_route(self):
        from backend.app.web.routes.ws_settings import router
        assert len(router.routes) == 1

    async def test_ping_returns_pong(self):
        from backend.app.web.routes.ws_settings import ws_settings

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "ping"}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            await ws_settings(ws, token="test")

        sent = [json.loads(c.args[0]) for c in ws.send_text.call_args_list]
        assert {"type": "pong"} in sent

    async def test_page_active_sets_active_page(self):
        from backend.app.web.routes.ws_settings import ws_settings

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "page-active", "page": "buy-target"}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.set_active_page = MagicMock()
            mock_mgr.clear_active_page = MagicMock()
            mock_mgr.client_count = 1
            await ws_settings(ws, token="test")

        mock_mgr.set_active_page.assert_called_once_with(ws, "buy-target")

    async def test_page_inactive_clears_active_page(self):
        from backend.app.web.routes.ws_settings import ws_settings

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "page-inactive"}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.set_active_page = MagicMock()
            mock_mgr.clear_active_page = MagicMock()
            mock_mgr.client_count = 1
            await ws_settings(ws, token="test")

        mock_mgr.clear_active_page.assert_called_once_with(ws)

    async def test_page_active_empty_page_ignored(self):
        from backend.app.web.routes.ws_settings import ws_settings

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "page-active", "page": ""}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.set_active_page = MagicMock()
            mock_mgr.clear_active_page = MagicMock()
            mock_mgr.client_count = 1
            await ws_settings(ws, token="test")

        mock_mgr.set_active_page.assert_not_called()

    async def test_websocket_disconnect_handled(self):
        from backend.app.web.routes.ws_settings import ws_settings
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 0
            await ws_settings(ws, token="test")

        mock_mgr.unregister.assert_called_once_with(ws)

    async def test_unregister_always_called(self):
        from backend.app.web.routes.ws_settings import ws_settings

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=RuntimeError("unexpected"))
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 0
            await ws_settings(ws, token="test")

        mock_mgr.unregister.assert_called_once_with(ws)

    async def test_invalid_json_ignored(self):
        from backend.app.web.routes.ws_settings import ws_settings

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            "not json",
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws_settings.ws_manager") as mock_mgr:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            await ws_settings(ws, token="test")

        ws.send_text.assert_not_called()


# ── ws_subscribe.py ───────────────────────────────────────────────────────────

class TestSubscribeGroup:
    """ws_subscribe.py: SubscribeGroup Enum 검증."""

    def test_sector_value(self):
        from backend.app.web.routes.ws_subscribe import SubscribeGroup
        assert SubscribeGroup.sector.value == "sector"

    def test_industry_value(self):
        from backend.app.web.routes.ws_subscribe import SubscribeGroup
        assert SubscribeGroup.industry.value == "industry"

    def test_quote_value(self):
        from backend.app.web.routes.ws_subscribe import SubscribeGroup
        assert SubscribeGroup.quote.value == "quote"


class TestSubscribeRequest:
    """ws_subscribe.py: SubscribeRequest Pydantic 모델 검증."""

    def test_valid_request(self):
        from backend.app.web.routes.ws_subscribe import SubscribeRequest, SubscribeGroup
        req = SubscribeRequest(group=SubscribeGroup.quote)
        assert req.group == SubscribeGroup.quote

    def test_string_group_accepted(self):
        from backend.app.web.routes.ws_subscribe import SubscribeRequest
        req = SubscribeRequest(group="quote")
        assert req.group.value == "quote"


class TestStartSubscription:
    """ws_subscribe.py: POST /api/ws-subscribe/start — 수동 구독 시작."""

    async def test_outside_window_raises_400(self):
        from backend.app.web.routes.ws_subscribe import start_subscription, SubscribeRequest, SubscribeGroup
        from fastapi import HTTPException
        from backend.app.services.engine_state import state

        state.integrated_system_settings_cache = {"test": True}
        req = SubscribeRequest(group=SubscribeGroup.quote)
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await start_subscription(req, _="dev")
        assert exc_info.value.status_code == 400

    async def test_sector_returns_status(self):
        from backend.app.web.routes.ws_subscribe import start_subscription, SubscribeRequest, SubscribeGroup
        from backend.app.services.engine_state import state

        state.integrated_system_settings_cache = {"test": True}
        req = SubscribeRequest(group=SubscribeGroup.sector)
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True):
            with patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={"quote": False}):
                result = await start_subscription(req, _="dev")
        assert result["ok"] is True
        assert "status" in result

    async def test_industry_returns_status(self):
        from backend.app.web.routes.ws_subscribe import start_subscription, SubscribeRequest, SubscribeGroup
        from backend.app.services.engine_state import state

        state.integrated_system_settings_cache = {"test": True}
        req = SubscribeRequest(group=SubscribeGroup.industry)
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True):
            with patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={"industry": False}):
                result = await start_subscription(req, _="dev")
        assert result["ok"] is True

    async def test_quote_start_success(self):
        from backend.app.web.routes.ws_subscribe import start_subscription, SubscribeRequest, SubscribeGroup
        from backend.app.services.engine_state import state

        state.integrated_system_settings_cache = {"test": True}
        req = SubscribeRequest(group=SubscribeGroup.quote)
        mock_result = {"ok": True, "status": {"quote": True}}
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True):
            with patch("backend.app.services.ws_subscribe_control.start_quote", new_callable=AsyncMock, return_value=mock_result):
                result = await start_subscription(req, _="dev")
        assert result["ok"] is True
        assert result["status"] == {"quote": True}

    async def test_quote_start_failure(self):
        from backend.app.web.routes.ws_subscribe import start_subscription, SubscribeRequest, SubscribeGroup
        from backend.app.services.engine_state import state

        state.integrated_system_settings_cache = {"test": True}
        req = SubscribeRequest(group=SubscribeGroup.quote)
        mock_result = {"ok": False, "message": "이미 구독 중"}
        with patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True):
            with patch("backend.app.services.ws_subscribe_control.start_quote", new_callable=AsyncMock, return_value=mock_result):
                result = await start_subscription(req, _="dev")
        assert result["ok"] is False
        assert "이미 구독 중" in result["message"]


class TestStopSubscription:
    """ws_subscribe.py: POST /api/ws-subscribe/stop — 수동 구독 해지."""

    async def test_sector_stops_industry(self):
        from backend.app.web.routes.ws_subscribe import stop_subscription, SubscribeRequest, SubscribeGroup
        req = SubscribeRequest(group=SubscribeGroup.sector)
        with patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={"quote": False}):
            result = await stop_subscription(req, _="dev")
        assert result["ok"] is True

    async def test_industry_stop_success(self):
        from backend.app.web.routes.ws_subscribe import stop_subscription, SubscribeRequest, SubscribeGroup
        req = SubscribeRequest(group=SubscribeGroup.industry)
        with patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={"quote": False}):
            result = await stop_subscription(req, _="dev")
        assert result["ok"] is True
        assert result["status"] == {"quote": False}

    async def test_quote_stop_success(self):
        from backend.app.web.routes.ws_subscribe import stop_subscription, SubscribeRequest, SubscribeGroup
        req = SubscribeRequest(group=SubscribeGroup.quote)
        with patch("backend.app.services.ws_subscribe_control.stop_quote", new_callable=AsyncMock, return_value={"ok": True, "status": {"quote": False}}):
                result = await stop_subscription(req, _="dev")
        assert result["ok"] is True
        assert result["status"] == {"quote": False}

    async def test_quote_stop_failure(self):
        from backend.app.web.routes.ws_subscribe import stop_subscription, SubscribeRequest, SubscribeGroup
        req = SubscribeRequest(group=SubscribeGroup.quote)
        with patch("backend.app.services.ws_subscribe_control.stop_quote", new_callable=AsyncMock, return_value={"ok": False, "message": "미구독 상태"}):
                result = await stop_subscription(req, _="dev")
        assert result["ok"] is False
        assert "미구독 상태" in result["message"]

class TestWsSubscribeRouter:
    """ws_subscribe.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.ws_subscribe import router
        assert router.prefix == "/api/ws-subscribe"
        assert "ws-subscribe" in router.tags

    def test_router_has_two_routes(self):
        from backend.app.web.routes.ws_subscribe import router
        assert len(router.routes) == 2


# ── ws.py ─────────────────────────────────────────────────────────────────────

class TestSendInitialSnapshotDelayed:
    """ws.py: _send_initial_snapshot_delayed — 초기 스냅샷 순차 유니캐스트."""

    async def test_full_snapshot_sequence(self):
        from backend.app.web.routes.ws import _send_initial_snapshot_delayed

        ws = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.send_to = AsyncMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"trade_mode": "test"}), \
             patch("backend.app.core.stock_classification_data.load_custom_data", return_value=MagicMock(sectors={}, stock_moves={})), \
             patch("backend.app.core.sector_mapping.get_merged_all_sectors", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.sector_data_provider.get_all_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.core.sector_stock_cache.assemble_filter_summary", return_value=""), \
             patch("backend.app.services.engine_snapshot.build_initial_snapshot", new_callable=AsyncMock, return_value={"_v": 1}), \
             patch("backend.app.services.engine_snapshot.build_sector_stocks_payload", new_callable=AsyncMock, return_value={"_v": 1}), \
             patch("backend.app.pipelines.pipeline_compute.is_sector_threshold_passed", return_value=True), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", return_value=([], 0)), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={}):
            mock_state.data_ready_event.is_set.return_value = True
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.sector_summary_ready_event.is_set.return_value = True
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5}
            mock_state.sector_summary_cache = MagicMock()
            await _send_initial_snapshot_delayed(ws, mock_mgr)

        sent_events = [c.args[1] for c in mock_mgr.send_to.call_args_list]
        assert "engine-ready" in sent_events
        assert "stock-classification-changed" in sent_events
        assert "initial-snapshot" in sent_events
        assert "sector-stocks-refresh" in sent_events
        assert "index-data" in sent_events

    async def test_threshold_not_passed_skips_sector_scores(self):
        from backend.app.web.routes.ws import _send_initial_snapshot_delayed

        ws = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.send_to = AsyncMock()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"trade_mode": "test"}), \
             patch("backend.app.core.stock_classification_data.load_custom_data", return_value=MagicMock(sectors={}, stock_moves={})), \
             patch("backend.app.core.sector_mapping.get_merged_all_sectors", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.sector_data_provider.get_all_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.core.sector_stock_cache.assemble_filter_summary", return_value=""), \
             patch("backend.app.services.engine_snapshot.build_initial_snapshot", new_callable=AsyncMock, return_value={"_v": 1}), \
             patch("backend.app.services.engine_snapshot.build_sector_stocks_payload", new_callable=AsyncMock, return_value={"_v": 1}), \
             patch("backend.app.pipelines.pipeline_compute.is_sector_threshold_passed", return_value=False), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={}):
            mock_state.data_ready_event.is_set.return_value = True
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.sector_summary_ready_event.is_set.return_value = True
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5}
            mock_state.sector_summary_cache = MagicMock()
            await _send_initial_snapshot_delayed(ws, mock_mgr)

        sent_events = [c.args[1] for c in mock_mgr.send_to.call_args_list]
        assert "sector-scores" not in sent_events

    async def test_buy_targets_sent_when_nonempty(self):
        from backend.app.web.routes.ws import _send_initial_snapshot_delayed

        ws = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.send_to = AsyncMock()

        targets = [{"code": "005930", "cur_price": 50000}]
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"trade_mode": "test"}), \
             patch("backend.app.core.stock_classification_data.load_custom_data", return_value=MagicMock(sectors={}, stock_moves={})), \
             patch("backend.app.core.sector_mapping.get_merged_all_sectors", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.sector_data_provider.get_all_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.core.sector_stock_cache.assemble_filter_summary", return_value=""), \
             patch("backend.app.services.engine_snapshot.build_initial_snapshot", new_callable=AsyncMock, return_value={"_v": 1}), \
             patch("backend.app.services.engine_snapshot.build_sector_stocks_payload", new_callable=AsyncMock, return_value={"_v": 1}), \
             patch("backend.app.pipelines.pipeline_compute.is_sector_threshold_passed", return_value=True), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", return_value=([], 0)), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={}):
            mock_state.data_ready_event.is_set.return_value = True
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.sector_summary_ready_event.is_set.return_value = True
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5}
            mock_state.sector_summary_cache = MagicMock()
            await _send_initial_snapshot_delayed(ws, mock_mgr)

        sent_events = [c.args[1] for c in mock_mgr.send_to.call_args_list]
        assert "buy-targets-update" in sent_events

    async def test_exception_logged_no_raise(self):
        from backend.app.web.routes.ws import _send_initial_snapshot_delayed

        ws = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.send_to = AsyncMock(side_effect=RuntimeError("send failed"))

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_config.get_settings_snapshot", side_effect=RuntimeError("boom")):
            mock_state.data_ready_event.is_set.return_value = True
            mock_state.bootstrap_event.is_set.return_value = True
            # 예외가 raise되지 않고 로깅만 처리되어야 함
            await _send_initial_snapshot_delayed(ws, mock_mgr)


class TestWsPrices:
    """ws.py: WebSocket /api/ws/prices — 연결 관리 + ping-pong."""

    async def test_ping_returns_pong(self):
        from backend.app.web.routes.ws import ws_prices

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "ping"}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws.ws_manager") as mock_mgr, \
             patch("asyncio.create_task") as mock_create:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 1
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_create.side_effect = lambda coro: (coro.close(), mock_task)[1]
            await ws_prices(ws, token="test")

        sent = [json.loads(c.args[0]) for c in ws.send_text.call_args_list]
        assert {"type": "pong"} in sent

    async def test_page_active_sets_active_page(self):
        from backend.app.web.routes.ws import ws_prices

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "page-active", "page": "buy-target"}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws.ws_manager") as mock_mgr, \
             patch("asyncio.create_task") as mock_create:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.set_active_page = MagicMock()
            mock_mgr.clear_active_page = MagicMock()
            mock_mgr.client_count = 1
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_create.side_effect = lambda coro: (coro.close(), mock_task)[1]
            await ws_prices(ws, token="test")

        mock_mgr.set_active_page.assert_called_once_with(ws, "buy-target")

    async def test_page_inactive_clears_active_page(self):
        from backend.app.web.routes.ws import ws_prices

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "page-inactive"}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws.ws_manager") as mock_mgr, \
             patch("asyncio.create_task") as mock_create:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.set_active_page = MagicMock()
            mock_mgr.clear_active_page = MagicMock()
            mock_mgr.client_count = 1
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_create.side_effect = lambda coro: (coro.close(), mock_task)[1]
            await ws_prices(ws, token="test")

        mock_mgr.clear_active_page.assert_called_once_with(ws)

    async def test_subscribe_fids_sets_subscribed_fids(self):
        from backend.app.web.routes.ws import ws_prices

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "subscribe-fids", "fids": ["0B", "0D"]}),
            Exception("disconnect"),
        ])
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws.ws_manager") as mock_mgr, \
             patch("asyncio.create_task") as mock_create:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.set_subscribed_fids = MagicMock()
            mock_mgr.client_count = 1
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_create.side_effect = lambda coro: (coro.close(), mock_task)[1]
            await ws_prices(ws, token="test")

        mock_mgr.set_subscribed_fids.assert_called_once_with(ws, ["0B", "0D"])

    async def test_websocket_disconnect_handled(self):
        from backend.app.web.routes.ws import ws_prices
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
        ws.send_text = AsyncMock()

        with patch("backend.app.web.routes.ws.ws_manager") as mock_mgr, \
             patch("asyncio.create_task") as mock_create:
            mock_mgr.register = AsyncMock()
            mock_mgr.unregister = MagicMock()
            mock_mgr.client_count = 0
            mock_task = MagicMock()
            mock_task.cancel = MagicMock()
            mock_create.side_effect = lambda coro: (coro.close(), mock_task)[1]
            await ws_prices(ws, token="test")

        mock_mgr.unregister.assert_called_once_with(ws)
        mock_task.cancel.assert_called_once()


class TestWsRouter:
    """ws.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.ws import router
        assert router.prefix == "/api/ws"
        assert "websocket" in router.tags

    def test_router_has_one_route(self):
        from backend.app.web.routes.ws import router
        assert len(router.routes) == 1
