import logging
from backend.app.db.database import get_db_connection, get_db_lock

_log = logging.getLogger(__name__)

async def _init_cache_table() -> None:
    conn = await get_db_connection()
    async with get_db_lock():
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()

async def save_filter_summary_cache(summary: str) -> None:
    """필터 요약 정보를 DB 캐시에 영구 보존"""
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        async with get_db_lock():
            await conn.execute(
                "INSERT OR REPLACE INTO system_state_cache (key, value) VALUES (?, ?)",
                ("filter_summary", summary)
            )
            await conn.commit()
        _log.info("[캐시저장] 필터링 요약 캐시 DB 저장 완료")
    except Exception as e:
        _log.error("[캐시저장] 필터링 요약 캐시 DB 저장 실패: %s", e)

async def load_filter_summary_cache() -> str:
    """DB 캐시에서 필터 요약 정보 로드"""
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        cursor = await conn.execute(
            "SELECT value FROM system_state_cache WHERE key = ?",
            ("filter_summary",)
        )
        row = await cursor.fetchone()
        return row["value"] if row else ""
    except Exception as e:
        _log.error("[캐시로드] 필터링 요약 캐시 로드 실패: %s", e)
        return ""
