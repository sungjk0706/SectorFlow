# -*- coding: utf-8 -*-
"""
설정 데이터베이스(SQLite) 읽기/쓰기 헬퍼.
단일 사용자 모드: SQLite의 integrated_system_settings 단일 테이블 사용.
"""
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def migrate_rank_primary_to_weights(sector_rank_primary: str) -> dict[str, float]:
    """기존 sector_rank_primary 값을 가중치로 변환."""
    if sector_rank_primary == "total_trade_amount":
        return {"total_trade_amount": 0.7, "rise_ratio": 0.3}
    if sector_rank_primary == "rise_ratio":
        return {"rise_ratio": 0.7, "total_trade_amount": 0.3}
    return {"total_trade_amount": 0.5, "rise_ratio": 0.5}


def _migrate_sector_weights(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    if "sector_weights" in raw_data:
        return merged, False
    rank_primary = raw_data.get("sector_rank_primary")
    if rank_primary:
        merged["sector_weights"] = migrate_rank_primary_to_weights(rank_primary)
        return merged, True
    return merged, False


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
    return merged, False


def _migrate_trade_mode(merged: dict) -> tuple[dict, bool]:
    dirty = False
    tm = merged.get("trade_mode")
    if tm == "mock":
        merged["trade_mode"] = "test"
        tm = "test"
        dirty = True
    if tm not in ("test", "real"):
        merged["trade_mode"] = "test" if bool(merged.get("test_mode", merged.get("mock_mode", True))) else "real"
        dirty = True
    tm = str(merged["trade_mode"])
    if bool(merged.get("test_mode", False)) != (tm == "test"):
        merged["test_mode"] = tm == "test"
        dirty = True
    if bool(merged.get("mock_mode", True)) != (tm == "test"):
        merged["mock_mode"] = tm == "test"
        dirty = True
    if bool(merged.get("mode_real", False)) != (tm == "real"):
        merged["mode_real"] = tm == "real"
        dirty = True
    return merged, dirty


# 암호화 필드 목록 (단일 정의)
_ENCRYPT_FIELDS: frozenset[str] = frozenset({
    "kiwoom_app_key", "kiwoom_app_secret",
    "ls_app_key", "ls_app_secret",
    "telegram_bot_token",
})

# 모듈 레벨 캐시 (Cache-Aside 패턴 — 이 모듈이 소유)
_integrated_system_settings_cache: dict | None = None
_cache_lock = asyncio.Lock()


async def load_integrated_system_settings() -> dict:
    """
    Cache-Aside 패턴: 캐시가 있으면 반환, 없으면 DB 로드 후 캐시 저장.
    캐시 무효화는 save_settings() 커밋 직후 수행.
    """
    global _integrated_system_settings_cache

    async with _cache_lock:
        if _integrated_system_settings_cache is not None:
            return dict(_integrated_system_settings_cache)

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
            logger.info("[설정] DB integrated_system_settings 로드 완료 (%d개 설정 항목)", len(db_data))
        except Exception as e:
            logger.error("[설정] DB integrated_system_settings 로드 실패: %s", e)
            return {**DEFAULT_USER_SETTINGS, **DEFAULT_SYSTEM_CONFIG}

        for key, default_value in DEFAULT_USER_SETTINGS.items():
            if key not in db_data:
                db_data[key] = default_value

        for key, default_value in DEFAULT_SYSTEM_CONFIG.items():
            if key not in db_data:
                db_data[key] = default_value

        if "_broker_specs" not in db_data or not db_data["_broker_specs"]:
            from pathlib import Path
            broker_specs_dir = Path(__file__).parent.parent.parent / "data" / "broker_specs"
            if broker_specs_dir.exists():
                db_data["_broker_specs"] = {}
                for spec_file in broker_specs_dir.glob("*.json"):
                    broker_name = spec_file.stem
                    try:
                        with open(spec_file, "r", encoding="utf-8") as f:
                            spec_data = json.load(f)
                        db_data["_broker_specs"][broker_name] = spec_data
                        logger.info("[설정] broker_specs 초기화: %s", broker_name)
                    except Exception as e:
                        logger.warning("[설정] broker_specs 로드 실패 (%s): %s", spec_file, e)

        merged = {**db_data}
        merged, dirty = _migrate_legacy_auto_trade_on(merged)
        merged, dirty_tm = _migrate_trade_mode(merged)
        merged, dirty_tr = _migrate_time_range_split(merged)
        merged, dirty_sw = _migrate_sector_weights(merged, db_data)
        merged, dirty_si = _migrate_sector_to_industry_index(merged, db_data)
        merged, dirty_bc = _migrate_broker_config(merged, db_data)

        dirty = dirty or dirty_tm or dirty_tr or dirty_sw or dirty_si or dirty_bc
        if dirty:
            await save_settings(merged)

        from backend.app.core.encryption import decrypt_value
        for f in _ENCRYPT_FIELDS:
            v = merged.get(f)
            if v and str(v).startswith("gAAAA"):
                merged[f] = decrypt_value(v) or ""

        _integrated_system_settings_cache = dict(merged)
        return dict(_integrated_system_settings_cache)




def _parse_value(value: str, value_type: str) -> Any:
    from backend.app.db.json_utils import decode_json_field
    import json
    
    if value_type == "boolean":
        return value == "True"
    elif value_type == "number":
        if "." in value:
            return float(value)
        return int(value)
    elif value_type == "json":
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decode_json_field(value, expected_type=dict)
            elif isinstance(decoded, list):
                return decode_json_field(value, expected_type=list)
            else:
                raise ValueError(f"[settings] JSON 타입 지원 안 함: {type(decoded).__name__}")
        except json.JSONDecodeError as e:
            raise ValueError(f"[settings] JSON 파싱 실패: {e}")
    else:
        return value


async def save_settings(data: dict) -> None:
    """SQLite 데이터베이스 integrated_system_settings 테이블에 저장.
    암호화 필드가 평문인 경우 자동 암호화 후 저장 (engine_state 캐시에서 온 복호화값 대응)."""
    from backend.app.db.database import get_db_connection
    from backend.app.core.encryption import encrypt_value

    conn = await get_db_connection()
    try:
        await conn.execute("BEGIN TRANSACTION")

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
                        spec_str = json.dumps(spec, ensure_ascii=False)
                        await conn.execute(
                            "INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at) VALUES (?, ?, 'json', CURRENT_TIMESTAMP)",
                            (f"_broker_specs:{b_name}", spec_str)
                        )
                continue
            if k.startswith("_broker_specs:") or k.startswith("broker_specs:"):
                b_name = k.split(":", 1)[1]
                spec_str = json.dumps(v, ensure_ascii=False)
                await conn.execute(
                    "INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at) VALUES (?, ?, 'json', CURRENT_TIMESTAMP)",
                    (f"_broker_specs:{b_name}", spec_str)
                )
                continue


            if isinstance(v, bool):
                value_type = "boolean"
                val_str = str(v)
            elif isinstance(v, (int, float)):
                value_type = "number"
                val_str = str(v)
            elif isinstance(v, (dict, list)):
                value_type = "json"
                val_str = json.dumps(v, ensure_ascii=False)
            else:
                value_type = "string"
                val_str = str(v)

            await conn.execute(
                "INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (k, val_str, value_type)
            )

        await conn.commit()
        # Cache-Aside 무효화: 다음 읽기 시 DB에서 최신값 재로드
        global _integrated_system_settings_cache
        _integrated_system_settings_cache = None
    except Exception as e:
        await conn.rollback()
        logger.error("[설정] DB 저장 실패: %s", e)


async def update_settings(updates: dict) -> dict:
    """기존 설정에 업데이트를 병합하여 DB 저장. 캐시는 save_settings()에서 자동 무효화."""
    current = await load_integrated_system_settings()
    current.update({k: v for k, v in updates.items() if v is not None or k in current})
    await save_settings(current)
    return current


