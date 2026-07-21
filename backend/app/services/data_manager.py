# -*- coding: utf-8 -*-
"""
종목명 조회
종목명: 로컬 stock_name_cache.json (장마감 파이프라인에서 갱신)
"""
import logging

logger = logging.getLogger(__name__)


async def _get_rest_base() -> str:
    """증권사 라우터의 인증 제공자에서 REST 기본 주소 획득."""
    from backend.app.core.broker_factory import get_router
    from backend.app.core.broker_urls import build_broker_urls
    from backend.app.services.engine_state import state
    try:
        auth = get_router().auth
        if hasattr(auth, "rest_api") and hasattr(auth.rest_api, "base_url"):
            return auth.rest_api.base_url
    except Exception:
        logger.warning("[데이터] 기본 주소 조회 실패", exc_info=True)
    # 기본값: 증권사 기반 URL
    broker_nm = str(state.integrated_system_settings_cache["broker"]).lower().strip()
    urls = build_broker_urls(broker_nm)
    return urls.get("rest_base", "")


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
