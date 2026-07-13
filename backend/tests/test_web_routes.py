"""Web 라우트 단위 테스트 — account, market, settlement, auth.

라우트 핸들러 함수를 직접 await로 호출하여 테스트.
TestClient 없이 함수 단위 테스트 — 기존 test_settings_boost_order_ratio.py 패턴과 동일.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── account.py ────────────────────────────────────────────────────────────────

class TestAccountRouter:
    """account.py: 라우터만 정의, 엔드포인트 없음."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.account import router
        assert router.prefix == "/api"
        assert "account" in router.tags

    def test_router_has_no_routes(self):
        from backend.app.web.routes.account import router
        assert len(router.routes) == 0


# ── market.py ─────────────────────────────────────────────────────────────────

class TestGetTradingDay:
    """market.py: GET /api/trading-day — 오늘이 KRX 거래일인지 반환."""

    async def test_trading_day_true(self):
        from backend.app.web.routes.market import get_trading_day
        from datetime import date
        mock_today = date(2026, 7, 10)
        with patch("backend.app.web.routes.market.get_kst_today", return_value=mock_today):
            with patch("backend.app.web.routes.market.is_trading_day", return_value=True):
                result = await get_trading_day(_="dev")
        assert result["is_trading_day"] is True
        assert result["today"] == "2026-07-10"

    async def test_trading_day_false(self):
        from backend.app.web.routes.market import get_trading_day
        from datetime import date
        mock_today = date(2026, 7, 12)  # 일요일
        with patch("backend.app.web.routes.market.get_kst_today", return_value=mock_today):
            with patch("backend.app.web.routes.market.is_trading_day", return_value=False):
                result = await get_trading_day(_="dev")
        assert result["is_trading_day"] is False
        assert result["today"] == "2026-07-12"

    async def test_today_iso_format(self):
        from backend.app.web.routes.market import get_trading_day
        from datetime import date
        mock_today = date(2026, 1, 5)
        with patch("backend.app.web.routes.market.get_kst_today", return_value=mock_today):
            with patch("backend.app.web.routes.market.is_trading_day", return_value=True):
                result = await get_trading_day(_="dev")
        assert result["today"] == "2026-01-05"


class TestMarketRouter:
    """market.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.market import router
        assert router.prefix == "/api"
        assert "market" in router.tags

    def test_router_has_one_route(self):
        from backend.app.web.routes.market import router
        assert len(router.routes) == 1


# ── settlement.py ─────────────────────────────────────────────────────────────

class TestChargeSettlement:
    """settlement.py: POST /api/settlement/charge — 투자금 충전."""

    async def test_charge_success(self):
        from backend.app.web.routes.settlement import charge_settlement
        with patch("backend.app.services.settlement_engine.charge", new_callable=AsyncMock, return_value=12_000_000):
            result = await charge_settlement({"amount": 2_000_000}, _="dev")
        assert result["ok"] is True
        assert result["balance"] == 12_000_000

    async def test_charge_zero_amount(self):
        from backend.app.web.routes.settlement import charge_settlement
        result = await charge_settlement({"amount": 0}, _="dev")
        assert result["ok"] is False
        assert "0보다 커야" in result["reason"]

    async def test_charge_negative_amount(self):
        from backend.app.web.routes.settlement import charge_settlement
        result = await charge_settlement({"amount": -1000}, _="dev")
        assert result["ok"] is False
        assert "0보다 커야" in result["reason"]

    async def test_charge_missing_amount_defaults_zero(self):
        from backend.app.web.routes.settlement import charge_settlement
        result = await charge_settlement({}, _="dev")
        assert result["ok"] is False
        assert "0보다 커야" in result["reason"]

    async def test_charge_string_amount_converted(self):
        from backend.app.web.routes.settlement import charge_settlement
        with patch("backend.app.services.settlement_engine.charge", new_callable=AsyncMock, return_value=11_000_000):
            result = await charge_settlement({"amount": "1000000"}, _="dev")
        assert result["ok"] is True
        assert result["balance"] == 11_000_000


class TestSettlementRouter:
    """settlement.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.settlement import router
        assert router.prefix == "/api/settlement"
        assert "settlement" in router.tags

    def test_router_has_one_route(self):
        from backend.app.web.routes.settlement import router
        assert len(router.routes) == 1


# ── auth.py ───────────────────────────────────────────────────────────────────

