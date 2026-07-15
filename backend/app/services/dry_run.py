# -*- coding: utf-8 -*-
"""
Dry-Run 모듈 — 테스트모드 전용 가상 체결 엔진 + 영속 잔고.

책임:
  1. fake_send_order()  — 키움 send_order 응답과 동일한 구조의 가짜 체결 반환
  2. _test_positions     — 가상 잔고 (trades 테이블 기반 파생, 인메모리 캐시)
  3. update_price()      — 0B 틱으로 가상 잔고 현재가/수익률 갱신
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging
from backend.app.core.settings_file import update_settings
from backend.app.services import settlement_engine
logger = logging.getLogger(__name__)

# ── 가상 잔고 (trades 기반 파생 캐시 — SSOT: trade_history) ────────────────
# key: stk_cd (서버 수신 형식 그대로), value: dict (kt00018 응답 필드와 동일 구조)
# _test_positions는 trade_history.build_positions_from_trades()의 파생 캐시이다.
# record_buy/record_sell이 _insert_trade에서 _positions_dirty=True로 설정하면,
# 다음 get_positions() 호출 시 build_positions_from_trades()로 재구축된다.
# cur_price/stk_nm 등 비파생 필드는 재구축 시 기존 캐시에서 보존된다.
_test_positions: dict[str, dict] = {}
_positions_loaded: bool = False
_positions_dirty: bool = True   # 최초 로드 필요

# 가짜 주문번호 시퀀스
_fake_order_seq: int = 9_000_000

# ── 가상 예수금 ──────────────────────────────────────────────────────────────
# Settlement Engine으로 위임 (settlement_engine.py)


# ── 포지션 캐시 재구축 ──────────────────────────────────────────────────────

async def _refresh_positions_if_dirty() -> None:
    """_positions_dirty가 True면 trade_history.build_positions_from_trades()로 재구축.

    SSOT: trade_history._buy_history/_sell_history가 유일한 진실 원천.
    _test_positions는 파생 캐시이며, record_buy/record_sell 후 무효화된다.
    재구축 시 cur_price/stk_nm 등 비파생 필드는 기존 캐시에서 보존된다.
    재구축 실패 시 _positions_dirty를 True로 유지하여 다음 호출에서 재시도한다.
    """
    global _positions_loaded, _positions_dirty
    if _positions_loaded and not _positions_dirty:
        return
    _positions_loaded = True
    from backend.app.services import trade_history
    computed = await trade_history.build_positions_from_trades("test")
    # 비파생 필드 보존: cur_price, change, change_rate, bid_depth, ask_depth, stk_nm
    _preserve_fields = ("cur_price", "change", "change_rate", "bid_depth", "ask_depth")
    for cd, new_pos in computed.items():
        old = _test_positions.get(cd)
        if old:
            for f in _preserve_fields:
                if old.get(f) is not None:
                    new_pos[f] = old[f]
            # stk_nm: 기존 캐시에 있고 새 값이 비어있으면 보존
            if old.get("stk_nm") and not new_pos.get("stk_nm"):
                new_pos["stk_nm"] = old["stk_nm"]
        _recalc_pnl(new_pos)
    _test_positions.clear()
    _test_positions.update(computed)
    _positions_dirty = False
    logger.info("[매매] 포지션 캐시 재구축 — %d종목", len(_test_positions))


def _next_fake_order_no() -> str:
    global _fake_order_seq
    _fake_order_seq += 1
    return str(_fake_order_seq)


# ── 1. 가짜 체결 응답 ───────────────────────────────────────────────────────

FAKE_FILL_DELAY: float = 0.1  # 초

# ── 호가단위 / 슬리피지 ──────────────────────────────────────────────────────

SLIPPAGE_TICKS: int = 1  # 시장가 주문 슬리피지 (틱 단위)

_TICK_TABLE: tuple[tuple[int, int], ...] = (
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (999_999_999, 500),
)


def _tick_size(price: int) -> int:
    """한국 증시 호가단위 (가격대별 틱 사이즈)."""
    for threshold, tick in _TICK_TABLE:
        if price < threshold:
            return tick
    return 500


def _apply_slippage(price: int, side: str, ticks: int = SLIPPAGE_TICKS) -> int:
    """시장가 주문 슬리피지 적용. 매수: +N틱, 매도: -N틱. price <= 0이면 그대로 반환."""
    if price <= 0:
        return price
    tick = _tick_size(price)
    if side.upper() == "BUY":
        return price + tick * ticks
    return max(tick, price - tick * ticks)


def estimate_fill_price(price: int, side: str) -> int:
    """테스트모드 시장가 주문 예상 체결가 (슬리피지 적용).

    trading.py에서 주문 전 수량/예수금 계산에 사용 — fake_fill_event 내부 슬리피지와 동일 로직.
    """
    return _apply_slippage(price, side)


async def fake_send_order(
    settings: dict,
    access_token: str,
    order_type: str,       # "BUY" | "SELL"
    code: str,
    qty: int,
    price: int = 0,
    trde_tp: str = "3",
) -> dict:
    """키움 send_order()와 동일한 반환 구조. 주문 접수만 (체결은 fake_fill_event에서).

    호출자(trading.py)는 항상 price > 0을 보장한다 (order_price 또는 current_price).
    """
    order_no = _next_fake_order_no()
    side = order_type.upper()
    logger.info(
        "[매매] %s 주문 접수 %s %d주 @%s 주문번호=%s",
        side, code, qty, f"{price:,}" if price else "시장가", order_no,
    )
    return {
        "success": True,
        "msg": "[매매] 가상 주문 접수 완료",
        "data": {
            "rt_cd": "0",
            "msg1": "[매매] 가상 주문 접수 완료",
            "output": {
                "ord_no": order_no,
                "stk_cd": str(code),
                "ord_qty": str(qty),
                "ord_uv": str(price),
            },
        },
    }


async def fake_fill_event(
    order_type: str,
    code: str,
    qty: int,
    price: int,
    stk_nm: str = "",
) -> None:
    """
    테스트모드 가상 체결 이벤트 — 실전 WS "00" 이벤트와 동일한 downstream 호출 체인.
    1. _apply_buy/_apply_sell (포지션 + Settlement Engine)
    2. on_fill_update (has_open_buy 해제, _recent_sells 해제, 로그/텔레그램)
    3. _on_fill_after_ws (계좌 갱신, 매도 조건 검사)
    """
    from backend.app.services.engine_state import state
    from backend.app.services import engine_account

    await asyncio.sleep(FAKE_FILL_DELAY)

    side = order_type.upper()
    fill_price = _apply_slippage(price, side)

    # 1. 가상 체결 (포지션 + Settlement Engine)
    if side == "BUY":
        await _apply_buy(code, qty, fill_price)
        if stk_nm:
            await set_stock_name(code, stk_nm)
    elif side == "SELL":
        await _apply_sell(code, qty, fill_price)

    logger.info(
        "[매매] 가상 체결 완료 %s %s %d주 @%s",
        side, code, qty, f"{fill_price:,}" if fill_price else "시장가",
    )

    # 2. on_fill_update (실전 _handle_real_00과 동일)
    #    side: "1"=매수, "2"=매도, unex=0 (전량 체결)
    ws_side = "1" if side == "BUY" else "2"
    if state.auto_trade:
        await state.auto_trade.on_fill_update(code, ws_side, 0, state.access_token)

    # 3. _on_fill_after_ws (실전 _handle_real_00과 동일)
    await engine_account._on_fill_after_ws()


# ── 2. 인메모리 잔고 관리 ───────────────────────────────────────────────────

async def _apply_buy(code: str, qty: int, price: int) -> None:
    """매수 체결 -> Settlement Engine 예수금 차감만 수행.

    _test_positions는 record_buy → 캐시 무효화 → get_positions() 시
    build_positions_from_trades()로 재구축되므로 여기서 직접 수정하지 않는다.
    """
    await settlement_engine.on_buy_fill(price, qty)

async def _apply_sell(code: str, qty: int, price: int) -> None:
    """매도 체결 -> Settlement Engine 매도 정산만 수행.

    _test_positions는 record_sell → 캐시 무효화 → get_positions() 시
    build_positions_from_trades()로 재구축되므로 여기서 직접 수정하지 않는다.
    """
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    norm_code = _base_stk_cd(code)
    await _refresh_positions_if_dirty()
    stk_nm = _test_positions.get(norm_code, {}).get("stk_nm", "")
    await settlement_engine.on_sell_fill(price, qty, norm_code, stk_nm)

def _recalc_pnl(pos: dict) -> None:
    """현재가 기준 손익 재계산 (순수 차익: 수수료/세금 제외)."""
    avg = int(pos.get("avg_price", 0))
    cur = int(pos.get("cur_price") or avg)
    qty = int(pos.get("qty", 0))
    total_fee = int(pos.get("total_fee", 0))
    buy_amount = avg * qty
    pos["buy_amount"] = buy_amount
    pos["buy_amt"] = buy_amount + total_fee
    pos["eval_amt"] = cur * qty
    pos["pnl_amount"] = pos["eval_amt"] - buy_amount
    pos["pnl_rate"] = round((pos["pnl_amount"] / buy_amount) * 100, 2) if buy_amount > 0 else 0.0


# ── 3. 실시간 시세 연동 ─────────────────────────────────────────────────────

async def update_price(code: str, price: int) -> bool:
    """
    0B 틱 수신 시 호출 — 가상 잔고의 현재가/수익률 갱신.
    반환: True=가격 변경됨, False=해당 종목 미보유 또는 가격 동일
    """
    from backend.app.services.engine_symbol_utils import _base_stk_cd

    await _refresh_positions_if_dirty()
    norm_code = _base_stk_cd(code)
    pos = _test_positions.get(norm_code)
    if not pos:
        return False
    cur_price = pos.get("cur_price")
    if cur_price is not None and int(cur_price) == price:
        return False  # 가격 변경 없음 — 재계산 스킵
    pos["cur_price"] = price
    _recalc_pnl(pos)
    return True


async def set_stock_name(code: str, name: str) -> None:
    """종목명 세팅 (매수 시점에 이름을 모를 수 있으므로 별도 호출).

    build_positions_from_trades가 _buy_history에서 stk_nm을 가져오므로,
    record_buy에 stk_nm이 정확히 전달되면 이 함수는 보조 역할만 한다.
    캐시 재구축 후에도 stk_nm이 보존되도록 _refresh_positions_if_dirty에서 처리한다.
    """
    from backend.app.services.engine_symbol_utils import _base_stk_cd

    await _refresh_positions_if_dirty()
    norm_code = _base_stk_cd(code)
    pos = _test_positions.get(norm_code)
    if pos:
        pos["stk_nm"] = name


# ── 4. 조회 헬퍼 ────────────────────────────────────────────────────────────

async def get_positions() -> list[dict]:
    """engine_service가 잔고 목록으로 사용할 수 있는 리스트 반환.

    _positions_dirty가 True면 build_positions_from_trades로 재구축 후 반환.
    """
    await _refresh_positions_if_dirty()
    return list(_test_positions.values())


async def get_position(code: str) -> Optional[dict]:
    from backend.app.services.engine_symbol_utils import _base_stk_cd

    await _refresh_positions_if_dirty()
    norm_code = _base_stk_cd(code)
    return _test_positions.get(norm_code)


async def has_position(code: str) -> bool:
    from backend.app.services.engine_symbol_utils import _base_stk_cd

    await _refresh_positions_if_dirty()
    norm_code = _base_stk_cd(code)
    pos = _test_positions.get(norm_code)
    return pos is not None and int(pos.get("qty", 0)) > 0


async def position_codes() -> set[str]:
    await _refresh_positions_if_dirty()
    return {cd for cd, p in _test_positions.items() if int(p.get("qty", 0)) > 0}


async def clear() -> None:
    """가상 포지션만 초기화 (예수금은 건드리지 않음 — 사용자 직접 초기화만 허용)."""
    global _positions_loaded, _positions_dirty
    _test_positions.clear()
    _positions_loaded = True
    _positions_dirty = False


# ── 5. 가상 예수금 관리 ─────────────────────────────────────────────────────

async def set_virtual_deposit(amount: int) -> None:
    """가상 예수금 설정값 저장."""
    await update_settings({
        "test_virtual_deposit": amount,
        "test_virtual_balance": amount,
    })
    logger.info("[매매] 가상 예수금 설정: %s원", f"{amount:,}")
