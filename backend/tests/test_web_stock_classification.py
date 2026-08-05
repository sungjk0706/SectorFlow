"""업종분류 커스텀 REST API 단위 테스트 — stock_classification.py.

9개 엔드포인트 + 헬퍼 함수 + Pydantic 모델 검증.
라우트 핸들러 함수를 직접 await로 호출 — 기존 test_web_routes.py 패턴과 동일.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Initialize queues before any lazy import of pipeline_compute (module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues
initialize_queues()


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class TestRenameRequest:
    """RenameRequest: old_name, new_name."""

    def test_valid(self):
        from backend.app.web.routes.stock_classification import RenameRequest
        req = RenameRequest(old_name="반도체", new_name="반도체/디스플레이")
        assert req.old_name == "반도체"
        assert req.new_name == "반도체/디스플레이"

    def test_missing_field_raises(self):
        from backend.app.web.routes.stock_classification import RenameRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RenameRequest(old_name="반도체")


class TestCreateRequest:
    """CreateRequest: name."""

    def test_valid(self):
        from backend.app.web.routes.stock_classification import CreateRequest
        req = CreateRequest(name="신규업종")
        assert req.name == "신규업종"

    def test_missing_name_raises(self):
        from backend.app.web.routes.stock_classification import CreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateRequest()


class TestDeleteRequest:
    """DeleteRequest: name."""

    def test_valid(self):
        from backend.app.web.routes.stock_classification import DeleteRequest
        req = DeleteRequest(name="삭제업종")
        assert req.name == "삭제업종"


class TestMoveStockRequest:
    """MoveStockRequest: stock_code, target_sector."""

    def test_valid(self):
        from backend.app.web.routes.stock_classification import MoveStockRequest
        req = MoveStockRequest(stock_code="005930", target_sector="반도체")
        assert req.stock_code == "005930"
        assert req.target_sector == "반도체"

    def test_missing_field_raises(self):
        from backend.app.web.routes.stock_classification import MoveStockRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MoveStockRequest(stock_code="005930")


class TestMoveStocksRequest:
    """MoveStocksRequest: stock_codes (list), target_sector."""

    def test_valid(self):
        from backend.app.web.routes.stock_classification import MoveStocksRequest
        req = MoveStocksRequest(stock_codes=["005930", "000660"], target_sector="반도체")
        assert req.stock_codes == ["005930", "000660"]
        assert req.target_sector == "반도체"

    def test_empty_list_valid(self):
        from backend.app.web.routes.stock_classification import MoveStocksRequest
        req = MoveStocksRequest(stock_codes=[], target_sector="반도체")
        assert req.stock_codes == []

    def test_missing_field_raises(self):
        from backend.app.web.routes.stock_classification import MoveStocksRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MoveStocksRequest(target_sector="반도체")


# ── _maybe_warning ─────────────────────────────────────────────────────────────

class TestMaybeWarning:
    """_maybe_warning: market_phase 기반 장중 여부에 따라 warning 반환 (시간대 자의적 판정 제거)."""

    async def test_market_active_returns_warning(self):
        from backend.app.web.routes.stock_classification import _maybe_warning
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _maybe_warning()
        assert "warning" in result
        assert "장중" in result["warning"]

    async def test_market_inactive_returns_empty(self):
        from backend.app.web.routes.stock_classification import _maybe_warning
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "장개시전", "nxt": "장개시전"}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _maybe_warning()
        assert result == {}


# ── broadcast_stock_classification_changed ─────────────────────────────────────

class TestBroadcastStockClassificationChanged:
    """broadcast_stock_classification_changed: WS 이벤트 브로드캐스트."""

    async def test_success_via_broadcast_queue(self):
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        mock_merged = {"반도체": ["005930"], "미분류": []}
        mock_stocks = [{"code": "005930", "sector": "반도체"}]

        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(side_effect=[
            [{"stock_code": "005930", "name": "삼성전자"}],  # custom_sectors
            [{"name": "반도체"}],  # sectors 테이블
        ])
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_queue = MagicMock()
        mock_queue.full = MagicMock(return_value=False)
        mock_queue.put_nowait = MagicMock()

        with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
            with patch("backend.app.services.sector_data_provider.get_all_sector_stocks", AsyncMock(return_value=mock_stocks)):
                with patch("backend.app.core.sector_stock_cache.assemble_filter_summary", return_value="필터요약"):
                    with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
                        with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_queue):
                            await broadcast_stock_classification_changed()

        mock_queue.put_nowait.assert_called_once()
        event = mock_queue.put_nowait.call_args[0][0]
        assert event["type"] == "stock-classification-changed"
        assert event["data"]["merged_sectors"] == mock_merged
        assert event["data"]["all_stocks"] == mock_stocks

    async def test_all_stocks_exception_fallback(self):
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        mock_merged = {"반도체": ["005930"]}

        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        mock_queue = MagicMock()
        mock_queue.full = MagicMock(return_value=False)
        mock_queue.put_nowait = MagicMock()

        with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
            with patch("backend.app.services.sector_data_provider.get_all_sector_stocks",
                       AsyncMock(side_effect=Exception("db error"))):
                with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
                    with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_queue):
                        await broadcast_stock_classification_changed()

        mock_queue.put_nowait.assert_called_once()
        event = mock_queue.put_nowait.call_args[0][0]
        assert event["data"]["all_stocks"] == []

    async def test_queue_full_falls_back_to_ws_manager(self):
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        mock_merged = {}
        mock_stocks = []

        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()

        with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
            with patch("backend.app.services.sector_data_provider.get_all_sector_stocks", AsyncMock(return_value=mock_stocks)):
                with patch("backend.app.services.core_queues.get_broadcast_queue",
                           side_effect=Exception("queue not initialized")):
                    with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
                        await broadcast_stock_classification_changed()

        mock_ws.broadcast.assert_awaited_once()

    async def test_db_exception_still_broadcasts(self):
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        mock_merged = {}
        mock_stocks = [{"code": "005930", "sector": "반도체"}]

        mock_queue = MagicMock()
        mock_queue.full = MagicMock(return_value=False)
        mock_queue.put_nowait = MagicMock()

        with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
            with patch("backend.app.services.sector_data_provider.get_all_sector_stocks", AsyncMock(return_value=mock_stocks)):
                with patch("backend.app.db.database.get_db_connection",
                           AsyncMock(side_effect=Exception("db error"))):
                    with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_queue):
                        await broadcast_stock_classification_changed()

        mock_queue.put_nowait.assert_called_once()

    async def test_no_sector_count(self):
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        mock_merged = {"미분류": []}
        mock_stocks = [
            {"code": "005930", "sector": "미분류"},
            {"code": "000660", "sector": "미분류"},
        ]

        mock_queue = MagicMock()
        mock_queue.full = MagicMock(return_value=False)
        mock_queue.put_nowait = MagicMock()

        with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
            with patch("backend.app.services.sector_data_provider.get_all_sector_stocks", AsyncMock(return_value=mock_stocks)):
                with patch("backend.app.db.database.get_db_connection",
                           AsyncMock(side_effect=Exception("db error"))):
                    with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_queue):
                        await broadcast_stock_classification_changed()

        event = mock_queue.put_nowait.call_args[0][0]
        assert event["data"]["no_sector_count"] == 2
        assert event["data"]["sector_counts"] == {}


# ── _trigger_recompute ─────────────────────────────────────────────────────────

class TestTriggerRecompute:
    """_trigger_recompute: 업종순위 재계산 신호 전송."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import _trigger_recompute
        mock_queue = MagicMock()
        mock_queue.put = AsyncMock()
        with patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            await _trigger_recompute()
        mock_queue.put.assert_awaited_once()
        item = mock_queue.put.call_args[0][0]
        assert item[0] == 1  # 우선순위
        assert item[2]["type"] == "RECOMPUTE_SECTOR"

    async def test_exception_no_raise(self):
        from backend.app.web.routes.stock_classification import _trigger_recompute
        with patch("backend.app.services.core_queues.get_control_queue",
                   side_effect=Exception("queue error")):
            await _trigger_recompute()  # 예외 전파 없음