class TestLogin:
    """auth.py: POST /api/auth/login — 로그인 + JWT 토큰 발급."""

    async def test_login_success(self):
        from backend.app.web.routes.auth import login, LoginRequest
        with patch("backend.app.web.routes.auth.authenticate_user", return_value=True):
            with patch("backend.app.web.routes.auth.create_access_token", return_value="fake_jwt_token"):
                req = LoginRequest(username="admin", password="1234")
                result = await login(req)
        assert result.access_token == "fake_jwt_token"
        assert result.token_type == "bearer"

    async def test_login_failure_raises_401(self):
        from backend.app.web.routes.auth import login, LoginRequest
        from fastapi import HTTPException
        with patch("backend.app.web.routes.auth.authenticate_user", return_value=False):
            req = LoginRequest(username="wrong", password="wrong")
            with pytest.raises(HTTPException) as exc_info:
                await login(req)
        assert exc_info.value.status_code == 401
        assert "인증 실패" in exc_info.value.detail

    async def test_login_calls_authenticate_user(self):
        from backend.app.web.routes.auth import login, LoginRequest
        with patch("backend.app.web.routes.auth.authenticate_user", return_value=True) as mock_auth:
            with patch("backend.app.web.routes.auth.create_access_token", return_value="token"):
                req = LoginRequest(username="admin", password="1234")
                await login(req)
        mock_auth.assert_called_once_with("admin", "1234")

    async def test_login_calls_create_access_token(self):
        from backend.app.web.routes.auth import login, LoginRequest
        with patch("backend.app.web.routes.auth.authenticate_user", return_value=True):
            with patch("backend.app.web.routes.auth.create_access_token", return_value="token") as mock_create:
                req = LoginRequest(username="admin", password="1234")
                await login(req)
        mock_create.assert_called_once_with("admin")


class TestAuthModels:
    """auth.py: Pydantic 모델 검증."""

    def test_login_request_fields(self):
        from backend.app.web.routes.auth import LoginRequest
        req = LoginRequest(username="admin", password="1234")
        assert req.username == "admin"
        assert req.password == "1234"

    def test_login_response_default_token_type(self):
        from backend.app.web.routes.auth import LoginResponse
        resp = LoginResponse(access_token="token123")
        assert resp.access_token == "token123"
        assert resp.token_type == "bearer"

    def test_login_response_custom_token_type(self):
        from backend.app.web.routes.auth import LoginResponse
        resp = LoginResponse(access_token="token123", token_type="custom")
        assert resp.token_type == "custom"


