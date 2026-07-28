# -*- coding: utf-8 -*-
"""
설정 데이터베이스(SQLite) 읽기/쓰기 헬퍼.
단일 사용자 모드: SQLite의 integrated_system_settings 단일 테이블 사용.
"""
import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
from backend.app.core.trade_mode import normalize_trade_mode
from backend.app.db.json_utils import encode_json_field, loads

if TYPE_CHECKING:
    from backend.app.core.encryption import SecretValueState

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
    tm = merged.get("trade_mode")
    normalized = normalize_trade_mode(tm)
    dirty = normalized != tm
    merged["trade_mode"] = normalized
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


def _migrate_remove_ws_subscribe_window_keys(merged: dict) -> tuple[dict, bool]:
    """market_phase 기반 전환으로 WS 구독 시간 설정 키 2개 제거 (Step 3).
    구독 시작/종료는 장운영정보(market_phase) 페이즈 변경 감지로 자동 처리되므로 별도 설정 불필요."""
    dirty = False
    for key in ("ws_subscribe_start", "ws_subscribe_end"):
        if key in merged:
            del merged[key]
            dirty = True
    return merged, dirty


def _migrate_remove_ws_subscribe_on(merged: dict) -> tuple[dict, bool]:
    """실시간 자동 연결 토글 제거로 ws_subscribe_on 키 제거.
    07:59 자동 구독이 항상 실행되므로 수동 스위치 불필요 — market_phase 기반으로만 동작."""
    dirty = False
    if "ws_subscribe_on" in merged:
        del merged["ws_subscribe_on"]
        dirty = True
    return merged, dirty


def _migrate_loss_val_to_negative(merged: dict) -> tuple[dict, bool]:
    """손절 하락률(loss_val) 양수→음수 규약 전환 (후안 B Step 2).
    종목 손익률이 이 값 이하일 때 손절 발동 — 하락/손실은 음수 규약(P23).
    top-level loss_val + sell_per_symbol JSON 내부 loss_val 모두 변환.
    양수(>0)만 음수화, 0/음수는 그대로 (idempotent)."""
    dirty = False
    _v = merged.get("loss_val")
    if _v is not None:
        try:
            _f = float(_v)
        except (TypeError, ValueError):
            _f = None
        if _f is not None and _f > 0:
            merged["loss_val"] = -_f
            dirty = True
    _sps = merged.get("sell_per_symbol")
    if isinstance(_sps, dict):
        for _row in _sps.values():
            if not isinstance(_row, dict):
                continue
            _rv = _row.get("loss_val")
            if _rv is None:
                continue
            try:
                _rf = float(_rv)
            except (TypeError, ValueError):
                continue
            if _rf > 0:
                _row["loss_val"] = -_rf
                dirty = True
    return merged, dirty


def _migrate_ts_drop_val_to_negative(merged: dict) -> tuple[dict, bool]:
    """추적 고점대비 하락률(ts_drop_val) 양수→음수 규약 전환 (후안 B Step 3).
    고점 대비 하락률이 이 값 이하일 때 T/S 매도 — 하락/손실은 음수 규약(P23).
    top-level ts_drop_val + sell_per_symbol JSON 내부 ts_drop_val 모두 변환.
    양수(>0)만 음수화, 0/음수는 그대로 (idempotent)."""
    dirty = False
    _v = merged.get("ts_drop_val")
    if _v is not None:
        try:
            _f = float(_v)
        except (TypeError, ValueError):
            _f = None
        if _f is not None and _f > 0:
            merged["ts_drop_val"] = -_f
            dirty = True
    _sps = merged.get("sell_per_symbol")
    if isinstance(_sps, dict):
        for _row in _sps.values():
            if not isinstance(_row, dict):
                continue
            _rv = _row.get("ts_drop_val")
            if _rv is None:
                continue
            try:
                _rf = float(_rv)
            except (TypeError, ValueError):
                continue
            if _rf > 0:
                _row["ts_drop_val"] = -_rf
                dirty = True
    return merged, dirty


def _migrate_remove_max_position_size(merged: dict) -> tuple[dict, bool]:
    """max_position_size 키 제거 (COUPLING-S2 후속, P10 SSOT).
    운영 참조 0건 — DEFAULT에서 제거됨. DB 잔존 키 삭제."""
    dirty = False
    if "max_position_size" in merged:
        del merged["max_position_size"]
        dirty = True
    return merged, dirty