# ── GET /all-stocks ────────────────────────────────────────────────────────────

class TestGetAllStocks:
    """GET /api/stock-classification/all-stocks."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import get_all_stocks
        mock_stocks = [{"code": "005930", "name": "삼성전자", "sector": "반도체"}]
        with patch("backend.app.services.sector_data_provider.get_all_sector_stocks",
                   AsyncMock(return_value=mock_stocks)):
            result = await get_all_stocks(_="dev")
        assert result == {"stocks": mock_stocks}


# ── GET / (get_stock_classification) ───────────────────────────────────────────

class TestGetStockClassification:
    """GET /api/stock-classification."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import get_stock_classification
        mock_custom = MagicMock()
        mock_custom.sectors = {"반도체": ["005930"]}
        mock_custom.stock_moves = {"005930": "반도체"}
        mock_merged = {"반도체": ["005930"], "미분류": []}
        mock_stocks = [{"code": "005930", "sector": "반도체"}]

        with patch("backend.app.core.stock_classification_data.load_custom_data", return_value=mock_custom):
            with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
                with patch("backend.app.services.sector_data_provider.get_all_sector_stocks", AsyncMock(return_value=mock_stocks)):
                    with patch("backend.app.core.sector_stock_cache.assemble_filter_summary", return_value="필터요약"):
                        result = await get_stock_classification(_="dev")

        assert result["custom_data"]["sectors"] == {"반도체": ["005930"]}
        assert result["custom_data"]["stock_moves"] == {"005930": "반도체"}
        assert result["merged_sectors"] == mock_merged
        assert result["edit_window_open"] is True

    async def test_filter_summary_exception(self):
        from backend.app.web.routes.stock_classification import get_stock_classification
        mock_custom = MagicMock()
        mock_custom.sectors = {}
        mock_custom.stock_moves = {}
        mock_merged = {}

        with patch("backend.app.core.stock_classification_data.load_custom_data", return_value=mock_custom):
            with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
                with patch("backend.app.services.sector_data_provider.get_all_sector_stocks",
                           AsyncMock(side_effect=Exception("db error"))):
                    result = await get_stock_classification(_="dev")

        assert result["filter_summary"] == ""
        assert result["no_sector_count"] == 0

    async def test_no_sector_count_calculation(self):
        from backend.app.web.routes.stock_classification import get_stock_classification
        mock_custom = MagicMock()
        mock_custom.sectors = {}
        mock_custom.stock_moves = {}
        mock_merged = {"미분류": []}
        mock_stocks = [
            {"code": "005930", "sector": "미분류"},
            {"code": "000660", "sector": "반도체"},
            {"code": "035420", "sector": "미분류"},
        ]

        with patch("backend.app.core.stock_classification_data.load_custom_data", return_value=mock_custom):
            with patch("backend.app.core.sector_mapping.get_merged_all_sectors", AsyncMock(return_value=mock_merged)):
                with patch("backend.app.services.sector_data_provider.get_all_sector_stocks", AsyncMock(return_value=mock_stocks)):
                    with patch("backend.app.core.sector_stock_cache.assemble_filter_summary", return_value=""):
                        result = await get_stock_classification(_="dev")

        assert result["no_sector_count"] == 2


