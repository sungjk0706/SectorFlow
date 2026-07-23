# -*- coding: utf-8 -*-
"""
종목명 조회
종목명: 로컬 stock_name_cache.json (장마감 파이프라인에서 갱신)
"""
import logging

logger = logging.getLogger(__name__)


def _norm_stk_cd(stk_cd: str) -> str:
    """캐시 키용. 순수 숫자만 6자리로; 비숫자 포함(0120G0)은 숫자만 남기면 001200과 충돌하므로 원문 유지."""
    s = str(stk_cd).strip()
    if not s:
        return ""
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s.upper()


def get_stock_name(stk_cd: str, access_token: str | None = None) -> str:
    """종목코드 -> 종목명. 메모리 캐시(_master_stocks_cache)에서만 조회."""
    from backend.app.services.engine_state import state
    norm = _norm_stk_cd(stk_cd)
    if not norm:
        return "알수없음"
    entry = state.master_stocks_cache.get(norm, {})
    return entry.get("name", norm) if entry else norm
