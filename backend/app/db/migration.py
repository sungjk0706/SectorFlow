# -*- coding: utf-8 -*-
"""
설정 테이블 마이그레이션 (system_settings → user_settings, broker_credentials, system_config)
"""

import logging
import json
from typing import Any

from backend.app.db.database import get_db_connection
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS, DEFAULT_SYSTEM_CONFIG

logger = logging.getLogger(__name__)

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


async def migrate_settings_from_system_settings() -> None:
    """system_settings 테이블의 데이터를 3개 테이블로 분배 마이그레이션"""
    conn = await get_db_connection()
    
    try:
        # 0. 마이그레이션 완료 플래그 확인 (user_settings 테이블에 데이터가 있으면 이미 마이그레이션 완료)
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM user_settings")
        row = await cursor.fetchone()
        if row and row["cnt"] > 0:
            logger.info("[마이그레이션] 이미 마이그레이션 완료됨 - 생략")
            return

        # 1. system_settings 테이블 존재 확인
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_settings'"
        )
        if not await cursor.fetchone():
            logger.info("[마이그레이션] system_settings 테이블 없음 - 생략")
            return
        
        # 2. system_settings 데이터 로드
        cursor = await conn.execute("SELECT key, value FROM system_settings")
        rows = await cursor.fetchall()
        
        if not rows:
            logger.info("[마이그레이션] system_settings 데이터 없음 - 생략")
            return
        
        logger.info("[마이그레이션] system_settings에서 %d건 데이터 로드", len(rows))
        
        # 3. 데이터 분류
        user_settings_data: dict[str, tuple[str, str]] = {}  # key → (value, value_type)
        broker_credentials_data: dict[str, dict[str, str]] = {}  # broker_name → {key: value}
        system_config_data: dict[str, tuple[str, str]] = {}  # key → (value, value_type)
        
        for row in rows:
            key = row["key"]
            value = row["value"]
            
            # broker_specs 처리
            if key.startswith("broker_specs:"):
                # broker_specs는 별도 처리 (기존 로직 유지)
                continue
            
            # 증권사 인증 키
            if any(key.startswith(prefix) for prefix in BROKER_KEY_PREFIXES):
                broker_name = "kiwoom" if key.startswith("kiwoom") else "ls"
                if broker_name not in broker_credentials_data:
                    broker_credentials_data[broker_name] = {}
                broker_credentials_data[broker_name][key] = value
                continue
            
            # 시스템 설정
            if any(key.startswith(prefix) for prefix in SYSTEM_CONFIG_KEYS):
                value_type = "number" if _is_numeric(value) else "string"
                system_config_data[key] = (value, value_type)
                continue
            
            # 나머지는 사용자 설정
            if key in DEFAULT_USER_SETTINGS:
                default = DEFAULT_USER_SETTINGS[key]
                value_type = _infer_value_type(default)
            elif key in DEFAULT_SYSTEM_CONFIG:
                default = DEFAULT_SYSTEM_CONFIG[key]
                value_type = _infer_value_type(default)
            else:
                value_type = _infer_value_type(value)
            
            user_settings_data[key] = (value, value_type)
        
        # 4. user_settings에 저장
        if user_settings_data:
            for key, (value, value_type) in user_settings_data.items():
                await conn.execute(
                    "INSERT OR REPLACE INTO user_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (key, value, value_type)
                )
            await conn.commit()
            logger.info("[마이그레이션] user_settings에 %d건 저장", len(user_settings_data))
        
        # 5. broker_credentials에 저장
        if broker_credentials_data:
            for broker_name, keys in broker_credentials_data.items():
                for key, value in keys.items():
                    await conn.execute(
                        "INSERT OR REPLACE INTO broker_credentials (broker_name, key, value, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (broker_name, key, value)
                    )
            await conn.commit()
            logger.info("[마이그레이션] broker_credentials에 %d건 저장", sum(len(v) for v in broker_credentials_data.values()))
        
        # 6. system_config에 저장
        if system_config_data:
            for key, (value, value_type) in system_config_data.items():
                await conn.execute(
                    "INSERT OR REPLACE INTO system_config (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (key, value, value_type)
                )
            await conn.commit()
            logger.info("[마이그레이션] system_config에 %d건 저장", len(system_config_data))
        
        # 7. 기본값 채우기 (DB에 없는 기본값 추가)
        await _fill_default_values(conn)
        
        logger.info("[마이그레이션] 완료")
        
    except Exception as e:
        await conn.rollback()
        logger.error("[마이그레이션] 실패: %s", e, exc_info=True)
        raise


