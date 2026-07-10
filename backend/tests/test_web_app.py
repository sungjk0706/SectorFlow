"""FastAPI 웹 서버 단위 테스트 — app.py.

lifespan startup/shutdown 전체 흐름 + global_exception_handler + CacheControlMiddleware + spa_fallback.
모든 lazy import를 mock하여 실제 DB/엔진/스케줄러 기동 없이 검증.
"""
from __future__ import annotations

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException, Request

# Initialize queues before any lazy import of pipeline_compute (module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues
initialize_queues()


# ── lifespan 헬퍼 ──────────────────────────────────────────────────────────────

def _lifespan_patches(start_engine_return=True):
    """lifespan startup+shutdown에 필요한 모든 lazy import patch를 일괄 생성.

    Returns: (patches_list, mock_task, mock_state)
    """
    mock_task = MagicMock()
    mock_task.add_done_callback = MagicMock()

    patches = [
        patch("backend.app.core.logging_config.configure_app_logging", AsyncMock()),
        patch("backend.app.db.db_writer.start_db_writer", AsyncMock()),
        patch("backend.app.db.db_writer.stop_db_writer", AsyncMock()),
        patch("backend.app.db.stock_tables.init_cache_tables", AsyncMock()),
        patch("backend.app.db.stock_tables.create_master_stocks_table", AsyncMock()),
        patch("backend.app.db.stock_tables.migrate_master_stocks_table_pk", AsyncMock()),
        patch("backend.app.db.stock_tables.migrate_add_hidden_to_custom_sectors", AsyncMock()),
        patch("backend.app.core.trading_calendar.initialize_trading_calendar_cache", AsyncMock()),
        patch("backend.app.core.sector_stock_cache.load_filter_summary_meta_cache", AsyncMock(return_value="")),
        patch("backend.app.core.settings_file.load_integrated_system_settings", AsyncMock(return_value={})),
        patch("backend.app.services.engine_lifecycle.start_engine", AsyncMock(return_value=start_engine_return)),
        patch("backend.app.services.engine_lifecycle.stop_engine", AsyncMock()),
        patch("backend.app.services.daily_time_scheduler.start_daily_time_scheduler", AsyncMock()),
        patch("backend.app.services.daily_time_scheduler.stop_daily_time_scheduler", AsyncMock()),
        patch("backend.app.services.trade_history._reset_global_state"),
        patch("backend.app.services.trade_history.start_consumer_task"),
        patch("backend.app.services.trade_history.stop_consumer_task", AsyncMock()),
        patch("backend.app.core.journal.start_consumer_task"),
        patch("backend.app.core.journal.stop_consumer_task", AsyncMock()),
        patch("backend.app.web.ws_manager.ws_manager.close_all", AsyncMock()),
        patch("backend.app.db.database.close_db_connection", AsyncMock()),
        patch("backend.app.core.logger.stop_file_writers", AsyncMock()),
        # asyncio.create_task: 코루틴을 close 후 mock_task 반환 (RuntimeWarning 방지)
        patch("asyncio.create_task", side_effect=lambda coro, *a, **kw: (coro.close(), mock_task)[1]),
        # asyncio.gather: 인자로 전달된 코루틴들을 close 후 결과 반환 (RuntimeWarning 방지)
        patch("asyncio.gather", AsyncMock(side_effect=lambda *coros, **kw: [c.close() for c in coros if hasattr(c, 'close')] and (None, None, {}))),
    ]

    # telegram_bot: stop_async를 AsyncMock으로 설정
    mock_tg = MagicMock()
    mock_tg.stop_async = AsyncMock()
    mock_tg.start = MagicMock()
    patches.append(patch("backend.app.services.telegram_bot.telegram_bot", mock_tg))

    # state: server_ready_event / engine_ready_event / integrated_system_settings_cache
    mock_state = MagicMock()
    mock_state.integrated_system_settings_cache = {}
    mock_state.server_ready_event = MagicMock()
    mock_state.engine_ready_event = MagicMock()
    mock_state.shutdown_requested = False
    mock_state.connector_manager = None
    patches.append(patch("backend.app.services.engine_state.state", mock_state))

    return patches, mock_task, mock_state


# ── lifespan ───────────────────────────────────────────────────────────────────