class TestAuthRouter:
    """auth.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.auth import router
        assert router.prefix == "/api/auth"
        assert "auth" in router.tags

    def test_router_has_one_route(self):
        from backend.app.web.routes.auth import router
        assert len(router.routes) == 1


# ── status.py ────────────────────────────────────────────────────────────────

class TestHealthCheck:
    """status.py: GET /api/health — 엔진 준비 상태 확인."""

    async def test_ready_status(self):
        from backend.app.web.routes.status import health_check
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.server_ready_event.is_set.return_value = True
            mock_state.engine_ready_event.is_set.return_value = True
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.running = True
            mock_state.confirmed_refresh_running = False
            mock_state.access_token = "token123"
            mock_state.account_snapshot = {"timestamp": "2026-07-10T09:00:00"}
            result = await health_check()
        assert result["status"] == "ready"
        assert result["message"] == "엔진 준비 완료"
        assert result["progress"]["server_ready"] is True
        assert result["progress"]["engine_ready"] is True
        assert result["progress"]["bootstrap_done"] is True
        assert result["progress"]["broker_connected"] is True
        assert result["timestamp"] == "2026-07-10T09:00:00"

    async def test_downloading_status(self):
        from backend.app.web.routes.status import health_check
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.server_ready_event.is_set.return_value = True
            mock_state.engine_ready_event.is_set.return_value = False
            mock_state.bootstrap_event.is_set.return_value = False
            mock_state.running = True
            mock_state.confirmed_refresh_running = True
            mock_state.access_token = None
            mock_state.account_snapshot = None
            result = await health_check()
        assert result["status"] == "downloading"
        assert result["message"] == "확정 데이터 다운로드 중"
        assert result["progress"]["server_ready"] is True
        assert result["progress"]["engine_ready"] is False
        assert result["progress"]["broker_connected"] is False

    async def test_initializing_status(self):
        from backend.app.web.routes.status import health_check
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.server_ready_event.is_set.return_value = False
            mock_state.engine_ready_event.is_set.return_value = False
            mock_state.bootstrap_event.is_set.return_value = False
            mock_state.running = True
            mock_state.confirmed_refresh_running = False
            mock_state.access_token = None
            mock_state.account_snapshot = None
            result = await health_check()
        assert result["status"] == "initializing"
        assert result["message"] == "초기화 중..."
        assert result["progress"]["server_ready"] is False
        assert result["progress"]["engine_ready"] is False

    async def test_ready_no_engine_status(self):
        from backend.app.web.routes.status import health_check
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.server_ready_event.is_set.return_value = False
            mock_state.engine_ready_event.is_set.return_value = False
            mock_state.bootstrap_event.is_set.return_value = False
            mock_state.running = False
            mock_state.confirmed_refresh_running = False
            mock_state.access_token = None
            mock_state.account_snapshot = None
            result = await health_check()
        assert result["status"] == "ready"
        assert "서버 준비 완료" in result["message"]


class TestDebugSectorStock:
    """status.py: GET /api/debug/sector-stock/{code} — 종목 실시간 데이터 상태."""

    async def test_filtered_and_subscribed_stock(self):
        from backend.app.web.routes.status import debug_sector_stock
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            with patch("backend.app.services.engine_state.state") as mock_state:
                mock_state.master_stocks_cache.get.return_value = {
                    "_filtered": True,
                    "_subscribed": True,
                    "status": "ok",
                    "cur_price": 50000,
                    "change": 100,
                    "change_rate": 0.2,
                    "strength": 1.5,
                    "trade_amount": 1000000,
                }
                mock_state.master_stocks_cache.values.return_value = [
                    {"_filtered": True}, {"_filtered": False},
                ]
                result = await debug_sector_stock("005930")
        assert result["code"] == "005930"
        assert result["in_filtered_sector_codes"] is True
        assert result["in_subscribed_stocks"] is True
        assert result["pending_cur_price"] == 50000
        assert result["filtered_count"] == 1

    async def test_unfiltered_stock(self):
        from backend.app.web.routes.status import debug_sector_stock
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="000660"):
            with patch("backend.app.services.engine_state.state") as mock_state:
                mock_state.master_stocks_cache.get.return_value = {
                    "_filtered": False,
                    "_subscribed": False,
                }
                mock_state.master_stocks_cache.values.return_value = []
                result = await debug_sector_stock("000660")
        assert result["in_filtered_sector_codes"] is False
        assert result["in_subscribed_stocks"] is False
        assert result["filtered_count"] == 0

    async def test_nonexistent_stock(self):
        from backend.app.web.routes.status import debug_sector_stock
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="999999"):
            with patch("backend.app.services.engine_state.state") as mock_state:
                mock_state.master_stocks_cache.get.return_value = {}
                mock_state.master_stocks_cache.values.return_value = []
                result = await debug_sector_stock("999999")
        assert result["in_filtered_sector_codes"] is False
        assert result["pending_cur_price"] is None


class TestDebugWsStatus:
    """status.py: GET /api/debug/ws-status — WS 연결 상태 + 구독 현황."""

    async def test_ws_connected(self):
        from backend.app.web.routes.status import debug_ws_status
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_ws = MagicMock()
            mock_ws.is_connected.return_value = True
            mock_state.active_connector = mock_ws
            mock_state.login_ok = True
            mock_state.running = True
            mock_state.master_stocks_cache.values.return_value = [
                {"_subscribed": True, "_filtered": True},
                {"_subscribed": False, "_filtered": False},
            ]
            mock_state.ws_reg_pipeline_done.is_set.return_value = True
            mock_state.bootstrap_event.is_set.return_value = True
            result = await debug_ws_status()
        assert result["ws_connected"] is True
        assert result["login_ok"] is True
        assert result["running"] is True
        assert result["subscribed_stocks_count"] == 1
        assert result["filtered_sector_codes_count"] == 1
        assert result["ws_reg_pipeline_done"] is True

    async def test_ws_not_connected(self):
        from backend.app.web.routes.status import debug_ws_status
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.active_connector = None
            mock_state.login_ok = False
            mock_state.running = False
            mock_state.master_stocks_cache.values.return_value = []
            mock_state.ws_reg_pipeline_done.is_set.return_value = False
            mock_state.bootstrap_event.is_set.return_value = False
            result = await debug_ws_status()
        assert result["ws_connected"] is False
        assert result["login_ok"] is False
        assert result["running"] is False


class TestDebugTriggerConfirmed:
    """status.py: POST /api/debug/trigger-confirmed — 통합 확정 조회 수동 트리거."""

    async def test_success(self):
        from backend.app.web.routes.status import debug_trigger_confirmed
        with patch("backend.app.services.market_close_pipeline.fetch_unified_confirmed_data", new_callable=AsyncMock, return_value={"data": "ok"}):
            result = await debug_trigger_confirmed()
        assert result["status"] == "ok"
        assert result["result"] == {"data": "ok"}

    async def test_exception_returns_error(self):
        from backend.app.web.routes.status import debug_trigger_confirmed
        with patch("backend.app.services.market_close_pipeline.fetch_unified_confirmed_data", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            result = await debug_trigger_confirmed()
        assert result["status"] == "error"
        assert "fail" in result["message"]


class TestDebugSectorRefreshSample:
    """status.py: GET /api/debug/sector-refresh-sample — sector-refresh 샘플 데이터."""

    async def test_with_sample_stocks(self):
        from backend.app.web.routes.status import debug_sector_refresh_sample
        stocks = [
            {"code": "005930", "cur_price": 50000, "change": 100, "change_rate": 0.2, "strength": 1.5, "trade_amount": 1000000, "avg_amt_5d": 900000, "sector": "반도체"},
            {"code": "000660", "cur_price": 120000, "change": -500, "change_rate": -0.4, "strength": 0.8, "trade_amount": 2000000, "avg_amt_5d": 1800000, "sector": "반도체"},
            {"code": "035420", "cur_price": 200000, "change": 1000, "change_rate": 0.5, "strength": 2.0, "trade_amount": 500000, "avg_amt_5d": 400000, "sector": "IT서비스"},
        ]
        with patch("backend.app.services.sector_data_provider.get_sector_stocks", new_callable=AsyncMock, return_value=stocks):
            with patch("backend.app.web.ws_manager.ws_manager") as mock_mgr:
                mock_mgr.client_count = 2
                result = await debug_sector_refresh_sample()
        assert result["total_stocks_in_response"] == 3
        assert result["sample_005930"]["cur_price"] == 50000
        assert result["sample_000660"]["cur_price"] == 120000
        assert result["ws_client_count"] == 2

    async def test_no_sample_stocks(self):
        from backend.app.web.routes.status import debug_sector_refresh_sample
        stocks = [{"code": "035420", "cur_price": 200000}]
        with patch("backend.app.services.sector_data_provider.get_sector_stocks", new_callable=AsyncMock, return_value=stocks):
            with patch("backend.app.web.ws_manager.ws_manager") as mock_mgr:
                mock_mgr.client_count = 0
                result = await debug_sector_refresh_sample()
        assert result["total_stocks_in_response"] == 1
        assert result["sample_005930"] == "NOT_FOUND"
        assert result["sample_000660"] == "NOT_FOUND"


class TestStatusRouter:
    """status.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.status import router
        assert router.prefix == "/api"
        assert "status" in router.tags

    def test_router_has_five_routes(self):
        from backend.app.web.routes.status import router
        assert len(router.routes) == 5


