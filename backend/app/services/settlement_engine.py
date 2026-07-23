# -*- coding: utf-8 -*-
"""
Settlement Engine — 테스트모드 전용 누적투자금/주문가능금액 관리.

책임:
  1. _accumulated_investment (누적투자금) 관리 — 초기투자금 + 충전금액, 매수/매도 시 불변
  2. _orderable (주문가능금액) 관리 — 매수 시 차감, 매도/충전 시 증가
  3. SQLite kv_store 영속화 (settlement_state 키)

누적투자금 vs 주문가능금액:
  - 누적투자금: 처음 설정한 투자금 + 충전한 금액의 누적. 매수/매도에 변하지 않음.
  - 주문가능금액: 지금 당장 매수에 쓸 수 있는 돈.
    매수하면 줄고, 매도/충전하면 늘어남.
"""
from __future__ import annotations
import logging
from backend.app.core.constants import (
    BUY_COMMISSION,
    SELL_COMMISSION,
    SECURITIES_TAX,
)
from backend.app.db.stock_tables import load_settlement_state, save_settlement_state
logger = logging.getLogger(__name__)


# ── 영속화 ──────────────────────────────────────────────────────────────


# ── 모듈 레벨 상태 ──────────────────────────────────────────────────────────
_accumulated_investment: int = 0   # 누적투자금 (초기투자금 + 충전금액, 매수/매도 시 불변)
_orderable: int = 0                 # 주문가능금액 (매수 시 차감, 매도/충전 시 증가)
_loaded: bool = False
_initial_deposit: int = 10_000_000


# ── 기본 getters ────────────────────────────────────────────────────────────

def get_available_cash() -> int:
    """주문가능금액 반환 (하위 호환 — orderable과 동일)."""
    return _orderable


def get_accumulated_investment() -> int:
    """누적투자금 반환 (초기투자금 + 충전금액)."""
    return _accumulated_investment


def get_orderable() -> int:
    """주문가능금액 반환."""
    return _orderable


def get_initial_deposit() -> int:
    """초기 투자금(설정값) 반환."""
    return _initial_deposit


# ── 매수 관련 ───────────────────────────────────────────────────────────────

def check_buy_power(order_amount: int, daily_limit: int = 0, daily_spent: int = 0) -> tuple[bool, str]:
    """
    매수 가능 여부 확인.
    order_amount + 수수료가 주문가능금액(Effective_Buy_Power) 이내인지 검사.
    """
    cost = order_amount + round(order_amount * BUY_COMMISSION)
    effective = get_effective_buy_power(daily_limit, daily_spent)
    if cost > effective:
        return (False, f"주문가능금액 부족 (필요: {cost:,}원, 가용: {effective:,}원)")
    return (True, "")


async def reserve_buy_power(order_amount: int, daily_limit: int = 0, daily_spent: int = 0) -> tuple[bool, str, int]:
    """
    매수 가능 여부 확인 + 즉시 차감 (원자적). TOCTOU 경쟁 상태 방지.
    check_buy_power 검증 통과 시 _orderable에서 즉시 차감하고 영속화.
    반환: (ok, reason, cost) — cost는 차감된 금액 (롤백 시 release_buy_power에 전달).
    """
    cost = order_amount + round(order_amount * BUY_COMMISSION)
    effective = get_effective_buy_power(daily_limit, daily_spent)
    if cost > effective:
        return (False, f"주문가능금액 부족 (필요: {cost:,}원, 가용: {effective:,}원)", 0)
    global _orderable
    _orderable -= cost
    await _persist()
    await _broadcast_delta()
    logger.info("[정산] 사전 차감 %s원 — 주문가능 %s원", f"{cost:,}", f"{_orderable:,}")
    return (True, "", cost)


async def release_buy_power(cost: int) -> None:
    """
    사전 차감 롤백 (주문 실패 시).
    reserve_buy_power로 차감한 금액을 _orderable에 복원.
    """
    if cost <= 0:
        return
    global _orderable
    _orderable += cost
    await _persist()
    await _broadcast_delta()
    logger.info("[정산] 사전 차감 롤백 %s원 — 주문가능 %s원", f"{cost:,}", f"{_orderable:,}")


async def on_buy_fill(price: int, qty: int) -> int:
    """
    매수 체결 처리.
    - 주문가능금액(orderable)에서만 차감
    - 누적투자금은 변하지 않음
    반환: 차감 후 주문가능금액.
    """
    global _orderable
    cost = price * qty + round(price * qty * BUY_COMMISSION)
    _orderable = max(0, _orderable - cost)

    await _persist()
    await _broadcast_delta()
    return _orderable


