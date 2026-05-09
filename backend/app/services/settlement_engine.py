# -*- coding: utf-8 -*-
"""
Settlement Engine -- 테스트모드 전용 예수금 관리 + D+2 정산 시뮬레이션.

책임:
  1. Available_Cash 관리 (매수 차감, 매도 추가, 충전, 인출)
  2. Pending_Withdrawal 관리 (D+2 인출 제한)
  3. 정산 타이머 스케줄링 (asyncio.call_later)
  4. 파일 영속화 (settlement_state.json)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core.trading_calendar import _next_business_date

logger = logging.getLogger(__name__)

# ── KST 타임존 ──────────────────────────────────────────────────────────────
_KST = timezone(timedelta(hours=9))

# ── 수수료/세금 상수 ────────────────────────────────────────────────────────
BUY_COMMISSION = 0.00015       # 매수 수수료 0.015%
SELL_COMMISSION = 0.00015      # 매도 수수료 0.015%
SECURITIES_TAX = 0.002         # 증권거래세+농특세 0.20%

# ── 영속화 경로 ──────────────────────────────────────────────────────────────
_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "settlement_state.json"


# ── 데이터 모델 ──────────────────────────────────────────────────────────────
@dataclass
class PendingWithdrawal:
    """미정산 매도대금 항목."""
    sell_date: str          # 매도일 (YYYY-MM-DD)
    stk_cd: str             # 종목코드
    stk_nm: str             # 종목명
    amount: int             # 순매도대금 (원)
    settlement_date: str    # 정산일 (YYYY-MM-DD)


# ── 모듈 레벨 상태 ──────────────────────────────────────────────────────────
_available_cash: int = 0
_pending_withdrawals: list[PendingWithdrawal] = []
_timer_handles: list[tuple[PendingWithdrawal, asyncio.TimerHandle]] = []
_loaded: bool = False
_initial_deposit: int = 10_000_000


# ── 1.2: 기본 getters 및 init ───────────────────────────────────────────────

def init(initial_deposit: int) -> None:
    """Settlement Engine 초기화. Available_Cash를 initial_deposit으로 설정."""
    global _available_cash, _initial_deposit, _pending_withdrawals, _timer_handles
    _available_cash = initial_deposit
    _initial_deposit = initial_deposit
    _pending_withdrawals = []
    _timer_handles = []


def get_available_cash() -> int:
    """현재 매수 가능 금액(Available_Cash) 반환."""
    return _available_cash


def get_withdrawable_cash() -> int:
    """현재 인출 가능 금액 반환. Available_Cash - 총 Pending_Withdrawal 합계."""
    return _available_cash - sum(pw.amount for pw in _pending_withdrawals)


def get_pending_withdrawal_total() -> int:
    """정산 대기 금액 합계 반환."""
    return sum(pw.amount for pw in _pending_withdrawals)


def get_pending_withdrawals() -> list[dict]:
    """미정산 항목 목록을 dict 리스트로 반환."""
    return [asdict(pw) for pw in _pending_withdrawals]


# ── 1.3: 매수 관련 ──────────────────────────────────────────────────────────

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


# ── 1.4: 매도 관련 (D+2 스케줄링) ───────────────────────────────────────────

def on_sell_fill(price: int, qty: int, stk_cd: str, stk_nm: str) -> int:
    """
    매도 체결 처리. 순매도대금을 Available_Cash에 추가하고 Pending_Withdrawal 생성.
    반환: 추가 후 잔액.
    """
    global _available_cash
    gross = price * qty
    net_proceeds = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
    _available_cash += net_proceeds

    sell_date = datetime.now(_KST).date()
    settlement_date = _calc_settlement_date(sell_date)

    pw = PendingWithdrawal(
        sell_date=sell_date.isoformat(),
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        amount=net_proceeds,
        settlement_date=settlement_date.isoformat(),
    )
    _pending_withdrawals.append(pw)
    _schedule_settlement(pw)
    _persist()
    _broadcast_delta()
    return _available_cash


# ── 1.5: 정산일 계산 ────────────────────────────────────────────────────────

def _calc_settlement_date(sell_date: date) -> date:
    """매도일로부터 D+2 영업일 계산. _next_business_date를 2회 호출."""
    d1 = _next_business_date(sell_date)
    d2 = _next_business_date(d1)
    return d2


def _seconds_until_settlement(settlement_date: date) -> float:
    """settlement_date 09:00 KST까지 남은 초 계산. 이미 지났으면 0."""
    target = datetime(
        settlement_date.year, settlement_date.month, settlement_date.day,
        9, 0, 0, tzinfo=_KST,
    )
    now = datetime.now(_KST)
    diff = (target - now).total_seconds()
    return max(0.0, diff)


# ── 1.6: 타이머 스케줄링 ────────────────────────────────────────────────────

def _schedule_settlement(pw: PendingWithdrawal) -> None:
    """asyncio call_later로 정산 타이머 등록."""
    seconds = _seconds_until_settlement(date.fromisoformat(pw.settlement_date))
    try:
        loop = asyncio.get_running_loop()
        handle = loop.call_later(seconds, _settle_callback, pw)
        _timer_handles.append((pw, handle))
    except RuntimeError:
        # 이벤트 루프 없음 -- 앱 재시작 시 _load()에서 처리
        logger.debug("[정산엔진] 이벤트 루프 없음 -- 타이머 스케줄링 스킵 (재시작 시 복원)")


def _settle_callback(pw: PendingWithdrawal) -> None:
    """정산 타이머 콜백. Pending_Withdrawal 제거 + 영속화 + 브로드캐스트."""
    global _pending_withdrawals, _timer_handles
    _pending_withdrawals = [p for p in _pending_withdrawals if p is not pw]
    _timer_handles = [(p, h) for p, h in _timer_handles if p is not pw]
    _persist()
    logger.info(
        "[정산엔진] 정산 완료: %s %s %s원 (정산일: %s)",
        pw.stk_cd, pw.stk_nm, f"{pw.amount:,}", pw.settlement_date,
    )
    _broadcast_delta()


# ── 1.7: 영속화 ─────────────────────────────────────────────────────────────

def _persist() -> None:
    """현재 상태를 settlement_state.json에 저장."""
    data = {
        "available_cash": _available_cash,
        "pending_withdrawals": [asdict(pw) for pw in _pending_withdrawals],
        "initial_deposit": _initial_deposit,
    }
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[정산엔진] 상태 저장 실패: %s", e)


def _load() -> None:
    """settlement_state.json에서 상태 복원. 만료 항목 제거 + 타이머 재스케줄."""
    global _available_cash, _pending_withdrawals, _timer_handles, _loaded, _initial_deposit

    if not _STATE_PATH.is_file():
        # 파일 없음 -- 설정에서 초기 예수금 로드
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

        raw_pending = data.get("pending_withdrawals", [])
        today = datetime.now(_KST).date()

        _pending_withdrawals = []
        for item in raw_pending:
            pw = PendingWithdrawal(
                sell_date=item["sell_date"],
                stk_cd=item["stk_cd"],
                stk_nm=item["stk_nm"],
                amount=int(item["amount"]),
                settlement_date=item["settlement_date"],
            )
            sd = date.fromisoformat(pw.settlement_date)
            if sd <= today:
                # 이미 정산일 지남 -- 즉시 정산 (인출 가능 전환)
                logger.info("[정산엔진] 만료 항목 즉시 정산: %s %s %s원", pw.stk_cd, pw.stk_nm, f"{pw.amount:,}")
            else:
                _pending_withdrawals.append(pw)
                _schedule_settlement(pw)

        _loaded = True
        logger.info(
            "[정산엔진] 상태 복원 완료 -- 예수금: %s원, 미정산: %d건",
            f"{_available_cash:,}", len(_pending_withdrawals),
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
        _pending_withdrawals = []
        _loaded = True


# ── 1.8: 충전, 인출, Effective Buy Power ────────────────────────────────────

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


def withdraw(amount: int) -> tuple[bool, int]:
    """
    가상 인출. Withdrawable_Cash 범위 내에서만 차감.
    반환: (성공여부, 잔액).
    """
    global _available_cash
    if amount <= 0:
        return (False, _available_cash)
    withdrawable = get_withdrawable_cash()
    if amount > withdrawable:
        return (False, _available_cash)
    _available_cash -= amount
    _persist()
    _broadcast_delta()
    logger.info("[정산엔진] 인출 %s원 -> 잔액 %s원", f"{amount:,}", f"{_available_cash:,}")
    return (True, _available_cash)


def get_effective_buy_power(daily_limit: int = 0, daily_spent: int = 0) -> int:
    """
    실제 매수 가능 금액 계산.
    daily_limit == 0이면 무제한 (Available_Cash만 사용).
    """
    if daily_limit > 0:
        return min(_available_cash, max(0, daily_limit - daily_spent))
    return _available_cash


# ── 1.9: 리셋 및 모드 전환 ──────────────────────────────────────────────────

def reset(initial_deposit: int) -> None:
    """전체 초기화. 예수금 리셋 + 미정산 삭제 + 타이머 취소."""
    global _available_cash, _initial_deposit, _pending_withdrawals, _timer_handles
    _available_cash = initial_deposit
    _initial_deposit = initial_deposit
    _pending_withdrawals = []
    # 모든 활성 타이머 취소
    for _, handle in _timer_handles:
        handle.cancel()
    _timer_handles = []
    _persist()
    _broadcast_delta()
    logger.info("[정산엔진] 리셋 완료 -- 초기 예수금: %s원", f"{initial_deposit:,}")


def save_state() -> None:
    """현재 상태를 파일에 저장 (모드 전환 시 호출)."""
    _persist()


def restore_state() -> None:
    """파일에서 상태 복원 (모드 전환 시 호출). 만료 항목 정리 + 타이머 재스케줄."""
    global _timer_handles
    # 기존 타이머 취소
    for _, handle in _timer_handles:
        handle.cancel()
    _timer_handles = []
    _load()


# ── 1.10: 브로드캐스트 (플레이스홀더) ───────────────────────────────────────

def _broadcast_delta() -> None:
    """
    계좌 변경 브로드캐스트. engine_service의 account-update 메커니즘 사용.
    """
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
