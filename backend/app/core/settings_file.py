# -*- coding: utf-8 -*-
"""
설정 데이터베이스(SQLite) 읽기/쓰기 헬퍼.
단일 사용자 모드: SQLite의 integrated_system_settings 완성본 뷰 및 개별 테이블(user_settings, broker_credentials, system_config) 사용.
"""
import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULTS: dict = {
    "broker": "",
    # 테스트/실전 API·WS·REG·자격증명 분기의 기준
    "trade_mode": "test",
    "mode_real": False,
    "time_scheduler_on": True,
    "auto_buy_on": True,
    "auto_sell_on": True,
    "buy_time_start": "09:00",
    "buy_time_end": "15:20",
    "sell_time_start": "09:00",
    "sell_time_end": "15:20",
    "buy_amt": 0,
    "max_daily_total_buy_amt": 0,
    "max_stock_cnt": 5,
    # 매수 설정 UI -- 0이면 해당 자동 동작 비활성(엔진은 UI 값만 사용)
    "tp_val": 5.0,
    "tp_apply": True,
    "loss_apply": False,
    "loss_val": 0.0,
    "ts_apply": False,
    "ts_start_val": 0.0,
    "ts_drop_val": 0.0,
    "sell_price_type": "mkt",
    "sell_offset": 0,
    "sell_custom_qty": 0,
    "sell_qty_type": "%",
    "buy_min_trade_amt": 0.0,
    "max_position_size": None,
    "rate_limit_per_sec": 3,
    "tele_on": False,

    "telegram_bot_token": None,
    "telegram_chat_id": None,
    "kiwoom_app_key": None,
    "kiwoom_app_secret": None,
    "kiwoom_account_no": "",
    "kiwoom_app_key_real": None,
    "kiwoom_app_secret_real": None,
    "kiwoom_account_no_real": "",
    "ls_app_key": None,
    "ls_app_secret": None,
    "ls_account_no": "",
    "ls_app_key_real": None,
    "ls_app_secret_real": None,
    "ls_account_no_real": "",
    "mock_mode": True,

    "sell_per_symbol": {},
    # 매수/매도 폼 「기본값 저장」 전용 -- 엔진은 사용하지 않음(설정 저장과 별도 스냅샷).
    "buy_form_defaults": None,
    "sell_form_defaults": None,
    "theme_mode": "dark",
    "ui_zoom": 1.15,
    # 섹터 강도 / 매수 필터
    "sector_min_rise_ratio_pct": 60.0,
    "sector_min_trade_amt": 0.0,
    "sector_sort_keys": ["change_rate", "trade_amount", "strength"],
    "sector_rank_primary": "rise_ratio",
    "sector_weights": {"total_trade_amount": 0.5, "rise_ratio": 0.5},
    "sector_max_targets": 3,
    # 업종 내 종목 트리밍 비율 (%)
    "sector_trim_trade_amt_pct": 10.0,
    "sector_trim_change_rate_pct": 10.0,
    "buy_block_rise_pct": 7.0,
    "buy_block_fall_pct": 7.0,
    "buy_min_strength": 0,
    # 공휴일 자동 OFF
    "holiday_guard_on": True,
    # WS 구독 마스터 스위치
    "ws_subscribe_on": True,
    # WS 구독 제어 — 실시간시세(0B) 자동구독
    "quote_auto_subscribe": True,
    # 테스트모드 가상 예수금 -- 설정 금액(초기값)과 현재 잔액
    "test_virtual_deposit": 10_000_000,
    "test_virtual_balance": 10_000_000,
}


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


# 캐싱을 위한 모듈 레벨 변수
_integrated_system_settings_cache: dict | None = None
_cache_lock = asyncio.Lock()


