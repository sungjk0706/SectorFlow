"""get_daily_summary buy_total 중복 합산 회귀 테스트.

매수+매도가 같은 날 발생했을 때 pnl_rate가 정확한지 검증.
수정 전: buy_history.total_amt + sell_history.buy_total_amt 중복 합산 → pnl_rate 절반
수정 후: sell_history.buy_total_amt만 합산 → 정확한 pnl_rate
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _reset_trade_history():
    """각 테스트 전후로 trade_history 메모리 초기화."""
    from backend.app.services import trade_history
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()
    trade_history._loaded = True
    yield
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()
    trade_history._loaded = False


@pytest.mark.asyncio
async def test_daily_summary_no_duplicate_buy_total():
    """매수+매도 같은 날: pnl_rate가 realized_pnl / buy_total_amt * 100과 일치해야 함."""
    from backend.app.services import trade_history

    today = "2026-07-07"
    # 매수 기록
    trade_history._buy_history.append({
        "ts": f"{today}T09:10:00",
        "date": today,
        "time": "09:10:00",
        "side": "BUY",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "price": 70000,
        "qty": 10,
        "total_amt": 700105,
        "fee": 105,
        "tax": 0,
        "avg_buy_price": 0,
        "buy_total_amt": 0,
        "realized_pnl": 0,
        "pnl_rate": 0.0,
        "reason": "테스트",
        "trade_mode": "test",
    })
    # 매도 기록 (70000원 매수 → 69000원 매도, 10주)
    sell_total = 690000
    fee = round(sell_total * 0.00015)  # 104
    tax = round(sell_total * 0.002)    # 1380
    sell_net = sell_total - fee - tax   # 688516
    buy_total = 700000 + 105            # 700105 (매수가*수량 + 매수수수료)
    realized_pnl = sell_net - buy_total  # -11589

    trade_history._sell_history.append({
        "ts": f"{today}T10:00:00",
        "date": today,
        "time": "10:00:00",
        "side": "SELL",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "price": 69000,
        "qty": 10,
        "total_amt": sell_net,
        "fee": fee,
        "tax": tax,
        "avg_buy_price": 70000,
        "buy_total_amt": buy_total,
        "realized_pnl": realized_pnl,
        "pnl_rate": round(realized_pnl / buy_total * 100, 2),
        "reason": "손절",
        "trade_mode": "test",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="test"
        )

    today_entry = [r for r in result if r["date"] == today][0]
    expected_rate = round(realized_pnl / buy_total * 100, 2)

    assert today_entry["realized_pnl"] == realized_pnl
    assert today_entry["buy_count"] == 1
    assert today_entry["sell_count"] == 1
    # 핵심 검증: pnl_rate가 중복 합산으로 인해 절반이 되지 않아야 함
    assert today_entry["pnl_rate"] == expected_rate
    # 중복 합산이었다면 rate가 expected_rate의 절반에 가까웠을 것
    assert abs(today_entry["pnl_rate"] - expected_rate) < 0.01


@pytest.mark.asyncio
async def test_daily_summary_no_sell_zero_rate():
    """매수만 있고 매도가 없는 날: pnl_rate = 0.0 이어야 함."""
    from backend.app.services import trade_history

    today = "2026-07-07"
    trade_history._buy_history.append({
        "ts": f"{today}T09:10:00",
        "date": today,
        "time": "09:10:00",
        "side": "BUY",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "price": 70000,
        "qty": 10,
        "total_amt": 700105,
        "fee": 105,
        "tax": 0,
        "avg_buy_price": 0,
        "buy_total_amt": 0,
        "realized_pnl": 0,
        "pnl_rate": 0.0,
        "reason": "테스트",
        "trade_mode": "test",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="test"
        )

    today_entry = [r for r in result if r["date"] == today][0]
    assert today_entry["buy_count"] == 1
    assert today_entry["sell_count"] == 0
    assert today_entry["realized_pnl"] == 0
    assert today_entry["pnl_rate"] == 0.0


@pytest.mark.asyncio
async def test_daily_summary_fee_tax_aggregation():
    """get_daily_summary가 buy_fee, sell_fee, tax를 정확히 집계해야 함."""
    from backend.app.services import trade_history

    today = "2026-07-08"
    buy_fee = 105
    sell_total = 690000
    sell_fee = round(sell_total * 0.00015)  # 104
    sell_tax = round(sell_total * 0.002)    # 1380
    buy_total = 700000 + buy_fee             # 700105

    trade_history._buy_history.append({
        "ts": f"{today}T09:10:00",
        "date": today,
        "time": "09:10:00",
        "side": "BUY",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "price": 70000,
        "qty": 10,
        "total_amt": 700105,
        "fee": buy_fee,
        "tax": 0,
        "avg_buy_price": 0,
        "buy_total_amt": 0,
        "realized_pnl": 0,
        "pnl_rate": 0.0,
        "reason": "테스트",
        "trade_mode": "test",
    })
    trade_history._sell_history.append({
        "ts": f"{today}T10:00:00",
        "date": today,
        "time": "10:00:00",
        "side": "SELL",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "price": 69000,
        "qty": 10,
        "total_amt": sell_total - sell_fee - sell_tax,
        "fee": sell_fee,
        "tax": sell_tax,
        "avg_buy_price": 70000,
        "buy_total_amt": buy_total,
        "realized_pnl": -11589,
        "pnl_rate": -1.66,
        "reason": "손절",
        "trade_mode": "test",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="test"
        )

    entry = [r for r in result if r["date"] == today][0]
    assert entry["buy_fee"] == buy_fee
    assert entry["sell_fee"] == sell_fee
    assert entry["tax"] == sell_tax


@pytest.mark.asyncio
async def test_daily_summary_no_sell_zero_fee_tax():
    """매도가 없는 날: buy_fee만 집계되고 sell_fee/tax는 0이어야 함."""
    from backend.app.services import trade_history

    today = "2026-07-08"
    buy_fee = 105

    trade_history._buy_history.append({
        "ts": f"{today}T09:10:00",
        "date": today,
        "time": "09:10:00",
        "side": "BUY",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "price": 70000,
        "qty": 10,
        "total_amt": 700105,
        "fee": buy_fee,
        "tax": 0,
        "avg_buy_price": 0,
        "buy_total_amt": 0,
        "realized_pnl": 0,
        "pnl_rate": 0.0,
        "reason": "테스트",
        "trade_mode": "test",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="test"
        )

    entry = [r for r in result if r["date"] == today][0]
    assert entry["buy_fee"] == buy_fee
    assert entry["sell_fee"] == 0
    assert entry["tax"] == 0
