"""dry_run.py 단위 테스트 — 포지션 캐시, 시세 연동, 조회 헬퍼, 가상 예수금.

기존 test_dry_run_fill_event.py가 fake_fill_event/fake_send_order/슬리피지를버하므로,
이 파일은 미커버 영역을 보완:
  - _refresh_positions_if_dirty (캐시 재구축/스킵/비파생 필드 보존)
  - _next_fake_order_no (시퀀스)
  - update_price (가격 변경/동일/미보유/손익 재계산)
  - set_stock_name (설정/미보유)
  - get_positions / get_position (전체/단일/미보유)
  - has_position / position_codes (보유/수량0/codes)
  - clear (포지션 클리어)
  - _recalc_pnl (손익 계산/buy_amt=0)
  - 가상 예수금 (set_virtual_deposit)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.app.services import dry_run
from backend.app.services import settlement_engine
from backend.app.services import trade_history


# ── no-op stubs ──────────────────────────────────────────────────────────────

async def _noop_async(*args, **kwargs) -> None:
    pass


# ── 픽스처 ───────────────────────────────────────────────────────────────────

_TEST_CODE = "005930"
_TEST_NM = "삼성전자"
_TEST_PRICE = 70_000


@pytest.fixture(autouse=True)
def _setup_dry_run_env(monkeypatch):
    """각 테스트 전: DB I/O 차단, 가상 잔고 초기화, state 설정."""
    # DB I/O 경로 차단
    monkeypatch.setattr(settlement_engine, "_persist", _noop_async)
    monkeypatch.setattr(settlement_engine, "_broadcast_delta", _noop_async)
    monkeypatch.setattr(trade_history, "_ensure_loaded", _noop_async)

    # DB 로드 스킵
    dry_run._positions_loaded = True
    dry_run._positions_dirty = False
    settlement_engine._loaded = True

    # 인메모리 상태 초기화
    dry_run._test_positions.clear()
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()
    settlement_engine._accumulated_investment = 10_000_000
    settlement_engine._orderable = 10_000_000
    settlement_engine._initial_deposit = 10_000_000

    yield

    # 정리
    dry_run._test_positions.clear()
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()


def _make_position(cd=_TEST_CODE, qty=10, avg_price=70_000, cur_price=70_000, stk_nm=_TEST_NM):
    return {
        "stk_cd": cd,
        "stk_nm": stk_nm,
        "qty": qty,
        "avg_price": avg_price,
        "cur_price": cur_price,
        "total_fee": 105,
        "buy_amt": avg_price * qty + 105,
        "eval_amt": cur_price * qty,
        "pnl_amount": (cur_price - avg_price) * qty - 105,
        "pnl_rate": round(((cur_price - avg_price) * qty - 105) / (avg_price * qty + 105) * 100, 2),
        "buy_date": "2026-07-08",
    }


# ── _refresh_positions_if_dirty ───────────────────────────────────────────────

class TestRefreshPositionsIfDirty:
    """_refresh_positions_if_dirty: dirty→재구축, clean→스킵, 비파생 필드 보존."""

    async def test_dirty_triggers_rebuild(self):
        dry_run._positions_loaded = True
        dry_run._positions_dirty = True
        trade_history._buy_history.append({
            "ts": "2026-07-08T09:10:00", "date": "2026-07-08", "time": "09:10:00",
            "side": "BUY", "stk_cd": _TEST_CODE, "stk_nm": _TEST_NM,
            "price": 70_000, "qty": 10, "fee": 105, "tax": 0,
            "total_amt": 700105, "avg_buy_price": 0, "buy_total_amt": 0,
            "realized_pnl": 0, "pnl_rate": 0.0, "reason": "test",
            "trade_mode": "test",
        })
        with patch("backend.app.services.trade_history._history_lock"):
            await dry_run._refresh_positions_if_dirty()
        assert _TEST_CODE in dry_run._test_positions
        assert dry_run._positions_dirty is False

    async def test_clean_skips_rebuild(self):
        dry_run._positions_loaded = True
        dry_run._positions_dirty = False
        dry_run._test_positions[_TEST_CODE] = _make_position()
        with patch("backend.app.services.trade_history.build_positions_from_trades", new_callable=AsyncMock) as mock_build:
            await dry_run._refresh_positions_if_dirty()
        mock_build.assert_not_called()

    async def test_preserves_non_derived_fields(self):
        """재구축 시 cur_price/stk_nm 등 비파생 필드가 기존 캐시에서 보존되는지 확인."""
        dry_run._positions_loaded = True
        dry_run._positions_dirty = True
        # 기존 캐시에 비파생 필드 설정
        dry_run._test_positions[_TEST_CODE] = _make_position(cur_price=75_000, stk_nm="커스텀명")
        # build_positions_from_trades가 새 포지션 반환 (cur_price/stk_nm 없음)
        new_pos = {
            "stk_cd": _TEST_CODE, "stk_nm": "", "qty": 10, "avg_price": 70_000,
            "cur_price": 70_000, "total_fee": 105, "buy_amt": 700105,
            "eval_amt": 700000, "pnl_amount": -105, "pnl_rate": 0.0,
            "buy_date": "2026-07-08",
        }
        with patch("backend.app.services.trade_history._history_lock"):
            with patch("backend.app.services.trade_history.build_positions_from_trades", new_callable=AsyncMock, return_value={_TEST_CODE: new_pos}):
                await dry_run._refresh_positions_if_dirty()
        pos = dry_run._test_positions[_TEST_CODE]
        # cur_price는 보존되어야 함 (기존 75,000)
        assert pos["cur_price"] == 75_000


# ── _next_fake_order_no ───────────────────────────────────────────────────────

class TestNextFakeOrderNo:
    """_next_fake_order_no: 시퀀스 증가 + 문자열 반환."""

    def test_increments_and_returns_string(self):
        seq_before = dry_run._fake_order_seq
        result = dry_run._next_fake_order_no()
        assert dry_run._fake_order_seq == seq_before + 1
        assert result == str(seq_before + 1)

    def test_sequential_calls_increment(self):
        r1 = dry_run._next_fake_order_no()
        r2 = dry_run._next_fake_order_no()
        assert int(r2) == int(r1) + 1


# ── update_price ──────────────────────────────────────────────────────────────

class TestUpdatePrice:
    """update_price: 0B 틱으로 가상 잔고 현재가/수익률 갱신."""

    async def test_price_change_returns_true(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(cur_price=70_000)
        result = await dry_run.update_price(_TEST_CODE, 75_000)
        assert result is True
        assert dry_run._test_positions[_TEST_CODE]["cur_price"] == 75_000

    async def test_same_price_returns_false(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(cur_price=70_000)
        result = await dry_run.update_price(_TEST_CODE, 70_000)
        assert result is False

    async def test_not_held_returns_false(self):
        result = await dry_run.update_price("999999", 75_000)
        assert result is False

    async def test_pnl_recalculated(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(cur_price=70_000, avg_price=70_000)
        await dry_run.update_price(_TEST_CODE, 80_000)
        pos = dry_run._test_positions[_TEST_CODE]
        assert pos["eval_amt"] == 80_000 * 10
        assert pos["pnl_amount"] > 0
        assert pos["pnl_rate"] > 0


# ── set_stock_name ────────────────────────────────────────────────────────────

class TestSetStockName:
    """set_stock_name: 종목명 설정 (보유 시만)."""

    async def test_sets_name_when_held(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(stk_nm="이전명")
        await dry_run.set_stock_name(_TEST_CODE, "새이름")
        assert dry_run._test_positions[_TEST_CODE]["stk_nm"] == "새이름"

    async def test_noop_when_not_held(self):
        await dry_run.set_stock_name("999999", "새이름")
        assert "999999" not in dry_run._test_positions


# ── get_positions / get_position ──────────────────────────────────────────────

class TestGetPositions:
    """get_positions / get_position: 전체 목록, 단일 조회, 미보유."""

    async def test_get_positions_returns_list(self):
        dry_run._test_positions[_TEST_CODE] = _make_position()
        dry_run._test_positions["000660"] = _make_position(cd="000660", stk_nm="SK하이닉스")
        result = await dry_run.get_positions()
        assert len(result) == 2

    async def test_get_position_found(self):
        dry_run._test_positions[_TEST_CODE] = _make_position()
        pos = await dry_run.get_position(_TEST_CODE)
        assert pos is not None
        assert pos["stk_cd"] == _TEST_CODE

    async def test_get_position_not_found(self):
        pos = await dry_run.get_position("999999")
        assert pos is None


# ── has_position / position_codes ─────────────────────────────────────────────

class TestHasPosition:
    """has_position / position_codes: 보유 여부, codes 집합."""

    async def test_has_position_true(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(qty=10)
        assert await dry_run.has_position(_TEST_CODE) is True

    async def test_has_position_zero_qty_false(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(qty=0)
        assert await dry_run.has_position(_TEST_CODE) is False

    async def test_position_codes(self):
        dry_run._test_positions[_TEST_CODE] = _make_position(qty=10)
        dry_run._test_positions["000660"] = _make_position(cd="000660", qty=5)
        dry_run._test_positions["005930_zero"] = _make_position(cd="005930_zero", qty=0)
        codes = await dry_run.position_codes()
        assert _TEST_CODE in codes
        assert "000660" in codes
        assert "005930_zero" not in codes


# ── clear ─────────────────────────────────────────────────────────────────────

class TestClear:
    """clear: 포지션 클리어 + dirty=False."""

    async def test_clears_positions(self):
        dry_run._test_positions[_TEST_CODE] = _make_position()
        await dry_run.clear()
        assert len(dry_run._test_positions) == 0
        assert dry_run._positions_loaded is True
        assert dry_run._positions_dirty is False


# ── _recalc_pnl ───────────────────────────────────────────────────────────────

class TestRecalcPnl:
    """_recalc_pnl: 현재가 기준 손익 재계산."""

    def test_normal_pnl_calculation(self):
        pos = _make_position(avg_price=70_000, cur_price=80_000, qty=10)
        dry_run._recalc_pnl(pos)
        assert pos["eval_amt"] == 800_000
        assert pos["buy_amt"] == 700_000 + 105
        assert pos["pnl_amount"] == 800_000 - 700_105
        assert pos["pnl_rate"] == round((800_000 - 700_105) / 700_105 * 100, 2)

    def test_zero_buy_amt_pnl_rate_zero(self):
        pos = _make_position(avg_price=0, cur_price=80_000, qty=10)
        pos["total_fee"] = 0
        dry_run._recalc_pnl(pos)
        assert pos["buy_amt"] == 0
        assert pos["pnl_rate"] == 0.0


# ── 가상 예수금 ───────────────────────────────────────────────────────────────

class TestVirtualBalance:
    """가상 예수금 관리 — set_virtual_deposit 검증 (예수금 잔액/충전/리셋은 settlement_engine 라우터가 직접 처리)."""

    async def test_set_virtual_deposit(self):
        with patch("backend.app.services.dry_run.update_settings", new_callable=AsyncMock) as mock_update:
            await dry_run.set_virtual_deposit(20_000_000)
        mock_update.assert_called_once_with({
            "test_virtual_deposit": 20_000_000,
            "test_virtual_balance": 20_000_000,
        })


# ── _apply_buy / _apply_sell ──────────────────────────────────────────────────

class TestApplyBuySell:
    """_apply_buy / _apply_sell: Settlement Engine 위임만 수행 (포지션 직접 수정 없음)."""

    async def test_apply_buy_deducts_cash(self):
        original_cash = settlement_engine.get_orderable()
        await dry_run._apply_buy(_TEST_CODE, 10, 70_000)
        expected_cost = 70_000 * 10 + round(70_000 * 10 * 0.00015)
        assert settlement_engine.get_orderable() == original_cash - expected_cost

    async def test_apply_buy_no_direct_position_update(self):
        await dry_run._apply_buy(_TEST_CODE, 10, 70_000)
        assert _TEST_CODE not in dry_run._test_positions

    async def test_apply_sell_adds_cash(self):
        # 선매수로 예수금 차감
        await dry_run._apply_buy(_TEST_CODE, 10, 70_000)
        cash_after_buy = settlement_engine.get_orderable()
        # 매도
        await dry_run._apply_sell(_TEST_CODE, 10, 71_000)
        assert settlement_engine.get_orderable() > cash_after_buy