def _migrate_remove_market_time_keys(merged: dict) -> tuple[dict, bool]:
    """마켓 시간 14키(krx_*/nxt_*) 제거 (COUPLING-S2 후속, P10 SSOT).
    daily_time_scheduler.py 코드 상수가 SSOT (ARCHITECTURE.md 명시).
    DB에 저장되나 런타임 참조 0건 — DB 잔존 키 삭제."""
    dirty = False
    for key in (
        "krx_open_time", "krx_close_time",
        "krx_premarket_start", "krx_premarket_end",
        "krx_aftermarket_start", "krx_aftermarket_end",
        "krx_single_price_start", "krx_single_price_end",
        "nxt_premarket_start", "nxt_premarket_end",
        "nxt_mainmarket_start", "nxt_mainmarket_end",
        "nxt_aftermarket_start", "nxt_aftermarket_end",
    ):
        if key in merged:
            del merged[key]
            dirty = True
    return merged, dirty


def _migrate_remove_legacy_order_keys(merged: dict) -> tuple[dict, bool]:
    """레거시 주문 키 2개 제거 (COUPLING-S2 후속, P10 SSOT).
    - boost_order_ratio_side: 부호는 pct 값 자체에 인코딩 (음수=sell)
    - buy_interval_min: buy_interval_sec(초 단위)로 단일화
    DB 잔존 키 삭제."""
    dirty = False
    for key in ("boost_order_ratio_side", "buy_interval_min"):
        if key in merged:
            del merged[key]
            dirty = True
    return merged, dirty


def _migrate_remove_max_daily_loss_limit(merged: dict) -> tuple[dict, bool]:
    """max_daily_loss_limit 키 제거 (COUPLING-S2 후속, P10 SSOT).
    daily_loss_limit과 동일 기준이나 별도 저장 — daily_loss_limit이 SSOT.
    risk_manager.py는 daily_loss_limit의 폴백 기본값 소스로만 사용 → 제거.
    DB 잔존 키 삭제."""
    dirty = False
    if "max_daily_loss_limit" in merged:
        del merged["max_daily_loss_limit"]
        dirty = True
    return merged, dirty


# 암호화 필드 목록 (단일 정의)
_ENCRYPT_FIELDS: frozenset[str] = frozenset({
    "kiwoom_app_key", "kiwoom_app_secret",
    "ls_app_key", "ls_app_secret",
    "telegram_bot_token_test", "telegram_bot_token_real",
})

# _decrypt_encrypt_fields()가 원본 상태를 기록하는 키 (B21-01 bugfix — PLAINTEXT_LEGACY 오분류 방지).
_SECRET_FIELD_STATES_KEY = "_secret_field_states"

# 마이그레이션 1회 실행 플래그 — 최초 load_integrated_system_settings() 성공 후 True
_migrations_completed: bool = False


async def load_selected_settings(keys: set[str]) -> dict:
    """지정된 키만 DB에서 로드 (마이그레이션/기본값/브로커스펙 생략).
    암호화 필드는 복호화하여 반환. 증분 저장 경로에서 사용."""
    if not keys:
        return {}

    from backend.app.db.database import get_db_connection

    result: dict = {}
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

    _decrypt_encrypt_fields(result)

    return result


async def save_selected_settings(data: dict) -> None:
    """지정된 키만 DB에 저장 (전체 설정 덮어쓰기 없이 증분 저장).
    암호화 필드는 _encrypt_field_or_raise() 공통 검사 경유 — 전체 저장 경로와 동일 정책 (B21-01 세션2, P24 중복 제거)."""
    if not data:
        return

    from backend.app.db.database import get_db_connection, get_db_lock

    bulk_params: list[tuple[str, str, str]] = []

    for k, v in data.items():
        if v is None:
            continue
        if k.startswith("_broker_specs:") or k.startswith("broker_specs:"):
            continue
        if k in _ENCRYPT_FIELDS and v and not str(v).startswith("gAAAA"):
            v = _encrypt_field_or_raise(k, str(v))
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


async def _load_db_settings() -> dict:
    """integrated_system_settings 테이블에서 모든 키 로드. broker_specs 키는 _broker_specs dict로 병합."""
    from backend.app.db.database import get_db_connection
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS, DEFAULT_SYSTEM_CONFIG

    db_data: dict = {}
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

    for key, default_value in DEFAULT_USER_SETTINGS.items():
        if key not in db_data or db_data[key] is None:
            db_data[key] = default_value

    for key, default_value in DEFAULT_SYSTEM_CONFIG.items():
        if key not in db_data or db_data[key] is None:
            db_data[key] = default_value

    return db_data


