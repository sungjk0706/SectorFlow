"""settings_file DB 연동 통합 테스트.

in-memory SQLite를 사용하여 load_integrated_system_settings()와
save_settings()가 integrated_system_settings 테이블과 정상적으로
상호작용하는지 검증.
"""
from __future__ import annotations

import pytest
import aiosqlite

from backend.app.db import database
from backend.app.core.settings_file import (
    load_integrated_system_settings,
    save_settings,
    update_settings,
)


@pytest.fixture
async def in_memory_db():
    """in-memory SQLite 연결 생성 및 integrated_system_settings 테이블 구성."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS integrated_system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    await conn.commit()

    # database 모듈의 전역 연결을 in-memory로 교체
    original_conn = database._db_connection
    database._db_connection = conn

    yield conn

    # 정리
    database._db_connection = original_conn
    await conn.close()


class TestLoadIntegratedSystemSettingsDB:

    @pytest.mark.asyncio
    async def test_returns_defaults_when_table_empty(self, in_memory_db):
        """테이블이 빈 경우 기본값이 반환되는지 확인."""
        result = await load_integrated_system_settings()

        assert result["trade_mode"] == "test"
        assert result["time_scheduler_on"] is False
        assert result["broker"] == "kiwoom"
        assert result["sector_max_targets"] == 3

    @pytest.mark.asyncio
    async def test_loads_boolean_value_from_db(self, in_memory_db):
        """boolean 타입 값이 DB에서 올바르게 로드되는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("time_scheduler_on", "True", "boolean"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["time_scheduler_on"] is True

    @pytest.mark.asyncio
    async def test_loads_number_value_from_db(self, in_memory_db):
        """number 타입 값이 DB에서 올바르게 로드되는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("sector_max_targets", "5", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["sector_max_targets"] == 5

    @pytest.mark.asyncio
    async def test_loads_float_value_from_db(self, in_memory_db):
        """float 타입 값이 DB에서 올바르게 로드되는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("sector_min_rise_ratio_pct", "75.5", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["sector_min_rise_ratio_pct"] == 75.5

    @pytest.mark.asyncio
    async def test_loads_json_value_from_db(self, in_memory_db):
        """json 타입 값이 DB에서 올바르게 로드되는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("sector_weights", '{"rise_ratio": 0.6, "total_trade_amount": 0.4}', "json"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["sector_weights"]["rise_ratio"] == 0.6
        assert result["sector_weights"]["total_trade_amount"] == 0.4

    @pytest.mark.asyncio
    async def test_loads_string_value_from_db(self, in_memory_db):
        """string 타입 값이 DB에서 올바르게 로드되는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("broker", "ls", "string"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["broker"] == "ls"

    @pytest.mark.asyncio
    async def test_db_value_overrides_default(self, in_memory_db):
        """DB 값이 기본값보다 우선하는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("trade_mode", "real", "string"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["trade_mode"] == "real"

    @pytest.mark.asyncio
    async def test_migrates_legacy_trade_mode_mock_to_test(self, in_memory_db):
        """레거시 trade_mode='mock'이 'test'로 마이그레이션되는지 확인."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("trade_mode", "mock", "string"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["trade_mode"] == "test"


class TestSaveSettingsDB:

    @pytest.mark.asyncio
    async def test_saves_boolean_to_db(self, in_memory_db):
        """boolean 값이 DB에 올바른 타입으로 저장되는지 확인."""
        await save_settings({"time_scheduler_on": True})

        cursor = await in_memory_db.execute(
            "SELECT value, value_type FROM integrated_system_settings WHERE key = ?",
            ("time_scheduler_on",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "True"
        assert row["value_type"] == "boolean"

    @pytest.mark.asyncio
    async def test_saves_number_to_db(self, in_memory_db):
        """number 값이 DB에 올바른 타입으로 저장되는지 확인."""
        await save_settings({"sector_max_targets": 7})

        cursor = await in_memory_db.execute(
            "SELECT value, value_type FROM integrated_system_settings WHERE key = ?",
            ("sector_max_targets",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "7"
        assert row["value_type"] == "number"

    @pytest.mark.asyncio
    async def test_saves_json_to_db(self, in_memory_db):
        """json 값이 DB에 올바른 타입으로 저장되는지 확인."""
        weights = {"rise_ratio": 0.7, "total_trade_amount": 0.3}
        await save_settings({"sector_weights": weights})

        cursor = await in_memory_db.execute(
            "SELECT value, value_type FROM integrated_system_settings WHERE key = ?",
            ("sector_weights",),
        )
        row = await cursor.fetchone()
        assert row["value_type"] == "json"
        import json
        parsed = json.loads(row["value"])
        assert parsed["rise_ratio"] == 0.7

    @pytest.mark.asyncio
    async def test_overwrites_existing_key(self, in_memory_db):
        """동일 key 저장 시 기존 값이 덮어쓰기되는지 확인."""
        await save_settings({"broker": "kiwoom"})
        await save_settings({"broker": "ls"})

        cursor = await in_memory_db.execute(
            "SELECT value FROM integrated_system_settings WHERE key = ?",
            ("broker",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "ls"

    @pytest.mark.asyncio
    async def test_roundtrip_save_then_load(self, in_memory_db):
        """저장 후 로드 시 동일 값이 반환되는지 확인 (round-trip)."""
        test_settings = {
            "time_scheduler_on": True,
            "sector_max_targets": 5,
            "broker": "ls",
            "sector_min_rise_ratio_pct": 65.0,
        }
        await save_settings(test_settings)

        loaded = await load_integrated_system_settings()
        assert loaded["time_scheduler_on"] is True
        assert loaded["sector_max_targets"] == 5
        assert loaded["broker"] == "ls"
        assert loaded["sector_min_rise_ratio_pct"] == 65.0


class TestUpdateSettingsDB:

    @pytest.mark.asyncio
    async def test_update_merges_with_existing(self, in_memory_db):
        """기존 설정에 업데이트가 병합되는지 확인."""
        await save_settings({"broker": "kiwoom", "sector_max_targets": 3})

        result = await update_settings({"sector_max_targets": 5})

        assert result["broker"] == "kiwoom"
        assert result["sector_max_targets"] == 5

    @pytest.mark.asyncio
    async def test_update_persists_to_db(self, in_memory_db):
        """업데이트 후 DB에서 값이 확인되는지 확인."""
        await save_settings({"broker": "kiwoom"})

        await update_settings({"broker": "ls"})

        cursor = await in_memory_db.execute(
            "SELECT value FROM integrated_system_settings WHERE key = ?",
            ("broker",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "ls"
