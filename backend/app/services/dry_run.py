# -*- coding: utf-8 -*-
"""
Dry-Run 모듈 -- 테스트모드 전용 가상 체결 엔진 + 영속 잔고.

책임:
  1. fake_send_order()  -- 키움 send_order 응답과 동일한 구조의 가짜 체결 반환
  2. _test_positions     -- 가상 잔고 (data/test_positions.json 에 영속)
  3. update_price()      -- 0B 틱으로 가상 잔고 현재가/수익률 갱신
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from app.core.settings_file import load_settings, update_settings
from app.services import settlement_engine

logger = logging.getLogger(__name__)

# ── 가상 잔고 (파일 영속) ───────────────────────────────────────────────────
# key: stk_cd (6자리 정규화), value: dict (kt00018 응답 필드와 동일 구조)
_test_positions: dict[str, dict] = {}
_positions_loaded: bool = False

_POSITIONS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "test_positions.json"

# 가짜 주문번호 시퀀스
_fake_order_seq: int = 9_000_000

# ── 가상 예수금 ──────────────────────────────────────────────────────────────
# Settlement Engine으로 위임 (settlement_engine.py)


# ── 포지션 파일 저장/로드 ────────────────────────────────────────────────────

def _save_positions(data: dict[str, dict] | None = None) -> None:
    """가상 포지션을 JSON 파일에 저장. data가 주어지면 스냅샷을 저장."""
    to_save = data if data is not None else _test_positions
    try:
        _POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_POSITIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("[테스트모드] 가상보유종목.json 저장 실패: %s", e)


def _load_positions() -> None:
    """JSON 파일에서 가상 포지션 복원."""
    global _positions_loaded
    if _positions_loaded:
        return
    _positions_loaded = True
    if not _POSITIONS_PATH.is_file():
        return
    try:
        with open(_POSITIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _test_positions.update(data)
            logger.info("[테스트모드] 가상보유종목 복원 -- %d종목", len(_test_positions))
    except Exception as e:
        logger.warning("[테스트모드] 가상보유종목.json 로드 실패: %s", e)


_pos_save_pending: bool = False
_pos_save_running: bool = False
_pos_lock = threading.Lock()


def _schedule_save_positions() -> None:
    """포지션 파일 저장을 asyncio 스레드풀로 위임. 동시 실행 방지 (coalesce)."""
    global _pos_save_pending, _pos_save_running
    with _pos_lock:
        _pos_save_pending = True
        if _pos_save_running:
            return
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _coalesced_save_positions)
    except RuntimeError:
        with _pos_lock:
            _pos_save_pending = False
        _save_positions()


def _coalesced_save_positions() -> None:
    """pending 플래그가 True인 동안 반복 저장. 동시 실행 1개 보장."""
    global _pos_save_pending, _pos_save_running
    with _pos_lock:
        _pos_save_running = True
    try:
        while True:
            with _pos_lock:
                if not _pos_save_pending:
                    break
                _pos_save_pending = False
                snapshot = dict(_test_positions)
            _save_positions(snapshot)
    finally:
        with _pos_lock:
            _pos_save_running = False


def _next_fake_order_no() -> str:
    global _fake_order_seq
    _fake_order_seq += 1
    return str(_fake_order_seq)


# ── 1. 가짜 체결 응답 ───────────────────────────────────────────────────────

FAKE_FILL_DELAY: float = 0.1  # 초


async def fake_send_order(
    settings: dict,
    access_token: str,
    order_type: str,       # "BUY" | "SELL"
    code: str,
    qty: int,
    price: int = 0,
    trde_tp: str = "3",
) -> dict:
    """
    키움 send_order()와 동일한 반환 구조.
    0.1초 후 무조건 성공 응답 + 가상 잔고 반영.
    """
    await asyncio.sleep(FAKE_FILL_DELAY)

    order_no = _next_fake_order_no()
    fill_price = price if price > 0 else _estimate_market_price(code)

    side = order_type.upper()
    if side == "BUY":
        _apply_buy(code, qty, fill_price)
    elif side == "SELL":
        _apply_sell(code, qty, fill_price)

    logger.info(
        "[테스트모드] %s %s %d주 @%s -> 가상체결 ord_no=%s",
        side, code, qty, f"{fill_price:,}" if fill_price else "시장가", order_no,
    )

    return {
        "success": True,
        "msg": "[테스트모드] 가상 체결 완료",
        "data": {
            "rt_cd": "0",
            "msg1": "[테스트모드] 가상 체결 완료",
            "output": {
                "ord_no": order_no,
                "stk_cd": str(code),
                "ord_qty": str(qty),
                "ord_uv": str(fill_price),
            },
        },
    }


def fake_send_order_sync(
    settings: dict,
    access_token: str,
    order_type: str,
    code: str,
    qty: int,
    price: int = 0,
    trde_tp: str = "3",
) -> dict:
    """
    동기 버전 -- trading.py의 execute_buy/execute_sell은 동기 함수이므로
    이벤트 루프 없이 즉시 반환.
    """
    order_no = _next_fake_order_no()
    fill_price = price if price > 0 else _estimate_market_price(code)

    side = order_type.upper()
    if side == "BUY":
        _apply_buy(code, qty, fill_price)
    elif side == "SELL":
        _apply_sell(code, qty, fill_price)

    logger.info(
        "[테스트모드] %s %s %d주 @%s -> 가상체결 ord_no=%s",
        side, code, qty, f"{fill_price:,}" if fill_price else "시장가", order_no,
    )

    return {
        "success": True,
        "msg": "[테스트모드] 가상 체결 완료",
        "data": {
            "rt_cd": "0",
            "msg1": "[테스트모드] 가상 체결 완료",
            "output": {
                "ord_no": order_no,
                "stk_cd": str(code),
                "ord_qty": str(qty),
                "ord_uv": str(fill_price),
            },
        },
    }


# ── 2. 인메모리 잔고 관리 ───────────────────────────────────────────────────

def _apply_buy(code: str, qty: int, price: int) -> None:
    """매수 체결 -> 가상 잔고에 추가/증가 + Settlement Engine 예수금 차감."""
    _load_positions()
    settlement_engine.on_buy_fill(price, qty)
    fee = round(price * qty * 0.00015)  # 포지션 추적용 수수료
    pos = _test_positions.get(code)
    if pos:
        old_qty = int(pos.get("qty", 0))
        old_avg = int(pos.get("avg_price", 0))
        old_fee = int(pos.get("total_fee", 0))
        new_qty = old_qty + qty
        new_avg = ((old_avg * old_qty) + (price * qty)) // new_qty if new_qty > 0 else price
        pos["qty"] = new_qty
        pos["avg_price"] = new_avg
        pos["total_fee"] = old_fee + fee
        pos["buy_amt"] = new_avg * new_qty + pos["total_fee"]
    else:
        _test_positions[code] = {
            "stk_cd": code,
            "stk_nm": "",       # 외부에서 set_stock_name()으로 채움
            "qty": qty,
            "avg_price": price,
            "cur_price": price,
            "total_fee": fee,
            "buy_amt": price * qty + fee,
            "eval_amt": price * qty,
            "pnl_amount": -(fee),
            "pnl_rate": 0.0,
        }
    _schedule_save_positions()


def _apply_sell(code: str, qty: int, price: int) -> None:
    """매도 체결 -> 가상 잔고에서 차감 + Settlement Engine 매도 정산. 수량 0이면 제거."""
    _load_positions()
    stk_nm = _test_positions.get(code, {}).get("stk_nm", "")
    settlement_engine.on_sell_fill(price, qty, code, stk_nm)
    pos = _test_positions.get(code)
    if not pos:
        logger.warning("[테스트모드] 매도 요청했으나 가상 잔고에 %s 없음", code)
        return
    old_qty = int(pos.get("qty", 0))
    new_qty = max(0, old_qty - qty)
    if new_qty == 0:
        _test_positions.pop(code, None)
    else:
        pos["qty"] = new_qty
        avg = int(pos.get("avg_price", 0))
        pos["buy_amt"] = avg * new_qty
        pos["eval_amt"] = int(pos.get("cur_price") or avg) * new_qty
        _recalc_pnl(pos)
    _schedule_save_positions()


def _recalc_pnl(pos: dict) -> None:
    """현재가 기준 손익 재계산 (매수금액=수수료 포함)."""
    avg = int(pos.get("avg_price", 0))
    cur = int(pos.get("cur_price") or avg)
    qty = int(pos.get("qty", 0))
    total_fee = int(pos.get("total_fee", 0))
    pos["eval_amt"] = cur * qty
    pos["buy_amt"] = avg * qty + total_fee
    pos["pnl_amount"] = pos["eval_amt"] - pos["buy_amt"]
    pos["pnl_rate"] = round((pos["pnl_amount"] / pos["buy_amt"]) * 100, 2) if pos["buy_amt"] > 0 else 0.0


# ── 3. 실시간 시세 연동 ─────────────────────────────────────────────────────

def update_price(code: str, price: int) -> bool:
    """
    0B 틱 수신 시 호출 -- 가상 잔고의 현재가/수익률 갱신.
    반환: True=가격 변경됨, False=해당 종목 미보유 또는 가격 동일
    """
    _load_positions()
    pos = _test_positions.get(code)
    if not pos:
        return False
    cur_price = pos.get("cur_price")
    if cur_price is not None and int(cur_price) == price:
        return False  # 가격 변경 없음 — 재계산 스킵
    pos["cur_price"] = price
    _recalc_pnl(pos)
    return True


def set_stock_name(code: str, name: str) -> None:
    """종목명 세팅 (매수 시점에 이름을 모를 수 있으므로 별도 호출)."""
    pos = _test_positions.get(code)
    if pos:
        pos["stk_nm"] = name
        _schedule_save_positions()


# ── 4. 조회 헬퍼 ────────────────────────────────────────────────────────────

def get_positions() -> list[dict]:
    """engine_service가 잔고 목록으로 사용할 수 있는 리스트 반환."""
    _load_positions()
    return list(_test_positions.values())


def get_position(code: str) -> Optional[dict]:
    _load_positions()
    return _test_positions.get(code)


def has_position(code: str) -> bool:
    _load_positions()
    pos = _test_positions.get(code)
    return pos is not None and int(pos.get("qty", 0)) > 0


def position_codes() -> set[str]:
    _load_positions()
    return {cd for cd, p in _test_positions.items() if int(p.get("qty", 0)) > 0}


def clear() -> None:
    """가상 포지션만 초기화 (예수금은 건드리지 않음 -- 사용자 직접 초기화만 허용)."""
    global _positions_loaded
    _test_positions.clear()
    _positions_loaded = True
    _schedule_save_positions()


def _estimate_market_price(code: str) -> int:
    """시장가 주문 시 현재가 추정 -- 가상 잔고에 있으면 그 값, 없으면 0."""
    pos = _test_positions.get(code)
    if pos:
        return int(pos.get("cur_price", 0))
    return 0


# ── 5. 가상 예수금 관리 ─────────────────────────────────────────────────────

def get_virtual_balance() -> int:
    """현재 가상 예수금 잔액 반환 (Settlement Engine 위임)."""
    return settlement_engine.get_available_cash()


def get_virtual_deposit_setting() -> int:
    """설정된 가상 예수금 초기값 반환."""
    s = load_settings()
    return int(s.get("test_virtual_deposit", 10_000_000) or 0)


def set_virtual_deposit(amount: int) -> None:
    """가상 예수금 설정값 저장 + 현재 잔액도 동일하게 리셋."""
    update_settings({
        "test_virtual_deposit": amount,
        "test_virtual_balance": amount,
    })
    settlement_engine.reset(amount)
    logger.info("[테스트모드] 가상 예수금 설정: %s원 (잔액도 리셋)", f"{amount:,}")


def reset_virtual_balance() -> None:
    """현재 가상 예수금 잔액을 설정값(초기값)으로 리셋 (Settlement Engine 위임)."""
    deposit = get_virtual_deposit_setting()
    settlement_engine.reset(deposit)
    update_settings({"test_virtual_balance": deposit})
    logger.info("[테스트모드] 가상 예수금 잔액 초기화: %s원", f"{deposit:,}")


def charge_virtual_balance(amount: int) -> int:
    """가상 예수금 충전 (Settlement Engine 위임). 반환: 충전 후 잔액."""
    result = settlement_engine.charge(amount)
    logger.info("[테스트모드] 가상 예수금 충전 %s원 -> 잔액 %s원", f"{amount:,}", f"{result:,}")
    return result