async def _ensure_broker_specs(db_data: dict) -> None:
    """_broker_specs가 DB에 없으면 디스크(data/broker_specs/*.json)에서 로드하여 채운다."""
    if "_broker_specs" in db_data and db_data["_broker_specs"]:
        return
    broker_specs_dir = Path(__file__).parent.parent.parent / "data" / "broker_specs"
    if not await asyncio.to_thread(broker_specs_dir.exists):
        return
    db_data["_broker_specs"] = {}
    spec_files = await asyncio.to_thread(lambda: list(broker_specs_dir.glob("*.json")))
    for spec_file in spec_files:
        broker_name = spec_file.stem
        try:
            async with aiofiles.open(spec_file, mode="r", encoding="utf-8") as f:
                content = await f.read()
            spec_data = loads(content)
            db_data["_broker_specs"][broker_name] = spec_data
            logger.info("[설정] 증권사 명세 로드 완료: %s", BROKER_DISPLAY_NAMES.get(broker_name, broker_name))
        except Exception as e:
            logger.warning("[설정] 증권사 명세 로드 실패 (%s): %s", spec_file, e, exc_info=True)


def _classify_secret(value: object) -> "SecretValueState":
    """단일 민감값의 상태를 분류 (읽기 전용 — 값 변경 없음).

    B21-01 세션7: _decrypt_encrypt_fields와 classify_secret_fields가 공유하는 분류 SSOT.
    - 빈 값 → EMPTY
    - gAAAA 접두 아님 → PLAINTEXT_LEGACY (설계 6.2 — 자동 마이그레이션 금지)
    - gAAAA 접두 → decrypt_secret() 결과 상태 (ENCRYPTED/KEY_UNAVAILABLE/DECRYPT_FAILED)
    """
    from backend.app.core.encryption import decrypt_secret, SecretValueState
    v_str = str(value) if value else ""
    if not v_str:
        return SecretValueState.EMPTY
    if not v_str.startswith("gAAAA"):
        return SecretValueState.PLAINTEXT_LEGACY
    return decrypt_secret(v_str).state


def _decrypt_encrypt_fields(merged: dict) -> None:
    """_ENCRYPT_FIELDS의 민감값을 상태 기반으로 처리하여 in-place 치환 (B21-01 세션2).

    - gAAAA 접두 암호문 → decrypt_secret() 결과 상태별 처리:
      - ENCRYPTED → 평문 치환 (정상)
      - KEY_UNAVAILABLE → 암호문 유지 + 경고 로그 (빈문자열 폴백 제거 — P20)
      - DECRYPT_FAILED → 암호문 유지 + 경고 로그 (빈문자열 폴백 제거 — P20)
    - gAAAA 접두 아닌 비어있지 않은 값 → PLAINTEXT_LEGACY 분류 (평문 유지, 자동 마이그레이션 금지 — 설계 6.2)
    - 빈 값 → 그대로

    평문 값은 로그에 노출하지 않음 (설계 6.2 — 평문 값 UI/로그/저널 새 노출 금지).
    사용 경로(엔진 설정·텔레그램)의 상태 기반 차단은 세션 4-5에서 연계.
    B21-01 세션7: 분류 로직은 _classify_secret() 공유 헬퍼로 추출 (P24 중복 제거).
    B21-01 bugfix: 원본 상태를 merged[_SECRET_FIELD_STATES_KEY]에 기록하여,
    평문 치환 후 _pick_broker_credentials()/classify_secret_fields()가
    이미 복호화된 평문을 PLAINTEXT_LEGACY로 오분류하는 문제를 해결.
    """
    from backend.app.core.encryption import SecretValueState
    original_states: dict[str, str] = {}
    for enc_field in _ENCRYPT_FIELDS:
        v = merged.get(enc_field)
        if not v:
            original_states[enc_field] = SecretValueState.EMPTY.name
            continue
        secret_state = _classify_secret(v)
        original_states[enc_field] = secret_state.name
        if secret_state is SecretValueState.EMPTY:
            continue
        if secret_state is SecretValueState.PLAINTEXT_LEGACY:
            # 평문 레거시 — 자동 마이그레이션·삭제 금지 (설계 6.2). 평문 값은 로그에 노출하지 않음.
            logger.warning(
                "[설정] %s 평문 레거시 감지 — 재저장 시 암호화 필요 (PLAINTEXT_LEGACY). 자동 마이그레이션 금지.",
                enc_field,
            )
            continue
        if secret_state is SecretValueState.ENCRYPTED:
            # 평문 치환은 decrypt_secret()에서 평문을 받아와야 하므로 별도 호출.
            from backend.app.core.encryption import decrypt_secret
            result = decrypt_secret(str(v))
            if result.plaintext is not None:
                merged[enc_field] = result.plaintext
        elif secret_state is SecretValueState.KEY_UNAVAILABLE:
            logger.warning(
                "[설정] %s 복호화 불가 — 암호화 키 없음/오류 (KEY_UNAVAILABLE). 암호문 유지, 사용 경로 차단 필요.",
                enc_field,
            )
        elif secret_state is SecretValueState.DECRYPT_FAILED:
            logger.warning(
                "[설정] %s 복호화 실패 — 암호문 손상/다른 키 (DECRYPT_FAILED). 암호문 유지, 재입력 필요.",
                enc_field,
            )
    merged[_SECRET_FIELD_STATES_KEY] = original_states


