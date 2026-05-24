# -*- coding: utf-8 -*-
"""
업종별 종목 레이아웃 + KRX 스냅샷 캐시. (SQLite 기반)

앱 기동 시 캐시를 먼저 로드해서 UI를 즉시 표시하고,
이후 백그라운드에서 ka10095 최신 데이터로 갱신한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime

from backend.app.core.trading_calendar import is_cache_valid, current_trading_date_str, _next_business_date
from backend.app.db.database import get_db_connection

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = None

_log = logging.getLogger(__name__)

# ── sector_stock_layout 캐시 ─────────────────────────────────────────────

def save_layout_cache(layout: list[tuple[str, str]]) -> None:
    """업종별 종목 레이아웃을 SQLite에 저장."""
    try:
        date_str = current_trading_date_str()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sector_layout")
        
        insert_values = [(i, date_str, k, v) for i, (k, v) in enumerate(layout)]
        cursor.executemany("INSERT INTO sector_layout (id, date, kind, val) VALUES (?, ?, ?, ?)", insert_values)
        
        conn.commit()
        conn.close()
        count = sum(1 for k, _ in layout if k == "code")
        _log.info("[layout_cache] SQLite 저장 완료 -- %d종목", count)
    except Exception as e:
        _log.warning("[layout_cache] SQLite 저장 실패: %s", e)

def load_layout_cache() -> list[tuple[str, str]] | None:
    """다음 거래일 NXT 장마감(20:00)까지 유효하면 레이아웃 반환, 아니면 None."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT date, kind, val FROM sector_layout ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
            
        cached_date = rows[0]["date"]
        
        layout = []
        for row in rows:
            layout.append((row["kind"], row["val"]))
            
        _log.info("[layout_cache] SQLite 로드 -- %d종목 (cached=%s)", sum(1 for k, _ in layout if k == "code"), cached_date)
        return layout
    except Exception as e:
        _log.warning("[layout_cache] SQLite 로드 실패: %s", e)
        return None

def find_sector_for_code(stock_code: str, layout: list[tuple[str, str]]) -> str:
    target = ("code", stock_code)
    try:
        idx = layout.index(target)
    except ValueError:
        return ""
    for i in range(idx - 1, -1, -1):
        kind, val = layout[i]
        if kind == "sector":
            return val
    return ""

# ── KRX 스냅샷 캐시 ─────────────────────────────────────────────────────

def save_snapshot_cache(rows: list[tuple[str, dict]]) -> None:
    """ka10095 스냅샷 결과를 SQLite에 저장."""
    try:
        date_str = current_trading_date_str()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM snapshot_cache")
        
        insert_values = []
        for stk_cd, detail in rows:
            insert_values.append((stk_cd, date_str, json.dumps(detail, ensure_ascii=False)))
            
        cursor.executemany("INSERT INTO snapshot_cache (code, date, detail) VALUES (?, ?, ?)", insert_values)
        
        conn.commit()
        conn.close()
        _log.info("[snapshot_cache] SQLite 저장 완료 -- %d종목", len(rows))
    except Exception as e:
        _log.warning("[snapshot_cache] SQLite 저장 실패: %s", e)

