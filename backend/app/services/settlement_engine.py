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
import asyncio
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
_daily_deposit_total: int = 0       # 당일 입금액 누적 (장마감 스냅샷 저장 후 reset)


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


# ── 매수 관련 ───────────────────────────────────────────────────────────────

async def reserve_buy_power(order_amount: int, daily_limit: int = 0, daily_spent: int = 0) -> tuple[bool, str, int]:
    """
    매수 가능 여부 확인 + 즉시 차감 (원자적). TOCTOU 경쟁 상태 방지 (테스트모드 전용 — P18).
    검증 통과 시 _orderable에서 즉시 차감하고 영속화.
    반환: (ok, reason, cost) — cost는 차감된 금액 (롤백 시 release_buy_power에 전달).
    실전은 증권사 서버가 SSOT이므로 이 함수 미호출 (engine_strategy_core.reserve_test_buy_power 경유, trading.py에서 is_virtual_mode 게이트).
    """
    cost = order_amount + round(order_amount * BUY_COMMISSION)
    effective = get_effective_buy_power(daily_limit, daily_spent)
    if cost > effective:
        return (False, f"주문가능금액 부족 (필요: {cost:,}원, 가용: {effective:,}원)", 0)
    global _orderable
    _orderable -= cost
    await _persist()
    await _broadcast_delta()
    logger.debug("[정산] 사전 차감 %s원 — 주문가능 %s원", f"{cost:,}", f"{_orderable:,}")
    return (True, "", cost)


async def release_buy_power(cost: int) -> None:
    """
    사전 차감 롤백 (주문 실패 시). 테스트모드 전용 (P18).
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
    매수 체결 처리 (테스트모드 전용 — P18).
    - 주문가능금액(orderable)에서만 차감
    - 누적투자금은 변하지 않음
    반환: 차감 후 주문가능금액.
    실전은 dry_run._apply_buy 경유로만 호출되므로 실전 미호출 — 증권사 서버가 SSOT.
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
    매도 체결 처리 (테스트모드 전용 — P18).
    - 순매도대금을 주문가능금액(orderable)에만 추가
    - 누적투자금은 변하지 않음
    반환: 추가 후 주문가능금액.
    실전은 dry_run._apply_sell 경유로만 호출되므로 실전 미호출 — 증권사 서버가 SSOT.
    """
    global _orderable
    gross = price * qty
    net_proceeds = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
    _orderable += net_proceeds
    await _persist()
    await _broadcast_delta()

    # ── 상태 게이트 회복: 매도 체결로 주문가능 금액 증가 시 매수 재평가 → 주문 실행 큐로 이동 (결정 5) ──
    try:
        from backend.app.services.buy_order_executor import _cash_insufficient, invalidate_buy_snapshot
        from backend.app.services.core_queues import get_order_queue
        if _cash_insufficient:
            invalidate_buy_snapshot()
            try:
                get_order_queue().put_nowait({"type": "buy_evaluate"})
            except asyncio.QueueFull:
                logger.warning("[정산] 주문 큐 가득 참 — 매수 후보 평가 요청 드롭 (매도 체결 후)")
    except Exception as e:
        logger.warning("[정산] 상태 게이트 회복 실패 (매도 정산은 성공): %s", e, exc_info=True)

    return _orderable


# ── 충전, Effective Buy Power ───────────────────────────────────────────────

async def charge(amount: int) -> int:
    """누적투자금 + 주문가능금액 동시 충전. 반환: 충전 후 주문가능금액."""
    global _accumulated_investment, _orderable, _daily_deposit_total
    if amount <= 0:
        return _orderable
    _accumulated_investment += amount
    _orderable += amount
    _daily_deposit_total += amount
    await _persist()
    await _broadcast_delta()
    logger.info("[정산] 충전 %s원 — 누적투자금 %s원 / 주문가능 %s원", f"{amount:,}", f"{_accumulated_investment:,}", f"{_orderable:,}")
    return _orderable


def get_daily_deposit_total() -> int:
    """당일 입금액 누적 반환 (기초자산 분모 방식 — 당일 순입출금 추적)."""
    return _daily_deposit_total


