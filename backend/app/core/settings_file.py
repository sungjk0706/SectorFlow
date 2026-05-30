# -*- coding: utf-8 -*-
"""
로컬 settings.json 파일 읽기/쓰기 헬퍼.
단일 사용자 모드: backend/data/settings.json 만 사용 (사용자별 폴더 없음).
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR      = Path(__file__).resolve().parent.parent.parent / "data"
_SETTINGS_PATH = _DATA_DIR / "settings.json"


def is_root_settings_profile() -> bool:
    """단일 파일 모드: 항상 data/settings.json 만 사용."""
    return True


def settings_path_for_profile(username: str) -> Path:
    """실제 읽기/쓰기 대상 settings.json 경로 (로깅·진단용). 항상 루트 파일."""
    return _SETTINGS_PATH


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
    # 매수 설정 UI -- 0이면 해당 자동 동작 비활성(엔진은 UI·settings.json 값만 사용)
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
    # 하이브리드 브로커 -- 기능별 증권사 매핑 (없으면 broker 값으로 폴백)
    # "broker_config": {"quote": "kiwoom", "account": "kiwoom", ...}
}


def migrate_rank_primary_to_weights(sector_rank_primary: str) -> dict[str, float]:
    """
    기존 sector_rank_primary 값을 가중치로 변환.
    - "total_trade_amount" → {"total_trade_amount": 0.7, "rise_ratio": 0.3}
    - "rise_ratio" → {"rise_ratio": 0.7, "total_trade_amount": 0.3}
    알 수 없는 값이면 기본 가중치(0.5/0.5) 반환.
    """
    if sector_rank_primary == "total_trade_amount":
        return {"total_trade_amount": 0.7, "rise_ratio": 0.3}
    if sector_rank_primary == "rise_ratio":
        return {"rise_ratio": 0.7, "total_trade_amount": 0.3}
    return {"total_trade_amount": 0.5, "rise_ratio": 0.5}


def _migrate_sector_weights(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    """
    sector_weights 마이그레이션.
    - raw_data에 sector_weights가 이미 있으면 스킵 (사용자가 명시적으로 저장한 값)
    - sector_weights 없고 sector_rank_primary만 있으면 마이그레이션
    - 둘 다 없으면 기본 가중치 적용 (_DEFAULTS에서 이미 병합됨)
    """
    if "sector_weights" in raw_data:
        return merged, False
    rank_primary = raw_data.get("sector_rank_primary")
    if rank_primary:
        merged["sector_weights"] = migrate_rank_primary_to_weights(rank_primary)
        return merged, True
    # 둘 다 없으면 _DEFAULTS 병합으로 기본 가중치가 이미 적용됨
    return merged, False


def _migrate_legacy_auto_trade_on(merged: dict) -> tuple[dict, bool]:
    """
    예전 auto_trade_on 필드를 제거하고 time_scheduler_on 으로 승격한다.
    반환: (병합 dict, 디스크에 다시 써야 하면 True)
    """
    if "auto_trade_on" not in merged:
        return merged, False
    legacy = bool(merged.pop("auto_trade_on"))
    if not bool(merged.get("time_scheduler_on")):
        merged["time_scheduler_on"] = legacy
    return merged, True


def _migrate_time_range_split(merged: dict) -> tuple[dict, bool]:
    """
    레거시 time_start/time_end -> buy_time_start/buy_time_end + sell_time_start/sell_time_end 분리.
    신규 키가 이미 있으면 스킵. 마이그레이션 후 레거시 키 제거.
    """
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
    """
    sector_auto_subscribe → quote_auto_subscribe 마이그레이션.
    raw_data에 sector_auto_subscribe가 있고 신규 키가 없으면 변환.
    industry_auto_subscribe는 제거됨 (0U 구독 폐지).
    """
    dirty = False
    # industry_auto_subscribe 잔존 키 제거
    if "industry_auto_subscribe" in merged:
        del merged["industry_auto_subscribe"]
        dirty = True
    if "sector_auto_subscribe" not in raw_data:
        return merged, dirty
    # 이미 신규 키가 raw_data에 있으면 스킵 (이미 마이그레이션됨)
    if "quote_auto_subscribe" in raw_data:
        # 레거시 키만 제거
        merged.pop("sector_auto_subscribe", None)
        return merged, True
    old_val = bool(raw_data["sector_auto_subscribe"])
    merged["quote_auto_subscribe"] = old_val
    merged.pop("sector_auto_subscribe", None)
    return merged, True


def _migrate_broker_config(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    """
    broker_config 마이그레이션.
    - raw_data에 broker_config가 이미 있으면 스킵
    - broker_config 없으면 기본값 생성하지 않음 (BrokerRouter가 broker 값으로 폴백)
    - broker_config 내 일부 키 누락 시에도 BrokerRouter가 폴백 처리
    """
    # broker_config가 이미 있으면 그대로 사용
    if "broker_config" in raw_data:
        return merged, False
    # 없으면 아무것도 하지 않음 -- BrokerRouter가 broker 값으로 폴백
    return merged, False


def _migrate_trade_mode(merged: dict) -> tuple[dict, bool]:
    """
    trade_mode 도입 이전 설정 호환: mock_mode -> trade_mode.
    trade_mode·mock_mode·test_mode·mode_real 필드를 일치시킨다.
    레거시 'mock' 값은 'test'로 자동 변환.
    """
    dirty = False
    tm = merged.get("trade_mode")
    # 레거시 'mock' -> 'test' 자동 변환
    if tm == "mock":
        merged["trade_mode"] = "test"
        tm = "test"
        dirty = True
    if tm not in ("test", "real"):
        merged["trade_mode"] = "test" if bool(merged.get("test_mode", merged.get("mock_mode", True))) else "real"
        dirty = True
    tm = str(merged["trade_mode"])
    # test_mode 불리언 동기화
    if bool(merged.get("test_mode", False)) != (tm == "test"):
        merged["test_mode"] = tm == "test"
        dirty = True
    # mock_mode 하위 호환 동기화
    if bool(merged.get("mock_mode", True)) != (tm == "test"):
        merged["mock_mode"] = tm == "test"
        dirty = True
    if bool(merged.get("mode_real", False)) != (tm == "real"):
        merged["mode_real"] = tm == "real"
        dirty = True
    return merged, dirty


async def load_settings() -> dict:
    """통합설정 완성본 뷰(integrated_system_settings)에서 설정을 1:1로 로드합니다.
    실패 시 기본값 사용, 사용자에게 알림.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS, DEFAULT_SYSTEM_CONFIG

    db_data: dict = {}

    try:
        conn = await get_db_connection()
        # 오직 integrated_system_settings 완성본 뷰 하나만 1:1 조회
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
        logger.info("[설정] integrated_system_settings 로드 완료 (%d개 설정 항목)", len(db_data))
    except Exception as e:
        logger.error("[설정] integrated_system_settings 로드 실패: %s", e)
        _notify_load_failure("설정 데이터 로드 실패. 기본값으로 설정됩니다.")
        # 실패 시 기본값 리턴
        return {**DEFAULT_USER_SETTINGS, **DEFAULT_SYSTEM_CONFIG}

    # 기본값 병합 (DB에 없는 키)
    for key, default_value in DEFAULT_USER_SETTINGS.items():
        if key not in db_data:
            db_data[key] = default_value

    for key, default_value in DEFAULT_SYSTEM_CONFIG.items():
        if key not in db_data:
            db_data[key] = default_value

    # 레거시 마이그레이션 룰 적용
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

    return merged