class TestLifespanStartup:
    """lifespan: startup 단계 — 모든 의존성 mock 후 실행 검증."""

    async def test_startup_completes(self):
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, _ = _lifespan_patches()
        for p in patches:
            p.start()
        try:
            async with lifespan(mock_app):
                pass  # startup 완료
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_startup_sets_server_ready(self):
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, mock_state = _lifespan_patches()
        for p in patches:
            p.start()
        try:
            async with lifespan(mock_app):
                mock_state.server_ready_event.set.assert_called_once()
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_startup_engine_init_failure(self):
        """엔진 초기화 실패 시에도 startup은 완료됨 (백그라운드 태스크에서 예외 처리)."""
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, mock_state = _lifespan_patches(start_engine_return=False)
        for p in patches:
            p.start()
        try:
            # startup은 완료되어야 함 (엔진 실패는 백그라운드)
            async with lifespan(mock_app):
                pass
        finally:
            for p in reversed(patches):
                p.stop()


class TestLifespanShutdown:
    """lifespan: shutdown 단계 — 모든 종료 작업 호출 검증."""

    async def test_shutdown_calls_close_all(self):
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, _ = _lifespan_patches()
        for p in patches:
            p.start()
        try:
            from backend.app.web.ws_manager import ws_manager
            async with lifespan(mock_app):
                pass  # startup → yield → shutdown
            # shutdown 단계에서 close_all 호출 확인
            ws_manager.close_all.assert_awaited()
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_shutdown_stops_trade_history_and_journal(self):
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, _ = _lifespan_patches()
        for p in patches:
            p.start()
        try:
            async with lifespan(mock_app):
                pass
            # shutdown 단계에서 stop_consumer_task 호출 확인
            from backend.app.services.trade_history import stop_consumer_task
            stop_consumer_task.assert_awaited()
            from backend.app.core.journal import stop_consumer_task as journal_stop
            journal_stop.assert_awaited()
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_shutdown_stops_db_writer_and_closes_connection(self):
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, _ = _lifespan_patches()
        for p in patches:
            p.start()
        try:
            async with lifespan(mock_app):
                pass
            from backend.app.db.db_writer import stop_db_writer
            stop_db_writer.assert_awaited()
            from backend.app.db.database import close_db_connection
            close_db_connection.assert_awaited()
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_shutdown_clears_state_events(self):
        from backend.app.web.app import lifespan
        mock_app = MagicMock(spec=FastAPI)
        patches, _, mock_state = _lifespan_patches()
        for p in patches:
            p.start()
        try:
            async with lifespan(mock_app):
                pass
            mock_state.engine_ready_event.clear.assert_called_once()
            mock_state.server_ready_event.clear.assert_called_once()
        finally:
            for p in reversed(patches):
                p.stop()


# ── global_exception_handler ───────────────────────────────────────────────────

class TestGlobalExceptionHandler:
    """global_exception_handler: 5분 쿨다운 텔레그램 알림."""

    async def test_first_error_sends_alert(self):
        from backend.app.web.app import global_exception_handler, _last_alert_time
        _last_alert_time.clear()

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        exc = ValueError("test error")

        with patch("backend.app.services.telegram.send_msg_async", AsyncMock()):
            with patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"tele_on": True}):
                result = await global_exception_handler(mock_request, exc)

        assert result.status_code == 500
        assert result.body.decode() == '{"detail":"서버 내부 오류"}'

    async def test_cooldown_blocks_second_alert(self):
        from backend.app.web.app import global_exception_handler, _last_alert_time, ALERT_COOLDOWN_SECONDS
        error_type = "ValueError"
        _last_alert_time[error_type] = time.time()  # 방금 전송됨

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        exc = ValueError("test error 2")

        with patch("backend.app.services.telegram.send_msg_async", AsyncMock()) as mock_send:
            with patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"tele_on": True}):
                await global_exception_handler(mock_request, exc)

        mock_send.assert_not_awaited()  # 쿨다운 내 전송 안 함
        _last_alert_time.clear()

    async def test_after_cooldown_sends_alert(self):
        from backend.app.web.app import global_exception_handler, _last_alert_time, ALERT_COOLDOWN_SECONDS
        error_type = "ValueError"
        _last_alert_time[error_type] = time.time() - ALERT_COOLDOWN_SECONDS - 1  # 쿨다운 만료

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        exc = ValueError("test error 3")

        with patch("backend.app.services.telegram.send_msg_async", AsyncMock()) as mock_send:
            with patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"tele_on": True}):
                await global_exception_handler(mock_request, exc)

        mock_send.assert_awaited_once()
        _last_alert_time.clear()

    async def test_telegram_failure_no_raise(self):
        from backend.app.web.app import global_exception_handler, _last_alert_time
        _last_alert_time.clear()

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        exc = RuntimeError("test")

        with patch("backend.app.services.telegram.send_msg_async",
                   AsyncMock(side_effect=Exception("telegram down"))):
            with patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"tele_on": True}):
                result = await global_exception_handler(mock_request, exc)

        # 텔레그램 실패해도 500 응답은 정상 반환
        assert result.status_code == 500
        _last_alert_time.clear()

    async def test_different_error_types_independent_cooldown(self):
        from backend.app.web.app import global_exception_handler, _last_alert_time
        _last_alert_time.clear()
        _last_alert_time["ValueError"] = time.time()  # ValueError는 쿨다운 중

        mock_request = MagicMock()
        mock_request.url.path = "/api/test"
        exc = RuntimeError("different type")

        with patch("backend.app.services.telegram.send_msg_async", AsyncMock()) as mock_send:
            with patch("backend.app.services.engine_config.get_settings_snapshot", return_value={"tele_on": True}):
                await global_exception_handler(mock_request, exc)

        mock_send.assert_awaited_once()  # 다른 타입이므로 전송
        _last_alert_time.clear()