def classify_secret_fields(merged: dict) -> dict[str, str]:
    """_ENCRYPT_FIELDS 각 필드의 상태를 분류하여 {field: state_name} 반환 (B21-01 세션7).

    읽기 전용 — merged를 변경하지 않음. GET /api/settings 응답의 secret_field_states
    구성에 사용 (설계 7.1/7.2 — UI 상태 표시). _classify_secret() 공유 헬퍼 기반 (P24).

    B21-01 bugfix: _decrypt_encrypt_fields()가 기록한 원본 상태(_SECRET_FIELD_STATES_KEY)가
    있으면 이를 사용 — 평문 치환 후 재분류 시 PLAINTEXT_LEGACY 오분류 방지.
    """
    from backend.app.core.encryption import SecretValueState
    pre_computed = merged.get(_SECRET_FIELD_STATES_KEY)
    if pre_computed is not None:
        return {f: pre_computed.get(f, SecretValueState.EMPTY.name) for f in _ENCRYPT_FIELDS}
    return {f: _classify_secret(merged.get(f, "")).name for f in _ENCRYPT_FIELDS}


async def _apply_all_migrations(merged: dict, db_data: dict) -> None:
    """레거시 키 마이그레이션 15개 순차 적용. dirty 시 DB에 저장."""
    _keys_before = set(merged.keys())
    merged, dirty = _migrate_legacy_auto_trade_on(merged)
    merged, dirty_tm = _migrate_trade_mode(merged)
    merged, dirty_tr = _migrate_time_range_split(merged)
    merged, dirty_si = _migrate_sector_to_industry_index(merged, db_data)
    merged, dirty_bc = _migrate_broker_config(merged, db_data)
    merged, dirty_tg = _migrate_telegram_token_split(merged)
    merged, dirty_krx = _migrate_remove_krx_subscribe_keys(merged)
    merged, dirty_ws = _migrate_remove_ws_subscribe_window_keys(merged)
    merged, dirty_wso = _migrate_remove_ws_subscribe_on(merged)
    merged, dirty_lv = _migrate_loss_val_to_negative(merged)
    merged, dirty_td = _migrate_ts_drop_val_to_negative(merged)
    merged, dirty_mps = _migrate_remove_max_position_size(merged)
    merged, dirty_mt = _migrate_remove_market_time_keys(merged)
    merged, dirty_lo = _migrate_remove_legacy_order_keys(merged)
    merged, dirty_mdl = _migrate_remove_max_daily_loss_limit(merged)

    if dirty or dirty_tm or dirty_tr or dirty_si or dirty_bc or dirty_tg or dirty_krx or dirty_ws or dirty_wso or dirty_lv or dirty_td or dirty_mps or dirty_mt or dirty_lo or dirty_mdl:
        _legacy_keys = list(_keys_before - set(merged.keys()))
        await save_settings(merged, delete_keys=_legacy_keys or None)


async def load_integrated_system_settings() -> dict:
    """
    DB에서 직접 로드 (캐시 제거).
    engine_state._integrated_system_settings_cache를 단일 소스 진리로 사용.
    """
    db_data = await _load_db_settings()
    await _ensure_broker_specs(db_data)

    global _migrations_completed

    if _migrations_completed:
        # 마이그레이션 이미 완료 — 생략하고 복호화만 수행
        merged = {**db_data}
        _decrypt_encrypt_fields(merged)
        return dict(merged)

    merged = {**db_data}
    await _apply_all_migrations(merged, db_data)
    _migrations_completed = True
    _decrypt_encrypt_fields(merged)
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


