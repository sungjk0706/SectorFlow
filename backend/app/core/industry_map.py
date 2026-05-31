from __future__ import annotations
# -*- coding: utf-8 -*-
"""
업종 데이터 인프라

- ka10099: 적격 종목코드 수집 + 부적격 필터
- JSON 캐시 저장/로드 (backend/data/eligible_stocks_cache.json)

주의: ka10099 실제 응답 필드명이 키움AI 답변과 다를 수 있음.
      첫 호출 시 응답 전체를 로그에 남기고, 파싱 실패해도 앱이 죽지 않게 방어.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from backend.app.core.trading_calendar import is_cache_valid, get_current_trading_day_str
from backend.app.db.stock_tables import load_eligible_stocks_cache, save_eligible_stocks_cache




_log = logging.getLogger(__name__)

# ── 메모리 캐시 ──────────────────────────────────────────────────────────
# {종목코드(6자리): ""} — 키(종목코드)만 의미 있음, 값은 항상 빈 문자열
_eligible_stock_codes: dict[str, str] = {}
_eligible_cache_date: str = ""  # 캐시 날짜 (만료 확인용)


# ── 캐시 저장/로드 ───────────────────────────────────────────────────────



async def load_eligible_stocks_cache_from_db() -> dict[str, str] | None:
    """
    캐시 파일에서 적격 종목코드 맵 로드.
    설정된 실시간연결시작 시간을 기준으로 만료 여부를 판별합니다.
    """
    global _eligible_stock_codes, _eligible_cache_date
    
    try:
        raw = await load_eligible_stocks_cache()
        if not raw:
            return None
        data = raw.get("data")
        if not isinstance(data, dict) or not data:
            return None
        
        cached_date = raw.get("date", "")
        
        # 유효성 검사 추가 (_settings_cache는 app.py에서 이미 초기화됨)
        import backend.app.services.engine_state as _st
        settings = _st._settings_cache or {}
        ws_start = settings.get("ws_subscribe_start", "07:50")
        
        if not is_cache_valid(cached_date, ws_start):
            _log.info("[매매적격종목] 캐시 만료 (cached=%s, ws_start=%s)", cached_date, ws_start)
            _eligible_stock_codes = {}
            _eligible_cache_date = ""
            return None
        
        # 메모리 캐시 업데이트
        _eligible_stock_codes = dict(data)
        _eligible_cache_date = cached_date
        _log.info("[매매적격종목] SQLite 로드 -- %d종목 (cached=%s)", len(data), _eligible_cache_date)
        return data
    except Exception as e:
        _log.warning("[매매적격종목] SQLite 로드 실패: %s", e)
        return None


async def persist_eligible_stocks_cache(data: dict[str, str]) -> None:
    """적격 종목코드 맵을 JSON 캐시로 저장."""
    global _eligible_stock_codes, _eligible_cache_date
    try:
        date_str = get_current_trading_day_str()
        await save_eligible_stocks_cache(date_str, data)
        
        # 메모리 캐시 업데이트
        _eligible_stock_codes = dict(data)
        _eligible_cache_date = date_str
        _log.info("[매매적격종목] SQLite 저장완료 -- %d종목", len(data))
    except Exception as e:
        _log.warning("[매매적격종목] SQLite 저장실패: %s", e)
# ── 게터 ─────────────────────────────────────────────────────────────────


def get_eligible_stocks() -> dict[str, str]:
    """현재 메모리의 {종목코드: ""} 맵 복사본 반환. 키(종목코드)만 의미 있음."""
    return dict(_eligible_stock_codes)
