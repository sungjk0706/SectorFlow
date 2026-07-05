# -*- coding: utf-8 -*-
"""
자동매매 실행 / 매도조건 판단
legacy_pc_engine/logic_auto_trade.py 이식 (설정은 get_settings_fn, PyQt5 제거)
"""
import asyncio
import time
import logging
from datetime import datetime

from backend.app.services import data_manager
from backend.app.services.auto_trading_effective import auto_buy_effective, auto_sell_effective
from backend.app.core.broker_factory import get_router
from backend.app.core.trade_mode import is_test_mode
from backend.app.core import journal as _journal
from backend.app.services import dry_run
from backend.app.services import trade_history
from backend.app.services.engine_symbol_utils import _base_stk_cd
from backend.app.services.risk_manager import get_risk_manager

logger = logging.getLogger(__name__)


def _fire_and_forget_telegram(message: str, settings: dict | None) -> None:
    """텔레그램 알림을 NotificationWorker 큐로 전송. 예외 격리."""
    try:
        from backend.app.services.notification_worker import NotificationWorker
        NotificationWorker.get_instance().enqueue({
            "type": "telegram",
            "message": message,
            "settings": settings,
        })
    except Exception as e:
        logger.warning("[텔레그램] 알림 큐 등록 실패: %s", e, exc_info=True)


