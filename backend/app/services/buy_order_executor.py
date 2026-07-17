# -*- coding: utf-8 -*-
"""
매수 주문 실행기 - 업종 매수 판단 및 실행 로직.

engine_lifecycle.py에서 업종 매수 관련 함수를 분리.
"""
from __future__ import annotations
import logging
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.auto_trading_effective import auto_buy_effective
logger = logging.getLogger(__name__)

# ── State Gate: 주문가능 금액 부족 시 evaluate_buy_candidates 호출 차단 ──
# 매도 체결 / 잔고 업데이트 이벤트에서 해제 후 재호출.
_cash_insufficient: bool = False

# ── 전역 조건 스냅샷: 조건 변화 없으면 매수 시도 스킵 (원칙 11 이벤트 기반) ──
_last_global_snapshot: dict | None = None


def invalidate_buy_snapshot() -> None:
    """전역 조건 스냅샷 무효화 — 매수 성공/설정 변경/잔고 회복 시 호출."""
    global _last_global_snapshot
    _last_global_snapshot = None


# ──────────────────────────────────────────────────────────────────────────────
# 업종 매수 실행 함수
# ──────────────────────────────────────────────────────────────────────────────

async def evaluate_buy_candidates() -> None:
    """
    이벤트 기반 매수 판단 — 실시간 데이터 변경 시 _do_sector_recompute()에서 호출.
    auto_buy_effective(시간 범위 + auto_buy_on + 마스터 스위치) 통과 시 매수 실행.
    매수 후보 테이블 1순위 종목만 매수, buy_interval_on 시 사용자 설정 간격(초) 대기.
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
    _max_limit_on = bool(state.integrated_system_settings_cache.get("max_stock_cnt_on", True))
    if is_test_mode(state.integrated_system_settings_cache):
        _pos_for_cnt = await dry_run.get_positions()
    else:
        _pos_for_cnt = state.positions
    _holding_cnt = sum(1 for p in _pos_for_cnt if int(p.get("qty", 0)) > 0)
    if _max_limit_on and _holding_cnt >= _max_limit:
        return

    _buy_amt = int(state.integrated_system_settings_cache["buy_amt"])
    _buy_amt_on = bool(state.integrated_system_settings_cache.get("buy_amt_on", True))
    if _buy_amt_on and _buy_amt <= 0:
        return

    _max_daily = int(state.integrated_system_settings_cache["max_daily_total_buy_amt"])
    _max_daily_on = bool(state.integrated_system_settings_cache.get("max_daily_total_buy_on", False))
    _daily_remain: int | None = None
    if _max_daily_on and _max_daily > 0:
        if state.auto_trade._daily_buy_spent is None:
            logger.critical("[매매] 일일 매수 상태 로드 실패 — 매수 시도 중단")
            return
        _daily_remain = _max_daily - state.auto_trade._daily_buy_spent
        if _daily_remain <= 0:
            return

    # ── 주문가능 금액 사전 체크 (매수 시도 전 조기 차단) ────────────────
    from backend.app.services.risk_manager import get_risk_manager
    _available = get_risk_manager().get_withdrawable_deposit()
    if _buy_amt_on:
        if _max_daily_on and _max_daily > 0 and _daily_remain is not None:
            _effective_buy_amt = min(_buy_amt, _daily_remain)
        else:
            _effective_buy_amt = _buy_amt
    else:
        # buy_amt_on=False → 종목당 한도 없음, 일일 한도만 적용
        if _max_daily_on and _max_daily > 0 and _daily_remain is not None:
            _effective_buy_amt = _daily_remain
        else:
            _effective_buy_amt = None  # 주문가능 금액이 상한
    if _available <= 0:
        _cash_insufficient = True
        logger.info("[매매] 주문가능 금액 0원 — 매수 시도 중단")
        return
    _cash_insufficient = False

    # ── 전체 매수 간격 게이트 (토글 ON 시) ──────────────────────────
    from backend.app.services.order_interval import check_order_interval
    if not check_order_interval(state.integrated_system_settings_cache, "buy"):
        return

    # ── 전역 조건 스냅샷: 변화 없으면 매수 시도 스킵 (원칙 11 이벤트 기반) ──
    _after_hours = is_krx_after_hours()
    _rebuy_block_on = bool(state.integrated_system_settings_cache.get("rebuy_block_on", True))
    _is_test = is_test_mode(state.integrated_system_settings_cache)

    # ── 매수 가능 종목 집합: guard_pass + 장외 + 재매수 + 주문가능금액/가격 ──
    # execute_buy 내부(trading.py:250-257)와 동일 기준으로 사전 필터링하여
    # "매수 시도" 로그 후 차단되는 불필요한 호출 제거 (P10 SSOT, P21 사용자 투명성).
    # available_cash를 snapshot에서 제거하고 _buyable_codes가 orderable/가격에
    # 의존하도록 통일 — orderable 변동 시 _buyable_codes가 변하여 snapshot 반영.
    _buyable_codes: set[str] = set()
    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        if _after_hours and not is_nxt_enabled(s.code):
            continue
        if _rebuy_block_on and s.code in state.auto_trade._bought_today:
            continue
        _price = int(s.cur_price or 0)
        if _price <= 0:
            continue
        # 테스트모드 슬리피지 적용 (trading.py:254와 동일)
        _est_price = dry_run.estimate_fill_price(_price, "BUY") if _is_test else _price
        # 종목별 가용 금액 = min(effective_buy_amt, available) 또는 available
        _max_for_code = min(_effective_buy_amt, _available) if _effective_buy_amt is not None else _available
        if _max_for_code < _est_price:
            continue
        _buyable_codes.add(s.code)

    _current_snapshot = {
        "buyable_codes": tuple(sorted(_buyable_codes)),
        "holding_cnt": _holding_cnt,
        "daily_remain": _daily_remain if (_max_daily_on and _max_daily > 0) else None,
        "buy_amt": _buy_amt,
        "buy_amt_on": _buy_amt_on,
        "max_limit": _max_limit,
        "max_limit_on": _max_limit_on,
    }

    global _last_global_snapshot
    if _current_snapshot == _last_global_snapshot:
        return
    _last_global_snapshot = _current_snapshot

    # ── 1순위 종목만 매수 시도 ───────────────────────────────────────
    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        # 장외 시간 KRX 단독 종목 매수 차단
        if _after_hours and not is_nxt_enabled(s.code):
            continue
        # 재매수 차단 + 주문가능금액/가격 필터 (buyable_codes와 동일 조건)
        if s.code not in _buyable_codes:
            continue

        logger.info("[매매] 매수 시도: %s(%s) 업종=%s",
                    s.name, s.code, s.sector)
        try:
            _price = int(s.cur_price or 0)
            if _price <= 0:
                break
            _ordered = await state.auto_trade.execute_buy(
                s.code, float(_price), state.access_token or "",
                reason=f"업종자동매수 업종={s.sector}",
            )
            if _ordered:
                logger.info("[매매] 매수 주문 전송: %s(%s)", s.name, s.code)
                invalidate_buy_snapshot()
                from backend.app.services.order_interval import mark_order_executed
                mark_order_executed("buy")
                _holding_cnt += 1
                if _max_limit_on and _holding_cnt >= _max_limit:
                    break
                await state.auto_trade._ensure_daily_buy_counter()
                if state.auto_trade._daily_buy_spent is not None and _max_daily > 0 and state.auto_trade._daily_buy_spent >= _max_daily:
                    break
        except Exception as e:
            logger.warning("[매매] 매수 실행 오류 %s: %s", s.code, e, exc_info=True)
        # 1순위 종목 1종목만 시도 후 종료
        break
