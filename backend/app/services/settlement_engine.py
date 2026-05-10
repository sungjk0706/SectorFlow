# -*- coding: utf-8 -*-
"""
Settlement Engine -- 테스트모드 전용 예수금 관리.

책임:
  1. Available_Cash 관리 (매수 차감, 매도 추가, 충전)
  2. 파일 영속화 (settlement_state.json)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── KST 타임존 ──────────────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))

# ── 수수료/세금 상수 ────────────────────────────────────────────────────────
BUY_COMMISSION = 0.00015       # 매수 수수료 0.015%
SELL_COMMISSION = 0.00015      # 매도 수수료 0.015%
SECURITIES_TAX = 0.002         # 증권거래세+농특세 0.20%

# ── 영속화 경로 ──────────────────────────────────────────────────────────────
_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "settlement_state.json"


# ── 모듈 레벨 상태 ──────────────────────────────────────────────────────────
_available_cash: int = 0
_loaded: bool = False
_initial_deposit: int = 10_000_000


# ── 기본 getters 및 init ────────────────────────────────────────────────────

def init(initial_deposit: int) -> None:
    """Settlement Engine 초기화. Available_Cash를 initial_deposit으로 설정."""
    global _available_cash, _initial_deposit
    _available_cash = initial_deposit
    _initial_deposit = initial_deposit


def get_available_cash() -> int:
    """현재 매수 가능 금액(Available_Cash) 반환."""
    return _available_cash


# ── 매수 관련 ───────────────────────────────────────────────────────────────

def check_buy_power(order_amount: int, daily_limit: int = 0, daily_spent: int = 0) -> tuple[bool, str]:
    """
    매수 가능 여부 확인.
    order_amount + 수수료가 Effective_Buy_Power 이내인지 검사.
    """
    cost = order_amount + round(order_amount * BUY_COMMISSION)
    effective = get_effective_buy_power(daily_limit, daily_spent)
    if cost > effective:
        return (False, f"예수금 부족 (필요: {cost:,}원, 가용: {effective:,}원)")
    return (True, "")


def on_buy_fill(price: int, qty: int) -> int:
    """
    매수 체결 처리. 주문금액 + 수수료를 Available_Cash에서 차감.
    반환: 차감 후 잔액.
    """
    global _available_cash
    cost = price * qty + round(price * qty * BUY_COMMISSION)
    _available_cash = max(0, _available_cash - cost)
    _persist()
    _broadcast_delta()
    return _available_cash


# ── 매도 관련 ───────────────────────────────────────────────────────────────

def on_sell_fill(price: int, qty: int, stk_cd: str, stk_nm: str) -> int:
    """
    매도 체결 처리. 순매도대금을 Available_Cash에 추가.
    반환: 추가 후 잔액.
    """
    global _available_cash
    gross = price * qty
    net_proceeds = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
    _available_cash += net_proceeds
    _persist()
    _broadcast_delta()
    return _available_cash


# ── 충전, Effective Buy Power ───────────────────────────────────────────────

def charge(amount: int) -> int:
    """예수금 충전. 반환: 충전 후 잔액."""
    global _available_cash
    if amount <= 0:
        return _available_cash
    _available_cash += amount
    _persist()
    _broadcast_delta()
    logger.info("[정산엔진] 충전 %s원 -> 잔액 %s원", f"{amount:,}", f"{_available_cash:,}")
    return _available_cash


def get_effective_buy_power(daily_limit: int = 0, daily_spent: int = 0) -> int:
    """
    실제 매수 가능 금액 계산.
    daily_limit == 0이면 무제한 (Available_Cash만 사용).
    """
    if daily_limit > 0:
        return min(_available_cash, max(0, daily_limit - daily_spent))
    return _available_cash


# ── 리셋 및 모드 전환 ───────────────────────────────────────────────────────

def reset(initial_deposit: int) -> None:
    """전체 초기화. 예수금 리셋."""
    global _available_cash, _initial_deposit
    _available_cash = initial_deposit
    _initial_deposit = initial_deposit
    _persist()
    _broadcast_delta()
    logger.info("[정산엔진] 리셋 완료 -- 초기 예수금: %s원", f"{initial_deposit:,}")


def save_state() -> None:
    """현재 상태를 파일에 저장 (모드 전환 시 호출)."""
    _persist()


def restore_state() -> None:
    """파일에서 상태 복원 (모드 전환 시 호출)."""
    _load()


# ── 영속화 ──────────────────────────────────────────────────────────────────

def _persist() -> None:
    """현재 상태를 settlement_state.json에 저장."""
    data = {
        "available_cash": _available_cash,
        "initial_deposit": _initial_deposit,
    }
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[정산엔진] 상태 저장 실패: %s", e)


def _load() -> None:
    """settlement_state.json에서 상태 복원."""
    global _available_cash, _loaded, _initial_deposit

    if not _STATE_PATH.is_file():
        try:
            from app.core.settings_file import load_settings
            s = load_settings()
            _initial_deposit = int(s.get("test_virtual_deposit", 10_000_000) or 0)
            _available_cash = _initial_deposit
        except Exception:
            _available_cash = _initial_deposit
        _loaded = True
        return

    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        _available_cash = int(data.get("available_cash", _initial_deposit))
        _initial_deposit = int(data.get("initial_deposit", _initial_deposit))
        _loaded = True
        logger.info(
            "[정산엔진] 상태 복원 완료 -- 예수금: %s원",
            f"{_available_cash:,}",
        )
    except Exception as e:
        logger.warning("[정산엔진] 상태 파일 로드 실패 (기본값 사용): %s", e)
        try:
            from app.core.settings_file import load_settings
            s = load_settings()
            _initial_deposit = int(s.get("test_virtual_deposit", 10_000_000) or 0)
            _available_cash = _initial_deposit
        except Exception:
            _available_cash = _initial_deposit
        _loaded = True


# ── 브로드캐스트 ────────────────────────────────────────────────────────────

def _broadcast_delta() -> None:
    """계좌 변경 브로드캐스트. engine_service의 account-update 메커니즘 사용."""
    try:
        from app.services import engine_service as es
        from app.core.trade_mode import is_test_mode
        if is_test_mode(es._settings_cache):
            es._refresh_account_snapshot_meta()
            es._broadcast_account(reason="settlement_delta")
    except Exception as e:
        logger.debug(
            "[정산엔진] 브로드캐스트 실패 (엔진 미기동 가능): %s", e,
        )
