from __future__ import annotations
# -*- coding: utf-8 -*-
"""
매수 파이프라인 핵심 로직: 시장가 즉시 매수, 모니터링 종목 등록, 스냅샷·매도 검사, WS 연결 시도.

engine_service 모듈의 전역 상태에 get_state/set_state로 접근한다.
"""

import asyncio
from datetime import datetime

from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
from backend.app.services import data_manager
from backend.app.services import dry_run
from backend.app.services import settlement_engine
from backend.app.services.auto_trading_effective import auto_sell_effective
from backend.app.services.engine_state import state

logger = get_logger("engine")


def _is_placeholder_stock_name(nm: str) -> bool:
    s = (nm or "").strip()
    if not s or s == "알수없음":
        return True
    if len(s) >= 4 and s.startswith("종목(") and s.endswith(")"):
        return True
    return False


def resolve_radar_display_name(stk_cd: str, ws_stk_nm: str, access_token) -> str:
    """
    WS FID 302 등과 불일치 시 로컬 stock_name_cache로 보강.

    WS 힌트(FID 302)는 종목코드와 짝이 어긋날 수 있어, 로컬 종목명과 다르면 로컬을 우선한다.
    """
    hint = (ws_stk_nm or "").strip()
    rest_nm = ""
    try:
        rest_nm = (data_manager.get_stock_name(stk_cd, access_token) or "").strip()
    except Exception as e:
        logger.warning("[종목명] REST 조회 실패 %s: %s", stk_cd, e)
        rest_nm = ""

    if hint and hint != stk_cd:
        if not _is_placeholder_stock_name(rest_nm) and rest_nm and rest_nm != hint:
            return rest_nm
        return hint
    if rest_nm:
        return rest_nm
    return stk_cd


def make_detail(stk_cd: str, stk_nm: str, cur_price: int,
                 sign: str, change: int, change_rate: float,
                 trade_amount: int = 0, strength: str = "-", sector: str = "기타") -> dict:
    """대기 종목 상세 딕셔너리 생성 헬퍼."""
    return {
        "code":        stk_cd,
        "name":        stk_nm if stk_nm else stk_cd,
        "cur_price":   cur_price,
        "sign":        sign,        # "1"상한 "2"상승 "3"보합 "4"하한 "5"하락
        "change":      change,
        "change_rate": change_rate,
        "trade_amount": trade_amount,
        "strength":    str(strength or "-"),
        "sector":      sector,
    }


# register_pending_stock() 삭제: _radar_cnsr_order 삭제로 더 이상 필요 없음
# 호출처 없음 (dead code)


async def run_snapshot_and_sell_check(force_rest: bool) -> None:
    """
    매도 조건 검사 + (선택) REST 부트스트랩.
    - force_rest=True: 수동 동기화 -- kt00001/18 (예수금·수량·매입).
    - WS 구독 구간(장중): REST 생략, 스냅샷 메타만 갱신.
    - WS 구독 구간 외: REST 조회.
    """
    try:
        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        in_window = await is_ws_subscribe_window(state.integrated_system_settings_cache)
        ws_ok = bool(state.kiwoom_connector and state.kiwoom_connector.is_connected() and state.login_ok)
        # 장중(구독 구간)이면 force_rest여도 REST 생략 -- 실시간 데이터 우선
        if in_window and not force_rest:
            if state.refresh_account_snapshot_meta:
                await state.refresh_account_snapshot_meta()
        elif not in_window or force_rest:
            if not state.account_rest_bootstrapped or not ws_ok or force_rest:
                if state.update_account_memory:
                    await state.update_account_memory(state.integrated_system_settings_cache)
            else:
                if state.refresh_account_snapshot_meta:
                    await state.refresh_account_snapshot_meta()
        for s in state.positions:
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0)) > 0:
                state.checked_stocks.add(cd)
        # 테스트모드: dry_run 가상 잔고 기준으로 매도 조건 검사
        _sell_positions = await dry_run.get_positions() if is_test_mode(state.integrated_system_settings_cache) else state.positions
        # _checked_stocks를 현재 보유 종목 기준으로 재구성 -- 매도 완료 종목 제거 반영
        _live_codes: set[str] = set()
        for s in (await dry_run.get_positions() if is_test_mode(state.integrated_system_settings_cache) else state.positions):
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0)) > 0:
                _live_codes.add(cd)
        if is_test_mode(state.integrated_system_settings_cache):
            for cd in await dry_run.position_codes():
                _live_codes.add(cd)
        state.checked_stocks.clear()
        state.checked_stocks.update(_live_codes)
        if _sell_positions and state.auto_trade and auto_sell_effective(state.integrated_system_settings_cache) and state.access_token:
            await state.auto_trade.check_sell_conditions(_sell_positions, state.integrated_system_settings_cache, state.access_token)
    except Exception as e:
        logger.warning("[데이터] 처리 중 오류: %s", e)


def check_test_buy_power(price: int, qty: int, daily_spent: int) -> tuple[bool, str]:
    """
    테스트모드: 매수 전 예수금 검증.
    Settlement Engine의 check_buy_power를 호출하여 매수 가능 여부를 확인한다.
    반환: (ok, reason) -- ok=False이면 매수 거부 사유를 reason에 포함.
    """
    order_amount = price * qty
    daily_limit = int(state.integrated_system_settings_cache["max_daily_total_buy_amt"])
    ok, reason = settlement_engine.check_buy_power(order_amount, daily_limit, daily_spent)
    return ok, reason