def reset_daily_deposit_total() -> None:
    """당일 입금액 누적 리셋 (장마감 스냅샷 저장 후 호출)."""
    global _daily_deposit_total
    _daily_deposit_total = 0


def get_effective_buy_power(daily_limit: int = 0, daily_spent: int = 0) -> int:
    """
    실제 매수 가능 금액 계산 (주문가능금액 기준). 테스트모드 전용 (P18).
    daily_limit == 0이면 무제한 (주문가능금액만 사용).
    reserve_buy_power에서만 호출 → 실전 미호출.
    """
    if daily_limit > 0:
        return min(_orderable, max(0, daily_limit - daily_spent))
    return _orderable


def max_buy_qty_for_budget(price: int, budget: int, is_virtual: bool) -> int:
    """예산 내 최대 매수 수량 (수수료 포함, P10 SSOT, P18 부합).

    테스트모드: reserve_buy_power의 cost 공식(price*qty + round(price*qty*BUY_COMMISSION))
    과 정합되도록 수수료 여유분 확보.
    실전모드: 증권사 서버가 SSOT이므로 앱에서 수수료 계산하지 않음 — budget // price 만 사용.
    trading.py의 buy_qty 계산과 buy_order_executor._refresh_buyable_prices가
    동일 기준으로 호출 (P22 정합성).
    """
    if price <= 0 or budget <= 0:
        return 0
    if not is_virtual:
        return budget // price
    qty = budget // price
    while qty > 0 and qty * price + round(qty * price * BUY_COMMISSION) > budget:
        qty -= 1
    return qty


# ── 리셋 및 모드 전환 ───────────────────────────────────────────────────────

async def reset(initial_deposit: int) -> None:
    """전체 초기화. 누적투자금/주문가능금액 모두 리셋."""
    global _accumulated_investment, _orderable, _initial_deposit, _daily_deposit_total
    _accumulated_investment = initial_deposit
    _orderable = initial_deposit
    _initial_deposit = initial_deposit
    _daily_deposit_total = 0
    await _persist()
    await _broadcast_delta()
    logger.info("[정산] 리셋 — 초기투자금: %s원", f"{initial_deposit:,}")


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
            _initial_deposit = int(s["virtual_deposit"])
        _accumulated_investment = _initial_deposit
        _orderable = _initial_deposit
        _loaded = True
        await _persist()
        logger.info("[정산] 초기값 SQLite 저장 — 주문가능: %s원", f"{_orderable:,}")
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
        # accumulated_investment(초기투자금 + 충전 누적)을 재구축 시작 잔고로 사용.
        # _initial_deposit은 charge() 시 증가하지 않으므로 충전 후 재기동 시
        # 거짓 불일치로 충전금이 삭제되는 결함 방지 (P22 데이터 정합성).
        expected = await trade_history.compute_expected_orderable(_accumulated_investment, "virtual")
        actual = _orderable
        if expected == actual:
            logger.info("[정산] 기동 대조 — 주문가능 %s원 (일치)", f"{actual:,}")
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
            logger.warning("[정산] 정합성 복구 알림 전송 실패 (복구 자체는 성공): %s", e, exc_info=True)
    except Exception as e:
        # P25 격리된 실패 — 대조 자체 실패 시 기동 중단하지 않고 로깅 후 진행
        logger.error("[정산] 기동 대조 실패 — 정합성 검증 생략 (엔진은 계속 기동): %s", e, exc_info=True)


# ── 브로드캐스트 ────────────────────────────────────────────────────────────

async def _broadcast_delta() -> None:
    """계좌 변경 브로드캐스트. engine_account의 account-update 메커니즘 사용."""
    try:
        from backend.app.services.engine_state import state
        from backend.app.services.engine_account import _refresh_account_snapshot_meta, _broadcast_account
        from backend.app.core.trade_mode import is_virtual_mode
        if is_virtual_mode(state.integrated_system_settings_cache):
            await _refresh_account_snapshot_meta()
            await _broadcast_account(reason="settlement_delta")
    except Exception as e:
        logger.warning(
            "[정산] 전송 실패 (엔진 미기동 가능): %s", e,
        )
