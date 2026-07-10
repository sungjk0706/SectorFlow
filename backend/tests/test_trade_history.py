"""trade_history.py 단위 테스트.

기존: get_daily_summary buy_total 중복 합산 회귀 테스트 4건
추가: _ensure_loaded, _insert_trade, _trim_expired, _patch_sell_history,
      record_buy, record_sell, _calc_avg_buy_price, _lookup_sector,
      get_buy/sell_history, get_total_realized_pnl, get_daily_summary 확장,
      clear_test_history, build_positions_from_trades, get_earliest_buy_date,
      _reset_global_state, start/stop_consumer_task, 브로드캐스트 함수들
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


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────

def _make_buy_rec(
    stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
    date="2026-07-08", time="09:10:00", fee=105, trade_mode="test",
    reason="테스트",
):
    total_amt = price * qty
    return {
        "ts": f"{date}T{time}", "date": date, "time": time, "side": "BUY",
        "stk_cd": stk_cd, "stk_nm": stk_nm, "price": price, "qty": qty,
        "total_amt": total_amt + fee, "fee": fee, "tax": 0,
        "avg_buy_price": 0, "buy_total_amt": 0, "realized_pnl": 0,
        "pnl_rate": 0.0, "reason": reason, "trade_mode": trade_mode,
    }


def _make_sell_rec(
    stk_cd="005930", stk_nm="삼성전자", price=69000, qty=10,
    date="2026-07-08", time="10:00:00", avg_buy_price=70000,
    trade_mode="test", reason="손절", sector=None,
):
    total_amt = price * qty
    fee = round(total_amt * 0.00015) if trade_mode == "test" else 0
    tax = round(total_amt * 0.002) if trade_mode == "test" else 0
    sell_net = total_amt - fee - tax
    buy_fee = round(avg_buy_price * qty * 0.00015) if trade_mode == "test" and avg_buy_price > 0 else 0
    buy_total = avg_buy_price * qty + buy_fee if avg_buy_price > 0 else 0
    realized_pnl = sell_net - buy_total if avg_buy_price > 0 else 0
    rec = {
        "ts": f"{date}T{time}", "date": date, "time": time, "side": "SELL",
        "stk_cd": stk_cd, "stk_nm": stk_nm, "price": price, "qty": qty,
        "total_amt": sell_net, "fee": fee, "tax": tax,
        "avg_buy_price": avg_buy_price, "buy_total_amt": buy_total,
        "realized_pnl": realized_pnl,
        "pnl_rate": round(realized_pnl / buy_total * 100, 2) if buy_total > 0 else 0.0,
        "reason": reason, "trade_mode": trade_mode,
    }
    if sector is not None:
        rec["sector"] = sector
    return rec


# ── _ensure_loaded ────────────────────────────────────────────────────────────

class TestEnsureLoaded:
    """_ensure_loaded: 최초 1회만 DB → 메모리 로드."""

    async def test_first_load_sets_loaded_true(self):
        from backend.app.services import trade_history
        trade_history._loaded = False
        mock_conn = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchall.return_value = []
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_conn.execute.return_value = mock_cm
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with patch("backend.app.services.trade_history._history_lock"):
                with patch("backend.app.services.trade_history._trim_expired", new_callable=AsyncMock):
                    await trade_history._ensure_loaded()
        assert trade_history._loaded is True

    async def test_already_loaded_skips_db(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        with patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock) as mock_conn:
            await trade_history._ensure_loaded()
        mock_conn.assert_not_called()

    async def test_db_failure_logs_warning(self):
        from backend.app.services import trade_history
        trade_history._loaded = False
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB not found")
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with patch("backend.app.services.trade_history._history_lock"):
                await trade_history._ensure_loaded()
        assert trade_history._loaded is True
        assert len(trade_history._buy_history) == 0
        assert len(trade_history._sell_history) == 0


# ── _insert_trade ─────────────────────────────────────────────────────────────

class TestInsertTrade:
    """_insert_trade: 메모리 추가 + dry_run 캐시 무효화 + DB 비동기 저장."""

    async def test_buy_inserted_at_front(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        rec = _make_buy_rec()
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                await trade_history._insert_trade(rec)
        assert trade_history._buy_history[0] == rec

    async def test_sell_inserted_at_front(self):
        from backend.app.services import trade_history
        trade_history._sell_history.clear()
        rec = _make_sell_rec()
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                await trade_history._insert_trade(rec)
        assert trade_history._sell_history[0] == rec

    async def test_invalidates_dry_run_cache(self):
        from backend.app.services import trade_history
        from backend.app.services import dry_run
        dry_run._positions_dirty = False
        rec = _make_buy_rec()
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                await trade_history._insert_trade(rec)
        assert dry_run._positions_dirty is True

    async def test_db_failure_keeps_memory(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        rec = _make_buy_rec()
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock, side_effect=Exception("DB error")):
                await trade_history._insert_trade(rec)
        assert trade_history._buy_history[0] == rec


# ── _trim_expired ─────────────────────────────────────────────────────────────

class TestTrimExpired:
    """_trim_expired: 모드별 보관 기한 초과 레코드 제거 (메모리 + DB)."""

    async def test_test_mode_125_days_expired(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        old_rec = _make_buy_rec(date="2025-12-01", trade_mode="test")
        recent_rec = _make_buy_rec(date="2026-07-08", trade_mode="test")
        trade_history._buy_history.extend([old_rec, recent_rec])
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.core.trading_calendar.get_recent_trading_days") as mock_days:
                with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock) as mock_db:
                    from datetime import date as d
                    mock_days.return_value = [d(2026, 3, 1)]
                    await trade_history._trim_expired()
        dates = [r["date"] for r in trade_history._buy_history]
        assert "2026-07-08" in dates
        assert "2025-12-01" not in dates
        assert mock_db.call_count == 2  # test + real DB 삭제

    async def test_real_mode_90_days_preserved(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        real_rec = _make_buy_rec(date="2026-05-01", trade_mode="real")
        trade_history._buy_history.append(real_rec)
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.core.trading_calendar.get_recent_trading_days") as mock_days:
                with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                    from datetime import date as d
                    mock_days.return_value = [d(2026, 4, 1)]
                    await trade_history._trim_expired()
        assert real_rec in trade_history._buy_history

    async def test_trim_exception_logged(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._buy_history.append(_make_buy_rec())
        with patch("backend.app.core.trading_calendar.get_recent_trading_days", side_effect=Exception("cal error")):
            await trade_history._trim_expired()
        assert len(trade_history._buy_history) == 1


# ── _patch_sell_history ───────────────────────────────────────────────────────

class TestPatchSellHistory:
    """_patch_sell_history: avg_buy_price=0인 매도 건 실현손익 보정."""

    async def test_patches_zero_avg_buy_price(self):
        from backend.app.services import trade_history
        trade_history._sell_history.clear()
        trade_history._buy_history.clear()
        trade_history._buy_history.append(_make_buy_rec(price=70000, qty=10))
        sell_rec = _make_sell_rec(price=69000, qty=10, avg_buy_price=0)
        trade_history._sell_history.append(sell_rec)
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._calc_avg_buy_price", new_callable=AsyncMock, return_value=70000):
                await trade_history._patch_sell_history()
        assert trade_history._sell_history[0]["avg_buy_price"] == 70000
        assert trade_history._sell_history[0]["realized_pnl"] != 0

    async def test_skips_when_avg_le_zero(self):
        from backend.app.services import trade_history
        trade_history._sell_history.clear()
        sell_rec = _make_sell_rec(avg_buy_price=0)
        trade_history._sell_history.append(sell_rec)
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._calc_avg_buy_price", new_callable=AsyncMock, return_value=0):
                await trade_history._patch_sell_history()
        assert trade_history._sell_history[0]["avg_buy_price"] == 0

    async def test_normal_records_unchanged(self):
        from backend.app.services import trade_history
        trade_history._sell_history.clear()
        sell_rec = _make_sell_rec(avg_buy_price=70000)
        trade_history._sell_history.append(sell_rec)
        original_pnl = sell_rec["realized_pnl"]
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._calc_avg_buy_price", new_callable=AsyncMock, return_value=70000):
                await trade_history._patch_sell_history()
        assert trade_history._sell_history[0]["realized_pnl"] == original_pnl


# ── _trade_params ─────────────────────────────────────────────────────────────

class TestTradeParams:
    """_trade_params: 17필드 튜플 순서 검증."""

    def test_params_order(self):
        from backend.app.services import trade_history
        rec = _make_buy_rec()
        params = trade_history._trade_params(rec)
        assert params == (
            rec["ts"], rec["date"], rec["time"], rec["side"],
            rec["stk_cd"], rec["stk_nm"], rec["price"], rec["qty"],
            rec["total_amt"], rec["fee"], rec["tax"],
            rec["avg_buy_price"], rec["buy_total_amt"],
            rec["realized_pnl"], rec["pnl_rate"],
            rec["reason"], rec["trade_mode"],
        )
        assert len(params) == 17


# ── _migrate_from_json ────────────────────────────────────────────────────────

class TestMigrateFromJson:
    """_migrate_from_json: no-op 확인."""

    async def test_migrate_is_noop(self):
        from backend.app.services import trade_history
        await trade_history._migrate_from_json()  # 예외 없이 완료되어야 함


# ── record_buy ────────────────────────────────────────────────────────────────

class TestRecordBuy:
    """record_buy: 매수 체결 기록 + 브로드캐스트."""

    async def test_returns_correct_record(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_buy_append", new_callable=AsyncMock):
                    rec = await trade_history.record_buy(
                        stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
                        reason="테스트", trade_mode="test",
                    )
        assert rec["side"] == "BUY"
        assert rec["stk_cd"] == "005930"
        assert rec["price"] == 70000
        assert rec["qty"] == 10
        assert rec["total_amt"] == 700000 + 105  # price*qty + fee

    async def test_test_mode_fee_calculated(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_buy_append", new_callable=AsyncMock):
                    rec = await trade_history.record_buy(
                        stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
                        trade_mode="test",
                    )
        assert rec["fee"] == round(700000 * 0.00015)

    async def test_real_mode_fee_zero(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_buy_append", new_callable=AsyncMock):
                    rec = await trade_history.record_buy(
                        stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
                        trade_mode="real",
                    )
        assert rec["fee"] == 0

    async def test_broadcast_called(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_buy_append", new_callable=AsyncMock) as mock_bc:
                    await trade_history.record_buy(
                        stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
                    )
        mock_bc.assert_called_once()


# ── record_sell ───────────────────────────────────────────────────────────────

class TestRecordSell:
    """record_sell: 매도 체결 기록 + 실현손익 자동 계산."""

    async def test_realized_pnl_calculated(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_sell_append", new_callable=AsyncMock):
                    with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, return_value="반도체"):
                        rec = await trade_history.record_sell(
                            stk_cd="005930", stk_nm="삼성전자", price=71000, qty=10,
                            avg_buy_price=70000, trade_mode="test",
                        )
        assert rec["realized_pnl"] > 0
        assert rec["pnl_rate"] > 0

    async def test_zero_avg_buy_price_safety(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_sell_append", new_callable=AsyncMock):
                    with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, return_value="미분류"):
                        rec = await trade_history.record_sell(
                            stk_cd="005930", stk_nm="삼성전자", price=71000, qty=10,
                            avg_buy_price=0, trade_mode="test",
                        )
        assert rec["realized_pnl"] == 0
        assert rec["pnl_rate"] == 0.0

    async def test_test_mode_fee_tax(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_sell_append", new_callable=AsyncMock):
                    with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, return_value="미분류"):
                        rec = await trade_history.record_sell(
                            stk_cd="005930", stk_nm="삼성전자", price=71000, qty=10,
                            avg_buy_price=70000, trade_mode="test",
                        )
        assert rec["fee"] == round(710000 * 0.00015)
        assert rec["tax"] == round(710000 * 0.002)

    async def test_real_mode_fee_tax_zero(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_sell_append", new_callable=AsyncMock):
                    with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, return_value="미분류"):
                        rec = await trade_history.record_sell(
                            stk_cd="005930", stk_nm="삼성전자", price=71000, qty=10,
                            avg_buy_price=70000, trade_mode="real",
                        )
        assert rec["fee"] == 0
        assert rec["tax"] == 0

    async def test_sector_included(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_sell_append", new_callable=AsyncMock):
                    with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, return_value="반도체"):
                        rec = await trade_history.record_sell(
                            stk_cd="005930", stk_nm="삼성전자", price=71000, qty=10,
                            avg_buy_price=70000, trade_mode="test",
                        )
        assert rec["sector"] == "반도체"


# ── _calc_avg_buy_price ───────────────────────────────────────────────────────

class TestCalcAvgBuyPrice:
    """_calc_avg_buy_price: 매수 이력에서 가중평균 매입가 역산."""

    async def test_weighted_average(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(price=70000, qty=10),
            _make_buy_rec(price=72000, qty=10),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            avg = await trade_history._calc_avg_buy_price("005930")
        assert avg == round((700000 + 720000) / 20)

    async def test_no_buy_history_returns_zero(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            avg = await trade_history._calc_avg_buy_price("999999")
        assert avg == 0

    async def test_multi_stock_mixed(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(stk_cd="005930", price=70000, qty=10),
            _make_buy_rec(stk_cd="000660", price=120000, qty=5),
            _make_buy_rec(stk_cd="005930", price=71000, qty=10),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            avg = await trade_history._calc_avg_buy_price("005930")
        assert avg == round((700000 + 710000) / 20)


# ── _lookup_sector ────────────────────────────────────────────────────────────

class TestLookupSector:
    """_lookup_sector: custom_sectors 테이블에서 업종명 조회."""

    async def test_normal_lookup(self):
        from backend.app.services import trade_history
        mock_conn = MagicMock()
        mock_cur = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(return_value="반도체")
        mock_cur.fetchone.return_value = mock_row
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_conn.execute.return_value = mock_cm
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            result = await trade_history._lookup_sector("005930")
        assert result == "반도체"

    async def test_no_match_returns_default(self):
        from backend.app.services import trade_history
        mock_conn = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone.return_value = None
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_conn.execute.return_value = mock_cm
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            result = await trade_history._lookup_sector("999999")
        assert result == "미분류"

    async def test_db_failure_returns_default(self):
        from backend.app.services import trade_history
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB error")
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            result = await trade_history._lookup_sector("005930")
        assert result == "미분류"


# ── get_buy_history / get_sell_history ────────────────────────────────────────

class TestGetBuySellHistory:
    """get_buy_history / get_sell_history: 필터링 조회."""

    async def test_get_buy_history_today_only(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        from datetime import date as d
        today_str = d.today().isoformat()
        today_rec = _make_buy_rec(date=today_str)
        old_rec = _make_buy_rec(date="2026-01-01")
        trade_history._buy_history.extend([today_rec, old_rec])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_buy_history(today_only=True)
        assert len(result) == 1
        assert result[0]["date"] == today_str

    async def test_get_sell_history_date_range(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        trade_history._sell_history.extend([
            _make_sell_rec(date="2026-07-01"),
            _make_sell_rec(date="2026-07-05"),
            _make_sell_rec(date="2026-07-10"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_sell_history(date_from="2026-07-03", date_to="2026-07-08")
        assert len(result) == 1
        assert result[0]["date"] == "2026-07-05"

    async def test_get_buy_history_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(trade_mode="test"),
            _make_buy_rec(trade_mode="real"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_buy_history(trade_mode="real")
        assert len(result) == 1
        assert result[0]["trade_mode"] == "real"

    async def test_get_sell_history_empty(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_sell_history()
        assert result == []

    async def test_get_buy_history_all_no_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(trade_mode="test"),
            _make_buy_rec(trade_mode="real"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_buy_history()
        assert len(result) == 2


# ── get_total_realized_pnl ────────────────────────────────────────────────────

class TestGetTotalRealizedPnl:
    """get_total_realized_pnl: 실현손익 합계."""

    async def test_total_pnl_all(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec1 = _make_sell_rec(price=71000, avg_buy_price=70000)
        rec2 = _make_sell_rec(price=69000, avg_buy_price=70000)
        rec1["realized_pnl"] = 500
        rec2["realized_pnl"] = -1000
        trade_history._sell_history.extend([rec1, rec2])
        with patch("backend.app.services.trade_history._history_lock"):
            total = await trade_history.get_total_realized_pnl()
        assert total == -500

    async def test_total_pnl_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec_test = _make_sell_rec(trade_mode="test")
        rec_real = _make_sell_rec(trade_mode="real")
        rec_test["realized_pnl"] = 500
        rec_real["realized_pnl"] = 2000
        trade_history._sell_history.extend([rec_test, rec_real])
        with patch("backend.app.services.trade_history._history_lock"):
            total = await trade_history.get_total_realized_pnl(trade_mode="test")
        assert total == 500

    async def test_total_pnl_date_range(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec1 = _make_sell_rec(date="2026-07-01")
        rec2 = _make_sell_rec(date="2026-07-10")
        rec1["realized_pnl"] = 300
        rec2["realized_pnl"] = 700
        trade_history._sell_history.extend([rec1, rec2])
        with patch("backend.app.services.trade_history._history_lock"):
            total = await trade_history.get_total_realized_pnl(date_from="2026-07-05", date_to="2026-07-15")
        assert total == 700


# ── get_daily_summary 확장 ────────────────────────────────────────────────────

class TestGetDailySummaryExtended:
    """get_daily_summary: 다일자 범위, trade_mode, 빈 날짜, days 파라미터."""

    async def test_multi_date_range(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.append(_make_buy_rec(date="2026-07-01"))
        trade_history._sell_history.append(_make_sell_rec(date="2026-07-02"))
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_daily_summary(
                date_from="2026-07-01", date_to="2026-07-03"
            )
        assert len(result) == 3
        dates = [r["date"] for r in result]
        assert dates == ["2026-07-01", "2026-07-02", "2026-07-03"]
        assert result[0]["buy_count"] == 1
        assert result[1]["sell_count"] == 1

    async def test_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(date="2026-07-01", trade_mode="test"),
            _make_buy_rec(date="2026-07-01", trade_mode="real"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_daily_summary(
                date_from="2026-07-01", date_to="2026-07-01", trade_mode="test"
            )
        assert result[0]["buy_count"] == 1

    async def test_empty_date_defaults(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_daily_summary(
                date_from="2026-07-01", date_to="2026-07-01"
            )
        assert result[0]["buy_count"] == 0
        assert result[0]["sell_count"] == 0
        assert result[0]["realized_pnl"] == 0
        assert result[0]["pnl_rate"] == 0.0

    async def test_days_param_uses_trading_calendar(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        from datetime import date as d
        mock_days = [d(2026, 7, 7), d(2026, 7, 8)]
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.core.trading_calendar.get_recent_trading_days", return_value=mock_days):
                result = await trade_history.get_daily_summary(days=2)
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-07"


# ── clear_test_history ────────────────────────────────────────────────────────

class TestClearTestHistory:
    """clear_test_history: test 모드 이력만 삭제, real 보존."""

    async def test_removes_test_keeps_real(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(trade_mode="test"),
            _make_buy_rec(trade_mode="real"),
        ])
        trade_history._sell_history.extend([
            _make_sell_rec(trade_mode="test"),
            _make_sell_rec(trade_mode="real"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                await trade_history.clear_test_history()
        assert all(r["trade_mode"] == "real" for r in trade_history._buy_history)
        assert all(r["trade_mode"] == "real" for r in trade_history._sell_history)
        assert len(trade_history._buy_history) == 1
        assert len(trade_history._sell_history) == 1

    async def test_invalidates_dry_run_cache(self):
        from backend.app.services import trade_history
        from backend.app.services import dry_run
        dry_run._positions_dirty = False
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                await trade_history.clear_test_history()
        assert dry_run._positions_dirty is True

    async def test_db_delete_failure_handled(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._buy_history.append(_make_buy_rec(trade_mode="test"))
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock, side_effect=Exception("DB error")):
                await trade_history.clear_test_history()
        assert len(trade_history._buy_history) == 0  # 메모리는 정상 삭제됨


# ── build_positions_from_trades ───────────────────────────────────────────────

class TestBuildPositionsFromTrades:
    """build_positions_from_trades: trades 이력에서 보유 포지션 파생."""

    async def test_single_buy(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.append(_make_buy_rec(price=70000, qty=10))
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("test")
        assert "005930" in positions
        assert positions["005930"]["qty"] == 10
        assert positions["005930"]["avg_price"] == 70000

    async def test_multiple_buys_weighted_avg(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(price=70000, qty=10),
            _make_buy_rec(price=72000, qty=10),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("test")
        pos = positions["005930"]
        assert pos["qty"] == 20
        assert pos["avg_price"] == (700000 + 720000) // 20

    async def test_partial_sell_remaining(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.append(_make_buy_rec(price=70000, qty=10))
        trade_history._sell_history.append(_make_sell_rec(qty=4, avg_buy_price=70000))
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("test")
        assert positions["005930"]["qty"] == 6

    async def test_full_sell_removes_position(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.append(_make_buy_rec(price=70000, qty=10))
        trade_history._sell_history.append(_make_sell_rec(qty=10, avg_buy_price=70000))
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("test")
        assert "005930" not in positions

    async def test_buy_date_tracks_earliest(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        # DESC 정렬: 최신이 먼저
        trade_history._buy_history.extend([
            _make_buy_rec(date="2026-07-10", price=70000, qty=5),
            _make_buy_rec(date="2026-07-05", price=71000, qty=5),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("test")
        assert positions["005930"]["buy_date"] == "2026-07-05"

    async def test_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(trade_mode="test"),
            _make_buy_rec(trade_mode="real", stk_cd="000660"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("test")
        assert "005930" in positions
        assert "000660" not in positions


# ── get_earliest_buy_date ─────────────────────────────────────────────────────

class TestGetEarliestBuyDate:
    """get_earliest_buy_date: 해당 종목의 최초 매수일 조회."""

    async def test_tracks_earliest(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(date="2026-07-10"),
            _make_buy_rec(date="2026-07-05"),
            _make_buy_rec(date="2026-07-08"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_earliest_buy_date("005930", "test")
        assert result == "2026-07-05"

    async def test_no_buy_returns_empty(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_earliest_buy_date("999999", "test")
        assert result == ""

    async def test_multi_stock_isolated(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(stk_cd="005930", date="2026-07-10"),
            _make_buy_rec(stk_cd="000660", date="2026-07-01"),
            _make_buy_rec(stk_cd="005930", date="2026-07-05"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_earliest_buy_date("005930", "test")
        assert result == "2026-07-05"


# ── _reset_global_state ───────────────────────────────────────────────────────

class TestResetGlobalState:
    """_reset_global_state: 전역 변수 초기화."""

    def test_clears_memory(self):
        from backend.app.services import trade_history
        trade_history._buy_history.append(_make_buy_rec())
        trade_history._sell_history.append(_make_sell_rec())
        trade_history._reset_global_state()
        assert len(trade_history._buy_history) == 0
        assert len(trade_history._sell_history) == 0
        assert trade_history._loaded is False

    def test_invalidates_dry_run_cache(self):
        from backend.app.services import trade_history
        from backend.app.services import dry_run
        dry_run._positions_dirty = False
        trade_history._reset_global_state()
        assert dry_run._positions_dirty is True


# ── start/stop_consumer_task ──────────────────────────────────────────────────

class TestConsumerTaskNoops:
    """start/stop_consumer_task: SQLite 구조에서 no-op."""

    def test_start_is_noop(self):
        from backend.app.services import trade_history
        trade_history.start_consumer_task()  # 예외 없이 완료

    async def test_stop_is_noop(self):
        from backend.app.services import trade_history
        await trade_history.stop_consumer_task()  # 예외 없이 완료


# ── 브로드캐스트 함수들 ──────────────────────────────────────────────────────

class TestBroadcastFunctions:
    """브로드캐스트 함수들: ws_manager.broadcast 호출 + 예외 무시."""

    async def test_broadcast_sell_append(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        rec = _make_sell_rec()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            with patch("backend.app.services.trade_history.get_daily_summary", new_callable=AsyncMock, return_value=[]):
                await trade_history._broadcast_sell_append(rec)
        mock_ws.broadcast.assert_called_once()

    async def test_broadcast_buy_append(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        rec = _make_buy_rec()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await trade_history._broadcast_buy_append(rec)
        mock_ws.broadcast.assert_called_once()

    async def test_broadcast_full_sell_history(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=[]):
                with patch("backend.app.services.trade_history.get_daily_summary", new_callable=AsyncMock, return_value=[]):
                    await trade_history._broadcast_full_sell_history("test")
        assert mock_ws.broadcast.call_count == 2

    async def test_broadcast_full_buy_history(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            with patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]):
                await trade_history._broadcast_full_buy_history("test")
        mock_ws.broadcast.assert_called_once()

    async def test_broadcast_order_filled(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await trade_history._broadcast_order_filled({"test": True})
        mock_ws.broadcast.assert_called_once_with("order-filled", {"test": True})

    async def test_broadcast_exception_ignored(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock(side_effect=Exception("WS error"))
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await trade_history._broadcast_buy_append(_make_buy_rec())  # 예외 전파 안 됨


# ── broadcast_history ─────────────────────────────────────────────────────────

class TestBroadcastHistory:
    """broadcast_history: 매수/매도 이력 브로드캐스트 통합."""

    async def test_calls_both_broadcasts(self):
        from backend.app.services import trade_history
        with patch("backend.app.services.trade_history._broadcast_full_buy_history", new_callable=AsyncMock) as mock_buy:
            with patch("backend.app.services.trade_history._broadcast_full_sell_history", new_callable=AsyncMock) as mock_sell:
                await trade_history.broadcast_history("test")
        mock_buy.assert_called_once_with("test")
        mock_sell.assert_called_once_with("test")


# ── close_db_connection ───────────────────────────────────────────────────────

class TestCloseDbConnection:
    """close_db_connection: no-op 확인."""

    async def test_close_is_noop(self):
        from backend.app.services import trade_history
        await trade_history.close_db_connection()  # 예외 없이 완료
