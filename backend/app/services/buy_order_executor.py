from __future__ import annotations
# -*- coding: utf-8 -*-
"""
매수 주문 실행기 - 섹터 매수 판단 및 실행 로직.

engine_lifecycle.py에서 섹터 매수 관련 함수를 분리.
"""

import time

from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.auto_trading_effective import auto_buy_effective

logger = get_logger("engine_lifecycle")


# ──────────────────────────────────────────────────────────────────────────────
# 섹터 매수 실행 함수
# ──────────────────────────────────────────────────────────────────────────────

async def evaluate_buy_candidates() -> None:
    """
    이벤트 기반 매수 판단 — 실시간 데이터 변경 시 _do_sector_recompute()에서 호출.
    auto_buy_effective(시간 범위 + auto_buy_on + 마스터 스위치) 통과 시 매수 실행.
    쿨다운: sector_buy_cooldown_sec(기본 90초).
    """
    from backend.app.services import dry_run
    from backend.app.services.daily_time_scheduler import is_krx_after_hours
    from backend.app.services.engine_symbol_utils import is_nxt_enabled
    from backend.app.services.engine_service import _sector_summary_cache
    from backend.app.services.engine_state import state

    if not state.running:
        return

    if not state.auto_trade:
        return

    ss = _sector_summary_cache
    if not ss or not ss.buy_targets:
        return

    # ── 자동매수 게이트 (auto_buy_on + 시간 범위 + 마스터 스위치 통합 체크) ──
    if not auto_buy_effective(state.integrated_system_settings_cache):
        return

    # ── 전역 조건 사전 체크 ──────────────────────────────────────────
    _max_limit = int(state.integrated_system_settings_cache["max_stock_cnt"])
    if is_test_mode(state.integrated_system_settings_cache):
        _pos_for_cnt = await dry_run.get_positions()
    else:
        _pos_for_cnt = state.positions
    _holding_cnt = sum(1 for p in _pos_for_cnt if int(p.get("qty", 0)) > 0)
    if _holding_cnt >= _max_limit:
        return

    _buy_amt = int(state.integrated_system_settings_cache["buy_amt"])
    if _buy_amt <= 0:
        return

    _max_daily = int(state.integrated_system_settings_cache["max_daily_total_buy_amt"])
    if _max_daily > 0:
        _daily_remain = _max_daily - state.auto_trade._daily_buy_spent
        if _daily_remain <= 0:
            return

    # ── 종목별 매수 시도 ─────────────────────────────────────────────
    cooldown = float(state.integrated_system_settings_cache["sector_buy_cooldown_sec"])
    now = time.time()

    _after_hours = is_krx_after_hours()

    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        # 장외 시간 KRX 단독 종목 매수 차단
        if _after_hours and not is_nxt_enabled(s.code):
            continue
        # 쿨다운 체크
        from backend.app.services.engine_state import state
        last_ts = state.master_stocks_cache.get(s.code, {}).get("_last_buy_ts") or 0.0
        if now - last_ts < cooldown:
            continue

        if s.code in state.master_stocks_cache:
            state.master_stocks_cache[s.code]["_last_buy_ts"] = now
        
        logger.info("[섹터매수] 매수 시도: %s(%s) 섹터=%s",
                    s.name, s.code, s.sector)
        try:
            _price = int(s.cur_price or 0)
            if _price <= 0:
                logger.debug("[섹터매수] %s 실시간 시세 없음 -- 생략", s.code)
                continue
            _ordered = await state.auto_trade.execute_buy(
                s.code, float(_price), state.checked_stocks, state.access_token,
                force_buy=False,
                reason=f"업종자동매수 업종={s.sector}",
            )
            if _ordered:
                logger.info("[섹터매수] 매수 주문 전송: %s(%s)", s.name, s.code)
                _holding_cnt += 1
                if _holding_cnt >= _max_limit:
                    break
                await state.auto_trade._ensure_daily_buy_counter()
                if _max_daily > 0 and state.auto_trade._daily_buy_spent >= _max_daily:
                    break
        except Exception as e:
            logger.warning("[섹터매수] execute_buy 오류 %s: %s", s.code, e, exc_info=True)
