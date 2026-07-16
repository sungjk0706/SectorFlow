"""계좌 잔액 검증 테스트 — settlement_engine 잔액 계산 정확성 + 실제 DB 재현.

근본 원인 후보 3개 검증:
  - A (정상 작동): 매수 차감 + 매도 증가 모두 정상 적용
  - B (매수 차감 누락): 매수 경로 차감이 누락되는 비대칭 버그
  - C (비동기 태스크 누락): fake_fill_event 태스크가 실행되지 않은 채 엔진 재시작

시나리오:
  S1: 단일 매수 차감 (수수료 포함)
  S2: 같은 종목 2회 매수 (누적 차감)
  S3: 매수 후 매도 (세금+수수료 공제, 누적투자금 불변)
  S4-1: 비동기 태스크 취소 시뮬레이션 (후보 C 재현)
  S4-2: 비동기 vs 동기 실행 비교 (경로 대칭성)
  S5: 반복 거래 오차 누적 (30건, 오차 0원)
  S6: 실제 DB 거래 재현 (원본 DB 읽기 전용 복사본 사용)

주의: DB Writer(db_writer.py)가 시작되지 않은 테스트 환경에서는
execute_db_write(wait=True)가 Future를 영원히 resolve하지 못해 무한 대기 발생.
따라서 settlement_engine._persist, _broadcast_delta, trade_history._ensure_loaded를
no-op으로 패치하여 DB I/O 경로를 차단한다. (기존 test_dry_run_fill_event.py 패턴)
"""
from __future__ import annotations

import asyncio
import os
import sqlite3

import pytest

from backend.app.core.constants import (
    BUY_COMMISSION,
    SECURITIES_TAX,
    SELL_COMMISSION,
)
from backend.app.services import dry_run
from backend.app.services import settlement_engine
from backend.app.services import trade_history
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
_INITIAL_DEPOSIT = 10_000_000


@pytest.fixture(autouse=True)
async def _setup_settlement_env(monkeypatch):
    """각 테스트 전: DB I/O 경로 차단, 가상 잔고 초기화, state 설정.

    기존 test_dry_run_fill_event.py 패턴 재사용:
      - _persist → no-op (save_settlement_state wait=True 무한 대기 방지)
      - _broadcast_delta → no-op (engine_account 미기동 환경 보호)
      - trade_history._ensure_loaded → no-op (DB 로드 차단)
      - trading._fire_and_forget_telegram → no-op (NotificationWorker 큐 충돌 방지)
    """
    # ── DB I/O 경로 차단 ──
    monkeypatch.setattr(settlement_engine, "_persist", _noop_async)
    monkeypatch.setattr(settlement_engine, "_broadcast_delta", _noop_async)
    monkeypatch.setattr(trade_history, "_ensure_loaded", _noop_async)
    import backend.app.services.trading as trading_mod
    monkeypatch.setattr(trading_mod, "_fire_and_forget_telegram", _noop_sync)

    # ── DB 로드 스킵 ──
    dry_run._positions_loaded = True
    dry_run._positions_dirty = False
    settlement_engine._loaded = True

    # ── 인메모리 상태 초기화 ──
    dry_run._test_positions.clear()
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()
    settlement_engine._accumulated_investment = _INITIAL_DEPOSIT
    settlement_engine._orderable = _INITIAL_DEPOSIT
    settlement_engine._initial_deposit = _INITIAL_DEPOSIT

    # ── state 설정 ──
    state.integrated_system_settings_cache = dict(_TEST_SETTINGS)
    state.access_token = "test_token"
    orig_auto_trade = state.auto_trade

    yield

    # ── 정리 ──
    dry_run._test_positions.clear()
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()
    state.auto_trade = orig_auto_trade
    state.access_token = None


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

async def _do_buy(code: str, qty: int, price: int, stk_nm: str = "") -> None:
    """프로덕션 매수 흐름: record_buy(슬리피지 적용가) → fake_fill_event.

    기존 test_dry_run_fill_event.py 패턴 재사용.
    """
    fill_price = dry_run.estimate_fill_price(price, "BUY")
    await trade_history.record_buy(
        stk_cd=code, stk_nm=stk_nm, price=fill_price, qty=qty,
        reason="test", trade_mode="test",
    )
    await dry_run.fake_fill_event("BUY", code, qty, price, stk_nm)


