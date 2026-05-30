from __future__ import annotations
# -*- coding: utf-8 -*-
"""
업종별 종목 레이아웃 + KRX 스냅샷 캐시. (SQLite 기반)

앱 기동 시 캐시를 먼저 로드해서 UI를 즉시 표시하고,
이후 백그라운드에서 ka10095 최신 데이터로 갱신한다.
"""

import json
import logging
from datetime import datetime

from backend.app.core.trading_calendar import (
    get_current_trading_day_str,
    _next_trading_day,
    _KST,
)
from backend.app.db.database import get_db_connection

_log = logging.getLogger(__name__)

# ── sector_stock_layout 캐시 삭제 (master_stocks_table sector 컬럼으로 대체) ──

# ── snapshot_cache 관련 함수 제거 (Phase 4) ─────────────────────────────────
# load_completed_stocks_from_snapshot 함수 제거 (system_settings 테이블 삭제로 인해)

# ── 시장구분 + NXT 캐시 (삭제됨, master_stocks_table로 통합) ───────────────────────

# ── 종목명 매핑 캐시 (ka10099) ────────────────────────────────────────────

async def save_stock_name_cache(name_map: dict[str, str]) -> None:
    """종목명을 master_stocks_table.name 컬럼에 업데이트 (단일 진실 공급원)."""
    try:
        conn = await get_db_connection()
        updated = 0
        
        for code, name in name_map.items():
            await conn.execute("""
                UPDATE master_stocks_table
                SET name = ?
                WHERE code = ?
            """, (name, code))
            updated += 1
        
        await conn.commit()
        _log.info("[stock_name_cache] master_stocks_table 업데이트 완료 -- %d종목", updated)
    except Exception as e:
        _log.warning("[stock_name_cache] master_stocks_table 업데이트 실패: %s", e)

async def load_stock_name_cache() -> dict[str, str] | None:
    """종목명을 master_stocks_table.name 컬럼에서 조회 (단일 진실 공급원)."""
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT code, name FROM master_stocks_table")
        rows = await cursor.fetchall()
        
        if not rows:
            return None
            
        name_map = {}
        for row in rows:
            name_map[str(row["code"])] = str(row["name"])
            
        _log.info("[stock_name_cache] master_stocks_table 로드 -- %d종목", len(name_map))
        return name_map
    except Exception as e:
        _log.warning("[stock_name_cache] master_stocks_table 로드 실패: %s", e)
        return None

# ── 확정 시세 다운로드 진행 파일 캐시 ──────────────────────────────────────

def _parse_hm(time_str: str) -> tuple[int, int]:
    try:
        parts = str(time_str).strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 7, 50

def _is_progress_valid(cached_date_str: str, ws_subscribe_start: str) -> bool:
    if not cached_date_str:
        return False
    try:
        cached_date = datetime.strptime(cached_date_str, "%Y%m%d").date()
        next_biz = _next_trading_day(cached_date)
        
        now = datetime.now(_KST) if _KST else datetime.now()
        sh, sm = _parse_hm(ws_subscribe_start)
        expiry = datetime(
            next_biz.year, next_biz.month, next_biz.day,
            sh, sm, tzinfo=_KST if _KST else None
        )
        return now < expiry
    except (ValueError, TypeError):
        return False

async def save_progress_cache(
    date: str,
    completed_codes: list[str],
    all_codes: list[str],
    data: "dict[str, dict] | None" = None,
) -> None:
    try:
        payload = {
            "date": date,
            "total": len(all_codes),
            "completed": completed_codes,
            "codes_hash": sorted(all_codes),
        }
        conn = await get_db_connection()
        await conn.execute("INSERT OR REPLACE INTO user_settings (key, value, value_type) VALUES (?, ?, ?)", 
                       ("download_progress", json.dumps(payload, ensure_ascii=False), "json"))
        
        if data:
            data_payload = {"date": date, "data": data}
            await conn.execute("INSERT OR REPLACE INTO user_settings (key, value, value_type) VALUES (?, ?, ?)", 
                           ("resume_data", json.dumps(data_payload, ensure_ascii=False), "json"))
            
        await conn.commit()
    except Exception as e:
        _log.warning("[progress_cache] SQLite 저장 실패: %s", e)

async def load_progress_cache(date: str, all_codes: list[str], ws_subscribe_start: str = "07:50") -> set[str]:
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT value FROM user_settings WHERE key = 'download_progress'")
        row = await cursor.fetchone()
        
        if not row:
            return set()
            
        raw = json.loads(row["value"])
        cached_date = raw.get("date", "")
        
        if not _is_progress_valid(cached_date, ws_subscribe_start):
            _log.info("[progress_cache] 만료 또는 날짜 불일치 (cached=%s)", cached_date)
            return set()
            
        cached_hash = raw.get("codes_hash", [])
        if set(cached_hash) != set(all_codes):
            _log.info("[progress_cache] 종목 목록 불일치 (상장폐지/신규상장 발생)")
            return set()
            
        completed = raw.get("completed", [])
        _log.info("[progress_cache] SQLite 로드 완료 -- %d/%d종목", len(completed), len(all_codes))
        return set(completed)
    except Exception as e:
        _log.warning("[progress_cache] SQLite 로드 실패: %s", e)
        return set()

async def clear_progress_cache() -> None:
    """다운로드 완료 후 진행 파일 및 임시 데이터 파일 삭제."""
    try:
        conn = await get_db_connection()
        await conn.execute("DELETE FROM user_settings WHERE key IN ('download_progress', 'resume_data')")
        await conn.commit()
        _log.debug("[progress_cache] SQLite 진행 데이터 삭제 완료")
    except Exception as e:
        _log.warning("[progress_cache] SQLite 진행 데이터 삭제 실패: %s", e)


# load_all_sector_stocks_from_cache 삭제 (master_stocks_table로 대체)

# ── 필터 요약 캐시 ─────────────────────────────────────────────

async def save_filter_summary_cache(summary: str) -> None:
    """필터 요약(filter_summary)를 user_settings에 저장."""
    try:
        conn = await get_db_connection()
        await conn.execute(
            "INSERT OR REPLACE INTO user_settings (key, value, value_type, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            ("latest_filter_summary", summary, "string")
        )
        await conn.commit()
    except Exception as e:
        _log.warning("[sector_stock_cache] 필터 요약 저장 실패: %s", e)

async def load_filter_summary_cache() -> str:
    """user_settings에서 필터 요약(filter_summary) 로드."""
    try:
        conn = await get_db_connection()
        async with conn.execute("SELECT value FROM user_settings WHERE key = 'latest_filter_summary'") as cursor:
            row = await cursor.fetchone()
            if row:
                return row["value"]
    except Exception as e:
        _log.warning("[sector_stock_cache] 필터 요약 로드 실패: %s", e)
    return ""
