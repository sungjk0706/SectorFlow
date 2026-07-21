"""settings_file DB 연동 통합 테스트.

in-memory SQLite를 사용하여 load_integrated_system_settings()와
save_settings()가 integrated_system_settings 테이블과 정상적으로
상호작용하는지 검증.
"""
from __future__ import annotations

import pytest
import aiosqlite
from unittest.mock import patch, AsyncMock

from backend.app.db import database
from backend.app.core.settings_file import (
    load_integrated_system_settings,
    load_selected_settings,
    save_settings,
    update_settings,
    _decrypt_encrypt_fields,
    _encrypt_field_or_raise,
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
            ("sell_per_symbol", '{"005930": {"tp_val": 10.0}}', "json"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["sell_per_symbol"]["005930"]["tp_val"] == 10.0

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
        sps = {"005930": {"tp_val": 10.0}}
        await save_settings({"sell_per_symbol": sps})

        cursor = await in_memory_db.execute(
            "SELECT value, value_type FROM integrated_system_settings WHERE key = ?",
            ("sell_per_symbol",),
        )
        row = await cursor.fetchone()
        assert row["value_type"] == "json"
        import json
        parsed = json.loads(row["value"])
        assert parsed["005930"]["tp_val"] == 10.0

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


class TestSettingsFileP20Propagation:
    """P20 폴백 제거: DB/암호화 실패 시 예외 전파 또는 로깅 (B13-01/02/04/11)."""

    @pytest.mark.asyncio
    async def test_load_selected_settings_propagates_db_error(self, in_memory_db):
        """B13-01: load_selected_settings DB 에러 시 예외 전파 (빈 dict 폴백 금지)."""
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(side_effect=RuntimeError("DB 에러"))):
            with pytest.raises(RuntimeError, match="DB 에러"):
                await load_selected_settings({"broker"})

    @pytest.mark.asyncio
    async def test_load_integrated_settings_propagates_db_error(self, in_memory_db):
        """B13-02: _load_db_settings DB 에러 시 예외 전파 (기본값 폴백 금지)."""
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(side_effect=RuntimeError("DB 에러"))):
            with pytest.raises(RuntimeError, match="DB 에러"):
                await load_integrated_system_settings()

    def test_decrypt_encrypt_fields_logs_on_failure(self):
        """B13-04: 복호화 실패(None) 시 경고 로그 + 빈문자열 (P21 사용자 투명성)."""
        with patch("backend.app.core.encryption.decrypt_value", return_value=None), \
             patch("backend.app.core.settings_file.logger") as mock_logger:
            merged = {"kiwoom_app_key": "gAAAAinvalidcipher"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == ""
            mock_logger.warning.assert_called_once()
            assert "복호화 실패" in mock_logger.warning.call_args[0][0]

    def test_encrypt_field_or_raise_blocks_plaintext(self):
        """B13-11: 암호화 실패(평문 반환) 시 ValueError — 평문 저장 차단 (P20/보안)."""
        with patch("backend.app.core.encryption.encrypt_value", return_value="plaintext_not_encrypted"):
            with pytest.raises(ValueError, match="암호화 실패"):
                _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")

    def test_encrypt_field_or_raise_blocks_none(self):
        """B13-11: 암호화 실패(None) 시 ValueError — 평문 저장 차단."""
        with patch("backend.app.core.encryption.encrypt_value", return_value=None):
            with pytest.raises(ValueError, match="암호화 실패"):
                _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")

    def test_encrypt_field_or_raise_success(self):
        """B13-11: 암호화 성공(gAAAA 접두) 시 암호문 반환."""
        with patch("backend.app.core.encryption.encrypt_value", return_value="gAAAAencrypted"):
            result = _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")
            assert result == "gAAAAencrypted"