def _encrypt_field_or_raise(field: str, plain: str) -> str:
    """암호화 필드 평문 → 암호문. 암호화 실패(Fernet 미가용/예외) 시 평문을 그대로 반환하지 않고
    EncryptionError 발생 (P20 폴백 금지 + 보안: 평문 저장 차단).

    B21-01 세션2: encrypt_secret() 결과 상태 기반 검사로 전환 (임시 래퍼 의존 제거).
    B21-01 세션3: ValueError → EncryptionError(code/message/field) 전환 — 라우터가 422 detail
    객체로 변환 (설계 5). 오류 코드 매핑:
      - KEY_UNAVAILABLE + KeyState.MISSING → ENCRYPTION_KEY_MISSING
      - KEY_UNAVAILABLE + KeyState.INVALID  → ENCRYPTION_KEY_INVALID
      - DECRYPT_FAILED (암호화 자체 실패)   → ENCRYPTION_FAILED
      - EMPTY                              → ENCRYPTION_FAILED (빈 입력은 호출부에서 걸러지지만 방어)
    복호화 관련 코드(DECRYPTION_*)는 저장 경로가 아닌 복호화 소비자(세션 4)에서 사용."""
    from backend.app.core.encryption import (
        encrypt_secret, get_key_state, KeyState, SecretValueState, EncryptionError,
    )
    result = encrypt_secret(str(plain))
    if result.state is SecretValueState.ENCRYPTED and result.ciphertext is not None:
        return result.ciphertext
    enc_state = result.state
    if enc_state is SecretValueState.KEY_UNAVAILABLE:
        key_state = get_key_state()
        if key_state is KeyState.MISSING:
            code = "ENCRYPTION_KEY_MISSING"
            message = "암호화 키가 설정되지 않아 인증정보를 저장할 수 없습니다."
        else:
            code = "ENCRYPTION_KEY_INVALID"
            message = "암호화 키를 사용할 수 없어 인증정보를 저장할 수 없습니다. 키 설정을 확인하세요."
    else:
        # DECRYPT_FAILED (암호화 자체 실패) / EMPTY / 기타 — 모두 암호화 처리 실패로 분류.
        code = "ENCRYPTION_FAILED"
        message = "인증정보 암호화 처리에 실패해 저장할 수 없습니다."
    logger.error(
        "[설정] %s 암호화 실패 (상태: %s, 코드: %s) — 평문 저장 차단 (P20/보안). 암호화 키 확인 필요.",
        field, enc_state.name, code, exc_info=True,
    )
    raise EncryptionError(code=code, message=message, field=field)


def _collect_save_params(data: dict) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """save_settings용 벌크 파라미터 수집. (bulk_params, broker_specs_params) 반환.
    암호화 필드는 평문인 경우 자동 암호화. _broker_specs dict와 _broker_specs: 접두 키는 별도 파라미터로 분리."""
    bulk_params: list[tuple[str, str, str]] = []
    broker_specs_params: list[tuple[str, str, str]] = []

    for k, v in data.items():
        if v is None:
            continue
        # 암호화 필드: 평문이면 암호화 (engine_state 캐시에서 온 복호화값 처리)
        if k in _ENCRYPT_FIELDS and v and not str(v).startswith("gAAAA"):
            v = _encrypt_field_or_raise(k, str(v))
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

    return bulk_params, broker_specs_params


_UPSERT_SQL = (
    "INSERT OR REPLACE INTO integrated_system_settings "
    "(key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)"
)


async def save_settings(data: dict, delete_keys: list[str] | None = None) -> None:
    """SQLite 데이터베이스 integrated_system_settings 테이블에 저장.
    암호화 필드가 평문인 경우 자동 암호화 후 저장 (engine_state 캐시에서 온 복호화값 대응).
    delete_keys: 마이그레이션으로 제거된 레거시 키 목록 — 같은 트랜잭션 내에서 DELETE 처리."""
    from backend.app.db.database import get_db_connection, get_db_lock

    bulk_params, broker_specs_params = _collect_save_params(data)

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

            # 벌크 실행
            if broker_specs_params:
                await conn.executemany(_UPSERT_SQL, broker_specs_params)
            if bulk_params:
                await conn.executemany(_UPSERT_SQL, bulk_params)

            await conn.commit()
            logger.info("[설정] DB 저장 완료 — %d개 증권사 명세, %d개 일반 설정", len(broker_specs_params), len(bulk_params))
        except Exception as e:
            await conn.rollback()
            logger.error("[설정] DB 저장 실패: %s", e, exc_info=True)
            raise
