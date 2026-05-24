# -*- coding: utf-8 -*-
"""
5일 평균 거래대금 저장데이터 — SQLite 기반 범용 모듈.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime

from backend.app.core.trading_calendar import is_cache_valid, current_trading_date_str, _next_business_date
from backend.app.db.database import get_db_connection
from backend.app.db.cache_db import get_kv, set_kv, delete_kv

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
    if v > 10_000_000:
        v = v / 100_000_000
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

def load_avg_amt_cache(path=None) -> tuple[dict[str, int], dict[str, int]] | None:
    raw = get_kv("avg_amt_5d_cache")
    if not raw:
        return None
    try:
        cached_date = raw.get("date", "")
        data = raw.get("data")
        if not isinstance(data, dict):
            return None

        is_v2 = raw.get("version") == 2
        _h5d_raw = raw.get("high_5d")
        high_5d: dict[str, int] = {}
        if isinstance(_h5d_raw, dict):
            high_5d = {str(k): int(v) for k, v in _h5d_raw.items() if isinstance(v, (int, float))}

        if is_v2:
            if not is_cache_valid(cached_date):
                _log.info("[avg_amt_cache] 날짜 만료 -- 저장데이터 무효화 (cached=%s)", cached_date)
                return None
            result: dict[str, int] = {}
            for k, v in data.items():
                if isinstance(v, list) and v:
                    valid = [x for x in v if isinstance(x, (int, float)) and x > 0]
                    if valid:
                        val = int(sum(valid) / len(valid))
                        result[str(k)] = normalize_avg_amt_5d_value(val)
                elif isinstance(v, (int, float)) and v > 0:
                    result[str(k)] = normalize_avg_amt_5d_value(v)
            _log.debug("[avg_amt_cache] v2 SQLite 로드 -- %d종목, high_5d=%d (cached=%s)", len(result), len(high_5d), cached_date)
            return result, high_5d
        else:
            if not is_cache_valid(cached_date):
                _log.info("[avg_amt_cache] v1 날짜 만료 -- 저장데이터 무효화 (cached=%s)", cached_date)
                return None
            return normalize_avg_amt_5d_map(data), high_5d
    except Exception as e:
        _log.warning("[avg_amt_cache] 로드 실패 -- %s", e)
        return None

def load_avg_amt_cache_v2(path=None) -> tuple[dict[str, list[int]], dict[str, list[int]]] | None:
    raw = get_kv("avg_amt_5d_cache")
    if not raw:
        return None
    try:
        if raw.get("version") != 2:
            return None
        cached_date = raw.get("date", "")
        data = raw.get("data")
        if not isinstance(data, dict):
            return None
        result: dict[str, list[int]] = {}
        for k, v in data.items():
            if isinstance(v, list):
                result[str(k)] = [int(x) for x in v]

        _h5d_arr_raw = raw.get("high_5d_arr")
        high_5d_arr: dict[str, list[int]] = {}
        if isinstance(_h5d_arr_raw, dict):
            for k, v in _h5d_arr_raw.items():
                if isinstance(v, list):
                    high_5d_arr[str(k)] = [int(x) for x in v]

        if not is_cache_valid(cached_date):
            _log.info("[avg_amt_cache_v2] 날짜 만료 -- stale 로드 (cached=%s, %d종목, high_5d_arr=%d)", cached_date, len(result), len(high_5d_arr))
        else:
            _log.debug("[avg_amt_cache_v2] 로드 -- %d종목, high_5d_arr=%d (cached=%s)", len(result), len(high_5d_arr), cached_date)
        return result, high_5d_arr
    except Exception as e:
        _log.warning("[avg_amt_cache_v2] 로드 실패 -- %s", e)
        return None

def save_avg_amt_cache(data: dict[str, int], path=None) -> None:
    payload = {"date": _kst_today_yyyymmdd(), "data": data}
    set_kv("avg_amt_5d_cache", payload)
    _log.info("[avg_amt_cache] SQLite 저장완료 -- %d종목", len(data))

def save_avg_amt_cache_v2(data: dict[str, list[int]], date_str: str | None = None, path=None, *, high_5d: dict[str, int] | None = None, high_5d_arr: dict[str, list[int]] | None = None) -> None:
    ds = date_str or _kst_today_yyyymmdd()
    try:
        existing = get_kv("avg_amt_5d_cache")
        if existing and existing.get("version") == 2 and existing.get("date") == ds and existing.get("data") == data:
            if high_5d is None or existing.get("high_5d") == high_5d:
                if high_5d_arr is None or existing.get("high_5d_arr") == high_5d_arr:
                    _log.info("[avg_amt_cache_v2] 데이터 동일 -- 저장 생략 (date=%s, %d종목)", ds, len(data))
                    return

        payload: dict = {"version": 2, "date": ds, "data": data}
        if high_5d is not None:
            payload["high_5d"] = high_5d
        elif existing and isinstance(existing.get("high_5d"), dict):
            payload["high_5d"] = existing["high_5d"]
            
        if high_5d_arr is not None:
            payload["high_5d_arr"] = high_5d_arr
        elif existing and isinstance(existing.get("high_5d_arr"), dict):
            payload["high_5d_arr"] = existing["high_5d_arr"]
            
        set_kv("avg_amt_5d_cache", payload)
        _log.info("[avg_amt_cache_v2] SQLite 저장 완료 -- %d종목 (date=%s)", len(data), ds)
    except Exception as e:
        _log.warning("[avg_amt_cache_v2] SQLite 저장 실패 -- %s", e)

def avg_from_v2(v2_data: dict[str, list[int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for k, arr in v2_data.items():
        if arr:
            valid = [x for x in arr if isinstance(x, (int, float)) and x > 0]
            if valid:
                val = int(sum(valid) / len(valid))
                result[str(k)] = normalize_avg_amt_5d_value(val)
            else:
                result[str(k)] = 0
        else:
            result[str(k)] = 0
    return result

def load_high_5d_from_cache(path=None) -> dict[str, int] | None:
    raw = get_kv("avg_amt_5d_cache")
    if not raw or raw.get("version") != 2:
        return None
    h5d = raw.get("high_5d")
    if not isinstance(h5d, dict) or not h5d:
        return None
    return {str(k): int(v) for k, v in h5d.items() if isinstance(v, (int, float))}

# ── 5일거래대금 이어받기 진행 파일 ────────────────────────────────────────

def save_avg_amt_progress(
    date: str, completed_codes: list[str], all_codes: list[str],
    v2_data: "dict[str, list[int]] | None" = None,
    high_cache: "dict[str, int] | None" = None,
    high_5d_arr: "dict[str, list[int]] | None" = None,
    latest_dict: "dict[str, dict] | None" = None,
) -> None:
    try:
        payload = {
            "date": date,
            "total": len(all_codes),
            "completed": completed_codes,
            "codes_hash": sorted(all_codes),
        }
        set_kv("avg_amt_5d_progress", payload)

        if v2_data is not None:
            data_payload = {
                "date": date,
                "v2_data": v2_data,
                "high_cache": high_cache or {},
                "high_5d_arr": high_5d_arr or {},
                "latest_dict": latest_dict or {},
            }
            set_kv("avg_amt_5d_resume", data_payload)
    except Exception as e:
        _log.warning("[avg_amt_progress] SQLite 저장 실패: %s", e)

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
    raw = get_kv("avg_amt_5d_progress")
    if not raw:
        return None
    try:
        cached_date = raw.get("date", "")
        if not _is_progress_valid(cached_date, ws_subscribe_start):
            _log.info("[avg_amt_progress] 만료 또는 날짜 불일치 (cached=%s)", cached_date)
            return None
        cached_hash = raw.get("codes_hash", [])
        if set(cached_hash) != set(all_codes):
            _log.info("[avg_amt_progress] 종목 목록 불일치")
            return None
        completed = set(raw.get("completed", []))

        v2_data, high_cache, high_5d_arr, latest_dict = {}, {}, {}, {}
        rraw = get_kv("avg_amt_5d_resume")
        if rraw:
            v2_data   = rraw.get("v2_data", {})
            high_cache  = rraw.get("high_cache", {})
            high_5d_arr = rraw.get("high_5d_arr", {})
            latest_dict = rraw.get("latest_dict", {})

        _log.info("[avg_amt_progress] SQLite 이어받기 로드 -- %d/%d종목 완료", len(completed), len(all_codes))
        return completed, v2_data, high_cache, high_5d_arr, latest_dict
    except Exception as e:
        _log.warning("[avg_amt_progress] 로드 실패: %s", e)
        return None

def clear_avg_amt_progress() -> None:
    delete_kv(["avg_amt_5d_progress", "avg_amt_5d_resume"])
    _log.debug("[avg_amt_progress] SQLite 임시 데이터 삭제 완료")