# ── 매도 관련 ───────────────────────────────────────────────────────────────

async def on_sell_fill(price: int, qty: int, stk_cd: str, stk_nm: str) -> int:
    """
    매도 체결 처리.
    - 순매도대금을 주문가능금액(orderable)에만 추가
    - 누적투자금은 변하지 않음
    반환: 추가 후 주문가능금액.
    """
    global _orderable
    gross = price * qty
    net_proceeds = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
    _orderable += net_proceeds
    await _persist()
    await _broadcast_delta()

    # ── 상태 게이트 회복: 매도 체결로 주문가능 금액 증가 시 매수 재평가 ──
    try:
        from backend.app.services.buy_order_executor import _cash_insufficient, evaluate_buy_candidates, invalidate_buy_snapshot
        if _cash_insufficient:
            invalidate_buy_snapshot()
            await evaluate_buy_candidates()
    except Exception as e:
        logger.warning("[정산] 상태 게이트 회복 실패 (매도 정산은 완료): %s", e, exc_info=True)

    return _orderable


# ── 충전, Effective Buy Power ───────────────────────────────────────────────

async def charge(amount: int) -> int:
    """누적투자금 + 주문가능금액 동시 충전. 반환: 충전 후 주문가능금액."""
    global _accumulated_investment, _orderable
    if amount <= 0:
        return _orderable
    _accumulated_investment += amount
    _orderable += amount
    await _persist()
    await _broadcast_delta()
    logger.info("[정산] 충전 %s원 — 누적투자금 %s원 / 주문가능 %s원", f"{amount:,}", f"{_accumulated_investment:,}", f"{_orderable:,}")
    return _orderable


def get_effective_buy_power(daily_limit: int = 0, daily_spent: int = 0) -> int:
    """
    실제 매수 가능 금액 계산 (주문가능금액 기준).
    daily_limit == 0이면 무제한 (주문가능금액만 사용).
    """
    if daily_limit > 0:
        return min(_orderable, max(0, daily_limit - daily_spent))
    return _orderable


# ── 리셋 및 모드 전환 ───────────────────────────────────────────────────────

async def reset(initial_deposit: int) -> None:
    """전체 초기화. 누적투자금/주문가능금액 모두 리셋."""
    global _accumulated_investment, _orderable, _initial_deposit
    _accumulated_investment = initial_deposit
    _orderable = initial_deposit
    _initial_deposit = initial_deposit
    await _persist()
    await _broadcast_delta()
    logger.info("[정산] 리셋 완료 — 초기투자금: %s원", f"{initial_deposit:,}")


async def save_state() -> None:
    """현재 상태를 파일에 저장 (모드 전환 시 호출)."""
    await _persist()


async def load_state(initial_deposit: int | None = None) -> None:
    """SQLite에서 상태 로드 (기동 시 및 모드 전환 시 호출)."""
    await _load(force_reload=True, initial_deposit=initial_deposit)


# ── 영속화 ──────────────────────────────────────────────────────────────────

async def _persist() -> None:
    """현재 상태를 SQLite KV 스토어에 저장."""
    data = {
        "accumulated_investment": _accumulated_investment,
        "orderable": _orderable,
        "initial_deposit": _initial_deposit,
    }
    await save_settlement_state(data)


