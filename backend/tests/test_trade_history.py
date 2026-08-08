"""trade_history.py 단위 테스트.

기존: get_daily_summary buy_total 중복 합산 회귀 테스트 4건
추가: _ensure_loaded, _insert_trade, _trim_expired,
      record_buy, record_sell, _lookup_sector,
      get_buy/sell_history, get_total_realized_pnl, get_daily_summary 확장,
      clear_test_history, build_positions_from_trades,
      _reset_global_state, 브로드캐스트 함수들
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
        "trade_mode": "virtual",
    })
    # 매도 기록 (70000원 매수 → 69000원 매도, 10주)
    sell_total = 690000
    fee = round(sell_total * 0.00015)  # 104
    tax = round(sell_total * 0.002)    # 1380
    sell_net = sell_total - fee - tax   # 688516
    buy_fee = 105
    buy_total = 700000 + buy_fee        # 700105 (매수가*수량 + 매수수수료)
    realized_pnl = sell_net - buy_total  # -11589 (현금 기준, 수수료/세금 포함)
    pnl_rate = round(realized_pnl / buy_total * 100, 2)

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
        "pnl_rate": pnl_rate,
        "reason": "손절",
        "trade_mode": "virtual",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="virtual"
        )

    today_entry = [r for r in result if r["date"] == today][0]
    expected_rate = pnl_rate

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
        "trade_mode": "virtual",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="virtual"
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
    sell_net = sell_total - sell_fee - sell_tax
    buy_total = 700000 + buy_fee             # 700105
    realized_pnl = sell_net - buy_total      # 현금 기준 (수수료/세금 포함)

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
        "trade_mode": "virtual",
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
        "total_amt": sell_net,
        "fee": sell_fee,
        "tax": sell_tax,
        "avg_buy_price": 70000,
        "buy_total_amt": buy_total,
        "realized_pnl": realized_pnl,
        "pnl_rate": round(realized_pnl / buy_total * 100, 2),
        "reason": "손절",
        "trade_mode": "virtual",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="virtual"
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
        "trade_mode": "virtual",
    })

    with patch("backend.app.services.trade_history._history_lock"):
        result = await trade_history.get_daily_summary(
            date_from=today, date_to=today, trade_mode="virtual"
        )

    entry = [r for r in result if r["date"] == today][0]
    assert entry["buy_fee"] == buy_fee
    assert entry["sell_fee"] == 0
    assert entry["tax"] == 0


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────

def _make_buy_rec(
    stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
    date="2026-07-08", time="09:10:00", fee=105, trade_mode="virtual",
    reason="테스트", sector="", buy_rank=None,
):
    total_amt = price * qty
    return {
        "ts": f"{date}T{time}", "date": date, "time": time, "side": "BUY",
        "stk_cd": stk_cd, "stk_nm": stk_nm, "price": price, "qty": qty,
        "total_amt": total_amt + fee, "fee": fee, "tax": 0,
        "avg_buy_price": 0, "buy_total_amt": 0, "realized_pnl": 0,
        "pnl_rate": 0.0, "reason": reason, "trade_mode": trade_mode,
        "sector": sector, "buy_rank": buy_rank,
    }


def _make_sell_rec(
    stk_cd="005930", stk_nm="삼성전자", price=69000, qty=10,
    date="2026-07-08", time="10:00:00", avg_buy_price=70000,
    trade_mode="virtual", reason="손절", sector=None,
):
    total_amt = price * qty
    fee = round(total_amt * 0.00015) if trade_mode == "virtual" else 0
    tax = round(total_amt * 0.002) if trade_mode == "virtual" else 0
    sell_net = total_amt - fee - tax
    buy_fee = round(avg_buy_price * qty * 0.00015) if trade_mode == "virtual" and avg_buy_price > 0 else 0
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

    async def test_db_failure_keeps_loaded_false_for_retry(self):
        from backend.app.services import trade_history
        trade_history._loaded = False
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB not found")
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with patch("backend.app.services.trade_history._history_lock"):
                await trade_history._ensure_loaded()
        assert trade_history._loaded is False
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

    async def test_test_mode_6_months_expired(self):
        """가상매매: 달력 6개월 이전 데이터 삭제, 최근 데이터 보존."""
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        old_rec = _make_buy_rec(date="2025-12-01", trade_mode="virtual")
        recent_rec = _make_buy_rec(date="2026-07-08", trade_mode="virtual")
        trade_history._buy_history.extend([old_rec, recent_rec])
        from datetime import date as d
        mock_today = d(2026, 7, 15)  # cutoff = 2026-01-15
        mock_conn = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone.return_value = (1,)  # test_db_count = 1
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_conn.execute.return_value = mock_cm
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.core.trading_calendar.get_kst_today", return_value=mock_today):
                with patch("backend.app.core.trading_calendar.get_recent_trading_days") as mock_days:
                    mock_days.return_value = [d(2026, 4, 1)]
                    with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
                        with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock) as mock_db:
                            await trade_history._trim_expired()
        dates = [r["date"] for r in trade_history._buy_history]
        assert "2026-07-08" in dates
        assert "2025-12-01" not in dates
        assert mock_db.call_count == 2  # test + real DB 삭제 (test_db_count=1, real_db_count=1)

    async def test_real_mode_90_days_preserved(self):
        """실전매매: 90거래일 이내 데이터 보존."""
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        real_rec = _make_buy_rec(date="2026-05-01", trade_mode="live")
        trade_history._buy_history.append(real_rec)
        from datetime import date as d
        mock_today = d(2026, 7, 15)
        mock_conn = MagicMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone.return_value = (0,)  # real_db_count = 0 (삭제 대상 없음)
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_conn.execute.return_value = mock_cm
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.core.trading_calendar.get_kst_today", return_value=mock_today):
                with patch("backend.app.core.trading_calendar.get_recent_trading_days") as mock_days:
                    mock_days.return_value = [d(2026, 4, 1)]
                    with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
                        with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock) as mock_db:
                            await trade_history._trim_expired()
        assert real_rec in trade_history._buy_history
        assert mock_db.call_count == 0  # 삭제 대상 0건 → DELETE 미호출

    async def test_trim_exception_logged(self):
        """캘린더 조회 실패 시 예외 로그 + 메모리 보존."""
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._buy_history.append(_make_buy_rec())
        with patch("backend.app.core.trading_calendar.get_kst_today", side_effect=Exception("cal error")):
            await trade_history._trim_expired()
        assert len(trade_history._buy_history) == 1


# ── _trade_params ─────────────────────────────────────────────────────────────

class TestTradeParams:
    """_trade_params: 20필드 튜플 순서 검증 (sector, buy_rank 추가)."""

    def test_params_order(self):
        from backend.app.services import trade_history
        rec = _make_buy_rec(sector="반도체", buy_rank=3)
        params = trade_history._trade_params(rec)
        assert params == (
            rec["ts"], rec["date"], rec["time"], rec["side"],
            rec["stk_cd"], rec["stk_nm"], rec["price"], rec["qty"],
            rec["total_amt"], rec["fee"], rec["tax"],
            rec["avg_buy_price"], rec["buy_total_amt"],
            rec["realized_pnl"], rec["pnl_rate"],
            rec["reason"], rec["trade_mode"],
            rec.get("buy_date", ""),
            rec.get("sector", ""),
            rec.get("buy_rank"),
        )
        assert len(params) == 20

    def test_params_defaults_when_missing(self):
        """rec에 sector/buy_rank 키가 없어도 기본값으로 안전 처리."""
        from backend.app.services import trade_history
        rec = _make_buy_rec()
        del rec["sector"]
        del rec["buy_rank"]
        params = trade_history._trade_params(rec)
        assert params[-2] == ""
        assert params[-1] is None
        assert len(params) == 20


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
                        reason="테스트", trade_mode="virtual",
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
                        trade_mode="virtual",
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
                        trade_mode="live",
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

    async def test_rec_has_no_sector_buy_rank_keys(self):
        """record_buy 반환 rec에서 sector/buy_rank 키 제거 검증 (매수 파이프라인 정리 — P24)."""
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_buy_append", new_callable=AsyncMock):
                    rec = await trade_history.record_buy(
                        stk_cd="005930", stk_nm="삼성전자", price=70000, qty=10,
                    )
        assert "sector" not in rec
        assert "buy_rank" not in rec


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
                            avg_buy_price=70000, trade_mode="virtual",
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
                            avg_buy_price=0, trade_mode="virtual",
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
                            avg_buy_price=70000, trade_mode="virtual",
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
                            avg_buy_price=70000, trade_mode="live",
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
                            avg_buy_price=70000, trade_mode="virtual",
                        )
        assert rec["sector"] == "반도체"

    async def test_sector_lookup_failure_falls_back_to_default(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history._insert_trade", new_callable=AsyncMock):
                with patch("backend.app.services.trade_history._broadcast_sell_append", new_callable=AsyncMock):
                    with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, side_effect=Exception("DB error")):
                        rec = await trade_history.record_sell(
                            stk_cd="005930", stk_nm="삼성전자", price=71000, qty=10,
                            avg_buy_price=70000, trade_mode="virtual",
                        )
        assert rec["sector"] == "미분류"


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

    async def test_db_failure_raises_exception(self):
        from backend.app.services import trade_history
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB error")
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with pytest.raises(Exception, match="DB error"):
                await trade_history._lookup_sector("005930")


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
            _make_buy_rec(trade_mode="virtual"),
            _make_buy_rec(trade_mode="live"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_buy_history(trade_mode="live")
        assert len(result) == 1
        assert result[0]["trade_mode"] == "live"

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
            _make_buy_rec(trade_mode="virtual"),
            _make_buy_rec(trade_mode="live"),
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
        trade_history._sell_history.extend([rec1, rec2])
        expected = (rec1["total_amt"] - rec1["buy_total_amt"]) + (rec2["total_amt"] - rec2["buy_total_amt"])
        with patch("backend.app.services.trade_history._history_lock"):
            total = await trade_history.get_total_realized_pnl()
        assert total == expected

    async def test_total_pnl_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec_test = _make_sell_rec(trade_mode="virtual")
        rec_real = _make_sell_rec(trade_mode="live")
        trade_history._sell_history.extend([rec_test, rec_real])
        expected = rec_test["total_amt"] - rec_test["buy_total_amt"]
        with patch("backend.app.services.trade_history._history_lock"):
            total = await trade_history.get_total_realized_pnl(trade_mode="virtual")
        assert total == expected

    async def test_total_pnl_date_range(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec1 = _make_sell_rec(date="2026-07-01")
        rec2 = _make_sell_rec(date="2026-07-10")
        trade_history._sell_history.extend([rec1, rec2])
        expected = rec2["total_amt"] - rec2["buy_total_amt"]
        with patch("backend.app.services.trade_history._history_lock"):
            total = await trade_history.get_total_realized_pnl(date_from="2026-07-05", date_to="2026-07-15")
        assert total == expected


# ── get_realized_pnl_summary ──────────────────────────────────────────────────

class TestGetRealizedPnlSummary:
    """get_realized_pnl_summary: (pnl, buy_total) 반환 — 프론트엔드 aggregatePnl과 동일 공식."""

    async def test_summary_all(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec1 = _make_sell_rec(price=71000, avg_buy_price=70000)
        rec2 = _make_sell_rec(price=69000, avg_buy_price=70000)
        trade_history._sell_history.extend([rec1, rec2])
        expected_pnl = (rec1["total_amt"] - rec1["buy_total_amt"]) + (rec2["total_amt"] - rec2["buy_total_amt"])
        expected_buy = rec1["buy_total_amt"] + rec2["buy_total_amt"]
        with patch("backend.app.services.trade_history._history_lock"):
            pnl, buy_total = await trade_history.get_realized_pnl_summary()
        assert pnl == expected_pnl
        assert buy_total == expected_buy

    async def test_summary_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        rec_test = _make_sell_rec(trade_mode="virtual")
        rec_real = _make_sell_rec(trade_mode="live")
        trade_history._sell_history.extend([rec_test, rec_real])
        expected_pnl = rec_test["total_amt"] - rec_test["buy_total_amt"]
        expected_buy = rec_test["buy_total_amt"]
        with patch("backend.app.services.trade_history._history_lock"):
            pnl, buy_total = await trade_history.get_realized_pnl_summary(trade_mode="virtual")
        assert pnl == expected_pnl
        assert buy_total == expected_buy

    async def test_summary_empty(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._sell_history.clear()
        with patch("backend.app.services.trade_history._history_lock"):
            pnl, buy_total = await trade_history.get_realized_pnl_summary()
        assert pnl == 0
        assert buy_total == 0


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
            _make_buy_rec(date="2026-07-01", trade_mode="virtual"),
            _make_buy_rec(date="2026-07-01", trade_mode="live"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            result = await trade_history.get_daily_summary(
                date_from="2026-07-01", date_to="2026-07-01", trade_mode="virtual"
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
            with patch("backend.app.core.trading_calendar.get_recent_trading_days", return_value=mock_days) as mock_recent:
                with patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=d(2026, 7, 8)):
                    result = await trade_history.get_daily_summary(days=2)
        # get_chart_reference_trading_day 결과가 from_date로 전달되는지 검증
        mock_recent.assert_called_once_with(2, from_date=d(2026, 7, 8))
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-07"

    async def test_days_param_premarket_excludes_today(self):
        """08:00 이전(장 미개시) 시 days=N 호출 → 오늘 미포함, 직전 거래일부터 N거래일.

        사용자 원칙: 오전 6:47에는 '어제 마감 기준 완료된 5거래일'만 표시.
        get_chart_reference_trading_day가 08:00 이전에 직전 거래일 반환 →
        get_recent_trading_days(N, from_date=직전거래일) → 오늘 제외.
        """
        from backend.app.services import trade_history
        from backend.app.core import trading_calendar
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        # 2026년 거래일 캐시 초기화
        trading_calendar._trading_days_cache = trading_calendar._generate_trading_days(2026)
        trading_calendar._cache_initialized = True
        try:
            from datetime import datetime as dt_cls
            from backend.app.core.constants import _KST
            from unittest.mock import MagicMock
            # 2026-07-30 목요일 06:47 (08:00 이전)
            mock_now = dt_cls(2026, 7, 30, 6, 47, 0, tzinfo=_KST)
            with patch.object(trading_calendar, "datetime", MagicMock(now=MagicMock(return_value=mock_now))):
                with patch("backend.app.services.trade_history._history_lock"):
                    with patch("backend.app.db.database.get_db_connection") as mock_conn:
                        mock_conn.return_value.execute = MagicMock(return_value=MagicMock())
                        result = await trade_history.get_daily_summary(days=5)
            dates = [r["date"] for r in result]
            # 오늘(2026-07-30) 미포함, 직전 거래일(07-29)부터 과거 5거래일
            assert "2026-07-30" not in dates
            assert dates == ["2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28", "2026-07-29"]
        finally:
            trading_calendar._cache_initialized = False
            trading_calendar._trading_days_cache = {}

    async def test_earliest_base_asset_field_present_and_uniform(self):
        """earliest_base_asset 필드가 모든 행에 동일 값으로 포함되는지 검증 (B-2 회귀).

        P10 SSOT — dailySummary가 일별 데이터 + 누적 분모 단일 소스.
        P24 단순성 — 1회 조회로 모든 행 동일 값 적용.
        """
        from backend.app.services import trade_history
        trade_history._buy_history.append(_make_buy_rec(date="2026-07-01"))
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.database.get_db_connection") as mock_conn:
                # get_base_asset_for_period / get_earliest_base_asset 모두 conn.execute 사용
                mock_cursor = MagicMock()
                mock_cursor.fetchone = AsyncMock(return_value={"total_asset": 5000000})
                mock_conn.return_value.execute = AsyncMock(return_value=mock_cursor)
                result = await trade_history.get_daily_summary(
                    date_from="2026-07-01", date_to="2026-07-03"
                )
        assert len(result) == 3
        # 모든 행에 earliest_base_asset 필드 존재 + 동일 값
        for row in result:
            assert "earliest_base_asset" in row
            assert row["earliest_base_asset"] == 5000000

    async def test_earliest_base_asset_none_when_no_snapshot(self):
        """스냅샷 없으면 earliest_base_asset=None (P20 폴백 금지 — 프론트 rate null → '-' 표시)."""
        from backend.app.services import trade_history
        trade_history._buy_history.append(_make_buy_rec(date="2026-07-01"))
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.database.get_db_connection") as mock_conn:
                mock_cursor = MagicMock()
                mock_cursor.fetchone = AsyncMock(return_value=None)
                mock_conn.return_value.execute = AsyncMock(return_value=mock_cursor)
                result = await trade_history.get_daily_summary(
                    date_from="2026-07-01", date_to="2026-07-01"
                )
        assert result[0]["earliest_base_asset"] is None
        assert result[0]["base_asset"] is None


# ── clear_test_history ────────────────────────────────────────────────────────

class TestClearTestHistory:
    """clear_test_history: test 모드 이력만 삭제, real 보존."""

    async def test_removes_test_keeps_real(self):
        from backend.app.services import trade_history
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(trade_mode="virtual"),
            _make_buy_rec(trade_mode="live"),
        ])
        trade_history._sell_history.extend([
            _make_sell_rec(trade_mode="virtual"),
            _make_sell_rec(trade_mode="live"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                await trade_history.clear_test_history()
        assert all(r["trade_mode"] == "live" for r in trade_history._buy_history)
        assert all(r["trade_mode"] == "live" for r in trade_history._sell_history)
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
        trade_history._buy_history.append(_make_buy_rec(trade_mode="virtual"))
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
            positions = await trade_history.build_positions_from_trades("virtual")
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
            positions = await trade_history.build_positions_from_trades("virtual")
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
            positions = await trade_history.build_positions_from_trades("virtual")
        assert positions["005930"]["qty"] == 6

    async def test_full_sell_removes_position(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.append(_make_buy_rec(price=70000, qty=10))
        trade_history._sell_history.append(_make_sell_rec(qty=10, avg_buy_price=70000))
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("virtual")
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
            positions = await trade_history.build_positions_from_trades("virtual")
        assert positions["005930"]["buy_date"] == "2026-07-05"

    async def test_trade_mode_filter(self):
        from backend.app.services import trade_history
        trade_history._loaded = True
        trade_history._buy_history.clear()
        trade_history._sell_history.clear()
        trade_history._buy_history.extend([
            _make_buy_rec(trade_mode="virtual"),
            _make_buy_rec(trade_mode="live", stk_cd="000660"),
        ])
        with patch("backend.app.services.trade_history._history_lock"):
            positions = await trade_history.build_positions_from_trades("virtual")
        assert "005930" in positions
        assert "000660" not in positions


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
                    await trade_history._broadcast_full_sell_history("virtual")
        assert mock_ws.broadcast.call_count == 2

    async def test_broadcast_full_buy_history(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            with patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]):
                await trade_history._broadcast_full_buy_history("virtual")
        mock_ws.broadcast.assert_called_once()

    async def test_broadcast_exception_ignored(self):
        from backend.app.services import trade_history
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock(side_effect=Exception("WS error"))
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await trade_history._broadcast_buy_append(_make_buy_rec())  # 예외 전파 안 됨


# ── daily_summary_days 캐시 N값 전파 (FIX-WS-04 6세션) ────────────────────────

class TestDailySummaryDaysCache:
    """WS push 3곳이 integrated_system_settings_cache의 daily_summary_days 값을
    get_daily_summary(days=N) 호출에 전달하는지 검증 (P13/P16/P22)."""

    async def test_broadcast_sell_append_uses_cache_days(self):
        from backend.app.services import trade_history
        from backend.app.services import engine_state
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        rec = _make_sell_rec()
        # 캐시에 N=5 설정
        engine_state.state.integrated_system_settings_cache["daily_summary_days"] = 5
        try:
            with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
                with patch("backend.app.services.trade_history.get_daily_summary", new_callable=AsyncMock, return_value=[]) as mock_gds:
                    await trade_history._broadcast_sell_append(rec)
            mock_gds.assert_called_once()
            assert mock_gds.call_args.kwargs["days"] == 5
        finally:
            engine_state.state.integrated_system_settings_cache.pop("daily_summary_days", None)

    async def test_broadcast_sell_append_defaults_to_20_when_cache_missing(self):
        from backend.app.services import trade_history
        from backend.app.services import engine_state
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        rec = _make_sell_rec()
        # 캐시에 키 없음 → 기본값 20
        engine_state.state.integrated_system_settings_cache.pop("daily_summary_days", None)
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            with patch("backend.app.services.trade_history.get_daily_summary", new_callable=AsyncMock, return_value=[]) as mock_gds:
                await trade_history._broadcast_sell_append(rec)
        mock_gds.assert_called_once()
        assert mock_gds.call_args.kwargs["days"] == 20

    async def test_broadcast_full_sell_history_uses_cache_days(self):
        from backend.app.services import trade_history
        from backend.app.services import engine_state
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        engine_state.state.integrated_system_settings_cache["daily_summary_days"] = 5
        try:
            with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
                with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=[]):
                    with patch("backend.app.services.trade_history.get_daily_summary", new_callable=AsyncMock, return_value=[]) as mock_gds:
                        await trade_history._broadcast_full_sell_history("virtual")
            mock_gds.assert_called_once()
            assert mock_gds.call_args.kwargs["days"] == 5
        finally:
            engine_state.state.integrated_system_settings_cache.pop("daily_summary_days", None)


# ── broadcast_history ─────────────────────────────────────────────────────────

class TestBroadcastHistory:
    """broadcast_history: 매수/매도 이력 브로드캐스트 통합."""

    async def test_calls_both_broadcasts(self):
        from backend.app.services import trade_history
        with patch("backend.app.services.trade_history._broadcast_full_buy_history", new_callable=AsyncMock) as mock_buy:
            with patch("backend.app.services.trade_history._broadcast_full_sell_history", new_callable=AsyncMock) as mock_sell:
                await trade_history.broadcast_history("virtual")
        mock_buy.assert_called_once_with("virtual")
        mock_sell.assert_called_once_with("virtual")


# ── _backfill_sell_sector ──────────────────────────────────────────────────────

class TestBackfillSellSector:
    """_backfill_sell_sector: 과거 매도 이력 sector=NULL 복구 (P22 데이터 정합성)."""

    async def test_no_null_sector_skips(self):
        """sector=NULL 0건이면 즉시 return (idempotent)."""
        from backend.app.services import trade_history
        mock_conn = MagicMock()
        mock_cur = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(return_value=0)
        mock_cur.fetchone.return_value = mock_row
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_cur
        mock_conn.execute.return_value = mock_cm
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock) as mock_lookup:
                await trade_history._backfill_sell_sector()
        mock_lookup.assert_not_called()

    async def test_backfill_matched_sector(self):
        """sector=NULL 매도를 _lookup_sector 업종명으로 채운다."""
        from backend.app.services import trade_history
        trade_history._sell_history.clear()
        trade_history._sell_history.extend([
            _make_sell_rec(stk_cd="005930", sector=None),
            _make_sell_rec(stk_cd="066570", sector=None),
        ])
        mock_conn = MagicMock()
        # 첫 번째 execute: COUNT 조회 → 2
        # 두 번째 execute: DISTINCT stk_cd 조회 → 005930, 066570
        mock_cur_count = AsyncMock()
        mock_row_count = MagicMock()
        mock_row_count.__getitem__ = MagicMock(return_value=2)
        mock_cur_count.fetchone.return_value = mock_row_count
        mock_cm_count = AsyncMock()
        mock_cm_count.__aenter__.return_value = mock_cur_count
        mock_cur_distinct = AsyncMock()
        mock_row1 = MagicMock()
        mock_row1.__getitem__ = MagicMock(return_value="005930")
        mock_row2 = MagicMock()
        mock_row2.__getitem__ = MagicMock(return_value="066570")
        mock_cur_distinct.fetchall.return_value = [mock_row1, mock_row2]
        mock_cm_distinct = AsyncMock()
        mock_cm_distinct.__aenter__.return_value = mock_cur_distinct
        mock_conn.execute.side_effect = [mock_cm_count, mock_cm_distinct]
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, side_effect=["반도체", "에너지/유틸리티"]) as mock_lookup:
                with patch("backend.app.services.trade_history._history_lock"):
                    with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                        await trade_history._backfill_sell_sector()
        # _lookup_sector가 각 종목코드별로 1회 호출
        assert mock_lookup.call_count == 2
        # 메모리 갱신 확인
        assert trade_history._sell_history[0]["sector"] == "반도체"
        assert trade_history._sell_history[1]["sector"] == "에너지/유틸리티"

    async def test_backfill_unclassified_when_no_match(self):
        """custom_sectors 미매칭 시 '미분류'로 채운다 (record_sell 정책과 일치)."""
        from backend.app.services import trade_history
        trade_history._sell_history.clear()
        trade_history._sell_history.append(_make_sell_rec(stk_cd="999999", sector=None))
        mock_conn = MagicMock()
        mock_cur_count = AsyncMock()
        mock_row_count = MagicMock()
        mock_row_count.__getitem__ = MagicMock(return_value=1)
        mock_cur_count.fetchone.return_value = mock_row_count
        mock_cm_count = AsyncMock()
        mock_cm_count.__aenter__.return_value = mock_cur_count
        mock_cur_distinct = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(return_value="999999")
        mock_cur_distinct.fetchall.return_value = [mock_row]
        mock_cm_distinct = AsyncMock()
        mock_cm_distinct.__aenter__.return_value = mock_cur_distinct
        mock_conn.execute.side_effect = [mock_cm_count, mock_cm_distinct]
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            with patch("backend.app.services.trade_history._lookup_sector", new_callable=AsyncMock, return_value="미분류"):
                with patch("backend.app.services.trade_history._history_lock"):
                    with patch("backend.app.db.db_writer.execute_db_write", new_callable=AsyncMock):
                        await trade_history._backfill_sell_sector()
        assert trade_history._sell_history[0]["sector"] == "미분류"

    async def test_failure_does_not_raise(self):
        """DB 조회 실패 시 예외 전파 없이 기동 계속 (P25 격리된 실패)."""
        from backend.app.services import trade_history
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DB error")
        with patch("backend.app.db.database.get_db_connection", return_value=mock_conn):
            # 예외 발생하지 않고 정상 return
            await trade_history._backfill_sell_sector()
