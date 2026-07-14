# -*- coding: utf-8 -*-
"""
설정 데이터베이스(SQLite) 읽기/쓰기 헬퍼.
단일 사용자 모드: SQLite의 integrated_system_settings 단일 테이블 사용.
"""
import asyncio
import logging
from pathlib import Path
from typing import Any

import aiofiles
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
from backend.app.db.json_utils import encode_json_field, loads

logger = logging.getLogger(__name__)


def _migrate_legacy_auto_trade_on(merged: dict) -> tuple[dict, bool]:
    if "auto_trade_on" not in merged:
        return merged, False
    legacy = bool(merged.pop("auto_trade_on"))
    if not bool(merged.get("time_scheduler_on")):
        merged["time_scheduler_on"] = legacy
    return merged, True


def _migrate_time_range_split(merged: dict) -> tuple[dict, bool]:
    dirty = False
    legacy_start = merged.get("time_start")
    legacy_end = merged.get("time_end")
    if legacy_start and "buy_time_start" not in merged:
        merged["buy_time_start"] = legacy_start
        merged["sell_time_start"] = legacy_start
        dirty = True
    if legacy_end and "buy_time_end" not in merged:
        merged["buy_time_end"] = legacy_end
        merged["sell_time_end"] = legacy_end
        dirty = True
    # 레거시 키 제거
    if "time_start" in merged:
        del merged["time_start"]
        dirty = True
    if "time_end" in merged:
        del merged["time_end"]
        dirty = True
    return merged, dirty


