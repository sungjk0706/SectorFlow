# -*- coding: utf-8 -*-
"""
Settlement Engine -- 테스트모드 전용 누적투자금/주문가능금액 관리.

책임:
  1. _accumulated_investment (누적투자금) 관리 -- 초기투자금 + 충전금액, 매수/매도 시 불변
  2. _orderable (주문가능금액) 관리 -- 매수 시 차감, 매도/충전 시 증가
  3. SQLite kv_store 영속화 (settlement_state 키)

누적투자금 vs 주문가능금액:
  - 누적투자금: 처음 설정한 투자금 + 충전한 금액의 누적. 매수/매도에 변하지 않음.
  - 주문가능금액: 지금 당장 매수에 쓸 수 있는 돈.
    매수하면 줄고, 매도/충전하면 늘어남.
"""
from __future__ import annotations
import logging
from datetime import timedelta, timezone
from backend.app.db.stock_tables import load_settlement_state, save_settlement_state
logger = logging.getLogger(__name__)

# ── KST 타임존 ──────────────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))

# ── 수수료/세금 상수 ────────────────────────────────────────────────────────
BUY_COMMISSION = 0.00015       # 매수 수수료 0.015%
SELL_COMMISSION = 0.00015      # 매도 수수료 0.015%
SECURITIES_TAX = 0.002         # 증권거래세+농특세 0.20%

# ── 영속화 ──────────────────────────────────────────────────────────────


# ── 모듈 레벨 상태 ──────────────────────────────────────────────────────────
_accumulated_investment: int = 0   # 누적투자금 (초기투자금 + 충전금액, 매수/매도 시 불변)
_orderable: int = 0                 # 주문가능금액 (매수 시 차감, 매도/충전 시 증가)
_loaded: bool = False
_initial_deposit: int = 10_000_000


# ── 기본 getters 및 init ────────────────────────────────────────────────────

def init(initial_deposit: int) -> None:
    """Settlement Engine 초기화 (기본값 설정만 수행, DB 로드는 _load()에서 수행)."""
    global _accumulated_investment, _orderable, _initial_deposit
    _initial_deposit = initial_deposit
    # _load()가 호출되지 않은 경우 기본값 사용
    if not _loaded:
        _accumulated_investment = initial_deposit
        _orderable = initial_deposit


def get_available_cash() -> int:
    """주문가능금액 반환 (하위 호환 -- orderable과 동일)."""
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

    # ── State Gate 회복: 매도 체결로 주문가능 금액 증가 시 매수 재평가 ──
    try:
        from backend.app.services.buy_order_executor import _cash_insufficient, evaluate_buy_candidates
        if _cash_insufficient:
            await evaluate_buy_candidates()
    except Exception:
        pass

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
    logger.info("[정산엔진] 충전 %s원 -> 누적투자금 %s원 / 주문가능 %s원", f"{amount:,}", f"{_accumulated_investment:,}", f"{_orderable:,}")
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
    logger.info("[정산엔진] 리셋 완료 -- 초기투자금: %s원", f"{initial_deposit:,}")


async def save_state() -> None:
    """현재 상태를 파일에 저장 (모드 전환 시 호출)."""
    await _persist()


async def restore_state() -> None:
    """파일에서 상태 복원 (모드 전환 시 호출)."""
    await _load(force_reload=True)


# ── 영속화 ──────────────────────────────────────────────────────────────────

async def _persist() -> None:
    """현재 상태를 SQLite KV 스토어에 저장."""
    data = {
        "accumulated_investment": _accumulated_investment,
        "orderable": _orderable,
        "initial_deposit": _initial_deposit,
    }
    try:
        await save_settlement_state(data)
    except Exception as e:
        logger.warning("[정산엔진] 상태 저장 실패: %s", e)


async def _load(force_reload: bool = False) -> None:
    """SQLite KV 스토어에서 상태 복원.
    
    Args:
        force_reload: True이면 이미 로드되어 있어도 강제 재로드 (모드 전환 시 사용)
    """
    global _accumulated_investment, _orderable, _loaded, _initial_deposit

    # 이미 로드되어 있고 강제 재로드가 아니면 스킵
    if _loaded and not force_reload:
        logger.debug("[정산엔진] 이미 로드됨 - 스킵")
        return

    try:
        data = await load_settlement_state()
        if not data:
            raise FileNotFoundError("SQLite KV Store에서 settlement_state를 찾을 수 없습니다.")

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
            "[정산엔진] 상태 복원 완료 -- 누적투자금: %s원 / 주문가능: %s원",
            f"{_accumulated_investment:,}", f"{_orderable:,}",
        )
    except Exception as e:
        logger.warning("[정산엔진] 상태 파일 로드 실패 (기본값 사용): %s", e)
        try:
            import backend.app.services.engine_state as _st
            s = _st._integrated_system_settings_cache
            _initial_deposit = int(s["test_virtual_deposit"])
            _accumulated_investment = _initial_deposit
            _orderable = _initial_deposit
        except Exception:
            _accumulated_investment = _initial_deposit
            _orderable = _initial_deposit
        _loaded = True
        await _persist()
        logger.info("[정산엔진] 초기값 SQLite 저장 완료 -- 주문가능: %s원", f"{_orderable:,}")


# ── 브로드캐스트 ────────────────────────────────────────────────────────────

async def _broadcast_delta() -> None:
    """계좌 변경 브로드캐스트. engine_service의 account-update 메커니즘 사용."""
    try:
        from backend.app.services import engine_service as es
        from backend.app.core.trade_mode import is_test_mode
        if is_test_mode(es.state.integrated_system_settings_cache):
            await es._refresh_account_snapshot_meta()
            await es._broadcast_account(reason="settlement_delta")
    except Exception as e:
        logger.warning(
            "[정산엔진] 브로드캐스트 실패 (엔진 미기동 가능): %s", e,
        )