# ── POST /rename ───────────────────────────────────────────────────────────────

class TestRenameSector:
    """POST /api/stock-classification/rename."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import rename_sector, RenameRequest
        body = RenameRequest(old_name="반도체", new_name="반도체/디스플레이")
        with patch("backend.app.core.stock_classification_data.rename_sector", AsyncMock()):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await rename_sector(body, _="dev")
        assert result["ok"] is True

    async def test_success_with_warning(self):
        from backend.app.web.routes.stock_classification import rename_sector, RenameRequest
        body = RenameRequest(old_name="반도체", new_name="반도체2")
        with patch("backend.app.core.stock_classification_data.rename_sector", AsyncMock()):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning",
                               AsyncMock(return_value={"warning": "장중 변경은 즉시 매매에 반영됩니다"})):
                        result = await rename_sector(body, _="dev")
        assert result["ok"] is True
        assert "warning" in result

    async def test_failure(self):
        from backend.app.web.routes.stock_classification import rename_sector, RenameRequest
        body = RenameRequest(old_name="반도체", new_name="반도체2")
        with patch("backend.app.core.stock_classification_data.rename_sector",
                   AsyncMock(side_effect=Exception("rename error"))):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await rename_sector(body, _="dev")
        assert result["ok"] is False
        assert "rename error" in result["error"]


# ── POST /create ───────────────────────────────────────────────────────────────

class TestCreateSector:
    """POST /api/stock-classification/create."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import create_sector, CreateRequest
        body = CreateRequest(name="신규업종")
        with patch("backend.app.core.stock_classification_data.create_sector", AsyncMock()):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await create_sector(body, _="dev")
        assert result["ok"] is True

    async def test_failure(self):
        from backend.app.web.routes.stock_classification import create_sector, CreateRequest
        body = CreateRequest(name="신규업종")
        with patch("backend.app.core.stock_classification_data.create_sector",
                   AsyncMock(side_effect=Exception("create error"))):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await create_sector(body, _="dev")
        assert result["ok"] is False
        assert "create error" in result["error"]


