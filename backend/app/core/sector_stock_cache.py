import logging
from backend.app.db.database import get_db_connection, get_db_lock
from backend.app.db.json_utils import dumps, loads

logger = logging.getLogger(__name__)

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
        logger.error("[데이터] 필터 요약 메타 로드 실패: %s", e)
        return ""

def assemble_filter_summary(meta_json: str, stock_count: int) -> str:
    """meta JSON + master_stocks_table 종목수 → filter_summary 표시 문자열 조립
    SSOT 원칙: 종목수는 master_stocks_table에서만 파생, meta에는 종목수 없음
    표시명은 to_display_reason()을 거친 일반 용어 (P21 사용자 투명성)"""
    if not meta_json:
        return f"매매 가능 {stock_count}종목" if stock_count > 0 else ""
    try:
        meta = loads(meta_json)
        pct_int = int(round(meta.get("pct", 0)))
        result = (
            f"전체 {meta['unique_codes']}종목 → 매매 가능 {stock_count}종목 "
            f"(제외 {meta['excluded_count']}종목, {pct_int}%)"
        )
        if meta.get("top_reasons"):
            reason_strs = [f"{r['k']} {r['v']}개" for r in meta["top_reasons"]]
            result += " | 주요 제외: " + ", ".join(reason_strs)
        return result
    except Exception as e:
        logger.error("[시스템] 메타데이터 조립 실패: %s", e)
        return ""


# ── 보류 설정 변경 ──────────────────────────────────────────

_PENDING_KEY = "pending_settings_changes"


async def save_pending_settings(changed_keys: set[str]) -> None:
    """엔진 미실행 시 변경된 설정 키를 system_state_cache에 저장."""
    if not changed_keys:
        return
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        async with get_db_lock():
            cursor = await conn.execute(
                "SELECT value FROM system_state_cache WHERE key = ?",
                (_PENDING_KEY,)
            )
            row = await cursor.fetchone()
            existing: set[str] = set()
            if row:
                try:
                    existing = set(loads(row["value"]))
                except Exception:
                    existing = set()
            merged = existing | changed_keys
            await conn.execute(
                "INSERT OR REPLACE INTO system_state_cache (key, value) VALUES (?, ?)",
                (_PENDING_KEY, dumps(sorted(merged)))
            )
            await conn.commit()
        logger.info("[연산] 설정 변경 보류 저장: %s", sorted(merged))
    except Exception as e:
        logger.error("[연산] 설정 변경 보류 저장 실패: %s", e)


async def load_pending_settings() -> set[str]:
    """엔진 기동 시 보류된 설정 변경 키 조회."""
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        cursor = await conn.execute(
            "SELECT value FROM system_state_cache WHERE key = ?",
            (_PENDING_KEY,)
        )
        row = await cursor.fetchone()
        if not row:
            return set()
        try:
            return set(loads(row["value"]))
        except Exception:
            return set()
    except Exception as e:
        logger.error("[연산] 보류 설정 로드 실패: %s", e)
        return set()


async def clear_pending_settings() -> None:
    """엔진 기동 시 보류 설정 적용 완료 후 삭제."""
    await _init_cache_table()
    conn = await get_db_connection()
    try:
        async with get_db_lock():
            await conn.execute(
                "DELETE FROM system_state_cache WHERE key = ?",
                (_PENDING_KEY,)
            )
            await conn.commit()
        logger.info("[연산] 보류 설정 변경 삭제 완료")
    except Exception as e:
        logger.error("[연산] 보류 설정 삭제 실패: %s", e)
