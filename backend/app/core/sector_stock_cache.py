import json
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

async def save_filter_summary_meta_cache(meta_json: str) -> None:
    """filter_summary 메타데이터(종목수 제외)를 DB에 저장 — SSOT: 종목수는 master_stocks_table"""
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        async with get_db_lock():
            await conn.execute(
                "INSERT OR REPLACE INTO system_state_cache (key, value) VALUES (?, ?)",
                ("filter_summary_meta", meta_json)
            )
            await conn.commit()
        _log.info("[캐시저장] filter_summary_meta DB 저장 완료")
    except Exception as e:
        _log.error("[캐시저장] filter_summary_meta DB 저장 실패: %s", e)

async def load_filter_summary_meta_cache() -> str:
    """DB에서 filter_summary 메타데이터 JSON 로드"""
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        cursor = await conn.execute(
            "SELECT value FROM system_state_cache WHERE key = ?",
            ("filter_summary_meta",)
        )
        row = await cursor.fetchone()
        return row["value"] if row else ""
    except Exception as e:
        _log.error("[캐시로드] filter_summary_meta 로드 실패: %s", e)
        return ""

def assemble_filter_summary(meta_json: str, stock_count: int) -> str:
    """meta JSON + master_stocks_table 종목수 → filter_summary 표시 문자열 조립
    SSOT 원칙: 종목수는 master_stocks_table에서만 파생, meta에는 종목수 없음"""
    if not meta_json:
        return f"적격 {stock_count}종목" if stock_count > 0 else ""
    try:
        meta = json.loads(meta_json)
        result = (
            f"전체 {meta['unique_codes']}종목(raw {meta['raw_rows']}행) → 적격 {stock_count}종목 "
            f"(제외 {meta['excluded_count']}종목, {meta['pct']:.1f}%, 중복 {meta['duplicate_count']}종목)"
        )
        if meta.get("top_reasons"):
            reason_strs = [f"{r['k']} {r['v']}개" for r in meta["top_reasons"]]
            result += " | 주요 부적격: " + ", ".join(reason_strs)
        return result
    except Exception as e:
        _log.error("[filter_summary] meta 조립 실패: %s", e)
        return ""