async def _do_sell(code: str, qty: int, price: int, stk_nm: str = "") -> None:
    """프로덕션 매도 흐름: record_sell(슬리피지 적용가) → fake_fill_event.

    기존 test_dry_run_fill_event.py 패턴 재사용.
    """
    fill_price = dry_run.estimate_fill_price(price, "SELL")
    await trade_history.record_sell(
        stk_cd=code, stk_nm=stk_nm, price=fill_price, qty=qty,
        avg_buy_price=dry_run.estimate_fill_price(_TEST_PRICE, "BUY"),
        reason="test", trade_mode="test",
    )
    await dry_run.fake_fill_event("SELL", code, qty, price, stk_nm)


def _expected_buy_cost(price: int, qty: int) -> int:
    """매수 차감 예상값: price*qty + 수수료 (settlement_engine.on_buy_fill 공식)."""
    return price * qty + round(price * qty * BUY_COMMISSION)


def _expected_sell_net(price: int, qty: int) -> int:
    """매도 증가 예상값: price*qty - 세금 - 수수료 (settlement_engine.on_sell_fill 공식)."""
    gross = price * qty
    return gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)


# ── S1: 단일 매수 차감 ───────────────────────────────────────────────────────


class TestSingleBuyDeduction:
    """S1: 단일 매수 체결 시 orderable이 정확히 차감되는지 확인."""

    async def test_single_buy_deduction(self):
        price, qty = 100_000, 10
        await settlement_engine.on_buy_fill(price, qty)

        expected = _INITIAL_DEPOSIT - _expected_buy_cost(price, qty)
        assert settlement_engine.get_orderable() == expected, \
            f"단일 매수 차감 불일치: expected={expected}, actual={settlement_engine.get_orderable()}"
        # 누적투자금은 매수 시 불변 (P10 SSOT)
        assert settlement_engine.get_accumulated_investment() == _INITIAL_DEPOSIT


# ── S2: 같은 종목 2회 매수 ────────────────────────────────────────────────────


class TestDoubleBuySameStock:
    """S2: 동일 종목 2회 매수 시 orderable이 2회 모두 누적 차감되는지 확인."""

    async def test_double_buy_same_stock(self):
        p1, q1 = 100_000, 5
        p2, q2 = 120_000, 5
        await settlement_engine.on_buy_fill(p1, q1)
        await settlement_engine.on_buy_fill(p2, q2)

        expected = _INITIAL_DEPOSIT - _expected_buy_cost(p1, q1) - _expected_buy_cost(p2, q2)
        assert settlement_engine.get_orderable() == expected, \
            f"2회 매수 누적 차감 불일치: expected={expected}, actual={settlement_engine.get_orderable()}"


# ── S3: 매수 후 매도 ──────────────────────────────────────────────────────────


class TestBuyThenSellSequence:
    """S3: 매수 → 매도 순서 시 orderable 차감 후 증가, 누적투자금 불변 확인."""

    async def test_buy_then_sell_sequence(self):
        buy_price, qty = 100_000, 10
        sell_price = 110_000
        await settlement_engine.on_buy_fill(buy_price, qty)
        after_buy = settlement_engine.get_orderable()
        assert after_buy == _INITIAL_DEPOSIT - _expected_buy_cost(buy_price, qty)

        await settlement_engine.on_sell_fill(sell_price, qty, _TEST_CODE, _TEST_NM)
        expected = after_buy + _expected_sell_net(sell_price, qty)
        assert settlement_engine.get_orderable() == expected, \
            f"매도 후 증가 불일치: expected={expected}, actual={settlement_engine.get_orderable()}"
        # 누적투자금은 매수/매도 시 모두 불변 (P10 SSOT)
        assert settlement_engine.get_accumulated_investment() == _INITIAL_DEPOSIT


# ── S4-1: 비동기 태스크 취소 시뮬레이션 (후보 C 재현) ──────────────────────────