# ── POST /delete ───────────────────────────────────────────────────────────────

class TestDeleteSector:
    """POST /api/stock-classification/delete."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import delete_sector, DeleteRequest
        body = DeleteRequest(name="삭제업종")
        with patch("backend.app.core.stock_classification_data.delete_sector", AsyncMock()):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await delete_sector(body, _="dev")
        assert result["ok"] is True

    async def test_failure(self):
        from backend.app.web.routes.stock_classification import delete_sector, DeleteRequest
        body = DeleteRequest(name="삭제업종")
        with patch("backend.app.core.stock_classification_data.delete_sector",
                   AsyncMock(side_effect=Exception("delete error"))):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await delete_sector(body, _="dev")
        assert result["ok"] is False
        assert "delete error" in result["error"]


# ── POST /move-stock ───────────────────────────────────────────────────────────

class TestMoveStock:
    """POST /api/stock-classification/move-stock."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import move_stock, MoveStockRequest
        body = MoveStockRequest(stock_code="005930", target_sector="반도체")
        with patch("backend.app.core.stock_classification_data.move_stock", AsyncMock()):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await move_stock(body, _="dev")
        assert result["ok"] is True

    async def test_failure(self):
        from backend.app.web.routes.stock_classification import move_stock, MoveStockRequest
        body = MoveStockRequest(stock_code="005930", target_sector="반도체")
        with patch("backend.app.core.stock_classification_data.move_stock",
                   AsyncMock(side_effect=Exception("move error"))):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await move_stock(body, _="dev")
        assert result["ok"] is False
        assert "move error" in result["error"]


# ── POST /move-stocks (배치) ───────────────────────────────────────────────────

class TestMoveStocks:
    """POST /api/stock-classification/move-stocks — 배치 이동."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import move_stocks, MoveStocksRequest
        body = MoveStocksRequest(stock_codes=["005930", "000660"], target_sector="반도체")
        mock_stocks = [{"code": "005930", "sector": "반도체"}, {"code": "000660", "sector": "반도체"}]
        with patch("backend.app.core.stock_classification_data.move_stock", AsyncMock()):
            with patch("backend.app.services.sector_data_provider.get_all_sector_stocks",
                       AsyncMock(return_value=mock_stocks)):
                with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                        with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                            result = await move_stocks(body, _="dev")
        assert result["ok"] is True
        assert result["all_stocks"] == mock_stocks

    async def test_failure(self):
        from backend.app.web.routes.stock_classification import move_stocks, MoveStocksRequest
        body = MoveStocksRequest(stock_codes=["005930"], target_sector="반도체")
        with patch("backend.app.core.stock_classification_data.move_stock",
                   AsyncMock(side_effect=Exception("batch error"))):
            with patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", AsyncMock()):
                with patch("backend.app.web.routes.stock_classification._trigger_recompute", AsyncMock()):
                    with patch("backend.app.web.routes.stock_classification._maybe_warning", AsyncMock(return_value={})):
                        result = await move_stocks(body, _="dev")
        assert result["ok"] is False
        assert "batch error" in result["error"]


# ── POST /trigger-confirmed-download ───────────────────────────────────────────

class TestTriggerConfirmedDownload:
    """POST /api/stock-classification/trigger-confirmed-download."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import trigger_confirmed_download
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.confirmed_refresh_running_confirmed = False
            mock_state.integrated_system_settings_cache = {}
            with patch("backend.app.services.engine_account_notify._rebuild_layout_cache"):
                with patch("backend.app.services.market_close_pipeline.fetch_confirmed_data_only",
                           AsyncMock()):
                    with patch("asyncio.create_task", side_effect=lambda coro: (coro.close(), mock_task)[1]):
                        result = await trigger_confirmed_download(_="dev")
        assert result["ok"] is True

    async def test_already_running(self):
        from backend.app.web.routes.stock_classification import trigger_confirmed_download
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.confirmed_refresh_running_confirmed = True
            result = await trigger_confirmed_download(_="dev")
        assert result["ok"] is False
        assert "진행 중" in result["error"]

    async def test_exception(self):
        from backend.app.web.routes.stock_classification import trigger_confirmed_download

        class RaisingState:
            def __getattr__(self, name):
                raise Exception("state error")

        with patch("backend.app.services.engine_state.state", new=RaisingState()):
            result = await trigger_confirmed_download(_="dev")
        assert result["ok"] is False
        assert "state error" in result["error"]