# ── settings.py ───────────────────────────────────────────────────────────────

class TestGetSettings:
    """settings.py: GET /api/settings — 전체 설정 조회."""

    async def test_success(self):
        from backend.app.web.routes.settings import get_settings
        with patch("backend.app.core.settings_store.build_masked_settings_dict", new_callable=AsyncMock, return_value={"trade_mode": "test"}):
            result = await get_settings(_="dev")
        assert result == {"trade_mode": "test"}

    async def test_exception_raises_500(self):
        from backend.app.web.routes.settings import get_settings
        from fastapi import HTTPException
        with patch("backend.app.core.settings_store.build_masked_settings_dict", new_callable=AsyncMock, side_effect=RuntimeError("db error")):
            with pytest.raises(HTTPException) as exc_info:
                await get_settings(_="dev")
        assert exc_info.value.status_code == 500
        assert "설정 조회 실패" in exc_info.value.detail


class TestPatchSettingField:
    """settings.py: PATCH /api/settings/{field_name} — 개별 필드 수정."""

    async def test_missing_value_raises_400(self):
        from backend.app.web.routes.settings import patch_setting_field
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await patch_setting_field("trade_mode", {}, _="dev")
        assert exc_info.value.status_code == 400
        assert "value 필드가 필요합니다" in exc_info.value.detail

    async def test_engine_running_applies_settings_change(self):
        from backend.app.web.routes.settings import patch_setting_field
        with patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock, return_value={"trade_mode"}), \
             patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=True), \
             patch("backend.app.services.engine_service.apply_settings_change", new_callable=AsyncMock) as mock_apply:
            result = await patch_setting_field("trade_mode", {"value": "real"}, _="dev")
        assert result["ok"] is True
        mock_apply.assert_called_once_with({"trade_mode"})

    async def test_engine_running_empty_changes_skips_apply(self):
        from backend.app.web.routes.settings import patch_setting_field
        with patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock, return_value=set()), \
             patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=True), \
             patch("backend.app.services.engine_service.apply_settings_change", new_callable=AsyncMock) as mock_apply:
            result = await patch_setting_field("trade_mode", {"value": "test"}, _="dev")
        assert result["ok"] is True
        mock_apply.assert_not_called()

    async def test_engine_not_running_saves_pending(self):
        from backend.app.web.routes.settings import patch_setting_field
        with patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock, return_value={"sector_max_targets"}), \
             patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=False), \
             patch("backend.app.core.sector_stock_cache.save_pending_settings", new_callable=AsyncMock) as mock_save, \
             patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new_callable=AsyncMock), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={"sector_max_targets": 5}), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5}
            result = await patch_setting_field("sector_max_targets", {"value": 5}, _="dev")
        assert result["ok"] is True
        mock_save.assert_called_once_with({"sector_max_targets"})

    async def test_tele_on_starts_telegram_bot(self):
        from backend.app.web.routes.settings import patch_setting_field
        with patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock, return_value={"tele_on"}), \
             patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=False), \
             patch("backend.app.core.sector_stock_cache.save_pending_settings", new_callable=AsyncMock), \
             patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new_callable=AsyncMock), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={"tele_on": True}), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            result = await patch_setting_field("tele_on", {"value": True}, _="dev")
        assert result["ok"] is True
        mock_bot.start.assert_called_once()

    async def test_tele_off_stops_telegram_bot(self):
        from backend.app.web.routes.settings import patch_setting_field
        with patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock, return_value={"tele_on"}), \
             patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=False), \
             patch("backend.app.core.sector_stock_cache.save_pending_settings", new_callable=AsyncMock), \
             patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new_callable=AsyncMock), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={"tele_on": False}), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": False}
            mock_bot.stop_async = AsyncMock()
            result = await patch_setting_field("tele_on", {"value": False}, _="dev")
        assert result["ok"] is True
        mock_bot.stop_async.assert_called_once()