class TestAsyncTaskCancellation:
    """S4-1: fake_fill_event 태스크 취소 시 orderable 차감 누락 재현 (후보 C).

    시나리오: record_buy 호출(체결 이력 기록) → fake_fill_event 태스크 생성 후 즉시 취소
    → on_buy_fill 미실행 → orderable 변동 없음 → 정합성 위반 상황 재현.
    """

    async def test_async_task_cancellation(self, monkeypatch):
        # load_settlement_state를 초기값 반환하도록 패치 (엔진 재시작 시 DB에서 로드 시뮬레이션)
        async def _fake_load_state():
            return {
                "accumulated_investment": _INITIAL_DEPOSIT,
                "orderable": _INITIAL_DEPOSIT,
                "initial_deposit": _INITIAL_DEPOSIT,
            }
        monkeypatch.setattr(settlement_engine, "load_settlement_state", _fake_load_state)

        # 1. record_buy 호출 (체결 이력 기록 — on_buy_fill은 아직 호출되지 않음)
        fill_price = dry_run.estimate_fill_price(_TEST_PRICE, "BUY")
        await trade_history.record_buy(
            stk_cd=_TEST_CODE, stk_nm=_TEST_NM, price=fill_price, qty=10,
            reason="test", trade_mode="test",
        )
        # 체결 이력이 기록되었는지 확인
        assert len(trade_history._buy_history) == 1, "record_buy 후 매수 이력이 존재해야 함"

        # 2. fake_fill_event 태스크 생성 후 즉시 취소 (on_buy_fill 미실행)
        task = asyncio.create_task(
            dry_run.fake_fill_event("BUY", _TEST_CODE, 10, _TEST_PRICE, _TEST_NM)
        )
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # 3. orderable은 차감되지 않음 (태스크 취소 → on_buy_fill 미실행)
        assert settlement_engine.get_orderable() == _INITIAL_DEPOSIT, \
            "태스크 취소 시 orderable이 차감되지 않아야 함 (후보 C 재현)"

        # 4. 엔진 재시작 시뮬레이션: _loaded=False 후 load_state() → DB에서 원래 값 로드
        settlement_engine._loaded = False
        await settlement_engine.load_state()
        assert settlement_engine.get_orderable() == _INITIAL_DEPOSIT, \
            "엔진 재시작 후 DB 값 로드 — orderable이 원래 값이어야 함"

        # 5. 정합성 위반 확인: trades에 매수 기록 있음 + orderable 차감 안 됨
        assert len(trade_history._buy_history) == 1, \
            "정합성 위반: 매수 이력은 존재하나 orderable이 차감되지 않음 (후보 C)"


# ── S4-2: 비동기 vs 동기 실행 비교 (경로 대칭성) ───────────────────────────────


class TestSyncVsAsyncEquivalence:
    """S4-2: 비동기 fake_fill_event와 동기 _apply_buy의 orderable 결과 동일성 검증."""

    async def test_sync_vs_async_equivalence(self):
        price, qty = 80_000, 10
        fill_price = dry_run.estimate_fill_price(price, "BUY")

        # (a) 비동기: fake_fill_event 태스크 실행 후 대기
        task = asyncio.create_task(
            dry_run.fake_fill_event("BUY", _TEST_CODE, qty, price, _TEST_NM)
        )
        await asyncio.sleep(0.3)  # FAKE_FILL_DELAY(0.1s) + 여유
        orderable_async = settlement_engine.get_orderable()

        # (b) 동기: _apply_buy 직접 호출 (별도 격리 필요하므로 상태 리셋)
        settlement_engine._orderable = _INITIAL_DEPOSIT
        await dry_run._apply_buy(_TEST_CODE, qty, fill_price)
        orderable_sync = settlement_engine.get_orderable()

        # 두 방식의 결과 동일성 검증 (경로 대칭성 — P16 살아있는 경로)
        expected = _INITIAL_DEPOSIT - _expected_buy_cost(fill_price, qty)
        assert orderable_async == expected, \
            f"비동기 경로 불일치: expected={expected}, actual={orderable_async}"
        assert orderable_sync == expected, \
            f"동기 경로 불일치: expected={expected}, actual={orderable_sync}"
        assert orderable_async == orderable_sync, \
            f"경로 대칭성 위반: async={orderable_async}, sync={orderable_sync}"


# ── S5: 반복 거래 오차 누적 ───────────────────────────────────────────────────


class TestRepeatedTradesNoDrift:
    """S5: 5개 종목 × 매수/매도 3회 = 30건 반복 후 오차 0원 검증."""

    async def test_repeated_trades_no_drift(self):
        stocks = [
            ("A001", "종목A", 50_000, 20),
            ("B002", "종목B", 80_000, 12),
            ("C003", "종목C", 30_000, 33),
            ("D004", "종목D", 120_000, 8),
            ("E005", "종목E", 15_000, 66),
        ]
        expected_orderable = _INITIAL_DEPOSIT

        for round_idx in range(3):
            for code, nm, price, qty in stocks:
                # 매수
                buy_price = price + round_idx * 1_000  # 회차별 가격 변동
                await settlement_engine.on_buy_fill(buy_price, qty)
                expected_orderable -= _expected_buy_cost(buy_price, qty)

                # 매도 (같은 가격으로 전량 매도)
                sell_price = buy_price + 500
                await settlement_engine.on_sell_fill(sell_price, qty, code, nm)
                expected_orderable += _expected_sell_net(sell_price, qty)

        actual = settlement_engine.get_orderable()
        assert actual == expected_orderable, \
            f"30건 반복 거래 후 오차: expected={expected_orderable:,}, actual={actual:,}, diff={actual - expected_orderable:,}"
        # 누적투자금은 30건 거래 후에도 불변 (P10 SSOT)
        assert settlement_engine.get_accumulated_investment() == _INITIAL_DEPOSIT


