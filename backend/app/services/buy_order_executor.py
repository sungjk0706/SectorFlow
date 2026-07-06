# -*- coding: utf-8 -*-
"""
매수 주문 실행기 - 섹터 매수 판단 및 실행 로직.

engine_lifecycle.py에서 섹터 매수 관련 함수를 분리.
"""
from __future__ import annotations
import time
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.auto_trading_effective import auto_buy_effective
logger = get_logger("engine_lifecycle")

# ── State Gate: 주문가능 금액 부족 시 evaluate_buy_candidates 호출 차단 ──
# 매도 체결 / 잔고 업데이트 이벤트에서 해제 후 재호출.
_cash_insufficient: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# 섹터 매수 실행 함수
# ──────────────────────────────────────────────────────────────────────────────

async def evaluate_buy_candidates() -> None:
    """
    이벤트 기반 매수 판단 — 실시간 데이터 변경 시 _do_sector_recompute()에서 호출.
    auto_buy_effective(시간 범위 + auto_buy_on + 마스터 스위치) 통과 시 매수 실행.
    매수후보 테이블 1순위 종목만 매수, buy_interval_on 시 사용자 설정 간격 대기.
    """
    global _cash_insufficient
    from backend.app.services import dry_run
    from backend.app.services.daily_time_scheduler import is_krx_after_hours
    from backend.app.services.engine_symbol_utils import is_nxt_enabled
    from backend.app.services.engine_state import state

    if not state.running:
        return

    if not state.auto_trade:
        return

    ss = state.sector_summary_cache
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
    _max_daily_on = bool(state.integrated_system_settings_cache.get("max_daily_total_buy_on", False))
    if _max_daily_on and _max_daily > 0:
        _daily_remain = _max_daily - state.auto_trade._daily_buy_spent
        if _daily_remain <= 0:
            return

    # ── 주문가능 금액 사전 체크 (매수 시도 전 조기 차단) ────────────────
    if is_test_mode(state.integrated_system_settings_cache):
        from backend.app.services.settlement_engine import get_available_cash
        _available = get_available_cash()
    else:
        from backend.app.services.risk_manager import get_risk_manager
        _available = get_risk_manager().account_manager.get_withdrawable_deposit()
    if _max_daily > 0:
        _effective_buy_amt = min(_buy_amt, _daily_remain)
    else:
        _effective_buy_amt = _buy_amt
    if _available <= 0:
        _cash_insufficient = True
        logger.info("[매매] 주문가능 금액 0원 — 매수 시도 중단")
        return
    _cash_insufficient = False

    # ── 전체 매수 간격 게이트 (토글 ON 시) ──────────────────────────
    _buy_interval_on = bool(state.integrated_system_settings_cache.get("buy_interval_on", False))
    if _buy_interval_on:
        _buy_interval_min = int(state.integrated_system_settings_cache.get("buy_interval_min", 0) or 0)
        if _buy_interval_min > 0:
            _now_check = time.time()
            if _now_check - state._last_global_buy_ts < _buy_interval_min * 60:
                return

    # ── 1순위 종목만 매수 시도 ───────────────────────────────────────
    _after_hours = is_krx_after_hours()

    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        # 장외 시간 KRX 단독 종목 매수 차단
        if _after_hours and not is_nxt_enabled(s.code):
            continue

        # 재매수 차단 사전 체크 — execute_buy 불필요 호출 + 로그 노이즈 제거
        _rebuy_block_on = bool(state.integrated_system_settings_cache.get("rebuy_block_on", True))
        if _rebuy_block_on and s.code in state.auto_trade._bought_today:
            continue

        logger.info("[매매] 매수 시도: %s(%s) 섹터=%s",
                    s.name, s.code, s.sector)
        try:
            _price = int(s.cur_price or 0)
            if _price <= 0:
                break
            _ordered = await state.auto_trade.execute_buy(
                s.code, float(_price), state.checked_stocks, state.access_token or "",
                force_buy=False,
                reason=f"업종자동매수 업종={s.sector}",
            )
            if _ordered:
                logger.info("[매매] 매수 주문 전송: %s(%s)", s.name, s.code)
                if _buy_interval_on:
                    state._last_global_buy_ts = time.time()
                _holding_cnt += 1
                if _holding_cnt >= _max_limit:
                    break
                await state.auto_trade._ensure_daily_buy_counter()
                if _max_daily > 0 and state.auto_trade._daily_buy_spent >= _max_daily:
                    break
        except Exception as e:
            logger.warning("[매매] 매수 실행 오류 %s: %s", s.code, e, exc_info=True)
        # 1순위 종목 1종목만 시도 후 종료
        break