def _parse_value(value: str, value_type: str) -> Any:
    """value_type에 따라 문자열을 적절한 타입으로 변환
    
    Repository Boundary: JSON TEXT는 반드시 이 함수에서 decode되어야 함.
    서비스/엔진 레이어는 순수 Python 타입만 사용해야 함.
    """
    from backend.app.db.json_utils import decode_json_field
    import json
    
    if value_type == "boolean":
        return value == "True"
    elif value_type == "number":
        if "." in value:
            return float(value)
        return int(value)
    elif value_type == "json":
        # JSON 타입은 반드시 decode_json_field로 변환
        # 타입 계약 강제: dict/list 반환 보장
        # 먼저 파싱 후 타입 확인
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decode_json_field(value, expected_type=dict)
            elif isinstance(decoded, list):
                return decode_json_field(value, expected_type=list)
            else:
                raise ValueError(f"[settings_file] JSON 타입 지원 안 함: {type(decoded).__name__}")
        except json.JSONDecodeError as e:
            raise ValueError(f"[settings_file] JSON 파싱 실패: {e}")
    else:  # string
        return value


def _notify_load_failure(message: str) -> None:
    """설정 로드 실패 알림 (로그 + WebSocket)"""
    logger.error("[설정] %s", message)
    # WebSocket UI 배너 알림은 나중에 구현 (프론트엔드 연동 필요)