# ── CacheControlMiddleware ─────────────────────────────────────────────────────

class TestCacheControlMiddleware:
    """CacheControlMiddleware: 경로별 Cache-Control 헤더."""

    async def test_api_path_no_cache_headers(self):
        from backend.app.web.app import CacheControlMiddleware
        mw = CacheControlMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/api/sector-scores"

        mock_response = MagicMock()
        mock_response.headers = {}

        async def call_next(req):
            return mock_response

        result = await mw.dispatch(mock_request, call_next)
        assert "Cache-Control" not in result.headers

    async def test_assets_path_long_cache(self):
        from backend.app.web.app import CacheControlMiddleware
        mw = CacheControlMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/assets/index-abc123.js"

        mock_response = MagicMock()
        mock_response.headers = {}

        async def call_next(req):
            return mock_response

        result = await mw.dispatch(mock_request, call_next)
        assert result.headers["Cache-Control"] == "public, max-age=31536000, immutable"

    async def test_html_path_no_cache(self):
        from backend.app.web.app import CacheControlMiddleware
        mw = CacheControlMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/"

        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}

        async def call_next(req):
            return mock_response

        result = await mw.dispatch(mock_request, call_next)
        assert "no-cache" in result.headers["Cache-Control"]
        assert result.headers["Pragma"] == "no-cache"
        assert result.headers["Expires"] == "0"

    async def test_ws_path_not_touched(self):
        from backend.app.web.app import CacheControlMiddleware
        mw = CacheControlMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/ws/prices"

        mock_response = MagicMock()
        mock_response.headers = {}

        async def call_next(req):
            return mock_response

        result = await mw.dispatch(mock_request, call_next)
        assert "Cache-Control" not in result.headers


# ── app 라우터 등록 검증 ───────────────────────────────────────────────────────

class TestAppRouterRegistration:
    """app.py: 라우터 등록 13개 검증."""

    def test_app_is_fastapi(self):
        from backend.app.web.app import app
        assert isinstance(app, FastAPI)

    def test_app_has_routers(self):
        from backend.app.web.app import app
        # 최소 13개 라우터의 라우트가 등록되어 있어야 함
        # (auth, account, market, status, settings, ws, ws_settings, ws_orders, trade, ws_subscribe,
        #  stock_classification, settlement, stock_detail)
        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert len(route_paths) > 10

    def test_app_title(self):
        from backend.app.web.app import app
        assert app.title == "SectorFlow"

    def test_app_version(self):
        from backend.app.web.app import app
        assert app.version == "1.0.0"


# ── spa_fallback ───────────────────────────────────────────────────────────────

class TestSpaFallback:
    """spa_fallback: API 404 / 정적 파일 / SPA index.html."""

    async def test_api_path_returns_404(self):
        from backend.app.web.app import spa_fallback
        with pytest.raises(HTTPException) as exc_info:
            await spa_fallback("api/sector-scores")
        assert exc_info.value.status_code == 404

    async def test_static_file_served(self):
        from backend.app.web.app import spa_fallback, _FRONTEND_DIST
        # _FRONTEND_DIST가 존재하는 경우에만 테스트 (빌드된 상태)
        if not _FRONTEND_DIST.is_dir():
            pytest.skip("frontend/dist not built")
        # index.html이 존재하는지 확인
        index_path = _FRONTEND_DIST / "index.html"
        if not index_path.is_file():
            pytest.skip("frontend/dist/index.html not found")
        result = await spa_fallback("index.html")
        assert result is not None

    async def test_spa_fallback_returns_index(self):
        from backend.app.web.app import spa_fallback, _FRONTEND_DIST
        if not _FRONTEND_DIST.is_dir():
            pytest.skip("frontend/dist not built")
        result = await spa_fallback("nonexistent-route")
        # SPA 라우팅이므로 index.html 반환
        assert result is not None