# ── POST /trigger-5d-download ──────────────────────────────────────────────────

class TestTrigger5dDownload:
    """POST /api/stock-classification/trigger-5d-download."""

    async def test_success(self):
        from backend.app.web.routes.stock_classification import trigger_5d_download
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.confirmed_refresh_running_5d = False
            with patch("backend.app.services.market_close_pipeline.fetch_5d_data_only",
                       AsyncMock()):
                with patch("asyncio.create_task", side_effect=lambda coro: (coro.close(), mock_task)[1]):
                    result = await trigger_5d_download(_="dev")
        assert result["ok"] is True

    async def test_already_running(self):
        from backend.app.web.routes.stock_classification import trigger_5d_download
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.confirmed_refresh_running_5d = True
            result = await trigger_5d_download(_="dev")
        assert result["ok"] is False
        assert "진행 중" in result["error"]

    async def test_exception(self):
        from backend.app.web.routes.stock_classification import trigger_5d_download

        class RaisingState:
            def __getattr__(self, name):
                raise Exception("state error")

        with patch("backend.app.services.engine_state.state", new=RaisingState()):
            result = await trigger_5d_download(_="dev")
        assert result["ok"] is False
        assert "state error" in result["error"]


# ── 라우터 검증 ─────────────────────────────────────────────────────────────────

class TestStockClassificationRouter:
    """stock_classification.py: 라우터 설정 검증."""

    def test_router_prefix_and_tags(self):
        from backend.app.web.routes.stock_classification import router
        assert router.prefix == "/api/stock-classification"
        assert "stock-classification" in router.tags

    def test_router_has_routes(self):
        from backend.app.web.routes.stock_classification import router
        # 10개 엔드포인트: all-stocks, "", rename, create, delete, move-stock, move-stocks,
        # trigger-confirmed-download, trigger-5d-download, download-data-exists
        assert len(router.routes) >= 10


# ── GET /download-data-exists — 5거래일 완전성 확인 (설계서 결정 5, 세션 4) ──────

