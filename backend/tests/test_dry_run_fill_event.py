"""테스트모드 동등성 근본해결 — fake_send_order / fake_fill_event 단위 테스트.

원칙 18(테스트모드 동등성) 검증:
- fake_send_order: 주문 접수만 (포지션 변경 없음)
- fake_fill_event: 체결 + on_fill_update + _on_fill_after_ws (실전 WS "00"과 동일)
- _dryrun_post_sell_broadcast 폴백 제거 확인 (원칙 20)
- _on_fill_after_ws TypeError 없이 정상 실행 확인 (사전 버그 B1~B3)

주의: DB Writer(db_writer.py)가 시작되지 않은 테스트 환경에서는
execute_db_write(wait=True)가 Future를 영원히 resolve하지 못해 무한 대기 발생.
따라서 settlement_engine._persist, _broadcast_delta, dry_run._schedule_save_positions를
no-op으로 패치하여 DB I/O 경로를 차단한다.
"""
from __future__ import annotations

import asyncio
import pytest

from backend.app.services import dry_run
from backend.app.services import settlement_engine
from backend.app.services.engine_state import state


# ── no-op stubs ──────────────────────────────────────────────────────────────

async def _noop_async(*args, **kwargs) -> None:
    pass


def _noop_sync(*args, **kwargs) -> None:
    pass


# ── 픽스처 ───────────────────────────────────────────────────────────────────

_TEST_SETTINGS = {
    "trade_mode": "test",
    "time_scheduler_on": False,
}
_TEST_CODE = "005930"
_TEST_NM = "삼성전자"
_TEST_PRICE = 70_000
_TEST_QTY = 10


@pytest.fixture(autouse=True)
async def _setup_test_env(monkeypatch):
    """각 테스트 전: DB I/O 경로 차단, 가상 잔고 초기화, settlement engine 초기화, state 설정."""
    # ── DB I/O 경로 차단 (무한 대기 근본 원인 제거) ──
    # 1. settlement_engine._persist → execute_db_write(wait=True) → Future 영원히 대기
    monkeypatch.setattr(settlement_engine, "_persist", _noop_async)
    # 2. settlement_engine._broadcast_delta → engine_service import 시도 (테스트 환경 미기동)
    monkeypatch.setattr(settlement_engine, "_broadcast_delta", _noop_async)
    # 3. dry_run._schedule_save_positions → 백그라운드 태스크 생성 + DB I/O
    monkeypatch.setattr(dry_run, "_schedule_save_positions", _noop_async)
    # 4. trading._fire_and_forget_telegram → NotificationWorker 큐가 다른 이벤트 루프에 바인딩되어 RuntimeError
    import backend.app.services.trading as trading_mod
    monkeypatch.setattr(trading_mod, "_fire_and_forget_telegram", _noop_sync)

    # ── DB 로드 스킵 ──
    # _positions_loaded = True → _load_positions()가 DB 조회하지 않고 즉시 return
    dry_run._positions_loaded = True
    # settlement_engine._loaded = True → _load()가 DB 조회하지 않고 즉시 return
    settlement_engine._loaded = True

    # ── 인메모리 상태 초기화 ──
    dry_run._test_positions.clear()
    # init()은 _loaded=False일 때만 기본값 설정하므로, 직접 변수 설정
    settlement_engine._accumulated_investment = 10_000_000
    settlement_engine._orderable = 10_000_000
    settlement_engine._initial_deposit = 10_000_000

    # ── state 설정 ──
    state.integrated_system_settings_cache = dict(_TEST_SETTINGS)
    state.access_token = "test_token"
    orig_auto_trade = state.auto_trade

    yield

    # ── 정리 ──
    dry_run._test_positions.clear()
    state.auto_trade = orig_auto_trade
    state.access_token = None


# ── 테스트 ───────────────────────────────────────────────────────────────────