async def _load(force_reload: bool = False, initial_deposit: int | None = None) -> None:
    """SQLite KV 스토어에서 상태 로드.

    - DB에 저장된 상태가 있으면 로드한다.
    - 없으면 initial_deposit(인자 → settings.test_virtual_deposit → 기본값)을 사용해 초기화.
    - DB 에러 시 예외 전파하여 기동 실패로 명시적 알림.

    Args:
        force_reload: True이면 이미 로드되어 있어도 강제 재로드 (모드 전환 시 사용)
        initial_deposit: DB에 상태가 없을 때 사용할 초기 투자금
    """
    global _accumulated_investment, _orderable, _loaded, _initial_deposit

    # 이미 로드되어 있고 강제 재로드가 아니면 스킵
    if _loaded and not force_reload:
        return

    data = await load_settlement_state()
    if not data:
        # 신규 설치 — initial_deposit으로 초기화
        if initial_deposit is not None and initial_deposit > 0:
            _initial_deposit = initial_deposit
        else:
            from backend.app.services.engine_state import state
            s = state.integrated_system_settings_cache
            _initial_deposit = int(s["test_virtual_deposit"])
        _accumulated_investment = _initial_deposit
        _orderable = _initial_deposit
        _loaded = True
        await _persist()
        logger.info("[정산] 초기값 SQLite 저장 완료 — 주문가능: %s원", f"{_orderable:,}")
        return

    _initial_deposit = int(data.get("initial_deposit", _initial_deposit))
    # 신버전 파일 (accumulated_investment 키) 처리
    if "accumulated_investment" in data:
        _accumulated_investment = int(data["accumulated_investment"])
        _orderable = int(data.get("orderable", _accumulated_investment))
    # 구버전 파일 (deposit 키) 하위 호환 처리
    elif "deposit" in data:
        _accumulated_investment = int(data["deposit"])
        _orderable = int(data.get("orderable", _accumulated_investment))
    # 구버전 파일 (available_cash 키) 하위 호환 처리
    else:
        _accumulated_investment = int(data.get("available_cash", _initial_deposit))
        _orderable = _accumulated_investment
    _loaded = True
    logger.info(
        "[정산] 상태 로드 완료 — 누적투자금: %s원 / 주문가능: %s원",
        f"{_accumulated_investment:,}", f"{_orderable:,}",
    )


# ── 기동 시 정합성 대조 (P22 데이터 정합성) ──────────────────────────────────

async def reconcile_with_trades() -> None:
    """기동 시 trade_history에서 주문가능금액을 재계산하여 현재 _orderable과 대조.

    fake_fill_event 태스크 실패/취소 시 on_buy_fill/on_sell_fill이 누락되어
    _orderable이 거래 이력과 불일치하는 상태가 영속화되는 것을 방지 (B5-08-03).

    - 일치 시: debug 로그만.
    - 불일치 시: 에러 로그 + 재계산값으로 _orderable 복구 + 영속화 + 브로드캐스트
                + UI 알림(settlement_reconciled 이벤트 — 불일치 금액/복구 여부 포함).

    P22(데이터 정합성) + P21(사용자 투명성) + P25(격리된 실패 — 대조 실패 시 기동 중단 아님).
    """
    global _orderable
    try:
        from backend.app.services import trade_history
        expected = await trade_history.compute_expected_orderable(_initial_deposit, "test")
        actual = _orderable
        if expected == actual:
            logger.info("[정산] 기동 대조 완료 — 주문가능 %s원 (일치)", f"{actual:,}")
            return
        diff = actual - expected
        logger.error(
            "[정산] 기동 대조 불일치 — DB=%s원, 재계산=%s원, 차액=%s원 → 재계산값으로 복구",
            f"{actual:,}", f"{expected:,}", f"{diff:+,}",
        )
        _orderable = expected
        await _persist()
        await _broadcast_delta()
        # P21 사용자 투명성 — 잔고 자동 보정을 화면에 알림
        try:
            from backend.app.services.engine_account_notify import _safe_broadcast
            await _safe_broadcast("settlement_reconciled", {
                "recovered": True,
                "expected": expected,
                "previous": actual,
                "diff": diff,
                "message": f"잔고 정합성 복구 — {diff:+,}원 보정 (거래내역 기준)",
            })
        except Exception as e:
            logger.warning("[정산] 정합성 복구 알림 전송 실패 (복구 자체는 완료): %s", e, exc_info=True)
    except Exception as e:
        # P25 격리된 실패 — 대조 자체 실패 시 기동 중단하지 않고 로깅 후 진행
        logger.error("[정산] 기동 대조 실패 — 정합성 검증 생략 (엔진은 계속 기동): %s", e, exc_info=True)


# ── 브로드캐스트 ────────────────────────────────────────────────────────────

async def _broadcast_delta() -> None:
    """계좌 변경 브로드캐스트. engine_account의 account-update 메커니즘 사용."""
    try:
        from backend.app.services.engine_state import state
        from backend.app.services.engine_account import _refresh_account_snapshot_meta, _broadcast_account
        from backend.app.core.trade_mode import is_test_mode
        if is_test_mode(state.integrated_system_settings_cache):
            await _refresh_account_snapshot_meta()
            await _broadcast_account(reason="settlement_delta")
    except Exception as e:
        logger.warning(
            "[정산] 전송 실패 (엔진 미기동 가능): %s", e,
        )
