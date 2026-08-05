"""stock_tables.py 단위 테스트 — DB 스키마/마이그레이션/캐시 로드."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock

from backend.app.db.stock_tables import (
    init_cache_tables,
    save_settlement_state,
    load_settlement_state,
    create_master_stocks_table,
    migrate_master_stocks_table_pk,
    migrate_add_hidden_to_custom_sectors,
    migrate_add_raw_payload_to_stock_5d_bars,
    migrate_drop_raw_status_columns,
    create_stock_5d_bars_table,
    save_trading_days_cache,
    load_trading_days_cache,
    load_master_stocks_table,
    get_earliest_base_asset,
    get_deposit_history,
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
    async def test_save_exception_propagates(self, _mock_db_connection):
        """저장 실패 시 예외 전파 (P20 폴백 금지)."""
        with patch("backend.app.db.db_writer.execute_db_write", new=AsyncMock(side_effect=Exception("DB error"))):
            with pytest.raises(Exception, match="DB error"):
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
    async def test_load_exception_propagates(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await load_settlement_state()


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


# ── migrate_add_raw_status_to_master_stocks 제거됨 (자료 상태 시스템 전면 제거) ──


# ── migrate_add_raw_payload_to_stock_5d_bars ────────────────────────

class TestMigrateAddRawPayloadToStock5dBars:
    @pytest.mark.asyncio
    async def test_column_missing_adds_it(self, _mock_db_connection):
        """raw_payload 컬럼이 없으면 추가."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"}, {"name": "dt"}, {"name": "trade_amount"},
            {"name": "high_price"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_raw_payload_to_stock_5d_bars()
        # PRAGMA + ALTER TABLE + commit
        assert _mock_db_connection.execute.call_count == 2
        _mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_column_exists_skip(self, _mock_db_connection):
        """raw_payload 컬럼이 있으면 스킵 (멱등성)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"}, {"name": "dt"}, {"name": "trade_amount"},
            {"name": "high_price"}, {"name": "raw_payload"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_raw_payload_to_stock_5d_bars()
        # PRAGMA만 호출
        assert _mock_db_connection.execute.call_count == 1
        _mock_db_connection.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_default_value_masking_missing(self, _mock_db_connection):
        """추가되는 컬럼에 기본값이 없는지 확인 (W8 폴백 금지)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{"name": "code"}])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_add_raw_payload_to_stock_5d_bars()
        for call in _mock_db_connection.execute.call_args_list:
            sql = call.args[0] if call.args else call.kwargs.get("sql", "")
            if "ALTER TABLE" in str(sql).upper():
                assert "DEFAULT" not in str(sql).upper(), \
                    f"원문 컬럼에 기본값이 있으면 누락이 정상값으로 위장됨: {sql}"


# ── migrate_drop_raw_status_columns ─────────────────────────────────

