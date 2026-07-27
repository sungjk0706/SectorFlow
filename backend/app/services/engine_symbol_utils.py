from __future__ import annotations
# -*- coding: utf-8 -*-
"""
키움·REST 종목코드 정규화 및 REAL item/9001 필드 해석 -- 전역 엔진 상태 없음.

engine_service에서 분리된 순수 함수만 둔다 (로직·입출력 동일 유지).

`_base_stk_cd`·`_real_item_stk_cd`(및 그 private helpers 3종)는 core/symbol_utils.py로
이동됨 (P10 SSOT, C-06 역참조 해소). 본 모듈에서 재수출하여 기존 호출부·테스트 patch
경로를 유지 (P16 살아있는 경로).
"""
from backend.app.core.symbol_utils import (
    _base_stk_cd,
    _dict_get_fid,
    _fid9001_to_stk_cd,
    _parse_real_item_field,
    _real_item_stk_cd,
)


def is_nxt_enabled(stk_cd: str) -> bool:
    """
    종목코드가 NXT 중복상장 종목인지 반환.
    `state.master_stocks_cache`에서 직접 조회.
    """
    from backend.app.services.engine_state import state
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    stock = state.master_stocks_cache.get(base, {})
    if stock:
        return bool(stock.get("nxt_enable", False))
    return False


def get_ws_subscribe_code(stk_cd: str) -> str:
    """
    웹소켓 구독 시 사용할 종목코드 반환.
    - NXT 중복상장: '005930_AL' (KRX+NXT 통합, 슬롯 1개)
    - KRX 단독: '005930' (접미사 없음)
    """
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    if not base:
        return stk_cd
    if is_nxt_enabled(base):
        return f"{base}_AL"
    return base


def get_stock_market(stk_cd: str) -> str | None:
    """
    종목코드 -> 시장 구분 코드 반환.
    "0" = 코스피, "10" = 코스닥, None = 미확인
    """
    from backend.app.services.engine_state import state
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    stock = state.master_stocks_cache.get(base, {})
    if stock:
        return stock.get("market")
    return None
