# -*- coding: utf-8 -*-
"""
5일 평균 거래대금 저장데이터 — completed_snapshot 테이블 기반 모듈.
"""
from __future__ import annotations

import logging
from datetime import datetime

from backend.app.core.trading_calendar import is_cache_valid, current_trading_date_str, _next_business_date
from backend.app.db.database import get_db_connection

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = None

_log = logging.getLogger(__name__)

KA10005_GAP_SEC = 0.3

def _kst_today_yyyymmdd() -> str:
    return current_trading_date_str()

def _norm_stk(s: str) -> str:
    t = str(s or "").strip().lstrip("A")
    if not t:
        return ""
    if t.isdigit():
        return t.zfill(6)[-6:]
    else:
        return t.upper()

def normalize_avg_amt_5d_value(value) -> int:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    # 백만원 단위 그대로 저장 (정규화 제거)
    return int(v)

def normalize_avg_amt_5d_map(data: dict) -> dict[str, int]:
    return {
        _norm_stk(k): normalize_avg_amt_5d_value(v)
        for k, v in (data or {}).items()
        if _norm_stk(k)
    }

def is_avg_amt_5d_map_usable(data: dict[str, int], *, min_positive: int = 100) -> bool:
    if not data:
        return False
    positive = sum(1 for v in data.values() if int(v or 0) > 0)
    return positive >= min_positive

def load_avg_amt_from_sector_summary_cache() -> dict[str, int]:
    try:
        from backend.app.core.sector_summary_cache import load_sector_summary_cache
        summary = load_sector_summary_cache()
        if not summary:
            return {}
        out: dict[str, int] = {}
        for sector in summary.sectors:
            for stock in sector.stocks:
                cd = _norm_stk(getattr(stock, "code", ""))
                val = normalize_avg_amt_5d_value(getattr(stock, "avg_amt_5d", 0))
                if cd and val > 0:
                    out[cd] = val
        return out
    except Exception as e:
        _log.warning("[avg_amt_cache] SectorSummary 기반 5일평균 복구 실패 -- %s", e, exc_info=True)
        return {}

# ── 저장데이터 저장/로드 ────────────────────────────────────────────────────────
# load_avg_amt_cache는 더 이상 사용하지 않음 (master_stocks_table 단일 진실 공급원)
# load_avg_amt_cache_v2, save_avg_amt_cache_v2, avg_from_v2는 더 이상 사용하지 않음 (master_stocks_table 단일 진실 공급원)

def load_high_5d_from_cache(path=None) -> dict[str, int] | None:
    """master_stocks_table 테이블에서 5일 최고가 로드 (컬럼 방식)"""
    try:
        date_str = current_trading_date_str()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT code, day1_high, day2_high, day3_high, day4_high, day5_high
            FROM master_stocks_table
            WHERE date = ?
        """, (date_str,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            _log.warning("[load_high_5d] 오늘 날짜의 데이터가 없습니다 (date=%s)", date_str)
            return None
        
        result: dict[str, int] = {}
        
        for row in rows:
            code = row["code"]
            highs = [row["day1_high"], row["day2_high"], row["day3_high"], row["day4_high"], row["day5_high"]]
            
            valid_highs = [x for x in highs if isinstance(x, (int, float)) and x > 0]
            if valid_highs:
                result[code] = int(max(valid_highs))
        
        _log.debug("[load_high_5d] 로드 완료 -- %d종목 (date=%s)", len(result), date_str)
        return result
    except Exception as e:
        _log.warning("[load_high_5d] 로드 실패 -- %s", e)
        return None

# ── 5일거래대금 이어받기 진행 파일 ────────────────────────────────────────

def save_avg_amt_progress(
    date: str, completed_codes: list[str], all_codes: list[str],
    v2_data: "dict[str, list[int]] | None" = None,
    high_cache: "dict[str, int] | None" = None,
    high_5d_arr: "dict[str, list[int]] | None" = None,
    latest_dict: "dict[str, dict] | None" = None,
) -> None:
    """이어받기 기능 - completed_snapshot 테이블에 직접 저장 (컬럼 방식)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 진행 상황 저장을 위한 별도 테이블 생성
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS avg_amt_progress (
                code TEXT PRIMARY KEY,
                date TEXT,
                completed INTEGER,
                day1_amount REAL,
                day2_amount REAL,
                day3_amount REAL,
                day4_amount REAL,
                day5_amount REAL,
                day1_high REAL,
                day2_high REAL,
                day3_high REAL,
                day4_high REAL,
                day5_high REAL
            )
        ''')
        
        # 완료된 종목 저장
        for code in completed_codes:
            if v2_data and code in v2_data:
                amounts = v2_data[code]
                highs = high_5d_arr.get(code, []) if high_5d_arr else []
                
                cursor.execute('''
                    INSERT OR REPLACE INTO avg_amt_progress
                    (code, date, completed, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                     day1_high, day2_high, day3_high, day4_high, day5_high)
                    VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (code, date, 
                      amounts[0] if len(amounts) > 0 else 0,
                      amounts[1] if len(amounts) > 1 else 0,
                      amounts[2] if len(amounts) > 2 else 0,
                      amounts[3] if len(amounts) > 3 else 0,
                      amounts[4] if len(amounts) > 4 else 0,
                      highs[0] if len(highs) > 0 else 0,
                      highs[1] if len(highs) > 1 else 0,
                      highs[2] if len(highs) > 2 else 0,
                      highs[3] if len(highs) > 3 else 0,
                      highs[4] if len(highs) > 4 else 0))
        
        conn.commit()
        conn.close()
        _log.info("[avg_amt_progress] 저장 완료 -- %d/%d종목", len(completed), len(all_codes))
    except Exception as e:
        _log.warning("[avg_amt_progress] 저장 실패: %s", e)

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