class TestMigrateDropRawStatusColumns:
    """자료 상태 컬럼 4개 삭제 마이그레이션 (자료 상태 시스템 전면 제거)."""

    @pytest.mark.asyncio
    async def test_drops_all_four_columns_when_present(self, _mock_db_connection):
        """4개 컬럼이 모두 존재하면 전부 DROP."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"}, {"name": "name"}, {"name": "market"},
            {"name": "sector"}, {"name": "cur_price"}, {"name": "change"},
            {"name": "change_rate"}, {"name": "trade_amount"},
            {"name": "avg_5d_trade_amount"}, {"name": "high_5d_price"},
            {"name": "date"}, {"name": "nxt_enable"},
            {"name": "raw_status"}, {"name": "request_date"},
            {"name": "response_date"}, {"name": "problems"},
            {"name": "raw_payload"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_drop_raw_status_columns()
        # PRAGMA + DROP 4회 = 5 execute calls
        assert _mock_db_connection.execute.call_count == 5
        _mock_db_connection.commit.assert_called_once()
        # DROP COLUMN 호출 4개 확인
        drop_calls = [
            call for call in _mock_db_connection.execute.call_args_list
            if "DROP COLUMN" in str(call.args[0] if call.args else "").upper()
        ]
        assert len(drop_calls) == 4
        dropped_names = {
            str(call.args[0]).split('"')[1] for call in drop_calls
        }
        assert dropped_names == {"raw_status", "request_date", "response_date", "problems"}

    @pytest.mark.asyncio
    async def test_skips_when_all_columns_already_dropped(self, _mock_db_connection):
        """컬럼이 이미 삭제된 경우 스킵 (멱등성)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"}, {"name": "name"}, {"name": "market"},
            {"name": "sector"}, {"name": "cur_price"}, {"name": "change"},
            {"name": "change_rate"}, {"name": "trade_amount"},
            {"name": "avg_5d_trade_amount"}, {"name": "high_5d_price"},
            {"name": "date"}, {"name": "nxt_enable"},
            {"name": "raw_payload"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_drop_raw_status_columns()
        # PRAGMA만 호출
        assert _mock_db_connection.execute.call_count == 1
        _mock_db_connection.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_drops_only_present_subset(self, _mock_db_connection):
        """일부 컬럼만 남아 있으면 해당 컬럼만 DROP."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"}, {"name": "name"},
            {"name": "raw_status"}, {"name": "problems"},
            {"name": "raw_payload"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_drop_raw_status_columns()
        # PRAGMA + DROP 2회 = 3 execute calls
        assert _mock_db_connection.execute.call_count == 3
        _mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_table_missing(self, _mock_db_connection):
        """테이블이 없으면 스킵."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_drop_raw_status_columns()
        # PRAGMA만 호출
        assert _mock_db_connection.execute.call_count == 1
        _mock_db_connection.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raw_payload_preserved(self, _mock_db_connection):
        """raw_payload 컬럼은 삭제 대상이 아님 (원문 보존)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"name": "code"}, {"name": "raw_status"},
            {"name": "request_date"}, {"name": "response_date"},
            {"name": "problems"}, {"name": "raw_payload"},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        await migrate_drop_raw_status_columns()
        # DROP COLUMN 호출에 raw_payload 없는지 확인
        for call in _mock_db_connection.execute.call_args_list:
            sql = str(call.args[0] if call.args else "")
            if "DROP COLUMN" in sql.upper():
                assert "raw_payload" not in sql, \
                    "raw_payload는 원문 보존 대상 — 삭제하면 안 됨"


# ── create_stock_5d_bars_table ─────────────────────────────────────

class TestCreateStock5dBarsTable:
    @pytest.mark.asyncio
    async def test_creates_table(self, _mock_db_connection):
        await create_stock_5d_bars_table()
        # DROP IF EXISTS + CREATE IF NOT EXISTS = 2 execute calls
        assert _mock_db_connection.execute.call_count == 2
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
    async def test_save_exception_propagates(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        # 예외 전파 (P20 폴백 금지)
        with pytest.raises(Exception, match="DB error"):
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
    async def test_load_exception_propagates(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        # 예외 전파 (P20 폴백 금지)
        with pytest.raises(Exception, match="DB error"):
            await load_trading_days_cache()


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
        # 자료 상태 관련 필드 제거 확인
        assert "raw_status" not in entry
        assert "request_date" not in entry
        assert "response_date" not in entry
        assert "problems" not in entry

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
    async def test_load_null_realtime_fields_preserved(self, _mock_db_connection):
        """DB NULL → None 보존 검증 (20:00~20:40 구간: _reset_realtime_fields 후 DB NULL).

        '데이터 없음'의 단일 기준은 None. 0 폴백 금지.
        4개 실시간 필드(cur_price/change/change_rate/trade_amount)가 모두 None으로 로드되어야 함.
        avg_5d_trade_amount/high_5d_price도 None 보존 — 5일 자료 부족 시 0이 아닌 None으로 저장.
        """
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"code": "005930", "name": "삼성전자", "market": "코스피", "sector": "반도체",
             "cur_price": None, "change": None, "change_rate": None,
             "trade_amount": None, "avg_5d_trade_amount": None, "high_5d_price": None,
             "date": "", "nxt_enable": 1},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await load_master_stocks_table()
        entry = result["005930"]
        assert entry["cur_price"] is None, f"cur_price should be None, got {entry['cur_price']!r}"
        assert entry["change"] is None, f"change should be None, got {entry['change']!r}"
        assert entry["change_rate"] is None, f"change_rate should be None, got {entry['change_rate']!r}"
        assert entry["trade_amount"] is None, f"trade_amount should be None, got {entry['trade_amount']!r}"
        # 5일 파생값 None 보존 — 0으로 덮어 "자료 없음"을 숨기지 않음
        assert entry["avg_5d_trade_amount"] is None
        assert entry["high_5d_price"] is None

    @pytest.mark.asyncio
    async def test_load_exception_propagates(self, _mock_db_connection):
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        # 예외 전파 (P20 폴백 금지) — 호출자가 빈 dict를 "데이터 없음"으로 오인 방지
        with pytest.raises(Exception, match="DB error"):
            await load_master_stocks_table()


# ── get_earliest_base_asset ─────────────────────────────────────────

class TestGetEarliestBaseAsset:
    @pytest.mark.asyncio
    async def test_returns_earliest_total_asset(self, _mock_db_connection):
        """가장 오래된 total_asset 반환 (누적 카드 분모용)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"total_asset": 1000000})
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await get_earliest_base_asset(_mock_db_connection, trade_mode="test")
        assert result == 1000000

    @pytest.mark.asyncio
    async def test_returns_none_when_no_snapshot(self, _mock_db_connection):
        """스냅샷 없으면 None (P20 폴백 금지 — 프론트에서 rate null → '-' 표시)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await get_earliest_base_asset(_mock_db_connection, trade_mode="test")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_propagates(self, _mock_db_connection):
        """예외 전파 (P20 폴백 금지)."""
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await get_earliest_base_asset(_mock_db_connection, trade_mode="test")


# ── get_deposit_history ─────────────────────────────────────────────

class TestGetDepositHistory:
    @pytest.mark.asyncio
    async def test_returns_deposit_rows_ascending(self, _mock_db_connection):
        """daily_deposit > 0 행을 date 오름차순으로 반환."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"date": "2026-01-05", "daily_deposit": 500000},
            {"date": "2026-02-10", "daily_deposit": 300000},
        ])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await get_deposit_history(_mock_db_connection, trade_mode="test")
        assert result == [
            {"date": "2026-01-05", "daily_deposit": 500000},
            {"date": "2026-02-10", "daily_deposit": 300000},
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_deposit(self, _mock_db_connection):
        """입금 이력 없으면 빈 리스트 (P20 — None 폴백 금지, 빈 리스트는 유효값)."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])
        _mock_db_connection.execute = AsyncMock(return_value=mock_cursor)
        result = await get_deposit_history(_mock_db_connection, trade_mode="test")
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_propagates(self, _mock_db_connection):
        """예외 전파 (P20 폴백 금지)."""
        _mock_db_connection.execute = AsyncMock(side_effect=Exception("DB error"))
        with pytest.raises(Exception, match="DB error"):
            await get_deposit_history(_mock_db_connection, trade_mode="test")


# ── 원자료 결과 계약 (broker_providers — 설계서 4.1·4.3) ────────────────────

class TestRawStockFetchResult:
    def test_create_with_payload(self):
        """raw_payload를 지정해 생성 가능."""
        from backend.app.core.broker_providers import RawStockFetchResult
        result = RawStockFetchResult(
            code="005930",
            raw_payload={"dt": "20260804", "cur_prc": "70,000"},
        )
        assert result.code == "005930"
        assert result.raw_payload == {"dt": "20260804", "cur_prc": "70,000"}

    def test_defaults_for_optional_fields(self):
        """선택 필드 기본값 — raw_payload 누락 시 None (W8 폴백 금지)."""
        from backend.app.core.broker_providers import RawStockFetchResult
        result = RawStockFetchResult(code="005930")
        assert result.raw_payload is None

    def test_frozen(self):
        """frozen dataclass — 생성 후 필드 변경 불가 (계약 불변)."""
        from backend.app.core.broker_providers import RawStockFetchResult
        result = RawStockFetchResult(code="005930", raw_payload={"dt": "20260804"})
        with pytest.raises(AttributeError):
            result.raw_payload = None  # type: ignore[misc]

    def test_failed_fetch_has_none_payload(self):
        """수신 실패 — raw_payload=None으로 구분 (설계서 4.3)."""
        from backend.app.core.broker_providers import RawStockFetchResult
        result = RawStockFetchResult(code="005930")
        assert result.raw_payload is None