async def load_integrated_system_settings() -> dict:
    """
    integrated_system_settings 테이블에서 설정을 로드하여 캐싱합니다.
    최초 호출 시에만 DB 조회를 수행하며, 이후에는 캐시된 데이터를 반환합니다.
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
                if key.startswith("broker_specs:"):
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

        # 복호화 처리 (암호화된 필드만 복호화)
        from backend.app.core.encryption import decrypt_value

        encrypt_fields = [
            "kiwoom_app_key", "kiwoom_app_secret", "kiwoom_app_key_real", "kiwoom_app_secret_real",
            "ls_app_key", "ls_app_secret", "ls_app_key_real", "ls_app_secret_real",
            "telegram_bot_token"
        ]

        for f in encrypt_fields:
            v = merged.get(f)
            if v and str(v).startswith("gAAAA"):
                merged[f] = decrypt_value(v) or ""

        # 캐시 저장
        _integrated_system_settings_cache = dict(merged)
        return dict(_integrated_system_settings_cache)


# 하위 호환성을 위한 별칭
load_settings = load_integrated_system_settings


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
    """SQLite 데이터베이스 각 설정 테이블 분기 저장 (user_settings, broker_credentials, system_config)."""
    from backend.app.db.database import get_db_connection
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS, DEFAULT_SYSTEM_CONFIG

    BROKER_KEY_PREFIXES = frozenset([
        "kiwoom_app_key", "kiwoom_app_secret",
        "kiwoom_app_key_real", "kiwoom_app_secret_real",
        "ls_app_key", "ls_app_secret",
    ])

    SYSTEM_CONFIG_KEYS = frozenset([
        "krx_", "nxt_",
        "db_connection_timeout", "db_retry_count", "db_retry_delay",
        "cache_size", "log_level",
    ])

    conn = await get_db_connection()
    try:
        await conn.execute("BEGIN TRANSACTION")

        for k, v in data.items():
            if k == "_broker_specs":
                if isinstance(v, dict):
                    for b_name, spec in v.items():
                        spec_str = json.dumps(spec, ensure_ascii=False)
                        await conn.execute(
                            "INSERT OR REPLACE INTO broker_specs (broker_name, spec_data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                            (b_name, spec_str)
                        )
                continue
            if k.startswith("broker_specs:"):
                b_name = k.split(":", 1)[1]
                spec_str = json.dumps(v, ensure_ascii=False)
                await conn.execute(
                    "INSERT OR REPLACE INTO broker_specs (broker_name, spec_data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (b_name, spec_str)
                )
                continue

            if v is None or (isinstance(v, str) and v == ""):
                if k in DEFAULT_USER_SETTINGS:
                    v = DEFAULT_USER_SETTINGS[k]
                elif k in DEFAULT_SYSTEM_CONFIG:
                    v = DEFAULT_SYSTEM_CONFIG[k]
                else:
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

            if any(k.startswith(prefix) for prefix in BROKER_KEY_PREFIXES):
                broker_name = "kiwoom" if k.startswith("kiwoom") else "ls"
                await conn.execute(
                    "INSERT OR REPLACE INTO broker_credentials (broker_name, key, value, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (broker_name, k, val_str)
                )
            elif any(k.startswith(prefix) for prefix in SYSTEM_CONFIG_KEYS):
                await conn.execute(
                    "INSERT OR REPLACE INTO system_config (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (k, val_str, value_type)
                )
            else:
                await conn.execute(
                    "INSERT OR REPLACE INTO user_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (k, val_str, value_type)
                )

        await conn.commit()
    except Exception as e:
        await conn.rollback()
        logger.error("[설정] DB 저장 실패: %s", e)


async def update_settings(updates: dict) -> dict:
    """기존 DB 설정에 업데이트를 병합하여 저장하고 최신 설정 반환."""
    global _integrated_system_settings_cache
    current = await load_integrated_system_settings()
    current.update({k: v for k, v in updates.items() if v is not None or k in current})
    await save_settings(current)
    # 캐시 무효화
    _integrated_system_settings_cache = None
    return current


async def save_settings_async(data: dict) -> None:
    """비동기 DB 설정 저장."""
    await save_settings(data)


async def update_settings_async(updates: dict) -> dict:
    """비동기 DB 설정 병합 저장."""
    return await update_settings(updates)