class TestFakeSendOrderNoPositionUpdate:
    """Step 1: fake_send_order는 주문 접수만 (포지션 변경 없음)."""

    async def test_fake_send_order_no_position_update(self):
        """fake_send_order 호출 후 _test_positions에 포지션 생성되지 않음 확인."""
        result = await dry_run.fake_send_order(
            _TEST_SETTINGS, "test_token", "BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE,
        )

        # 반환값 검증
        assert result["success"] is True
        assert "ord_no" in result["data"]["output"]

        # 포지션 생성되지 않음 확인
        pos = await dry_run.get_position(_TEST_CODE)
        assert pos is None, "fake_send_order가 포지션을 생성하면 안 됨 (주문 접수만)"

        # Settlement Engine 잔액 변동 없음 확인
        assert settlement_engine.get_orderable() == 10_000_000, \
            "fake_send_order가 예수금을 차감하면 안 됨 (체결 아님)"


class TestFakeFillEventBuy:
    """Step 2: fake_fill_event BUY — 포지션 생성 + Settlement Engine 반영."""

    async def test_fake_fill_event_buy_creates_position(self):
        """fake_fill_event("BUY", ...) 호출 후 포지션 생성 확인."""
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)

        pos = await dry_run.get_position(_TEST_CODE)
        assert pos is not None, "fake_fill_event BUY 후 포지션이 생성되어야 함"
        assert int(pos["qty"]) == _TEST_QTY
        _expected = dry_run.estimate_fill_price(_TEST_PRICE, "BUY")
        assert int(pos["avg_price"]) == _expected
        assert pos["stk_nm"] == _TEST_NM

    async def test_fake_fill_event_buy_deducts_cash(self):
        """fake_fill_event("BUY", ...) 후 Settlement Engine 예수금 차감 확인."""
        original_cash = settlement_engine.get_orderable()
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)

        after_cash = settlement_engine.get_orderable()
        _fill = dry_run.estimate_fill_price(_TEST_PRICE, "BUY")
        expected_cost = _fill * _TEST_QTY + round(_fill * _TEST_QTY * settlement_engine.BUY_COMMISSION)
        assert after_cash == original_cash - expected_cost, \
            f"예수금 차감 불일치: expected={original_cash - expected_cost}, actual={after_cash}"


class TestFakeFillEventSell:
    """Step 2: fake_fill_event SELL — 포지션 삭제 + Settlement Engine 반영."""

    async def test_fake_fill_event_sell_removes_position(self):
        """fake_fill_event("SELL", ...) 후 포지션 삭제 확인."""
        # 선매수
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)
        # 매도
        await dry_run.fake_fill_event("SELL", _TEST_CODE, _TEST_QTY, _TEST_PRICE + 1_000)

        pos = await dry_run.get_position(_TEST_CODE)
        assert pos is None, "fake_fill_event SELL 후 포지션이 삭제되어야 함 (수량 0)"

    async def test_fake_fill_event_sell_adds_cash(self):
        """fake_fill_event("SELL", ...) 후 Settlement Engine 예수금 증가 확인."""
        # 선매수
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)
        cash_after_buy = settlement_engine.get_orderable()
        # 매도
        sell_price = _TEST_PRICE + 1_000
        await dry_run.fake_fill_event("SELL", _TEST_CODE, _TEST_QTY, sell_price)

        cash_after_sell = settlement_engine.get_orderable()
        assert cash_after_sell > cash_after_buy, "매도 후 예수금이 증가해야 함"


