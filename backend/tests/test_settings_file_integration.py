"""settings_file DB 연동 통합 테스트.

in-memory SQLite를 사용하여 load_integrated_system_settings()와
save_settings()가 integrated_system_settings 테이블과 정상적으로
상호작용하는지 검증.

B21-01 세션2: 암호화 상태 모델(encrypt_secret/decrypt_secret) 기반 저장·로드 경로 검증.
"""
from __future__ import annotations

import pytest
import aiosqlite
from unittest.mock import patch, AsyncMock

from backend.app.db import database
from backend.app.core.encryption import (
    EncryptResult,
    DecryptResult,
    EncryptionError,
    KeyState,
    SecretValueState,
)
from backend.app.core.settings_file import (
    load_integrated_system_settings,
    load_selected_settings,
    save_settings,
    save_selected_settings,
    _decrypt_encrypt_fields,
    _encrypt_field_or_raise,
    classify_secret_fields,
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

    @pytest.mark.asyncio
    async def test_migrates_loss_val_positive_to_negative(self, in_memory_db):
        """loss_val 양수→음수 규약 전환 (후안 B Step 2). 양수 3 → -3."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("loss_val", "3", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["loss_val"] == -3.0

    @pytest.mark.asyncio
    async def test_migrates_loss_val_zero_unchanged(self, in_memory_db):
        """loss_val=0은 변환 없음 (0은 유효값, 하락/손실 음수 규약에서 중성)."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("loss_val", "0", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["loss_val"] == 0

    @pytest.mark.asyncio
    async def test_migrates_loss_val_negative_unchanged(self, in_memory_db):
        """loss_val 음수는 이미 새 규약 — 변환 없음 (idempotent)."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("loss_val", "-5", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["loss_val"] == -5.0

    @pytest.mark.asyncio
    async def test_migrates_loss_val_in_sell_per_symbol_json(self, in_memory_db):
        """sell_per_symbol JSON 내부 loss_val 양수→음수 변환 (종목별 덮어쓰기)."""
        import json as _json
        _sps = _json.dumps({"005930": {"loss_val": 4.0, "loss_apply": True}})
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("sell_per_symbol", _sps, "json"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        _row = result["sell_per_symbol"]["005930"]
        assert _row["loss_val"] == -4.0
        assert _row["loss_apply"] is True

    @pytest.mark.asyncio
    async def test_migrates_ts_drop_val_positive_to_negative(self, in_memory_db):
        """ts_drop_val 양수→음수 규약 전환 (후안 B Step 3). 양수 1.5 → -1.5."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("ts_drop_val", "1.5", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["ts_drop_val"] == -1.5

    @pytest.mark.asyncio
    async def test_migrates_ts_drop_val_zero_unchanged(self, in_memory_db):
        """ts_drop_val=0은 변환 없음 (0은 유효값, 하락/손실 음수 규약에서 중성)."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("ts_drop_val", "0", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["ts_drop_val"] == 0

    @pytest.mark.asyncio
    async def test_migrates_ts_drop_val_negative_unchanged(self, in_memory_db):
        """ts_drop_val 음수는 이미 새 규약 — 변환 없음 (idempotent)."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("ts_drop_val", "-2", "number"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert result["ts_drop_val"] == -2.0

    @pytest.mark.asyncio
    async def test_migrates_ts_drop_val_in_sell_per_symbol_json(self, in_memory_db):
        """sell_per_symbol JSON 내부 ts_drop_val 양수→음수 변환 (종목별 덮어쓰기)."""
        import json as _json
        _sps = _json.dumps({"005930": {"ts_drop_val": 3.0, "ts_apply": True}})
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("sell_per_symbol", _sps, "json"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        _row = result["sell_per_symbol"]["005930"]
        assert _row["ts_drop_val"] == -3.0
        assert _row["ts_apply"] is True

    @pytest.mark.asyncio
    async def test_migrates_removes_scheduler_5d_download_on(self, in_memory_db):
        """레거시 scheduler_5d_download_on 키 제거 (5거래일 자동 다운로드 레거시 제거).
        매일 일봉 확정시세 자동 다운로드 키(scheduler_market_close_on)는 유지."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("scheduler_5d_download_on", "True", "boolean"),
        )
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("scheduler_market_close_on", "True", "boolean"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert "scheduler_5d_download_on" not in result
        assert result["scheduler_market_close_on"] is True

    @pytest.mark.asyncio
    async def test_migrates_scheduler_5d_download_on_absent_idempotent(self, in_memory_db):
        """scheduler_5d_download_on 키가 없으면 마이그레이션 멱등 (다른 값 영향 없음)."""
        await in_memory_db.execute(
            "INSERT INTO integrated_system_settings (key, value, value_type) VALUES (?, ?, ?)",
            ("scheduler_market_close_on", "True", "boolean"),
        )
        await in_memory_db.commit()

        result = await load_integrated_system_settings()
        assert "scheduler_5d_download_on" not in result
        assert result["scheduler_market_close_on"] is True


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
    async def test_save_persists_to_db(self, in_memory_db):
        """save_settings 후 DB에서 값이 확인되는지 확인."""
        await save_settings({"broker": "kiwoom"})

        cursor = await in_memory_db.execute(
            "SELECT value FROM integrated_system_settings WHERE key = ?",
            ("broker",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "kiwoom"


class TestSettingsFileP20Propagation:
    """P20 폴백 제거: DB/암호화 실패 시 예외 전파 또는 로깅 (B13-01/02/04/11).
    B21-01 세션2: encrypt_secret/decrypt_secret 상태 모델 기반 검증."""

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

    def test_decrypt_encrypt_fields_decrypts_encrypted(self):
        """B21-01: ENCRYPTED 상태 → 평문 치환 (정상 경로)."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="secret123"),
        ):
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == "secret123"

    def test_decrypt_encrypt_fields_key_unavailable_keeps_cipher(self):
        """B21-01: KEY_UNAVAILABLE → 암호문 유지 + 경고 로그 (빈문자열 폴백 제거 — P20)."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.KEY_UNAVAILABLE),
        ), patch("backend.app.core.settings_file.logger") as mock_logger:
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == "gAAAAencryptedcipher"
            mock_logger.warning.assert_called_once()
            assert "KEY_UNAVAILABLE" in mock_logger.warning.call_args[0][0]

    def test_decrypt_encrypt_fields_decrypt_failed_keeps_cipher(self):
        """B21-01: DECRYPT_FAILED → 암호문 유지 + 경고 로그 (빈문자열 폴백 제거 — P20)."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.DECRYPT_FAILED),
        ), patch("backend.app.core.settings_file.logger") as mock_logger:
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == "gAAAAencryptedcipher"
            mock_logger.warning.assert_called_once()
            assert "DECRYPT_FAILED" in mock_logger.warning.call_args[0][0]

    def test_decrypt_encrypt_fields_plaintext_legacy_keeps_plaintext(self):
        """B21-01: gAAAA 접두 아닌 평문 → PLAINTEXT_LEGACY 분류 (평문 유지, 자동 마이그레이션 금지 — 설계 6.2)."""
        with patch("backend.app.core.settings_file.logger") as mock_logger:
            merged = {"kiwoom_app_key": "plaintext_legacy_key"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == "plaintext_legacy_key"
            mock_logger.warning.assert_called_once()
            assert "PLAINTEXT_LEGACY" in mock_logger.warning.call_args[0][0]

    def test_decrypt_encrypt_fields_empty_value_unchanged(self):
        """B21-01: 빈 값 → 그대로 (로깅 없음)."""
        with patch("backend.app.core.settings_file.logger") as mock_logger:
            merged = {"kiwoom_app_key": ""}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == ""
            mock_logger.warning.assert_not_called()


class TestClassifySecretFields:
    """B21-01 세션7: classify_secret_fields — 읽기 전용 상태 분류 (UI 상태 표시용)."""

    def test_empty_value_classified_as_empty(self):
        """빈 값 → EMPTY."""
        merged = {"kiwoom_app_key": "", "kiwoom_app_secret": None}
        result = classify_secret_fields(merged)
        assert result["kiwoom_app_key"] == "EMPTY"
        assert result["kiwoom_app_secret"] == "EMPTY"

    def test_plaintext_legacy_classified(self):
        """gAAAA 접두 아닌 평문 → PLAINTEXT_LEGACY (자동 마이그레이션 금지 — 설계 6.2)."""
        merged = {"kiwoom_app_key": "plaintext_key"}
        result = classify_secret_fields(merged)
        assert result["kiwoom_app_key"] == "PLAINTEXT_LEGACY"

    def test_encrypted_classified(self):
        """gAAAA 접두 + 복호화 성공 → ENCRYPTED."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="secret"),
        ):
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            result = classify_secret_fields(merged)
            assert result["kiwoom_app_key"] == "ENCRYPTED"

    def test_key_unavailable_classified(self):
        """gAAAA 접두 + 키 없음 → KEY_UNAVAILABLE."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.KEY_UNAVAILABLE),
        ):
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            result = classify_secret_fields(merged)
            assert result["kiwoom_app_key"] == "KEY_UNAVAILABLE"

    def test_decrypt_failed_classified(self):
        """gAAAA 접두 + 복호화 실패 → DECRYPT_FAILED."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.DECRYPT_FAILED),
        ):
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            result = classify_secret_fields(merged)
            assert result["kiwoom_app_key"] == "DECRYPT_FAILED"

    def test_read_only_does_not_modify_merged(self):
        """분류 후 merged 원본 변경 없음 (읽기 전용 — 마스킹 경로에서 안전)."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="secret"),
        ):
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher", "kiwoom_app_secret": "plaintext"}
            snapshot = dict(merged)
            classify_secret_fields(merged)
            assert merged == snapshot

    def test_all_encrypt_fields_covered(self):
        """_ENCRYPT_FIELDS 6개 필드 모두 분류 결과에 포함 (P10 SSOT)."""
        merged = {f: "" for f in [
            "kiwoom_app_key", "kiwoom_app_secret",
            "ls_app_key", "ls_app_secret",
            "telegram_bot_token_test", "telegram_bot_token_real",
        ]}
        result = classify_secret_fields(merged)
        assert set(result.keys()) == set(merged.keys())

    def test_pre_computed_states_prevent_plaintext_legacy_misclassification(self):
        """B21-01 bugfix: _decrypt_encrypt_fields()가 기록한 원본 상태 사용 —
        평문 치환 후 재분류 시 PLAINTEXT_LEGACY 오분류 방지."""
        # _decrypt_encrypt_fields() 호출 후: 암호문이 평문으로 치환됨
        merged = {"kiwoom_app_key": "decrypted_plaintext"}
        # _decrypt_encrypt_fields()가 원본 상태를 기록한 상태 시뮬레이션
        merged["_secret_field_states"] = {"kiwoom_app_key": "ENCRYPTED"}
        result = classify_secret_fields(merged)
        assert result["kiwoom_app_key"] == "ENCRYPTED"

    def test_decrypt_encrypt_fields_records_original_states(self):
        """B21-01 bugfix: _decrypt_encrypt_fields()가 원본 상태를 _secret_field_states에 기록."""
        with patch(
            "backend.app.core.encryption.decrypt_secret",
            return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="secret123"),
        ):
            merged = {"kiwoom_app_key": "gAAAAencryptedcipher"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == "secret123"
            assert merged["_secret_field_states"]["kiwoom_app_key"] == "ENCRYPTED"

    def test_decrypt_encrypt_fields_records_plaintext_legacy_state(self):
        """B21-01 bugfix: PLAINTEXT_LEGACY 값도 _secret_field_states에 기록."""
        with patch("backend.app.core.settings_file.logger"):
            merged = {"kiwoom_app_key": "plaintext_legacy_key"}
            _decrypt_encrypt_fields(merged)
            assert merged["kiwoom_app_key"] == "plaintext_legacy_key"
            assert merged["_secret_field_states"]["kiwoom_app_key"] == "PLAINTEXT_LEGACY"

    def test_decrypt_encrypt_fields_records_empty_state(self):
        """B21-01 bugfix: 빈 값도 _secret_field_states에 EMPTY로 기록."""
        with patch("backend.app.core.settings_file.logger") as mock_logger:
            merged = {"kiwoom_app_key": ""}
            _decrypt_encrypt_fields(merged)
            assert merged["_secret_field_states"]["kiwoom_app_key"] == "EMPTY"
            mock_logger.warning.assert_not_called()

    def test_encrypt_field_or_raise_blocks_key_unavailable(self):
        """B21-01 세션3: KEY_UNAVAILABLE 상태 → EncryptionError(ENCRYPTION_KEY_MISSING) (평문 저장 차단 — P20/보안)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.KEY_UNAVAILABLE),
        ), patch(
            "backend.app.core.encryption.get_key_state", return_value=KeyState.MISSING,
        ):
            with pytest.raises(EncryptionError) as exc_info:
                _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")
            assert exc_info.value.code == "ENCRYPTION_KEY_MISSING"
            assert exc_info.value.field == "kiwoom_app_key"

    def test_encrypt_field_or_raise_blocks_key_invalid(self):
        """B21-01 세션3: KEY_UNAVAILABLE + KeyState.INVALID → EncryptionError(ENCRYPTION_KEY_INVALID)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.KEY_UNAVAILABLE),
        ), patch(
            "backend.app.core.encryption.get_key_state", return_value=KeyState.INVALID,
        ):
            with pytest.raises(EncryptionError) as exc_info:
                _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")
            assert exc_info.value.code == "ENCRYPTION_KEY_INVALID"
            assert exc_info.value.field == "kiwoom_app_key"

    def test_encrypt_field_or_raise_blocks_decrypt_failed(self):
        """B21-01 세션3: DECRYPT_FAILED 상태(암호화 자체 실패) → EncryptionError(ENCRYPTION_FAILED)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.DECRYPT_FAILED),
        ):
            with pytest.raises(EncryptionError) as exc_info:
                _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")
            assert exc_info.value.code == "ENCRYPTION_FAILED"
            assert exc_info.value.field == "kiwoom_app_key"

    def test_encrypt_field_or_raise_blocks_empty(self):
        """B21-01 세션3: EMPTY 상태(빈 입력) → EncryptionError(ENCRYPTION_FAILED) (평문 저장 차단)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.EMPTY),
        ):
            with pytest.raises(EncryptionError) as exc_info:
                _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")
            assert exc_info.value.code == "ENCRYPTION_FAILED"
            assert exc_info.value.field == "kiwoom_app_key"

    def test_encrypt_field_or_raise_success(self):
        """B21-01: ENCRYPTED 상태 → 암호문 반환 (정상 경로)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.ENCRYPTED, ciphertext="gAAAAencrypted"),
        ):
            result = _encrypt_field_or_raise("kiwoom_app_key", "plaintext_key")
            assert result == "gAAAAencrypted"


class TestSaveSelectedSettingsEncryptionPolicy:
    """B21-01 세션2: 증분 저장 경로가 전체 저장과 동일 fail-closed 정책을 통과하는지 검증 (P24 중복 제거)."""

    @pytest.mark.asyncio
    async def test_save_selected_settings_blocks_plaintext_when_key_unavailable(self, in_memory_db):
        """증분 저장: 키 없음 시 평문 민감값 저장 차단 — EncryptionError(ENCRYPTION_KEY_MISSING) (전체 저장과 동일 정책, B21-01 세션3)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.KEY_UNAVAILABLE),
        ), patch(
            "backend.app.core.encryption.get_key_state", return_value=KeyState.MISSING,
        ):
            with pytest.raises(EncryptionError) as exc_info:
                await save_selected_settings({"kiwoom_app_key": "plaintext_key"})
            assert exc_info.value.code == "ENCRYPTION_KEY_MISSING"
            assert exc_info.value.field == "kiwoom_app_key"

    @pytest.mark.asyncio
    async def test_save_selected_settings_saves_non_sensitive_without_key(self, in_memory_db):
        """증분 저장: 비민감 설정은 암호화 키 상태와 무관하게 정상 저장 (P25 격리된 실패)."""
        await save_selected_settings({"broker": "ls", "sector_max_targets": 5})

        cursor = await in_memory_db.execute(
            "SELECT value, value_type FROM integrated_system_settings WHERE key = ?",
            ("broker",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "ls"
        assert row["value_type"] == "string"

        cursor = await in_memory_db.execute(
            "SELECT value, value_type FROM integrated_system_settings WHERE key = ?",
            ("sector_max_targets",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "5"
        assert row["value_type"] == "number"

    @pytest.mark.asyncio
    async def test_save_selected_settings_saves_encrypted_ciphertext_as_is(self, in_memory_db):
        """증분 저장: 이미 암호화된 값(gAAAA 접두)은 재암호화 없이 그대로 저장."""
        await save_selected_settings({"kiwoom_app_key": "gAAAAexistingcipher"})

        cursor = await in_memory_db.execute(
            "SELECT value FROM integrated_system_settings WHERE key = ?",
            ("kiwoom_app_key",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "gAAAAexistingcipher"

    @pytest.mark.asyncio
    async def test_save_selected_settings_encrypts_plaintext_when_key_available(self, in_memory_db):
        """증분 저장: 키 available 시 평문 민감값 암호화 후 저장 (정상 경로)."""
        with patch(
            "backend.app.core.encryption.encrypt_secret",
            return_value=EncryptResult(state=SecretValueState.ENCRYPTED, ciphertext="gAAAAnewcipher"),
        ):
            await save_selected_settings({"kiwoom_app_key": "plaintext_key"})

        cursor = await in_memory_db.execute(
            "SELECT value FROM integrated_system_settings WHERE key = ?",
            ("kiwoom_app_key",),
        )
        row = await cursor.fetchone()
        assert row["value"] == "gAAAAnewcipher"
