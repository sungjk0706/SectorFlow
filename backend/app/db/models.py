from backend.app.db.database import get_db_connection
import json

# stocks 테이블 삭제 - master_stocks_table로 통합

async def create_sectors_table():
    """sectors 테이블 생성"""
    conn = await get_db_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sectors (
            name TEXT PRIMARY KEY
        )
    """)
    await conn.commit()

async def create_system_settings_table():
    """system_settings 테이블 생성 (통합설정 완성본 - 마이그레이션용 임시)"""
    conn = await get_db_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        await conn.execute("ALTER TABLE system_settings ADD COLUMN value_type TEXT NOT NULL DEFAULT 'string'")
    except Exception:
        pass
    await conn.commit()

async def create_integrated_system_settings_table():
    """integrated_system_settings 물리 테이블 및 트리거 생성"""
    conn = await get_db_connection()
    # 기존 뷰가 있다면 안전하게 드랍
    try:
        await conn.execute("DROP VIEW IF EXISTS integrated_system_settings")
    except Exception:
        pass
    
    # 기존 물리 테이블 드랍
    await conn.execute("DROP TABLE IF EXISTS integrated_system_settings")
    
    # 1. 물리 마스터 테이블 생성
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integrated_system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. user_settings 동기화 트리거
    await conn.execute("DROP TRIGGER IF EXISTS trg_user_settings_ins")
    await conn.execute("""
        CREATE TRIGGER trg_user_settings_ins AFTER INSERT ON user_settings
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES (new.key, new.value, new.value_type, new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_user_settings_upd")
    await conn.execute("""
        CREATE TRIGGER trg_user_settings_upd AFTER UPDATE ON user_settings
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES (new.key, new.value, new.value_type, new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_user_settings_del")
    await conn.execute("""
        CREATE TRIGGER trg_user_settings_del AFTER DELETE ON user_settings
        BEGIN
            DELETE FROM integrated_system_settings WHERE key = old.key;
        END;
    """)

    # 3. system_config 동기화 트리거
    await conn.execute("DROP TRIGGER IF EXISTS trg_system_config_ins")
    await conn.execute("""
        CREATE TRIGGER trg_system_config_ins AFTER INSERT ON system_config
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES (new.key, new.value, new.value_type, new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_system_config_upd")
    await conn.execute("""
        CREATE TRIGGER trg_system_config_upd AFTER UPDATE ON system_config
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES (new.key, new.value, new.value_type, new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_system_config_del")
    await conn.execute("""
        CREATE TRIGGER trg_system_config_del AFTER DELETE ON system_config
        BEGIN
            DELETE FROM integrated_system_settings WHERE key = old.key;
        END;
    """)

    # 4. broker_credentials 동기화 트리거
    await conn.execute("DROP TRIGGER IF EXISTS trg_broker_credentials_ins")
    await conn.execute("""
        CREATE TRIGGER trg_broker_credentials_ins AFTER INSERT ON broker_credentials
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES (new.key, new.value, 'string', new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_broker_credentials_upd")
    await conn.execute("""
        CREATE TRIGGER trg_broker_credentials_upd AFTER UPDATE ON broker_credentials
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES (new.key, new.value, 'string', new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_broker_credentials_del")
    await conn.execute("""
        CREATE TRIGGER trg_broker_credentials_del AFTER DELETE ON broker_credentials
        BEGIN
            DELETE FROM integrated_system_settings WHERE key = old.key;
        END;
    """)

    # 5. broker_specs 동기화 트리거
    await conn.execute("DROP TRIGGER IF EXISTS trg_broker_specs_ins")
    await conn.execute("""
        CREATE TRIGGER trg_broker_specs_ins AFTER INSERT ON broker_specs
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES ('broker_specs:' || new.broker_name, new.spec_data, 'json', new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_broker_specs_upd")
    await conn.execute("""
        CREATE TRIGGER trg_broker_specs_upd AFTER UPDATE ON broker_specs
        BEGIN
            INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
            VALUES ('broker_specs:' || new.broker_name, new.spec_data, 'json', new.updated_at);
        END;
    """)
    await conn.execute("DROP TRIGGER IF EXISTS trg_broker_specs_del")
    await conn.execute("""
        CREATE TRIGGER trg_broker_specs_del AFTER DELETE ON broker_specs
        BEGIN
            DELETE FROM integrated_system_settings WHERE key = 'broker_specs:' || old.broker_name;
        END;
    """)

    # 6. 초기 강제 동기화 (Upsert)
    await conn.execute("""
        INSERT OR REPLACE INTO integrated_system_settings (key, value, value_type, updated_at)
        SELECT key, value, value_type, updated_at FROM user_settings
        UNION ALL
        SELECT key, value, value_type, updated_at FROM system_config
        UNION ALL
        SELECT key, value, 'string' AS value_type, updated_at FROM broker_credentials
        UNION ALL
        SELECT 'broker_specs:' || broker_name AS key, spec_data AS value, 'json' AS value_type, updated_at FROM broker_specs
    """)
    await conn.commit()

async def create_user_settings_table():
    """user_settings 테이블 생성 (사용자 설정)"""
    conn = await get_db_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()

async def create_broker_credentials_table():
    """broker_credentials 테이블 생성 (증권사 인증 정보)"""
    conn = await get_db_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_credentials (
            broker_name TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (broker_name, key)
        )
    """)
    await conn.commit()

async def create_system_config_table():
    """system_config 테이블 생성 (시스템 설정)"""
    conn = await get_db_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()

async def create_broker_specs_table():
    """broker_specs 테이블 생성 (증권사 spec JSON 데이터)"""
    conn = await get_db_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_specs (
            broker_name TEXT PRIMARY KEY,
            spec_data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()

async def save_broker_spec(broker_name: str, spec_data: dict) -> None:
    """broker spec을 broker_specs 테이블에 저장"""
    from backend.app.db.json_utils import encode_json_field
    conn = await get_db_connection()
    value = encode_json_field(spec_data)
    await conn.execute("""
        INSERT OR REPLACE INTO broker_specs (broker_name, spec_data, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (broker_name, value))
    await conn.commit()

async def load_broker_spec(broker_name: str) -> dict | None:
    """broker spec을 broker_specs 테이블에서 로드"""
    from backend.app.db.json_utils import decode_json_field
    conn = await get_db_connection()
    cursor = await conn.execute("""
        SELECT spec_data FROM broker_specs WHERE broker_name = ?
    """, (broker_name,))
    row = await cursor.fetchone()
    if row:
        return decode_json_field(row[0], expected_type=dict)
    return None

async def migrate_broker_specs_from_json() -> None:
    """broker_specs 디렉토리의 JSON 파일들을 SQLite로 이전"""
    from pathlib import Path
    import logging
    logger = logging.getLogger(__name__)
    
    specs_dir = Path(__file__).parent.parent.parent / "data" / "broker_specs"
    if not specs_dir.exists():
        logger.info("[마이그레이션] broker_specs 디렉토리 없음 - 생략")
        return
    
    json_files = list(specs_dir.glob("*.json"))
    if not json_files:
        logger.info("[마이그레이션] JSON 파일 없음 - 생략")
        return
    
    for json_file in json_files:
        broker_name = json_file.stem
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                spec_data = json.load(f)
            await save_broker_spec(broker_name, spec_data)
            logger.info("[마이그레이션] %s spec 이전 완료", broker_name)
        except Exception as e:
            logger.warning("[마이그레이션] %s spec 이전 실패: %s", broker_name, e)

