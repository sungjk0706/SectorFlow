# -*- coding: utf-8 -*-
"""
업종 데이터 인프라

- ka10099: 적격 종목코드 수집 + 부적격 필터
- JSON 캐시 저장/로드 (backend/data/eligible_stocks_cache.json)

주의: ka10099 실제 응답 필드명이 키움AI 답변과 다를 수 있음.
      첫 호출 시 응답 전체를 로그에 남기고, 파싱 실패해도 앱이 죽지 않게 방어.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from backend.app.core.trading_calendar import is_cache_valid, current_trading_date_str
from backend.app.db.cache_db import get_kv, set_kv

if TYPE_CHECKING:
    from backend.app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)

# ── 메모리 캐시 ──────────────────────────────────────────────────────────
# {종목코드(6자리): ""} — 키(종목코드)만 의미 있음, 값은 항상 빈 문자열
_eligible_stock_codes: dict[str, str] = {}
_eligible_cache_date: str = ""  # 캐시 날짜 (만료 확인용)


# ── 캐시 저장/로드 ───────────────────────────────────────────────────────



def load_eligible_stocks_cache() -> Optional[dict[str, str]]:
    """
    캐시 파일에서 적격 종목코드 맵 로드.
    (항상 SQLite에서 로드하며, 장마감 이후 확정 다운로드로만 갱신되므로 만료를 검사하지 않음)
    """
    global _eligible_stock_codes, _eligible_cache_date
    
    if _eligible_stock_codes:
        return dict(_eligible_stock_codes)
    
    try:
        raw = get_kv("eligible_stocks_cache")
        if not raw:
            return None
        data = raw.get("data")
        if not isinstance(data, dict) or not data:
            return None
        
        # 메모리 캐시 업데이트
        _eligible_stock_codes = dict(data)
        _eligible_cache_date = raw.get("date", "")
        _log.info("[매매적격종목] SQLite 로드 -- %d종목 (cached=%s)", len(data), _eligible_cache_date)
        return data
    except Exception as e:
        _log.warning("[매매적격종목] SQLite 로드 실패: %s", e)
        return None


def save_eligible_stocks_cache(data: dict[str, str]) -> None:
    """적격 종목코드 맵을 JSON 캐시로 저장."""
    global _eligible_stock_codes, _eligible_cache_date
    try:
        payload = {"date": current_trading_date_str(), "data": data}
        set_kv("eligible_stocks_cache", payload)
        
        # 메모리 캐시 업데이트
        _eligible_stock_codes = dict(data)
        _eligible_cache_date = current_trading_date_str()
        _log.info("[매매적격종목] SQLite 저장완료 -- %d종목", len(data))
    except Exception as e:
        _log.warning("[매매적격종목] SQLite 저장실패: %s", e)
# ── 게터 ─────────────────────────────────────────────────────────────────


def get_eligible_stocks() -> dict[str, str]:
    """현재 메모리의 {종목코드: ""} 맵 복사본 반환. 키(종목코드)만 의미 있음."""
    return dict(_eligible_stock_codes)
