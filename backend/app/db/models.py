from backend.app.db.database import get_db_connection
import json

# stocks 테이블 삭제 - master_stocks_table로 통합
# sectors 테이블 삭제 - custom_sectors가 원본, master_stocks_table.sector가 파생
# system_settings 테이블 삭제 - integrated_system_settings로 통합 완료

async def create_integrated_system_settings_table():
    """integrated_system_settings 물리 테이블 생성"""
    conn = await get_db_connection()
    # 기존 뷰가 있다면 안전하게 드랍
    try:
        await conn.execute("DROP VIEW IF EXISTS integrated_system_settings")
    except Exception:
        pass
    
    # 물리 마스터 테이블 생성
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integrated_system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()

# broker_specs 테이블 삭제 (integrated_system_settings가 단일 소스)

# migrate_broker_specs_from_json 삭제 (integrated_system_settings가 단일 소스)