class TestOnFillUpdateCalledInTestMode:
    """Step 6: fake_fill_event → on_fill_update 호출 확인 (has_open_buy 해제, _recent_sells 해제)."""

    async def test_on_fill_update_buy_releases_has_open_buy(self):
        """fake_fill_event BUY 후 has_open_buy가 False로 해제되는지 확인."""
        # AutoTradeManager mock 설정
        from backend.app.services.trading import AutoTradeManager
        mgr = AutoTradeManager(log_callback=lambda msg: None, get_settings_fn=lambda: _TEST_SETTINGS)
        mgr._buy_state[_TEST_CODE] = {"last_req_ts": 0.0, "has_open_buy": True}
        state.auto_trade = mgr

        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)

        assert mgr._buy_state[_TEST_CODE]["has_open_buy"] is False, \
            "fake_fill_event BUY 후 has_open_buy가 False로 해제되어야 함"

    async def test_on_fill_update_sell_releases_recent_sells(self):
        """fake_fill_event SELL 후 _recent_sells에서 discard되는지 확인."""
        from backend.app.services.trading import AutoTradeManager
        mgr = AutoTradeManager(log_callback=lambda msg: None, get_settings_fn=lambda: _TEST_SETTINGS)
        mgr._recent_sells.add(_TEST_CODE)
        state.auto_trade = mgr

        # 선매수 (포지션 생성)
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)
        # 매도
        await dry_run.fake_fill_event("SELL", _TEST_CODE, _TEST_QTY, _TEST_PRICE + 1_000)

        assert _TEST_CODE not in mgr._recent_sells, \
            "fake_fill_event SELL 후 _recent_sells에서 해제되어야 함 (잔고 기반 폴백 없음)"


class TestNoFallbackInSellBroadcast:
    """Step 5: _dryrun_post_sell_broadcast 함수가 더 이상 존재하지 않음 확인 (원칙 20)."""

    def test_no_dryrun_post_sell_broadcast(self):
        """_dryrun_post_sell_broadcast 함수가 trading.py에 존재하지 않음 확인."""
        import backend.app.services.trading as trading_mod

        assert not hasattr(trading_mod, "_dryrun_post_sell_broadcast"), \
            "_dryrun_post_sell_broadcast 함수가 삭제되어야 함 (폴백 제거, 원칙 20)"

    def test_no_dryrun_post_buy_broadcast(self):
        """_dryrun_post_buy_broadcast 함수가 trading.py에 존재하지 않음 확인."""
        import backend.app.services.trading as trading_mod

        assert not hasattr(trading_mod, "_dryrun_post_buy_broadcast"), \
            "_dryrun_post_buy_broadcast 함수가 삭제되어야 함"


class TestOnFillAfterWsWorksInTestMode:
    """Step 7: _on_fill_after_ws 호출 시 TypeError 없이 정상 실행 확인 (사전 버그 B1~B3)."""

    async def test_on_fill_after_ws_no_type_error(self):
        """_on_fill_after_ws 호출 시 TypeError 없이 정상 실행 확인."""
        from backend.app.services.engine_account import _on_fill_after_ws

        # 포지션 없는 상태에서 호출 — TypeError 발생하지 않아야 함
        try:
            await asyncio.wait_for(_on_fill_after_ws(), timeout=5.0)
        except TypeError as e:
            pytest.fail(f"_on_fill_after_ws에서 TypeError 발생 (사전 버그 B1~B3 미수정): {e}")
        except Exception:
            pass  # 다른 예외(브로드캐스트 실패 등)는 허용 — TypeError만 검증 대상

    async def test_on_fill_after_ws_after_buy_fill(self):
        """fake_fill_event BUY → _on_fill_after_ws 정상 실행 확인."""
        from backend.app.services.engine_account import _on_fill_after_ws

        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)

        # _on_fill_after_ws 직접 호출 — TypeError 없이 실행되어야 함
        try:
            await asyncio.wait_for(_on_fill_after_ws(), timeout=5.0)
        except TypeError as e:
            pytest.fail(f"_on_fill_after_ws에서 TypeError 발생: {e}")
        except Exception:
            pass  # 브로드캐스트/매도조건검사 실패는 허용


# ── 슬리피지 테스트 ──────────────────────────────────────────────────────────


class TestTickSize:
    """한국 증시 호가단위(틱 사이즈) 검증."""

    def test_tick_size_under_2000(self):
        assert dry_run._tick_size(1_500) == 1

    def test_tick_size_2000_to_5000(self):
        assert dry_run._tick_size(3_000) == 5

    def test_tick_size_5000_to_20000(self):
        assert dry_run._tick_size(10_000) == 10

    def test_tick_size_20000_to_50000(self):
        assert dry_run._tick_size(30_000) == 50

    def test_tick_size_50000_to_200000(self):
        assert dry_run._tick_size(100_000) == 100

    def test_tick_size_over_200000(self):
        assert dry_run._tick_size(300_000) == 500


