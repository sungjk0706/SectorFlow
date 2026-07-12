"""stock_classification_data.py 단위 테스트 — 업종분류 커스텀 데이터 관리."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.core.stock_classification_data import (
    StockClassificationData,
    load_custom_data,
    load_custom_data_readonly,
    update_sector_in_cache,
    rename_sector,
    create_sector,
    delete_sector,
    move_stock,
    sync_sector_from_custom_sectors,
)


# ── StockClassificationData / load_custom_data ──────────────────────

class TestStockClassificationData:
    def test_default_empty(self):
        d = StockClassificationData()
        assert d.sectors == {}
        assert d.stock_moves == {}

    def test_load_custom_data_returns_empty(self):
        result = load_custom_data()
        assert isinstance(result, StockClassificationData)
        assert result.sectors == {}

    def test_load_custom_data_readonly_returns_empty(self):
        result = load_custom_data_readonly()
        assert isinstance(result, StockClassificationData)
        assert result.stock_moves == {}


# ── update_sector_in_cache ──────────────────────────────────────────

class TestUpdateSectorInCache:
    def test_updates_existing_entry(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"name": "삼성전자", "sector": "전기전자"}}
            update_sector_in_cache("005930", "반도체")
            assert mock_state.master_stocks_cache["005930"]["sector"] == "반도체"

    def test_skips_missing_entry(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {}
            # 경고 로그만 출력, 예외 발생하지 않음
            update_sector_in_cache("999999", "반도체")
            assert "999999" not in mock_state.master_stocks_cache


# ── rename_sector (async) ───────────────────────────────────────────

class TestRenameSector:
    @pytest.mark.asyncio
    async def test_empty_old_name_raises(self):
        with pytest.raises(ValueError, match="기존 업종명과 새 업종명은 필수"):
            await rename_sector("", "새업종")

    @pytest.mark.asyncio
    async def test_empty_new_name_raises(self):
        with pytest.raises(ValueError, match="기존 업종명과 새 업종명은 필수"):
            await rename_sector("기존업종", "")

    @pytest.mark.asyncio
    async def test_same_name_raises(self):
        with pytest.raises(ValueError, match="동일"):
            await rename_sector("전기전자", "전기전자")

    @pytest.mark.asyncio
    async def test_successful_rename(self):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"sector": "전기전자"}}
            await rename_sector("전기전자", "반도체")
            # 3개 UPDATE 호출 확인
            assert mock_conn.execute.call_count == 3
            mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_error_rollback(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_conn.rollback = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            with pytest.raises(Exception, match="DB error"):
                await rename_sector("전기전자", "반도체")
            mock_conn.rollback.assert_called_once()


# ── create_sector (async) ───────────────────────────────────────────

class TestCreateSector:
    @pytest.mark.asyncio
    async def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="업종명은 필수"):
            await create_sector("")

    @pytest.mark.asyncio
    async def test_successful_create(self):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            await create_sector("신업종")
            # SELECT + INSERT = 2 calls
            assert mock_conn.execute.call_count == 2
            mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_raises(self):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            with pytest.raises(ValueError, match="이미 존재하는 업종명"):
                await create_sector("기존업종")

    @pytest.mark.asyncio
    async def test_db_error_rollback(self):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        # SELECT는 성공, INSERT에서 실패
        mock_conn.execute = AsyncMock(side_effect=[mock_cursor, Exception("DB error")])
        mock_conn.rollback = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            with pytest.raises(Exception, match="DB error"):
                await create_sector("신업종")
            mock_conn.rollback.assert_called_once()


# ── delete_sector (async) ───────────────────────────────────────────

class TestDeleteSector:
    @pytest.mark.asyncio
    async def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="업종명은 필수"):
            await delete_sector("")

    @pytest.mark.asyncio
    async def test_successful_delete(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {
                "005930": {"sector": "전기전자"},
                "005935": {"sector": "다른업종"},
            }
            await delete_sector("전기전자")
            # DELETE + UPDATE + DELETE = 3 calls
            assert mock_conn.execute.call_count == 3
            mock_conn.commit.assert_called_once()
            # 캐시에서 "미분류"로 변경
            assert mock_state.master_stocks_cache["005930"]["sector"] == "미분류"
            # 다른 업종은 변경되지 않음
            assert mock_state.master_stocks_cache["005935"]["sector"] == "다른업종"

    @pytest.mark.asyncio
    async def test_db_error_rollback(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_conn.rollback = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            with pytest.raises(Exception, match="DB error"):
                await delete_sector("전기전자")
            mock_conn.rollback.assert_called_once()


# ── move_stock (async) ──────────────────────────────────────────────

class TestMoveStock:
    @pytest.mark.asyncio
    async def test_empty_code_raises(self):
        with pytest.raises(ValueError, match="종목코드와 대상 업종명은 필수"):
            await move_stock("", "전기전자")

    @pytest.mark.asyncio
    async def test_empty_sector_raises(self):
        with pytest.raises(ValueError, match="종목코드와 대상 업종명은 필수"):
            await move_stock("005930", "")

    @pytest.mark.asyncio
    async def test_successful_move(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)), \
             patch("backend.app.core.stock_classification_data.update_sector_in_cache") as mock_update:
            await move_stock("005930", "반도체")
            # UPDATE + INSERT OR REPLACE + INSERT OR IGNORE = 3 calls
            assert mock_conn.execute.call_count == 3
            mock_conn.commit.assert_called_once()
            mock_update.assert_called_once_with("005930", "반도체")

    @pytest.mark.asyncio
    async def test_db_error_rollback(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_conn.rollback = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            with pytest.raises(Exception, match="DB error"):
                await move_stock("005930", "반도체")
            mock_conn.rollback.assert_called_once()


# ── sync_sector_from_custom_sectors (async) ─────────────────────────

class TestSyncSectorFromCustomSectors:
    @pytest.mark.asyncio
    async def test_successful_sync(self):
        """활성 매핑 + 숨김 매핑 동기화."""
        active_rows = [{"stock_code": "005930", "name": "반도체"}]
        hidden_rows = [{"stock_code": "005935", "name": "반도체"}]
        master_rows = [{"code": "005930"}, {"code": "005935"}]

        async def _execute(query, *args):
            if "hidden = 0" in query and "SELECT" in query:
                cur = AsyncMock()
                cur.fetchall = AsyncMock(return_value=active_rows)
                return cur
            elif "hidden = 1" in query and "SELECT" in query:
                cur = AsyncMock()
                cur.fetchall = AsyncMock(return_value=hidden_rows)
                return cur
            elif "SELECT code FROM master_stocks_table" in query:
                cur = AsyncMock()
                cur.fetchall = AsyncMock(return_value=master_rows)
                return cur
            return AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=_execute)
        mock_conn.commit = AsyncMock()

        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.stock_classification_data.update_sector_in_cache") as mock_update:
            mock_state.master_stocks_cache = {}
            await sync_sector_from_custom_sectors()
            mock_conn.commit.assert_called_once()
            # 활성 1종목 + 복원 1종목 = 2회 호출
            assert mock_update.call_count == 2

    @pytest.mark.asyncio
    async def test_orphaned_stock_hidden(self):
        """master_stocks_table에 없는 종목은 hidden=1로 숨김."""
        active_rows = [{"stock_code": "999999", "name": "삭제된종목"}]
        master_rows = [{"code": "005930"}]

        async def _execute(query, *args):
            if "hidden = 0" in query and "SELECT" in query:
                cur = AsyncMock()
                cur.fetchall = AsyncMock(return_value=active_rows)
                return cur
            elif "hidden = 1" in query and "SELECT" in query:
                cur = AsyncMock()
                cur.fetchall = AsyncMock(return_value=[])
                return cur
            elif "SELECT code FROM master_stocks_table" in query:
                cur = AsyncMock()
                cur.fetchall = AsyncMock(return_value=master_rows)
                return cur
            return AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=_execute)
        mock_conn.commit = AsyncMock()

        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.stock_classification_data.update_sector_in_cache"):
            mock_state.master_stocks_cache = {}
            await sync_sector_from_custom_sectors()
            mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_error_rollback(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_conn.rollback = AsyncMock()
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)), \
             patch("backend.app.services.engine_state.state"):
            with pytest.raises(Exception, match="DB error"):
                await sync_sector_from_custom_sectors()
            mock_conn.rollback.assert_called_once()
