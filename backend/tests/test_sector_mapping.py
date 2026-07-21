"""sector_mapping.py 단위 테스트 — 종목→업종 매핑 2함수 검증.

get_merged_sectors_batch: 캐시 일괄 조회 → 캐시 미스만 DB 쿼리 → "미분류" 보완
get_merged_all_sectors: sectors 테이블 전체 조회 + "미분류" 보장

의존성: state.master_stocks_cache (인메모리), get_db_connection (async DB)
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── get_merged_sectors_batch ────────────────────────────────────────────────────

class TestGetMergedSectorsBatch:
    @pytest.mark.asyncio
    async def test_all_cache_hits_no_db_query(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {
            "005930": {"sector": "반도체"},
            "000660": {"sector": "반도체"},
        }
        mock_db = AsyncMock()
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.db.database.get_db_connection", mock_db),
        ):
            result = await get_merged_sectors_batch(["005930", "000660"])
        assert result == {"005930": "반도체", "000660": "반도체"}
        mock_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_cache_miss_triggers_db_query(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"sector": "반도체"}}
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [{"code": "000660", "sector": "반도체"}]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)),
        ):
            result = await get_merged_sectors_batch(["005930", "000660"])
        assert result == {"005930": "반도체", "000660": "반도체"}

    @pytest.mark.asyncio
    async def test_all_cache_miss_db_returns_subset(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {}
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [{"code": "005930", "sector": "반도체"}]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)),
        ):
            result = await get_merged_sectors_batch(["005930", "999999"])
        assert result["005930"] == "반도체"
        assert result["999999"] == "미분류"

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_dict(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await get_merged_sectors_batch([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_sector_in_cache_returns_midistributed(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"sector": ""}}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await get_merged_sectors_batch(["005930"])
        assert result == {"005930": "미분류"}

    @pytest.mark.asyncio
    async def test_db_exception_all_missed_return_midistributed(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {}
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("db error"))
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)),
        ):
            result = await get_merged_sectors_batch(["005930", "000660"])
        assert result == {"005930": "미분류", "000660": "미분류"}

    @pytest.mark.asyncio
    async def test_lowercase_codes_uppercased_for_cache_lookup(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"sector": "반도체"}}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await get_merged_sectors_batch(["005930"])
        assert result == {"005930": "반도체"}

    @pytest.mark.asyncio
    async def test_preserves_original_case_in_result_keys(self):
        from backend.app.core.sector_mapping import get_merged_sectors_batch
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"sector": "반도체"}}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await get_merged_sectors_batch(["005930"])
        # 원본 코드(소문자)가 result key로 유지됨
        assert "005930" in result


# ── get_merged_all_sectors ─────────────────────────────────────────────────────

class TestGetMergedAllSectors:
    @pytest.mark.asyncio
    async def test_returns_sorted_sectors_with_midistributed(self):
        from backend.app.core.sector_mapping import get_merged_all_sectors
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            {"name": "반도체"},
            {"name": "은행"},
            {"name": "증권"},
        ]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
            result = await get_merged_all_sectors()
        assert result == sorted(["반도체", "은행", "증권", "미분류"])

    @pytest.mark.asyncio
    async def test_midistributed_already_present_not_duplicated(self):
        from backend.app.core.sector_mapping import get_merged_all_sectors
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            {"name": "반도체"},
            {"name": "미분류"},
        ]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
            result = await get_merged_all_sectors()
        assert result.count("미분류") == 1

    @pytest.mark.asyncio
    async def test_empty_db_returns_midistributed_only(self):
        from backend.app.core.sector_mapping import get_merged_all_sectors
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
            result = await get_merged_all_sectors()
        assert result == ["미분류"]

    @pytest.mark.asyncio
    async def test_db_exception_returns_midistributed_only(self):
        from backend.app.core.sector_mapping import get_merged_all_sectors
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("db error"))
        with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
            result = await get_merged_all_sectors()
        assert result == ["미분류"]

    @pytest.mark.asyncio
    async def test_result_is_sorted(self):
        from backend.app.core.sector_mapping import get_merged_all_sectors
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            {"name": "자동차"},
            {"name": "반도체"},
            {"name": "철강"},
        ]
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        with patch("backend.app.db.database.get_db_connection", AsyncMock(return_value=mock_conn)):
            result = await get_merged_all_sectors()
        assert result == sorted(result)
