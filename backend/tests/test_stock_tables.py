"""stock_tables.py 단위 테스트 — DB 스키마/마이그레이션/캐시 로드."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.db.stock_tables import (
    init_cache_tables,
    save_settlement_state,
    load_settlement_state,
    create_master_stocks_table,
    migrate_master_stocks_table_pk,
    migrate_add_hidden_to_custom_sectors,
    migrate_add_nxt_enable_column,
    create_stock_5d_array_table,
    save_trading_days_cache,
    load_trading_days_cache,
    load_master_stocks_table,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_db_connection():
    """DB 접근 차단 — 모든 테스트에서 실제 DB 사용 금지."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    mock_conn.rollback = AsyncMock()
    with patch("backend.app.db.stock_tables.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield mock_conn


# ── init_cache_tables ───────────────────────────────────────────────

class TestInitCacheTables:
    @pytest.mark.asyncio
    async def test_creates_tables(self, _mock_db_connection):
        await init_cache_tables()
        # 여러 CREATE TABLE + INSERT OR IGNORE + commit 호출
        assert _mock_db_connection.execute.call_count > 0
        _mock_db_connection.commit.assert_called_once()


# ── save_settlement_state ───────────────────────────────────────────

class TestSaveSettlementState:
    @pytest.mark.asyncio
    async def test_save_success(self, _mock_db_connection):
        with patch("backend.app.db.db_writer.execute_db_write", new=AsyncMock()):
            await save_settlement_state({
                "accumulated_investment": 1000000,
                "orderable": 500000,
                "initial_deposit": 1000000,
            })
            # 예외 없이 완료

    @pytest.mark.asyncio
    async def test_save_exception_logged(self, _mock_db_connection):
        """저장 실패 시 예외 로깅 후 종료 (raise 아님)."""
        with patch("backend.app.db.db_writer.execute_db_write", new=AsyncMock(side_effect=Exception("DB error"))):
            # 예외가 raise되지 않고 로깅만 수행
            await save_settlement_state({"accumulated_investment": 0})


# ── load_settlement_state ───────────────────────────────────────────

class TestLoadSettlementState:
    @pytest.mark.asyncio
    async def test_load_with_data(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={
            "accumulated_investment": 1000000,
            "orderable": 500000,
            "initial_deposit": 1000000,
        })
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_settlement_state()
        assert result is not None
        assert result["accumulated_investment"] == 1000000
        assert result["orderable"] == 500000
        assert result["initial_deposit"] == 1000000

    @pytest.mark.asyncio
    async def test_load_no_data(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_settlement_state()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_exception_returns_none(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        result = await load_settlement_state()
        assert result is None


# ── create_master_stocks_table ──────────────────────────────────────

class TestCreateMasterStocksTable:
    @pytest.mark.asyncio
    async def test_creates_table_and_indexes(self, _mock_db_connection):
        await create_master_stocks_table()
        # CREATE TABLE + 4 indexes + commit
        assert _mock_db_connection.execute.call_count >= 5
        _mock_db_connection.commit.assert_called_once()


# ── migrate_master_stocks_table_pk ──────────────────────────────────

class TestMigrateMasterStocksTablePk:
    @pytest.mark.asyncio
    async def test_no_table_skip(self, _mock_db_connection):
        """master_stocks_table이 없으면 스킵."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_master_stocks_table_pk()
        # PRAGMA table_info만 호출
        assert _mock_db_connection.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_pk_already_exists_skip(self, _mock_db_connection):
        """code 컬럼에 PK 이미 있으면 스킵."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code", "pk": 1},
            {"name": "name", "pk": 0},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_master_stocks_table_pk()
        # PRAGMA table_info만 호출
        assert _mock_db_connection.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_pk_missing_migration(self, _mock_db_connection):
        """code 컬럼에 PK 없으면 마이그레이션 수행."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code", "pk": 0},
            {"name": "name", "pk": 0},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_master_stocks_table_pk()
        # PRAGMA + CREATE tmp + INSERT + RENAME old + RENAME tmp + 4 indexes + DROP old
        assert _mock_db_connection.execute.call_count > 5


# ── migrate_add_hidden_to_custom_sectors ────────────────────────────

class TestMigrateAddHidden:
    @pytest.mark.asyncio
    async def test_column_missing_adds_it(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "stock_code"},
            {"name": "name"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_hidden_to_custom_sectors()
        # PRAGMA + ALTER TABLE + commit
        assert _mock_db_connection.execute.call_count == 2
        _mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_column_exists_skip(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "stock_code"},
            {"name": "name"},
            {"name": "hidden"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_hidden_to_custom_sectors()
        # PRAGMA만 호출
        assert _mock_db_connection.execute.call_count == 1


# ── migrate_add_nxt_enable_column ───────────────────────────────────

class TestMigrateAddNxtEnable:
    @pytest.mark.asyncio
    async def test_column_missing_adds_it(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"},
            {"name": "name"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_nxt_enable_column()
        assert _mock_db_connection.execute.call_count == 2
        _mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_column_exists_skip(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"},
            {"name": "nxt_enable"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_nxt_enable_column()
        assert _mock_db_connection.execute.call_count == 1


# ── create_stock_5d_array_table ─────────────────────────────────────

class TestCreateStock5dArrayTable:
    @pytest.mark.asyncio
    async def test_creates_table(self, _mock_db_connection):
        await create_stock_5d_array_table()
        assert _mock_db_connection.execute.call_count == 1
        _mock_db_connection.commit.assert_called_once()


# ── save_trading_days_cache ─────────────────────────────────────────

class TestSaveTradingDaysCache:
    @pytest.mark.asyncio
    async def test_save_multiple_years(self, _mock_db_connection):
        cache = {
            2024: {"2024-01-02", "2024-01-03"},
            2025: {"2025-01-01", "2025-01-02"},
        }
        await save_trading_days_cache(cache)
        # 2년 = 2 INSERT OR REPLACE + commit
        assert _mock_db_connection.execute.call_count == 2
        _mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_empty_cache(self, _mock_db_connection):
        await save_trading_days_cache({})
        # 빈 캐시 — INSERT 호출 없음, commit만
        assert _mock_db_connection.execute.call_count == 0
        _mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_exception_logged(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        # 예외가 raise되지 않고 로깅만
        await save_trading_days_cache({2024: {"2024-01-01"}})


# ── load_trading_days_cache ─────────────────────────────────────────

class TestLoadTradingDaysCache:
    @pytest.mark.asyncio
    async def test_load_with_data(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"year": 2024, "data": json.dumps(["2024-01-02", "2024-01-03"])},
            {"year": 2025, "data": json.dumps(["2025-01-01"])},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_trading_days_cache()
        assert result is not None
        assert 2024 in result
        assert result[2024] == {"2024-01-02", "2024-01-03"}
        assert 2025 in result
        assert result[2025] == {"2025-01-01"}

    @pytest.mark.asyncio
    async def test_load_no_data(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_trading_days_cache()
        assert result is None

    @pytest.mark.asyncio
    async def test_load_exception_returns_none(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        result = await load_trading_days_cache()
        assert result is None


# ── load_master_stocks_table ────────────────────────────────────────

class TestLoadMasterStocksTable:
    @pytest.mark.asyncio
    async def test_load_with_data(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"code": "005930", "name": "삼성전자", "market": "코스피", "sector": "반도체",
             "cur_price": 70000, "change": 500, "change_rate": 0.72,
             "trade_amount": 100000, "avg_5d_trade_amount": 90000, "high_5d_price": 71000,
             "date": "20240101", "nxt_enable": 1},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_master_stocks_table()
        assert "005930" in result
        entry = result["005930"]
        assert entry["name"] == "삼성전자"
        assert entry["cur_price"] == 70000
        assert entry["sector"] == "반도체"
        assert entry["nxt_enable"] is True
        assert entry["status"] == "active"

    @pytest.mark.asyncio
    async def test_load_empty_sector_defaults_to_미분류(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"code": "005930", "name": "삼성전자", "market": "코스피", "sector": None,
             "cur_price": 70000, "change": 500, "change_rate": 0.72,
             "trade_amount": 100000, "avg_5d_trade_amount": 90000, "high_5d_price": 71000,
             "date": "20240101", "nxt_enable": 0},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_master_stocks_table()
        assert result["005930"]["sector"] == "미분류"

    @pytest.mark.asyncio
    async def test_load_no_data(self, _mock_db_connection):
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_master_stocks_table()
        assert result == {}

    @pytest.mark.asyncio
    async def test_load_exception_returns_empty(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        result = await load_master_stocks_table()
        assert result == {}