async def save_settings(data: dict) -> None:
    """표준 아키텍처: 테이블별 분기 저장 (user_settings, broker_credentials, system_config).
    
    Repository Boundary: dict/list는 value_type="json"으로 저장하여 타입 계약 명확화.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS, DEFAULT_SYSTEM_CONFIG

    # 증권사 인증 키 접두사
    BROKER_KEY_PREFIXES = frozenset([
        "kiwoom_app_key", "kiwoom_app_secret",
        "kiwoom_app_key_real", "kiwoom_app_secret_real",
        "ls_app_key", "ls_app_secret",
    ])

    # 시스템 설정 키 접두사
    SYSTEM_CONFIG_KEYS = frozenset([
        "krx_", "nxt_",
        "db_connection_timeout", "db_retry_count", "db_retry_delay",
        "cache_size", "log_level",
    ])

    conn = await get_db_connection()
    try:
        # 트랜잭션 시작
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

            # None이나 빈 문자열이면 기본값으로 대체 (데이터 무결성 보장)
            if v is None or (isinstance(v, str) and v == ""):
                if k in DEFAULT_USER_SETTINGS:
                    v = DEFAULT_USER_SETTINGS[k]
                elif k in DEFAULT_SYSTEM_CONFIG:
                    v = DEFAULT_SYSTEM_CONFIG[k]
                else:
                    # 기본값이 없으면 건너뜀
                    continue

            # 값 타입 추론
            if isinstance(v, bool):
                value_type = "boolean"
                val_str = str(v)
            elif isinstance(v, (int, float)):
                value_type = "number"
                val_str = str(v)
            elif isinstance(v, (dict, list)):
                value_type = "json"  # 수정: dict/list는 "json" 타입으로 저장
                val_str = json.dumps(v, ensure_ascii=False)
            else:
                value_type = "string"
                val_str = str(v)

            # 테이블 분기 (개별 원천 데이터 테이블 갱신)
            if any(k.startswith(prefix) for prefix in BROKER_KEY_PREFIXES):
                # broker_credentials에 저장
                broker_name = "kiwoom" if k.startswith("kiwoom") else "ls"
                await conn.execute(
                    "INSERT OR REPLACE INTO broker_credentials (broker_name, key, value, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (broker_name, k, val_str)
                )
            elif any(k.startswith(prefix) for prefix in SYSTEM_CONFIG_KEYS):
                # system_config에 저장
                await conn.execute(
                    "INSERT OR REPLACE INTO system_config (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (k, val_str, value_type)
                )
            else:
                # user_settings에 저장
                await conn.execute(
                    "INSERT OR REPLACE INTO user_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (k, val_str, value_type)
                )

        await conn.commit()
    except Exception as e:
        await conn.rollback()
        logger.error("[설정] DB 저장 실패: %s", e)


async def update_settings(updates: dict) -> dict:
    """기존 설정에 업데이트를 병합하여 저장하고 최신 설정 반환."""
    current = await load_settings()
    current.update({k: v for k, v in updates.items() if v is not None or k in current})
    await save_settings(current)
    return current


async def load_user_settings(username: str) -> dict:
    """호환용 -- 사용자별 파일은 사용하지 않고 항상 load_settings() 를 반환."""
    return await load_settings()


async def save_user_settings(username: str, data: dict) -> None:
    """호환용 -- 항상 루트 settings.json 에 저장."""
    await save_settings(data)


async def iter_merged_settings_profiles() -> Iterator[tuple[str | None, dict]]:
    """루트 data/settings.json 한 개만 순회."""
    yield None, await load_settings()


# ── 비동기 버전 (이벤트 루프 블로킹 방지) ────────────────────────────────

async def load_settings_async() -> dict:
    """settings.json 읽기 (비동기 버전). 파일이 없거나 파싱 오류 시 기본값 반환."""
    return await load_settings()


async def save_settings_async(data: dict) -> None:
    """설정 전체를 settings.json에 저장 (비동기 버전)."""
    await save_settings(data)


async def update_settings_async(updates: dict) -> dict:
    """기존 설정에 업데이트를 병합하여 저장하고 최신 설정 반환 (비동기 버전)."""
    return await update_settings(updates)
