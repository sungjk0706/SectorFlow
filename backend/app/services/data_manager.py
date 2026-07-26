# -*- coding: utf-8 -*-
"""
종목명 조회
종목명: 로컬 stock_name_cache.json (장마감 파이프라인에서 갱신)
"""
import logging

from backend.app.core.symbol_utils import _base_stk_cd

logger = logging.getLogger(__name__)


def get_stock_name(stk_cd: str, access_token: str | None = None) -> str:
    """종목코드 -> 종목명. 메모리 캐시(_master_stocks_cache)에서만 조회.

    종목코드 정규화는 core/symbol_utils._base_stk_cd (P10 SSOT) 사용.
    입력은 master_stocks_cache 키와 동일 형태 (6자리, _AL/_NX 접미사 없음).
    """
    from backend.app.services.engine_state import state
    norm = _base_stk_cd(stk_cd)
    if not norm:
        return "알수없음"
    entry = state.master_stocks_cache.get(norm, {})
    return entry.get("name", norm) if entry else norm