def load_snapshot_cache() -> list[tuple[str, dict]] | None:
    """당일 캐시가 유효하면 [(종목코드, detail)] 반환, 아니면 None."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, date, detail FROM snapshot_cache")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
            
        cached_date = rows[0]["date"]
        
        result = [(str(row["code"]), json.loads(row["detail"])) for row in rows]
        _log.info("[snapshot_cache] SQLite 로드 -- %d종목 (cached=%s)", len(result), cached_date)
        return result
    except Exception as e:
        _log.warning("[snapshot_cache] SQLite 로드 실패: %s", e)
        return None

def load_completed_stocks_from_snapshot(completed_codes: set[str]) -> dict[str, dict]:
    if not completed_codes:
        return {}

    # 1순위: kv_store에서 resume_data 로드
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM kv_store WHERE key = 'resume_data'")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            raw = json.loads(row["value"])
            data: dict = raw.get("data", {})
            if data:
                result = {cd: detail for cd, detail in data.items() if cd in completed_codes}
                found = len(result)
                missing = len(completed_codes) - found
                if missing > 0:
                    _log.warning("[resume] resume_data에서 %d종목 누락 (완료 목록 %d종목 중 %d종목 복원)", missing, len(completed_codes), found)
                else:
                    _log.info("[resume] 완료된 %d종목 데이터 SQLite resume_data에서 복원 완료", found)
                return result
    except Exception as e:
        _log.warning("[resume] SQLite resume_data 로드 실패: %s", e)

    # 2순위: 기존 snapshot_cache
    snapshot = load_snapshot_cache()
    if not snapshot:
        _log.warning("[resume] snapshot_cache 없음 -- 완료된 %d종목 데이터 복원 불가", len(completed_codes))
        return {}

    result: dict[str, dict] = {}
    for code, detail in snapshot:
        if code in completed_codes:
            result[code] = detail

    found = len(result)
    missing = len(completed_codes) - found
    if missing > 0:
        _log.warning("[resume] snapshot에서 %d종목 누락 (완료 목록 %d종목 중 %d종목 복원)", missing, len(completed_codes), found)
    else:
        _log.info("[resume] 완료된 %d종목 데이터 SQLite snapshot에서 복원 완료", found)

    return result

# ── 시장구분 + NXT 캐시 ──────────────────────────────────────────────────

def save_market_map_cache(market_map: dict[str, str], nxt_map: dict[str, bool]) -> None:
    try:
        date_str = current_trading_date_str()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM market_map")
        
        insert_values = []
        for code, market in market_map.items():
            is_nxt = 1 if nxt_map.get(code) else 0
            insert_values.append((code, date_str, market, is_nxt))
            
        cursor.executemany("INSERT INTO market_map (code, date, market, is_nxt) VALUES (?, ?, ?, ?)", insert_values)
        
        conn.commit()
        conn.close()
        total_nxt = sum(1 for v in nxt_map.values() if v)
        _log.info("[market_map_cache] SQLite 저장 완료 -- %d종목 (NXT %d)", len(market_map), total_nxt)
    except Exception as e:
        _log.warning("[market_map_cache] SQLite 저장 실패: %s", e)

def load_market_map_cache() -> tuple[dict[str, str], dict[str, bool]] | None:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, date, market, is_nxt FROM market_map")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
            
        cached_date = rows[0]["date"]
        
        market_map = {}
        nxt_map = {}
        total_nxt = 0
        for row in rows:
            code = str(row["code"])
            market_map[code] = str(row["market"])
            is_nxt = bool(row["is_nxt"])
            nxt_map[code] = is_nxt
            if is_nxt:
                total_nxt += 1
                
        _log.info("[market_map_cache] SQLite 로드 -- %d종목 (NXT %d) (cached=%s)", len(market_map), total_nxt, cached_date)
        return market_map, nxt_map
    except Exception as e:
        _log.warning("[market_map_cache] SQLite 로드 실패: %s", e)
        return None

# ── 종목명 매핑 캐시 (ka10099) ────────────────────────────────────────────

def save_stock_name_cache(name_map: dict[str, str]) -> None:
    try:
        date_str = current_trading_date_str()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stock_names")
        
        insert_values = [(code, date_str, name) for code, name in name_map.items()]
        cursor.executemany("INSERT INTO stock_names (code, date, name) VALUES (?, ?, ?)", insert_values)
        
        conn.commit()
        conn.close()
        _log.info("[stock_name_cache] SQLite 저장 완료 -- %d종목", len(name_map))
    except Exception as e:
        _log.warning("[stock_name_cache] SQLite 저장 실패: %s", e)

def load_stock_name_cache() -> dict[str, str] | None:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, date, name FROM stock_names")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
            
        cached_date = rows[0]["date"]
        
        name_map = {}
        for row in rows:
            name_map[str(row["code"])] = str(row["name"])
            
        _log.info("[stock_name_cache] SQLite 로드 -- %d종목 (cached=%s)", len(name_map), cached_date)
        return name_map
    except Exception as e:
        _log.warning("[stock_name_cache] SQLite 로드 실패: %s", e)
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
        next_biz = _next_business_date(cached_date)
        
        now = datetime.now(_KST) if _KST else datetime.now()
        sh, sm = _parse_hm(ws_subscribe_start)
        expiry = datetime(
            next_biz.year, next_biz.month, next_biz.day,
            sh, sm, tzinfo=_KST if _KST else None
        )
        return now < expiry
    except (ValueError, TypeError):
        return False

def save_progress_cache(
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", 
                       ("download_progress", json.dumps(payload, ensure_ascii=False)))
        
        if data:
            data_payload = {"date": date, "data": data}
            cursor.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", 
                           ("resume_data", json.dumps(data_payload, ensure_ascii=False)))
            
        conn.commit()
        conn.close()
    except Exception as e:
        _log.warning("[progress_cache] SQLite 저장 실패: %s", e)

def load_progress_cache(date: str, all_codes: list[str], ws_subscribe_start: str = "07:50") -> set[str]:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM kv_store WHERE key = 'download_progress'")
        row = cursor.fetchone()
        conn.close()
        
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

def clear_progress_cache() -> None:
    """다운로드 완료 후 진행 파일 및 임시 데이터 파일 삭제."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM kv_store WHERE key IN ('download_progress', 'resume_data')")
        conn.commit()
        conn.close()
        _log.debug("[progress_cache] SQLite 진행 데이터 삭제 완료")
    except Exception as e:
        _log.warning("[progress_cache] SQLite 진행 데이터 삭제 실패: %s", e)