def _migrate_sector_to_industry_index(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    dirty = False
    if "industry_auto_subscribe" in merged:
        del merged["industry_auto_subscribe"]
        dirty = True
    if "sector_auto_subscribe" not in raw_data:
        return merged, dirty
    if "quote_auto_subscribe" in raw_data:
        merged.pop("sector_auto_subscribe", None)
        return merged, True
    old_val = bool(raw_data["sector_auto_subscribe"])
    merged["quote_auto_subscribe"] = old_val
    merged.pop("sector_auto_subscribe", None)
    return merged, True


def _migrate_broker_config(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    bc = merged.get("broker_config")
    if isinstance(bc, dict) and "stock" in bc:
        bc.pop("stock", None)
        return merged, True
    return merged, False


def _migrate_trade_mode(merged: dict) -> tuple[dict, bool]:
    dirty = False
    tm = merged.get("trade_mode")
    if tm == "mock":
        merged["trade_mode"] = "test"
        tm = "test"
        dirty = True
    if tm not in ("test", "real"):
        merged["trade_mode"] = "test"
        dirty = True
    # 레거시 파생 변수 제거 (단일 소스: trade_mode만 사용)
    for legacy_key in ("test_mode", "mock_mode", "mode_real"):
        if legacy_key in merged:
            del merged[legacy_key]
            dirty = True
    return merged, dirty


def _migrate_telegram_token_split(merged: dict) -> tuple[dict, bool]:
    """레거시 telegram_bot_token을 telegram_bot_token_test/real로 분리."""
    dirty = False
    legacy = merged.get("telegram_bot_token")
    if legacy and not merged.get("telegram_bot_token_test") and not merged.get("telegram_bot_token_real"):
        merged["telegram_bot_token_test"] = legacy
        merged["telegram_bot_token_real"] = legacy
        dirty = True
    if "telegram_bot_token" in merged:
        del merged["telegram_bot_token"]
        dirty = True
    return merged, dirty


def _migrate_remove_krx_subscribe_keys(merged: dict) -> tuple[dict, bool]:
    """반자동 방식 전환으로 KRX 구독 시간 설정 키 2개 제거 (그룹 B).
    09:00 KRX 추가 구독/15:30 KRX 해지는 장운영정보 이벤트로 자동 처리되므로 별도 설정 불필요."""
    dirty = False
    for key in ("ws_subscribe_start_krx", "ws_subscribe_end_krx"):
        if key in merged:
            del merged[key]
            dirty = True
    return merged, dirty


# 암호화 필드 목록 (단일 정의)
_ENCRYPT_FIELDS: frozenset[str] = frozenset({
    "kiwoom_app_key", "kiwoom_app_secret",
    "ls_app_key", "ls_app_secret",
    "telegram_bot_token_test", "telegram_bot_token_real",
})

# 마이그레이션 1회 실행 플래그 — 최초 load_integrated_system_settings() 성공 후 True
_migrations_completed: bool = False


async def load_selected_settings(keys: set[str]) -> dict:
    """지정된 키만 DB에서 로드 (마이그레이션/기본값/브로커스펙 생략).
    암호화 필드는 복호화하여 반환. 증분 저장 경로에서 사용."""
    if not keys:
        return {}

    from backend.app.db.database import get_db_connection

    result: dict = {}
    try:
        conn = await get_db_connection()
        placeholders = ",".join("?" * len(keys))
        cursor = await conn.execute(
            f"SELECT key, value, value_type FROM integrated_system_settings WHERE key IN ({placeholders})",
            list(keys),
        )
        rows = await cursor.fetchall()
        for row in rows:
            key = row["key"]
            if key.startswith("_broker_specs:") or key.startswith("broker_specs:"):
                continue
            result[key] = _parse_value(row["value"], row["value_type"])
    except Exception as e:
        logger.error("[설정] 선택 설정 로드 실패 (키=%s): %s", keys, e)

    from backend.app.core.encryption import decrypt_value
    for enc_field in _ENCRYPT_FIELDS:
        v = result.get(enc_field)
        if v and str(v).startswith("gAAAA"):
            result[enc_field] = decrypt_value(v) or ""

    return result


async def save_selected_settings(data: dict) -> None:
    """지정된 키만 DB에 저장 (전체 설정 덮어쓰기 없이 증분 저장).
    암호화 필드는 평문인 경우 자동 암호화."""
    if not data:
        return

    from backend.app.db.database import get_db_connection, get_db_lock
    from backend.app.core.encryption import encrypt_value

    bulk_params: list[tuple[str, str, str]] = []

    for k, v in data.items():
        if v is None:
            continue
        if k.startswith("_broker_specs:") or k.startswith("broker_specs:"):
            continue
        if k in _ENCRYPT_FIELDS and v and not str(v).startswith("gAAAA"):
            enc = encrypt_value(str(v))
            if enc:
                v = enc
        if isinstance(v, bool):
            value_type = "boolean"
            val_str = str(v)
        elif isinstance(v, (int, float)):
            value_type = "number"
            val_str = str(v)
        elif isinstance(v, (dict, list)):
            value_type = "json"
            val_str = encode_json_field(v)
        else:
            value_type = "string"
            val_str = str(v)
        bulk_params.append((k, val_str, value_type))

    if not bulk_params:
        return

    async with get_db_lock():
        conn = await get_db_connection()
        try:
            await conn.execute("BEGIN TRANSACTION")
            await conn.executemany(
                "INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                bulk_params,
            )
            await conn.commit()
            logger.info("[설정] 증분 저장 완료 — %d개 필드", len(bulk_params))
        except Exception as e:
            await conn.rollback()
            logger.error("[설정] 증분 저장 실패: %s", e, exc_info=True)
            raise


async def load_integrated_system_settings() -> dict:
    """
    DB에서 직접 로드 (캐시 제거).
    engine_state._integrated_system_settings_cache를 단일 소스 진리로 사용.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS, DEFAULT_SYSTEM_CONFIG

    db_data: dict = {}

    try:
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT key, value, value_type FROM integrated_system_settings")
        rows = await cursor.fetchall()
        for row in rows:
            key = row["key"]
            value = row["value"]
            value_type = row["value_type"]
            parsed_val = _parse_value(value, value_type)
            if key.startswith("_broker_specs:") or key.startswith("broker_specs:"):
                broker_name = key.split(":", 1)[1]
                if "_broker_specs" not in db_data:
                    db_data["_broker_specs"] = {}
                db_data["_broker_specs"][broker_name] = parsed_val
            else:
                db_data[key] = parsed_val
    except Exception as e:
        logger.error("[설정] DB 통합 설정 로드 실패: %s", e)
        return {**DEFAULT_USER_SETTINGS, **DEFAULT_SYSTEM_CONFIG}

    for key, default_value in DEFAULT_USER_SETTINGS.items():
        if key not in db_data or db_data[key] is None or db_data[key] == "":
            db_data[key] = default_value

    for key, default_value in DEFAULT_SYSTEM_CONFIG.items():
        if key not in db_data or db_data[key] is None or db_data[key] == "":
            db_data[key] = default_value

    if "_broker_specs" not in db_data or not db_data["_broker_specs"]:
        broker_specs_dir = Path(__file__).parent.parent.parent / "data" / "broker_specs"
        if await asyncio.to_thread(broker_specs_dir.exists):
            db_data["_broker_specs"] = {}
            spec_files = await asyncio.to_thread(lambda: list(broker_specs_dir.glob("*.json")))
            for spec_file in spec_files:
                broker_name = spec_file.stem
                try:
                    async with aiofiles.open(spec_file, mode="r", encoding="utf-8") as f:
                        content = await f.read()
                    spec_data = loads(content)
                    db_data["_broker_specs"][broker_name] = spec_data
                    logger.info("[설정] 증권사 명세 초기화: %s", BROKER_DISPLAY_NAMES.get(broker_name, broker_name))
                except Exception as e:
                    logger.warning("[설정] 증권사 명세 로드 실패 (%s): %s", spec_file, e)

    global _migrations_completed

    if _migrations_completed:
        # 마이그레이션 이미 완료 — 생략하고 복호화만 수행
        merged = {**db_data}
        from backend.app.core.encryption import decrypt_value
        for enc_field in _ENCRYPT_FIELDS:
            v = merged.get(enc_field)
            if v and str(v).startswith("gAAAA"):
                merged[enc_field] = decrypt_value(v) or ""
        return dict(merged)

    merged = {**db_data}
    _keys_before = set(merged.keys())
    merged, dirty = _migrate_legacy_auto_trade_on(merged)
    merged, dirty_tm = _migrate_trade_mode(merged)
    merged, dirty_tr = _migrate_time_range_split(merged)
    merged, dirty_si = _migrate_sector_to_industry_index(merged, db_data)
    merged, dirty_bc = _migrate_broker_config(merged, db_data)
    merged, dirty_tg = _migrate_telegram_token_split(merged)
    merged, dirty_krx = _migrate_remove_krx_subscribe_keys(merged)

    dirty = dirty or dirty_tm or dirty_tr or dirty_si or dirty_bc or dirty_tg or dirty_krx
    if dirty:
        _legacy_keys = list(_keys_before - set(merged.keys()))
        await save_settings(merged, delete_keys=_legacy_keys or None)

    _migrations_completed = True

    from backend.app.core.encryption import decrypt_value
    for enc_field in _ENCRYPT_FIELDS:
        v = merged.get(enc_field)
        if v and str(v).startswith("gAAAA"):
            merged[enc_field] = decrypt_value(v) or ""

    return dict(merged)




def _parse_value(value: str, value_type: str) -> Any:
    if value_type == "boolean":
        return value == "True"
    elif value_type == "number":
        if "." in value:
            return float(value)
        return int(value)
    elif value_type == "json":
        try:
            decoded = loads(value)
        except ValueError as e:
            raise ValueError(f"[settings] JSON 파싱 실패: {e}")
        if isinstance(decoded, (dict, list)):
            return decoded
        raise ValueError(f"[settings] JSON 타입 지원 안 함: {type(decoded).__name__}")
    else:
        return value


async def save_settings(data: dict, delete_keys: list[str] | None = None) -> None:
    """SQLite 데이터베이스 integrated_system_settings 테이블에 저장.
    암호화 필드가 평문인 경우 자동 암호화 후 저장 (engine_state 캐시에서 온 복호화값 대응).
    delete_keys: 마이그레이션으로 제거된 레거시 키 목록 — 같은 트랜잭션 내에서 DELETE 처리."""
    from backend.app.db.database import get_db_connection, get_db_lock
    from backend.app.core.encryption import encrypt_value

    async with get_db_lock():
        conn = await get_db_connection()
        try:
            await conn.execute("BEGIN TRANSACTION")

            # 마이그레이션으로 제거된 레거시 키 DELETE (INSERT OR REPLACE는 삭제하지 않으므로)
            if delete_keys:
                placeholders = ",".join("?" * len(delete_keys))
                await conn.execute(
                    f"DELETE FROM integrated_system_settings WHERE key IN ({placeholders})",
                    delete_keys,
                )
                logger.info("[설정] 레거시 키 %d개 DB에서 삭제: %s", len(delete_keys), delete_keys)

            # 벌크 파라미터 수집
            bulk_params = []
            broker_specs_params = []

            for k, v in data.items():
                if v is None:
                    continue
                # 암호화 필드: 평문이면 암호화 (engine_state 캐시에서 온 복호화값 처리)
                if k in _ENCRYPT_FIELDS and v and not str(v).startswith("gAAAA"):
                    enc = encrypt_value(str(v))
                    if enc:
                        v = enc
                if k == "_broker_specs":
                    if isinstance(v, dict):
                        for b_name, spec in v.items():
                            spec_str = encode_json_field(spec)
                            broker_specs_params.append((f"_broker_specs:{b_name}", spec_str, "json"))
                    continue
                if k.startswith("_broker_specs:") or k.startswith("broker_specs:"):
                    b_name = k.split(":", 1)[1]
                    spec_str = encode_json_field(v)
                    broker_specs_params.append((f"_broker_specs:{b_name}", spec_str, "json"))
                    continue

                # 타입 변환
                if isinstance(v, bool):
                    value_type = "boolean"
                    val_str = str(v)
                elif isinstance(v, (int, float)):
                    value_type = "number"
                    val_str = str(v)
                elif isinstance(v, (dict, list)):
                    value_type = "json"
                    val_str = encode_json_field(v)
                else:
                    value_type = "string"
                    val_str = str(v)

                bulk_params.append((k, val_str, value_type))

            # 벌크 실행
            if broker_specs_params:
                await conn.executemany(
                    "INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    broker_specs_params
                )
            if bulk_params:
                await conn.executemany(
                    "INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    bulk_params
                )

            await conn.commit()
            logger.info("[설정] DB 저장 완료 — %d개 증권사 명세, %d개 일반 설정", len(broker_specs_params), len(bulk_params))
        except Exception as e:
            await conn.rollback()
            logger.error("[설정] DB 저장 실패: %s", e, exc_info=True)
            raise


async def update_settings(updates: dict) -> dict:
    """기존 설정에 업데이트를 병합하여 DB 저장.
    전체 로드/저장 대신 변경된 필드만 증분 저장."""
    to_save = {k: v for k, v in updates.items() if v is not None}
    if to_save:
        await save_selected_settings(to_save)
    # 반환용: 기존 전체 설정 + 업데이트 병합
    current = await load_integrated_system_settings()
    current.update({k: v for k, v in updates.items() if v is not None or k in current})
    return current