class TestApplySlippage:
    """슬리피지 적용 로직 검증."""

    def test_buy_slippage_adds_tick(self):
        # 70,000원 → 틱 100원 (50,000~200,000 구간) → +100원
        assert dry_run._apply_slippage(70_000, "BUY") == 70_100

    def test_sell_slippage_subtracts_tick(self):
        # 70,000원 → 틱 100원 → -100원
        assert dry_run._apply_slippage(70_000, "SELL") == 69_900

    def test_buy_slippage_2_ticks(self):
        assert dry_run._apply_slippage(70_000, "BUY", ticks=2) == 70_200

    def test_sell_slippage_2_ticks(self):
        assert dry_run._apply_slippage(70_000, "SELL", ticks=2) == 69_800

    def test_zero_price_passthrough(self):
        assert dry_run._apply_slippage(0, "BUY") == 0

    def test_negative_price_passthrough(self):
        assert dry_run._apply_slippage(-1, "SELL") == -1

    def test_sell_floor_protection(self):
        # 1원짜리 종목: 틱 1원, 매도 시 1 - 1 = 0이 아닌 max(1, 0) = 1
        assert dry_run._apply_slippage(1, "SELL") == 1

    def test_case_insensitive(self):
        assert dry_run._apply_slippage(70_000, "buy") == 70_100
        assert dry_run._apply_slippage(70_000, "sell") == 69_900


class TestEstimateFillPrice:
    """estimate_fill_price가 _apply_slippage와 동일 결과 반환 검증."""

    def test_buy_estimate(self):
        assert dry_run.estimate_fill_price(70_000, "BUY") == 70_100

    def test_sell_estimate(self):
        assert dry_run.estimate_fill_price(70_000, "SELL") == 69_900


class TestFakeFillEventSlippage:
    """fake_fill_event에 슬리피지가 실제 반영되는지 검증."""

    async def test_buy_fill_price_includes_slippage(self):
        """매수 체결가가 슬리피지 적용 후 가격과 일치하는지 확인."""
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)

        pos = await dry_run.get_position(_TEST_CODE)
        assert pos is not None
        expected = dry_run.estimate_fill_price(_TEST_PRICE, "BUY")
        assert int(pos["avg_price"]) == expected, \
            f"매수 체결가 불일치: expected={expected}, actual={pos['avg_price']}"

    async def test_sell_fill_price_includes_slippage(self):
        """매도 체결가가 슬리피지 적용 후 가격과 일치하는지 확인 (예수금 증가량으로 간접 검증)."""
        # 선매수 (슬리피지 적용된 가격으로 포지션 생성)
        await dry_run.fake_fill_event("BUY", _TEST_CODE, _TEST_QTY, _TEST_PRICE, _TEST_NM)
        cash_after_buy = settlement_engine.get_orderable()

        # 매도 (슬리피지 적용된 가격으로 예수금 증가)
        sell_raw_price = _TEST_PRICE + 1_000  # 71,000
        await dry_run.fake_fill_event("SELL", _TEST_CODE, _TEST_QTY, sell_raw_price)

        cash_after_sell = settlement_engine.get_orderable()
        assert cash_after_sell > cash_after_buy, "매도 후 예수금이 증가해야 함"

        # 매도 체결가 = 71,000 - 100 (틱) = 70,900
        expected_sell_price = dry_run.estimate_fill_price(sell_raw_price, "SELL")
        gross = expected_sell_price * _TEST_QTY
        net_proceeds = gross - round(gross * settlement_engine.SECURITIES_TAX) - round(gross * settlement_engine.SELL_COMMISSION)
        expected_cash = cash_after_buy + net_proceeds
        assert cash_after_sell == expected_cash, \
            f"매도 체결가 슬리피지 미반영: expected_cash={expected_cash}, actual={cash_after_sell}"