class TestCheckDownloadDataExists:
    """GET /api/stock-classification/download-data-exists — 종목별 5거래일 완전성 확인."""

    EXPECTED = ["20260728", "20260729", "20260730", "20260731", "20260801"]

    def _make_cursor(self, fetchone_result=None, fetchall_result=None):
        cursor = MagicMock()
        cursor.fetchone = AsyncMock(return_value=fetchone_result)
        cursor.fetchall = AsyncMock(return_value=fetchall_result or [])
        return cursor

    def _bars_rows(self, code, days, amt=1000, high=50000):
        """종목별 5d bars 행 리스트 생성."""
        return [
            {"code": code, "dt": d, "trade_amount": amt, "high_price": high}
            for d in days
        ]

    async def _call(self, bars_rows, mock_cache, confirmed_cnt=1, bars_5d_cnt=100):
        from backend.app.web.routes.stock_classification import check_download_data_exists
        cursors = [
            self._make_cursor(fetchone_result={"cnt": confirmed_cnt}),
            self._make_cursor(fetchone_result={"cnt": bars_5d_cnt}),
            self._make_cursor(fetchall_result=bars_rows),
        ]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(side_effect=cursors)

        with patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20260802"), \
             patch("backend.app.core.trading_calendar.get_previous_trading_day_str", return_value="20260801"), \
             patch("backend.app.services.market_close_storage._expected_5d_days", return_value=list(self.EXPECTED)), \
             patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = mock_cache
            return await check_download_data_exists(_="dev")

    async def test_all_ok(self):
        """모든 종목 5거래일 완전 — ok_count만 반환."""
        bars = self._bars_rows("005930", self.EXPECTED) + self._bars_rows("000660", self.EXPECTED)
        cache = {"005930": {"status": "active"}, "000660": {"status": "active"}}
        result = await self._call(bars, cache)
        assert result["ok_count"] == 2
        assert result["preparing_count"] == 0
        assert result["ineligible_count"] == 0
        assert result["confirmed_exists"] is True
        assert result["5d_exists"] is True
        assert result["missing_days"] == []
        assert result["has_missing_amounts"] is False
        assert result["has_missing_highs"] is False
        assert result["expected_days"] == self.EXPECTED

    async def test_preparing(self):
        """5거래일 미만 종목 — preparing_count 증가, 빠진 거래일 수집."""
        partial_days = self.EXPECTED[:3]  # 3일분만 있음
        bars = self._bars_rows("005930", self.EXPECTED) + self._bars_rows("000660", partial_days)
        cache = {"005930": {"status": "active"}, "000660": {"status": "active"}}
        result = await self._call(bars, cache)
        assert result["ok_count"] == 1
        assert result["preparing_count"] == 1
        assert result["ineligible_count"] == 0
        # 000660이 준비 중 — 빠진 2거래일 수집
        assert set(result["missing_days"]) == {"20260731", "20260801"}

    async def test_ineligible_date_mismatch(self):
        """거래일 불일치 종목 — ineligible_count 증가."""
        wrong_days = ["20260720", "20260721", "20260722", "20260723", "20260724"]
        bars = self._bars_rows("005930", self.EXPECTED) + self._bars_rows("000660", wrong_days)
        cache = {"005930": {"status": "active"}, "000660": {"status": "active"}}
        result = await self._call(bars, cache)
        assert result["ok_count"] == 1
        assert result["preparing_count"] == 0
        assert result["ineligible_count"] == 1

    async def test_ineligible_numeric_missing(self):
        """거래대금·고가 누락 종목 — ineligible + has_missing 플래그."""
        bars = self._bars_rows("005930", self.EXPECTED) + self._bars_rows("000660", self.EXPECTED, amt=0, high=0)
        cache = {"005930": {"status": "active"}, "000660": {"status": "active"}}
        result = await self._call(bars, cache)
        assert result["ok_count"] == 1
        assert result["ineligible_count"] == 1
        assert result["has_missing_amounts"] is True
        assert result["has_missing_highs"] is True

    async def test_no_active_codes(self):
        """active 종목 없음 — 모든 신규 카운트 0."""
        bars = self._bars_rows("005930", self.EXPECTED)
        cache = {"005930": {"status": "inactive"}}
        result = await self._call(bars, cache)
        assert result["ok_count"] == 0
        assert result["preparing_count"] == 0
        assert result["ineligible_count"] == 0
        assert result["missing_days"] == []

    async def test_no_5d_data(self):
        """5d 자료 전혀 없음 — 전 종목 preparing."""
        cache = {"005930": {"status": "active"}, "000660": {"status": "active"}}
        result = await self._call([], cache)
        assert result["ok_count"] == 0
        assert result["preparing_count"] == 2
        assert result["ineligible_count"] == 0
        assert set(result["missing_days"]) == set(self.EXPECTED)

    async def test_backward_compat_fields(self):
        """기존 필드(confirmed_exists, 5d_exists, trading_day) 유지 확인."""
        bars = self._bars_rows("005930", self.EXPECTED)
        cache = {"005930": {"status": "active"}}
        result = await self._call(bars, cache, confirmed_cnt=0, bars_5d_cnt=0)
        assert result["confirmed_exists"] is False
        assert result["5d_exists"] is False
        assert result["trading_day"] == "20260801"

    async def test_empty_expected_days(self):
        """거래일 캘린더 미로드 — expected_days 빈 리스트, 신규 카운트 0."""
        from backend.app.web.routes.stock_classification import check_download_data_exists
        cursors = [
            self._make_cursor(fetchone_result={"cnt": 0}),
            self._make_cursor(fetchone_result={"cnt": 0}),
        ]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(side_effect=cursors)
        with patch("backend.app.core.trading_calendar.get_current_trading_day_str", return_value="20260802"), \
             patch("backend.app.core.trading_calendar.get_previous_trading_day_str", return_value="20260801"), \
             patch("backend.app.services.market_close_storage._expected_5d_days", return_value=[]), \
             patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"status": "active"}}
            result = await check_download_data_exists(_="dev")
        assert result["ok_count"] == 0
        assert result["preparing_count"] == 0
        assert result["ineligible_count"] == 0
        assert result["expected_days"] == []