class TestResetTestData:
    """settings.py: POST /api/test-data/reset — 테스트 데이터 전체 초기화."""

    async def test_success(self):
        from backend.app.web.routes.settings import reset_test_data
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trade_history.clear_test_history", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.clear", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.set_virtual_deposit", new_callable=AsyncMock), \
             patch("backend.app.services.settlement_engine.reset", new_callable=AsyncMock) as mock_reset, \
             patch("backend.app.services.trade_history.broadcast_history", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify._rebuild_positions_cache") as mock_rebuild, \
             patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_account", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_snapshot_history_update", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_broadcast:
            mock_state.integrated_system_settings_cache = {
                "test_virtual_deposit": 10_000_000,
                "sector_stock_layout": [],
            }
            mock_state.master_stocks_cache.values.return_value = []
            mock_state.positions = []
            mock_state.snapshot_history = MagicMock()
            mock_state.auto_trade = None
            mock_state.sector_summary_cache = None
            mock_state._last_global_buy_ts = 0.0
            result = await reset_test_data(_="dev")
        assert result["ok"] is True
        assert "초기화 완료" in result["message"]
        mock_reset.assert_called_once_with(10_000_000)
        mock_rebuild.assert_called_once_with([])
        mock_broadcast.assert_called_once_with("test-data-reset-completed", {"_v": 1})

    async def test_exception_raises_500(self):
        from backend.app.web.routes.settings import reset_test_data
        from fastapi import HTTPException
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trade_history.clear_test_history", new_callable=AsyncMock, side_effect=RuntimeError("db locked")):
            mock_state.integrated_system_settings_cache = {
                "test_virtual_deposit": 10_000_000,
                "sector_stock_layout": [],
            }
            with pytest.raises(HTTPException) as exc_info:
                await reset_test_data(_="dev")
        assert exc_info.value.status_code == 500
        assert "초기화 실패" in exc_info.value.detail


class TestSettingsRouter:
    """settings.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.settings import router
        assert router.prefix == "/api"
        assert "settings" in router.tags

    def test_router_has_three_routes(self):
        from backend.app.web.routes.settings import router
        assert len(router.routes) == 3