# ── S6: 실제 DB 거래 재현 ─────────────────────────────────────────────────────

_ORIG_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "stocks.db",
)


class TestRealDbReplay:
    """S6: 실제 DB의 trades 테이블을 재현하여 근본 원인 특정.

    원본 DB(stocks.db)를 tmp_path에 읽기 전용 복사본으로 보호.
    복사본에서 trades를 시간순 조회 → settlement_engine 로직에 적용 →
    계산값 vs DB 저장값(28,372,133) 비교 → 근본 원인 후보 A/B/C 중 특정.
    """

    async def test_real_db_replay(self, tmp_path):
        if not os.path.exists(_ORIG_DB_PATH):
            pytest.skip("원본 DB 파일이 존재하지 않음")

        # 1. 원본 DB를 tmp_path에 복사 (원본 보호)
        copy_path = tmp_path / "test_stocks_copy.db"
        import shutil
        shutil.copy2(_ORIG_DB_PATH, str(copy_path))

        # 2. 복사본에서 trades + settlement_state 직접 조회 (sqlite3 동기 읽기)
        conn = sqlite3.connect(str(copy_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT ts, side, stk_cd, stk_nm, price, qty, trade_mode "
            "FROM trades WHERE trade_mode = 'test' ORDER BY ts ASC"
        )
        trades = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT accumulated_investment, orderable, initial_deposit "
            "FROM settlement_state WHERE id = 1"
        )
        ss_row = cur.fetchone()
        conn.close()

        assert ss_row is not None, "settlement_state 행이 존재해야 함"
        db_orderable = int(ss_row["orderable"])
        db_accumulated = int(ss_row["accumulated_investment"])
        db_initial = int(ss_row["initial_deposit"])

        # 3. settlement_engine 초기화 후 trades 적용
        settlement_engine._orderable = db_initial
        settlement_engine._accumulated_investment = db_accumulated
        settlement_engine._initial_deposit = db_initial

        buy_count = 0
        sell_count = 0
        for t in trades:
            price = int(t["price"])
            qty = int(t["qty"])
            if t["side"] == "BUY":
                await settlement_engine.on_buy_fill(price, qty)
                buy_count += 1
            else:
                await settlement_engine.on_sell_fill(price, qty, t["stk_cd"], t["stk_nm"])
                sell_count += 1

        computed_orderable = settlement_engine.get_orderable()
        diff = computed_orderable - db_orderable

        # 4. 근본 원인 특정: 계산값 vs DB 저장값 비교
        # 후보 A (정상): |diff| < 1,000원 (반올림 미세 차이 허용 범위)
        # 후보 B (매수 차감 누락): computed << db (매수가 차감되지 않아 DB가 훨씬 큼)
        # 후보 C (비동기 태스크 누락): |diff| > 10,000원, 일부 거래 미반영
        print(f"\n[S6] 매수 {buy_count}건, 매도 {sell_count}건")
        print(f"[S6] 계산값: {computed_orderable:,}원")
        print(f"[S6] DB 저장값: {db_orderable:,}원")
        print(f"[S6] 차이: {diff:+,}원")

        # 원본 DB 미수정 확인 (복사본만 사용)
        assert os.path.exists(_ORIG_DB_PATH), "원본 DB 파일이 보존되어야 함"

        # 근본 원인 특정: 미세 차이(1,000원 미만)는 후보 A(정상 작동)로 판정
        if abs(diff) < 1_000:
            print("[S6] 결론: 후보 A (정상 작동) — 계산값과 DB 값이 미세 차이 내에서 일치")
            print(f"[S6] 차이 {diff:+,}원은 반올림/클램핑 미세 오차로 판단됨")
        elif abs(diff) > 10_000:
            print(f"[S6] 결론: 후보 C (비동기 태스크 누락) 가능성 — 차이 {diff:+,}원")
            print("[S6] 일부 fake_fill_event 태스크가 완료되지 않은 채 settlement_state가 저장되었을 가능성")
        else:
            print(f"[S6] 결론: 후보 A/C 혼합 가능성 — 차이 {diff:+,}원 (1,000~10,000원 범위)")