def _is_numeric(value: str) -> bool:
    """문자열이 숫자인지 확인"""
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _infer_value_type(value: Any) -> str:
    """값의 타입 추론"""
    if isinstance(value, bool):
        return "boolean"
    elif isinstance(value, (int, float)):
        return "number"
    else:
        return "string"


async def _fill_default_values(conn) -> None:
    """DB에 없는 기본값 채우기"""
    # user_settings 기본값 채우기
    for key, default_value in DEFAULT_USER_SETTINGS.items():
        cursor = await conn.execute("SELECT key FROM user_settings WHERE key = ?", (key,))
        if not await cursor.fetchone():
            value_type = _infer_value_type(default_value)
            value_str = str(default_value)
            await conn.execute(
                "INSERT OR REPLACE INTO user_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (key, value_str, value_type)
            )
    
    # system_config 기본값 채우기
    for key, default_value in DEFAULT_SYSTEM_CONFIG.items():
        cursor = await conn.execute("SELECT key FROM system_config WHERE key = ?", (key,))
        if not await cursor.fetchone():
            value_type = _infer_value_type(default_value)
            value_str = str(default_value)
            await conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (key, value_str, value_type)
            )
    
    await conn.commit()
    logger.info("[마이그레이션] 기본값 채우기 완료")


async def drop_system_settings_table() -> None:
    """기존 system_settings 테이블 삭제 (마이그레이션 완료 후)"""
    conn = await get_db_connection()
    
    try:
        # system_settings 테이블 존재 확인
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_settings'"
        )
        if not await cursor.fetchone():
            return
            
        # 백업 테이블 생성
        await conn.execute("DROP TABLE IF EXISTS system_settings_backup")
        await conn.execute("CREATE TABLE system_settings_backup AS SELECT * FROM system_settings")
        await conn.commit()
        logger.info("[마이그레이션] system_settings 백업 완료 (system_settings_backup)")
        
        # 원본 테이블 삭제
        await conn.execute("DROP TABLE IF EXISTS system_settings")
        await conn.commit()
        logger.info("[마이그레이션] system_settings 테이블 삭제 완료")
        
    except Exception as e:
        await conn.rollback()
        logger.error("[마이그레이션] system_settings 삭제 실패: %s", e, exc_info=True)
        raise


async def migrate_individual_tables_to_system_settings() -> None:
    """user_settings, broker_credentials, system_config 테이블의 데이터를 system_settings 통합설정 완성본 테이블로 동기화 마이그레이션"""
    conn = await get_db_connection()
    try:
        from backend.app.db.models import create_system_settings_table
        await create_system_settings_table()

        logger.info("[마이그레이션] 개별 설정 테이블 -> system_settings 동기화 시작")

        # 1. user_settings 로드 및 저장
        cursor = await conn.execute("SELECT key, value, value_type FROM user_settings")
        user_rows = await cursor.fetchall()
        for r in user_rows:
            await conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (r["key"], r["value"], r["value_type"])
            )

        # 2. system_config 로드 및 저장
        cursor = await conn.execute("SELECT key, value, value_type FROM system_config")
        config_rows = await cursor.fetchall()
        for r in config_rows:
            await conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (r["key"], r["value"], r["value_type"])
            )

        # 3. broker_credentials 로드 및 저장
        cursor = await conn.execute("SELECT key, value FROM broker_credentials")
        cred_rows = await cursor.fetchall()
        for r in cred_rows:
            await conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, value_type, updated_at) VALUES (?, ?, 'string', CURRENT_TIMESTAMP)",
                (r["key"], r["value"])
            )

        await conn.commit()
        logger.info("[마이그레이션] 개별 설정 -> system_settings 동기화 완료 (user_settings %d건, system_config %d건, broker_credentials %d건)", 
                    len(user_rows), len(config_rows), len(cred_rows))
    except Exception as e:
        await conn.rollback()
        logger.error("[마이그레이션] 개별 설정 -> system_settings 동기화 실패: %s", e, exc_info=True)