class AutoTradeManager:
    """자동매매 관리 - get_settings_fn으로 매번 최신 설정 로드."""

    def __init__(self, log_callback, get_settings_fn=None):
        self.highest_prices: dict = {}
        self.log_callback = log_callback
        self.get_settings_fn = get_settings_fn or (lambda: {})
        # ── 종목별 매도 설정 오버라이드 (기존 로직 유지) ────────────────────────
        self.ts_overrides: dict = {}
        # ────────────────────────────────────────────────────────────────────────
        self._recent_sells: set = set()  # 매도 주문 전송 완료 종목 -- 체결/실패 확인까지 재주문 차단
        self._buy_state: dict = {}
        self._daily_buy_date: str = ""
        self._daily_buy_spent = 0
        self._bought_today: dict[str, float] = {}  # stk_cd -> buy timestamp
        self._symbol_daily_buy_spent: dict[str, int] = {}

    async def _restore_daily_buy_state(self) -> tuple[int, dict[str, float], dict[str, int]]:
        """기동 시 trade_history에서 오늘 매수 합계 + 매수 종목 timestamp dict + 종목당 누적 매수금액 복원."""
        try:
            rows = await trade_history.get_buy_history(today_only=True)
            spent = sum(int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0) for r in rows)
            bought_today: dict[str, float] = {}
            symbol_spent: dict[str, int] = {}
            for r in rows:
                cd = str(r.get("stk_cd", "")).strip()
                if cd:
                    symbol_spent[cd] = symbol_spent.get(cd, 0) + int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0)
                    ts_str = r.get("ts") or r.get("date", "")
                    try:
                        ts_dt = datetime.fromisoformat(ts_str)
                        bought_today[cd] = ts_dt.timestamp()
                    except (ValueError, TypeError):
                        bought_today[cd] = time.time()
            return spent, bought_today, symbol_spent
        except Exception:
            logger.warning("[매매] 일일 매수 상태 복원 실패", exc_info=True)
            return 0, {}, {}

    async def _ensure_daily_buy_counter(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_buy_date != today:
            self._daily_buy_date = today
            self._daily_buy_spent, self._bought_today, self._symbol_daily_buy_spent = await self._restore_daily_buy_state()  # type: ignore
            logger.info(
                "[일일매수] 상태 복원 완료 — 날짜=%s 누적매수=%s원 종목수=%d",
                today, f"{self._daily_buy_spent:,}", len(self._bought_today),
            )

    async def execute_buy(self, stk_cd: str, current_price: float, checked_stocks: set,
                    access_token: str, force_buy: bool = False, reason: str = "") -> bool:
        """
        매수 주문 실행.
        force_buy=True: 매수대기 수동 매수 전용. 스케줄 자동매매 게이트만 우회하고
                        나머지 판단(buy_amt, max_limit, 쓰로틀 등)은 그대로 적용.
        reason: 매수 사유 (체결 이력 기록용).
        반환값: True=주문 전송 성공, False=가드에 의해 차단/실패
        """
        settings = self._to_trade_settings(self.get_settings_fn())
        raw_all = self.get_settings_fn()
        await self._ensure_daily_buy_counter()

        # ── 실시간 지연 중단 게이트 ────────────────────────────────────────────
        try:
            from backend.app.services.engine_state import state as engine_state
            if engine_state.realtime_latency_exceeded:
                self.log_callback(f"[실시간지연] {stk_cd} 매수 차단 — WS 지연 200ms 초과")
                return False
        except Exception:
            logger.warning("[매수가드] 실시간 지연 체크 실패", exc_info=True)

        # 스케줄 자동매매 게이트: force_buy(매수대기 수동 매수) 시에만 우회
        if not settings["is_auto"] and not force_buy:
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            self.log_callback(
                f" [자동매매 비활성화] {stk_nm}({stk_cd}) 주문 생략 "
                f"(force_buy={force_buy}, source=auto_signal)"
            )
            return False
        if stk_cd in checked_stocks:
            self.log_callback(f" [매수차단] {stk_cd} 이미 보유/감시 중인 종목입니다.")
            return False

        # ── 재매수 차단 (설정 기반: ON/OFF + 차단 기간) ──────────────────────
        rebuy_block_on = bool(settings.get("rebuy_block_on", True))
        if rebuy_block_on:
            rebuy_period = str(settings.get("rebuy_block_period", "today"))
            last_buy_ts = self._bought_today.get(stk_cd)
            if last_buy_ts is not None:
                if rebuy_period == "today":
                    self.log_callback(f" [매수차단] {stk_cd} 오늘 이미 매수한 종목입니다.")
                    return False
                else:
                    _period_hours = float(rebuy_period.rstrip("h")) if rebuy_period.endswith("h") else 24.0
                    _elapsed = time.time() - last_buy_ts
                    if _elapsed < _period_hours * 3600:
                        _remain_min = int((_period_hours * 3600 - _elapsed) / 60)
                        self.log_callback(
                            f" [매수차단] {stk_cd} 재매수 차단 중 (남은 {_remain_min}분 / 차단 {_period_hours:.0f}시간)"
                        )
                        return False

        state = self._buy_state.get(stk_cd, {"last_req_ts": 0.0, "has_open_buy": False})
        last_ts = float(state.get("last_req_ts", 0) or 0)
        has_open_buy = bool(state.get("has_open_buy", False))
        now = time.time()
        MIN_INTERVAL = 30.0

        if has_open_buy:
            self.log_callback(f"[매수차단] {stk_cd} 매수 주문이 이미 처리 중입니다.")
            return False
        if now - last_ts < MIN_INTERVAL:
            self.log_callback(f"[매수쓰로틀] {stk_cd} 연속 신호 감지. 차단.")
            return False

        # ── 실제 잔고 보유종목 수 기준으로 최대보유종목수 체크 ─────────────
        # 테스트모드: dry_run 가상 잔고 / 실전투자: 키움 실제 잔고
        max_limit = settings["max_limit"]
        from backend.app.services.engine_account import get_positions as _get_positions
        _positions_for_count = await _get_positions()
        holding_count = sum(
            1 for p in _positions_for_count
            if int(p.get("qty", 0)) > 0
        )
        if holding_count >= max_limit:
            self.log_callback(
                f"[매수제한] 잔고 보유종목 {holding_count}종목 ≥ 최대 {max_limit}종목. {stk_cd} 매수 차단."
            )
            return False

        buy_amt = settings.get("buy_amt", 0)
        if buy_amt <= 0:
            return False
        max_daily_total = int(settings.get("max_daily_total_buy_amt", 0) or 0)
        max_daily_on = bool(settings.get("max_daily_total_buy_on", False))
        # ── 종목당 일일 누적 매수금액 한도 체크 (buy_amt = 종목당 일일 최대 매수금액) ──
        symbol_spent = self._symbol_daily_buy_spent.get(stk_cd, 0)
        symbol_remain = max(0, int(buy_amt) - symbol_spent)
        if symbol_remain <= 0:
            self.log_callback(
                f"[종목당한도] {stk_cd} 차단. 종목누적 {symbol_spent:,}원 / 한도 {int(buy_amt):,}원"
            )
            return False
        # 일일 한도 내에서 실제 사용 가능 금액 계산 (잔여 한도가 종목당 한도보다 적으면 잔여 한도만큼만 매수)
        if max_daily_on and max_daily_total > 0:
            daily_remain = max(0, max_daily_total - self._daily_buy_spent)
            if daily_remain <= 0:
                self.log_callback(
                    f"[일일매수한도] {stk_cd} 차단. 잔여 0원 / 한도 {max_daily_total:,}원"
                )
                return False
            effective_buy_amt = min(symbol_remain, daily_remain)
        else:
            effective_buy_amt = symbol_remain

        if current_price <= 0:
            self.log_callback(f"[매수제한] {stk_cd} 서버 현재가 미수신(<=0). 주문 차단.")
            return False

        # ── 등락률 + 거래대금 가드 (설정값 기반) ──────────────────────────────
        # 단일 소스 진리: master_stocks_cache에서 직접 읽기
        from backend.app.services.engine_state import state

        # 등락률 가드
        _rise_limit = float(raw_all.get("buy_block_rise_pct", 7.0))
        _fall_limit = float(raw_all.get("buy_block_fall_pct", 7.0))
        _change_rate = state.master_stocks_cache.get(stk_cd, {}).get("change_rate")
        if _change_rate is not None:
            _blocked = False
            _block_reason = ""
            if _change_rate >= _rise_limit:
                _blocked = True
                _block_reason = f"상승률 {_change_rate:+.1f}%"
            elif _change_rate <= -_fall_limit:
                _blocked = True
                _block_reason = f"하락률 {abs(_change_rate):.1f}%"
            if _blocked:
                stk_nm_g = data_manager.get_stock_name(stk_cd, access_token)
                self.log_callback(
                    f"[등락률가드] {stk_nm_g}({stk_cd}) 등락률 {_block_reason} -- 매수 차단"
                )
                return False

        # 체결강도 가드
        _min_strength = float(raw_all.get("buy_min_strength", 0))
        if _min_strength > 0:
            _strength_raw = state.master_stocks_cache.get(stk_cd, {}).get("strength")
            if _strength_raw is not None and _strength_raw != "-":
                try:
                    _strength_val = float(_strength_raw)
                    if _strength_val < _min_strength:
                        stk_nm_s = data_manager.get_stock_name(stk_cd, access_token)
                        self.log_callback(
                            f"[체결강도가드] {stk_nm_s}({stk_cd}) 체결강도 {_strength_val:.0f} < {_min_strength:.0f} -- 매수 차단"
                        )
                        return False
                except (ValueError, TypeError):
                    pass

        # ── 주문가능 금액 내에서 최대한 매수 (buy_amt는 한도, 의무 지출액 아님) ──
        if is_test_mode(raw_all):
            from backend.app.services.settlement_engine import get_available_cash
            _orderable = get_available_cash()
        else:
            _orderable = get_risk_manager().account_manager.get_withdrawable_deposit()
        _max_available = min(effective_buy_amt, _orderable)
        _est_buy_price = dry_run.estimate_fill_price(int(current_price), "BUY") if is_test_mode(raw_all) else int(current_price)
        buy_qty = _max_available // _est_buy_price
        if buy_qty <= 0:
            return False

        # 시장가 단일 운용
        trde_tp = "3"
        order_price = 0
        order_type = "시장가"

        # ── RiskManager 게이트 (테스트/실전 공통 — 모드 분기는 RiskManager 내부에서 처리) ──
        risk_mgr = get_risk_manager()
        _allowed, _risk_reason = await risk_mgr.check_buy_order_allowed(
            stk_cd, float(current_price), buy_qty
        )
        if not _allowed:
            self.log_callback(f"[리스크차단] {stk_cd} 매수 차단 — {_risk_reason}")
            return False

        self._buy_state[stk_cd] = {"last_req_ts": now, "has_open_buy": True}
        stk_nm = data_manager.get_stock_name(stk_cd, access_token)

        self.log_callback(f"[매수주문] {stk_nm}({stk_cd}) 매수신호 감지. {order_type} {buy_qty}주 주문전송.")
        _fire_and_forget_telegram(f"🚀 [자동매매] {stk_nm} {buy_qty}주 매수 주문 전송 완료.", self.get_settings_fn())

        base_settings = self.get_settings_fn()

        # ── 테스트모드: 예수금 검증 (Settlement Engine) ────────────────────────
        if is_test_mode(base_settings):
            from backend.app.services.engine_strategy_core import check_test_buy_power
            _check_price = int(order_price) if order_price > 0 else int(current_price)
            _check_price = dry_run.estimate_fill_price(_check_price, "BUY")
            ok, reason = check_test_buy_power(
                _check_price, buy_qty, self._daily_buy_spent,
            )
            if not ok:
                logger.info("[전략] 매수 거부: %s (%s)", stk_cd, reason)
                self._buy_state[stk_cd]["has_open_buy"] = False
                return False

        # ── 테스트모드 가드: 테스트모드면 실전 서버에 절대 주문 안 보냄 ─────────
        if is_test_mode(base_settings):
            _dry_price = int(order_price) if order_price > 0 else int(current_price)
            res = await dry_run.fake_send_order(
                base_settings, access_token, "BUY", stk_cd, buy_qty, _dry_price, trde_tp,
            )
            await dry_run.set_stock_name(stk_cd, stk_nm)
        else:
            res = await get_router().order.send_order(base_settings, access_token, "BUY", stk_cd, buy_qty, int(order_price), trde_tp)

        if not (res and res.get("success")):
            self._buy_state[stk_cd]["has_open_buy"] = False
            self.log_callback(f" [매수실패] {stk_nm} 주문 전송 실패. 잠금 해제.")
            _fire_and_forget_telegram(f"⚠️ [매수실패] {stk_nm}({stk_cd}) 주문 전송 실패. 잠금 해제.", base_settings)
            try:
                risk_mgr = get_risk_manager()
                risk_mgr.record_order_failure()
                # CircuitBreaker OPEN 시 마스터 스위치 강제 OFF
                if risk_mgr.circuit_breaker.get_state() == "OPEN":
                    from backend.app.services.engine_state import state
                    from backend.app.services.engine_account_notify import _broadcast, notify_desktop_header_refresh, notify_desktop_settings_toggled
                    state.integrated_system_settings_cache["time_scheduler_on"] = False
                    await _broadcast("circuit_breaker_open", {
                        "message": "Circuit Breaker OPEN - 마스터 스위치 강제 OFF",
                    })
                    await notify_desktop_header_refresh()
                    await notify_desktop_settings_toggled({"time_scheduler_on": False})
                    logger.error("[CircuitBreaker] OPEN 상태 - 마스터 스위치 강제 OFF")
            except Exception:
                logger.warning("[매수] RiskManager 실패 보고 실패", exc_info=True)
            return False

        # ── 저널링: 주문 요청 기록 ─────────────────────────────────────────────
        order_id = res.get("order_id", f"buy_{stk_cd}_{int(time.time())}")
        _mode = "test" if is_test_mode(base_settings) else "real"
        await _journal.record_order_request(
            order_id=order_id,
            stock_code=stk_cd,
            side="buy",
            quantity=buy_qty,
            price=float(order_price) if order_price > 0 else float(current_price),
            trade_mode=_mode,
        )

        fill_price = int(order_price) if order_price > 0 else int(current_price)
        if is_test_mode(base_settings):
            fill_price = dry_run.estimate_fill_price(fill_price, "BUY")
        spent = int(buy_qty * fill_price)
        self._daily_buy_spent += max(0, spent)
        self._symbol_daily_buy_spent[stk_cd] = self._symbol_daily_buy_spent.get(stk_cd, 0) + max(0, spent)

        # ── 매수 성공 즉시 _bought_today 반영 (테스트/실전 공통 — 원칙 18 동등성) ──
        if stk_cd not in self._bought_today:
            self._bought_today[stk_cd] = time.time()
            self.log_callback(f"[매수기억] {stk_nm} 주문 성공! 금일 매수 이력 저장 완료.")

        # ── 체결 이력 기록 ────────────────────────────────────────────────────
        _buy_reason = reason or "자동매수"
        _mode = "test" if is_test_mode(base_settings) else "real"
        await trade_history.record_buy(
            stk_cd=stk_cd, stk_nm=stk_nm,
            price=fill_price, qty=buy_qty,
            reason=_buy_reason, trade_mode=_mode,
        )

        # ── 매수 성공 즉시 _checked_stocks 반영 -- 다음 매수 신호에서 한도 초과 차단 ──
        checked_stocks.add(stk_cd)

        # ── 매수 한도 상태 WS 브로드캐스트 (account-update보다 선행) ────────
        # buy-limit-status가 먼저 전송되어 uiStore.buyLimitStatus가 갱신된 후,
        # account-update가 hotStore를 갱신할 때 updateBadges()가 최신 daily_buy_spent 사용
        try:
            from backend.app.services.engine_account import _broadcast_buy_limit_status
            await _broadcast_buy_limit_status()
        except Exception:
            logger.warning("[매수] 매수한도 브로드캐스트 실패", exc_info=True)

        # ── 테스트모드: 가상 체결 이벤트 예약 (실전 WS "00"과 동일한 downstream) ──
        if is_test_mode(base_settings):
            _dry_fill_price = int(order_price) if order_price > 0 else int(current_price)
            _fill_task = asyncio.create_task(
                dry_run.fake_fill_event("BUY", stk_cd, buy_qty, _dry_fill_price, stk_nm)
            )
            _fill_task.add_done_callback(
                lambda t: logger.error("[테스트모드] fake_fill_event(BUY) 실패: %s", t.exception(), exc_info=t.exception()) if t.exception() else None
            )

        t_str = datetime.now().strftime("%H:%M:%S")
        fmt_price = f"{fill_price:,}"
        self.log_callback(
            f"[{t_str}] [매수주문] {stk_nm} | {order_type} | {buy_qty:,}주 | 단가: {fmt_price}원 | "
            f"일일누적매수 {self._daily_buy_spent:,}원"
        )

        # ── RiskManager 성공 보고 ─────────────────────────────────────────────
        try:
            risk_mgr = get_risk_manager()
            prev_state = risk_mgr.circuit_breaker.get_state()
            risk_mgr.record_order_success()
            new_state = risk_mgr.circuit_breaker.get_state()
            if prev_state == "HALF_OPEN" and new_state == "CLOSED":
                logger.info("[CircuitBreaker] OMS 복구 완료 — HALF_OPEN → CLOSED")
                _fire_and_forget_telegram("✅ [OMS] 서킷브레이커 복구 완료 — 주문 정상 작동 재개", self.get_settings_fn())
        except Exception:
            logger.warning("[매수] RiskManager 성공 보고 실패", exc_info=True)

        return True

    async def on_fill_update(
        self, stk_cd: str, side: str, unex_qty: int, access_token: str | None = None
    ) -> None:
        nk = _base_stk_cd(str(stk_cd or ""))
        state = self._buy_state.get(stk_cd, {"last_req_ts": 0.0, "has_open_buy": False})
        state["last_req_ts"] = time.time()
        unex = int(unex_qty) if str(unex_qty).lstrip("-").isdigit() else 0

        if str(side) == "1" and unex == 0:
            state["has_open_buy"] = False
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            self.log_callback(f"[매수체결] {stk_nm} 체결 확인!")
            _fire_and_forget_telegram(
                f"✅ [매수체결] {stk_nm}({stk_cd}) 매수 체결 완료!",
                self.get_settings_fn(),
            )
        elif str(side) == "2" and unex == 0:
            # 매도 체결 완료 -- 재매도 차단 해제
            self._recent_sells.discard(nk)
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            self.log_callback(f"[매도체결] {stk_nm}({stk_cd}) 매도 체결 완료!")
            _fire_and_forget_telegram(
                f"💰 [매도체결] {stk_nm}({stk_cd}) 매도 체결 완료!",
                self.get_settings_fn(),
            )
        elif str(side) in ("3", "4"):
            state["has_open_buy"] = False
        self._buy_state[stk_cd] = state

    async def execute_sell(
        self,
        stk_cd: str,
        cur_price: float,
        stk_nm: str,
        reason: str,
        qty: int,
        pnl_rate: float,
        trade_settings: dict,
        base_settings: dict,
        access_token: str,
    ) -> None:
        """trade_settings: _to_trade_settings (is_sell_mkt 등). base_settings: engine_settings (kiwoom/telegram용)."""
        if not trade_settings.get("is_sell_auto", False):
            return
        # 시장가 단일 운용
        order_type = "시장가"

        self.log_callback(f"[매도주문] {stk_nm} {reason}. {order_type} {qty}주 (단가: 시장가)")
        _fire_and_forget_telegram(f"[자동매매] {stk_nm}({stk_cd}) {reason} 발동! {qty}주 매도 전송.", base_settings)

        trde_tp = "3"
        order_price = 0  # 시장가
        self._recent_sells.add(stk_cd)

        # ── 평균매입가를 주문 전에 미리 조회 (주문 후 포지션 삭제되면 조회 불가) ──
        _mode = "test" if is_test_mode(base_settings) else "real"
        _avg_buy = 0
        try:
            if _mode == "test":
                _pos = await dry_run.get_position(stk_cd)
                _avg_buy = int(_pos.get("avg_price", 0)) if _pos else 0
            else:
                from backend.app.services.engine_account import get_positions as _get_positions
                for _p in await _get_positions():
                    if _base_stk_cd(str(_p.get("stk_cd", ""))) == stk_cd:
                        _avg_buy = int(_p.get("avg_price", 0))
                        break
        except Exception:
            logger.warning("[매도] 평균매수가 조회 실패", exc_info=True)

        # ── 테스트모드 가드: 테스트모드면 실전 서버에 절대 주문 안 보냄 ─────────
        if is_test_mode(base_settings):
            _dry_sell_price = int(order_price) if order_price > 0 else int(cur_price)
            result = await dry_run.fake_send_order(
                base_settings, access_token, "SELL", stk_cd, qty, _dry_sell_price, trde_tp,
            )
        else:
            result = await get_router().order.send_order(base_settings, access_token, "SELL", stk_cd, qty, int(order_price), trde_tp)

        if not result.get("success"):
            self._recent_sells.discard(stk_cd)
            self.log_callback(f"[매도] {stk_nm} 주문 전송 실패: {result.get('msg', '알 수 없음')}")
            _fire_and_forget_telegram(f"⚠️ [매도실패] {stk_nm}({stk_cd}) 주문 전송 실패: {result.get('msg', '알 수 없음')}", base_settings)
            try:
                risk_mgr = get_risk_manager()
                risk_mgr.record_order_failure()
                # CircuitBreaker OPEN 시 마스터 스위치 강제 OFF
                if risk_mgr.circuit_breaker.get_state() == "OPEN":
                    from backend.app.services.engine_state import state
                    from backend.app.services.engine_account_notify import _broadcast, notify_desktop_header_refresh, notify_desktop_settings_toggled
                    state.integrated_system_settings_cache["time_scheduler_on"] = False
                    await _broadcast("circuit_breaker_open", {
                        "message": "Circuit Breaker OPEN - 마스터 스위치 강제 OFF",
                    })
                    await notify_desktop_header_refresh()
                    await notify_desktop_settings_toggled({"time_scheduler_on": False})
                    logger.error("[CircuitBreaker] OPEN 상태 - 마스터 스위치 강제 OFF")
            except Exception:
                logger.warning("[매도] RiskManager 실패 보고 실패", exc_info=True)
            return

        # ── 저널링: 주문 요청 기록 ─────────────────────────────────────────────
        order_id = result.get("order_id", f"sell_{stk_cd}_{int(time.time())}")
        await _journal.record_order_request(
            order_id=order_id,
            stock_code=stk_cd,
            side="sell",
            quantity=qty,
            price=float(order_price) if order_price > 0 else float(cur_price),
            trade_mode=_mode,
        )

        t_str = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{t_str}] [매도주문] {stk_nm} | {reason} | {order_type} | {qty:,}주 | 평가손익: {pnl_rate}%")

        # ── 체결 이력 기록 ────────────────────────────────────────────────────
        _sell_price = int(order_price) if order_price > 0 else int(cur_price)
        if _mode == "test":
            _sell_price = dry_run.estimate_fill_price(_sell_price, "SELL")
        await trade_history.record_sell(
            stk_cd=stk_cd, stk_nm=stk_nm,
            price=_sell_price, qty=qty,
            avg_buy_price=_avg_buy, reason=reason,
            pnl_rate=pnl_rate, trade_mode=_mode,
        )

        # ── 테스트모드: 가상 체결 이벤트 예약 (실전 WS "00"과 동일한 downstream) ──
        if is_test_mode(base_settings):
            _dry_sell_price = int(order_price) if order_price > 0 else int(cur_price)
            _fill_task = asyncio.create_task(
                dry_run.fake_fill_event("SELL", stk_cd, qty, _dry_sell_price, stk_nm)
            )
            _fill_task.add_done_callback(
                lambda t: logger.error("[테스트모드] fake_fill_event(SELL) 실패: %s", t.exception(), exc_info=t.exception()) if t.exception() else None
            )

        # ── RiskManager 성공 보고 ─────────────────────────────────────────────
        try:
            risk_mgr = get_risk_manager()
            prev_state = risk_mgr.circuit_breaker.get_state()
            risk_mgr.record_order_success()
            new_state = risk_mgr.circuit_breaker.get_state()
            if prev_state == "HALF_OPEN" and new_state == "CLOSED":
                logger.info("[CircuitBreaker] OMS 복구 완료 — HALF_OPEN → CLOSED")
                _fire_and_forget_telegram("✅ [OMS] 서킷브레이커 복구 완료 — 주문 정상 작동 재개", self.get_settings_fn())
        except Exception:
            logger.warning("[매도] RiskManager 성공 보고 실패", exc_info=True)

    async def check_sell_conditions(self, stock_list: list, base_settings: dict, access_token: str) -> None:
        settings = self._to_trade_settings(base_settings)
        if not settings.get("is_sell_auto", False):
            return

        # ── 실시간 지연 중단 게이트 ────────────────────────────────────────────
        try:
            from backend.app.services.engine_state import state as engine_state
            if engine_state.realtime_latency_exceeded:
                self.log_callback("[실시간지연] 매도 조건 전체 차단 — WS 지연 200ms 초과")
                return
        except Exception:
            logger.warning("[매도가드] 실시간 지연 체크 실패", exc_info=True)

        # ── RiskManager Circuit Breaker 체크 ───────────────────────────────────
        try:
            risk_mgr = get_risk_manager()
            allowed, reason = risk_mgr.check_sell_order_allowed("", 0, 0)
            if not allowed:
                self.log_callback(f"[리스크차단] 매도 조건 전체 차단 — {reason}")
                return
        except Exception:
            logger.warning("[매도가드] RiskManager 체크 실패", exc_info=True)

        for stock in stock_list:
            s = dict(settings)
            stk_cd = _base_stk_cd(str(stock.get("stk_cd", "") or ""))
            stk_nm = stock.get("stk_nm", "")
            if not stk_cd:
                continue
            # 매도 주문 전송 완료 종목 -- 재주문 차단
            if stk_cd in self._recent_sells:
                continue

            cur_price = float(str(stock.get("cur_price", 0)).replace(",", ""))
            qty = int(str(stock.get("qty", 0)).replace(",", ""))
            pnl_rate = float(stock.get("pnl_rate", 0))
            # 서버 손익값만 사용: 표준 키(pnl_amount) 우선, 하위 호환 키(pnl_amt) 보조.
            pnl_amt = float(stock.get("pnl_amount", stock.get("pnl_amt", 0)) or 0)

            override = self.ts_overrides.get(stk_cd, {}) if isinstance(self.ts_overrides, dict) else {}
            if override:
                for key in (
                    "tp_val", "tp_apply",
                    "ts_start_val", "ts_drop_val",
                    "ts_apply", "loss_apply",
                    "sell_custom_qty", "sell_qty_type", "loss_val",
                ):
                    if override.get(key) is not None:
                        s[key] = override[key]
                if override.get("order_type") in ("시장가", "지정가"):
                    s["is_sell_mkt"] = override["order_type"] == "시장가"
                tp_v = float(s.get("tp_val") or 0)
                s["chk_tp"] = bool(s.get("tp_apply", True)) and tp_v > 0
                s["chk_loss"] = bool(s.get("loss_apply"))
                s["chk_ts"] = bool(s.get("ts_apply"))

            if qty <= 0:
                continue
            custom_qty = s.get("sell_custom_qty", 0)
            custom_type = s.get("sell_qty_type", "%")
            sell_qty = max(1, int(qty * (custom_qty / 100.0))) if custom_type == "%" and custom_qty > 0 else min(qty, custom_qty) if custom_qty > 0 else qty

            if stk_cd not in self.highest_prices or pnl_rate > self.highest_prices[stk_cd]["pnl_rate"]:
                self.highest_prices[stk_cd] = {"price": cur_price, "pnl_rate": pnl_rate, "pnl_amt": pnl_amt}

            max_reached = self.highest_prices[stk_cd]
            highest_price = max_reached["price"]

            if s.get("chk_loss", False):
                loss_val = float(s.get("loss_val") or 0)
                hit_sl = pnl_rate <= -loss_val
                if hit_sl:
                    try:
                        await self.execute_sell(stk_cd, cur_price, stk_nm, "손절 발동", sell_qty, pnl_rate, s, base_settings, access_token)
                    except Exception:
                        logger.error("[매도] 손절 실행 실패", exc_info=True)
                    continue

            if s.get("chk_tp", False):
                tp_val = float(s.get("tp_val") or 0)
                hit_tp = pnl_rate >= tp_val
                if hit_tp:
                    try:
                        await self.execute_sell(stk_cd, cur_price, stk_nm, "익절 발동", sell_qty, pnl_rate, s, base_settings, access_token)
                    except Exception:
                        logger.error("[매도] 익절 실행 실패", exc_info=True)
                    continue

            if s.get("chk_ts", False):
                ts_start_val = float(s.get("ts_start_val") or 0)
                ts_drop_val = float(s.get("ts_drop_val") or 0)

                if max_reached["pnl_rate"] >= ts_start_val:
                    drop_rate = ((highest_price - cur_price) / highest_price * 100) if highest_price > 0 else 0
                    if drop_rate >= ts_drop_val:
                        await self.execute_sell(stk_cd, cur_price, stk_nm, "T/S 익절", sell_qty, pnl_rate, s, base_settings, access_token)

    def _to_trade_settings(self, raw: dict) -> dict:
        """engine_settings 형식을 logic_auto_trade 호환 형식으로 변환."""
        r = raw
        tp_val = float(r["tp_val"])
        tp_on = bool(r["tp_apply"])
        return {
            "is_auto": auto_buy_effective(r),
            "is_sell_auto": auto_sell_effective(r),
            "max_limit": int(r["max_stock_cnt"]),
            "buy_amt": int(r["buy_amt"]),
            "max_daily_total_buy_on": bool(r.get("max_daily_total_buy_on", False)),
            "max_daily_total_buy_amt": int(r["max_daily_total_buy_amt"]),
            "rebuy_block_on": bool(r.get("rebuy_block_on", True)),
            "rebuy_block_period": str(r.get("rebuy_block_period", "today")),
            "is_sell_mkt": r["sell_price_type"] == "mkt",
            "sell_offset": int(r["sell_offset"]),
            "sell_custom_qty": int(r["sell_custom_qty"]),
            "sell_qty_type": r["sell_qty_type"],
            "tp_val": tp_val,
            "tp_apply": tp_on,
            "chk_tp": tp_on and tp_val > 0,
            "chk_loss": bool(r["loss_apply"]),
            "loss_val": float(r["loss_val"]),
            "ts_apply": bool(r["ts_apply"]),
            "chk_ts": bool(r["ts_apply"]),
            "ts_start_val": float(r["ts_start_val"]),
            "ts_drop_val": float(r["ts_drop_val"]),
        }