def load_avg_amt_progress(date: str, all_codes: list[str], ws_subscribe_start: str = "07:50") -> "tuple[set[str], dict[str, list[int]], dict[str, int], dict[str, list[int]], dict[str, dict]] | None":
    """이어받기 기능 - avg_amt_progress 테이블에서 로드 (컬럼 방식)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT date FROM avg_amt_progress LIMIT 1")
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        
        cached_date = row["date"]
        if not _is_progress_valid(cached_date, ws_subscribe_start):
            _log.info("[avg_amt_progress] 만료 또는 날짜 불일치 (cached=%s)", cached_date)
            conn.close()
            return None
        
        cursor.execute("SELECT code FROM avg_amt_progress WHERE completed = 1")
        rows = cursor.fetchall()
        completed = {row["code"] for row in rows}
        
        v2_data, high_cache, high_5d_arr, latest_dict = {}, {}, {}, {}
        
        cursor.execute("""
            SELECT code, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                   day1_high, day2_high, day3_high, day4_high, day5_high
            FROM avg_amt_progress
            WHERE completed = 1
        """)
        rows = cursor.fetchall()
        
        for row in rows:
            code = row["code"]
            amounts = [row["day1_amount"], row["day2_amount"], row["day3_amount"], row["day4_amount"], row["day5_amount"]]
            highs = [row["day1_high"], row["day2_high"], row["day3_high"], row["day4_high"], row["day5_high"]]
            
            valid_amounts = [int(x) for x in amounts if isinstance(x, (int, float)) and x > 0]
            if valid_amounts:
                v2_data[code] = valid_amounts
            
            valid_highs = [int(x) for x in highs if isinstance(x, (int, float)) and x > 0]
            if valid_highs:
                high_5d_arr[code] = valid_highs
                high_cache[code] = int(max(valid_highs))
        
        conn.close()
        _log.info("[avg_amt_progress] 이어받기 로드 -- %d/%d종목 완료", len(completed), len(all_codes))
        return completed, v2_data, high_cache, high_5d_arr, latest_dict
    except Exception as e:
        _log.warning("[avg_amt_progress] 로드 실패: %s", e)
        return None

def clear_avg_amt_progress() -> None:
    """이어받기 기능 - avg_amt_progress 테이블 삭제"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS avg_amt_progress")
        conn.commit()
        conn.close()
        _log.debug("[avg_amt_progress] 테이블 삭제 완료")
    except Exception as e:
        _log.warning("[avg_amt_progress] 삭제 실패: %s", e)
