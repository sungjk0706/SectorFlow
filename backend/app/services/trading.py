# -*- coding: utf-8 -*-
"""
자동매매 실행 / 매도조건 판단
legacy_pc_engine/logic_auto_trade.py 이식 (설정은 get_settings_fn, PyQt5 제거)
"""
import time
import asyncio
import logging
from datetime import datetime

from app.services import data_manager
from app.services import telegram
from app.services.auto_trading_effective import auto_buy_effective, auto_sell_effective
from app.core.broker_factory import get_router
from app.core.trade_mode import is_test_mode
from app.services import dry_run
from app.services import trade_history
from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd

logger = logging.getLogger(__name__)


def _fire_and_forget_telegram(message: str, settings: dict | None) -> None:
    """텔레그램 알림을 NotificationWorker 큐로 전송. 예외 격리."""
    try:
        from app.services.notification_worker import NotificationWorker
        NotificationWorker.get_instance().enqueue({
            "type": "telegram",
            "message": message,
            "settings": settings,
        })
    except Exception as e:
        logger.warning("[텔레그램] 알림 큐 등록 실패: %s", e)


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
        self._daily_buy_date: str = datetime.now().strftime("%Y-%m-%d")
        self._daily_buy_spent, self._bought_today = self._restore_daily_buy_state()

    def _restore_daily_buy_state(self) -> tuple[int, set]:
        """기동 시 trade_history에서 오늘 매수 합계 + 매수 종목 set 복원."""
        try:
            rows = trade_history.get_buy_history(today_only=True)
            spent = sum(int(r.get("total_amt", 0) or 0) for r in rows)
            codes = {str(r.get("stk_cd", "")).strip() for r in rows if r.get("stk_cd")}
            codes.discard("")
            return spent, codes
        except Exception:
            return 0, set()

    def _ensure_daily_buy_counter(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_buy_date != today:
            self._daily_buy_date = today
            self._daily_buy_spent, self._bought_today = self._restore_daily_buy_state()

    def execute_buy(self, stk_cd: str, current_price: float, checked_stocks: set,
                    access_token: str, force_buy: bool = False, reason: str = "") -> bool:
        """
        매수 주문 실행.
        force_buy=True: 매수대기 수동 매수 전용. 스케줄 자동매매 게이트만 우회하고
                        나머지 판단(buy_amt, max_limit, 쓰로틀 등)은 그대로 적용.
        reason: 매수 사유 (체결 이력 기록용).
        반환값: True=주문 전송 성공, False=가드에 의해 차단/실패
        """
        settings = self._to_trade_settings(self.get_settings_fn())
        raw_all = self.get_settings_fn() or {}
        self._ensure_daily_buy_counter()

        # ── 실시간 지연 중단 게이트 ────────────────────────────────────────────
        try:
            import app.services.engine_service as _es_latency
            if _es_latency._realtime_latency_exceeded:
                self.log_callback(f"[실시간지연] {stk_cd} 매수 차단 — WS 지연 200ms 초과")
                return False
        except Exception:
            pass

        # 스케줄 자동매매 게이트: force_buy(매수대기 수동 매수) 시에만 우회
        if not settings.get("is_auto", False) and not force_buy:
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            self.log_callback(
                f" [자동매매 비활성화] {stk_nm}({stk_cd}) 주문 생략 "
                f"(force_buy={force_buy}, source=auto_signal)"
            )
            return False
        if stk_cd in self._bought_today:
            self.log_callback(f" [매수차단] {stk_cd} 오늘 이미 매수한 종목입니다.")
            return False
        if stk_cd in checked_stocks:
            self.log_callback(f" [매수차단] {stk_cd} 이미 보유/감시 중인 종목입니다.")
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
        max_limit = settings.get("max_limit", 5)
        base_settings_for_mode = self.get_settings_fn() or {}
        if is_test_mode(base_settings_for_mode):
            _positions_for_count = dry_run.get_positions()
        else:
            try:
                import app.services.engine_service as _es_pos
                _positions_for_count = _es_pos._positions
            except Exception:
                _positions_for_count = []
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
        # 일일 한도 내에서 실제 사용 가능 금액 계산 (잔여 한도가 종목당 한도보다 적으면 잔여 한도만큼만 매수)
        if max_daily_total > 0:
            daily_remain = max(0, max_daily_total - self._daily_buy_spent)
            if daily_remain <= 0:
                self.log_callback(
                    f"[일일매수한도] {stk_cd} 차단. 잔여 0원 / 한도 {max_daily_total:,}원"
                )
                return False
            effective_buy_amt = min(int(buy_amt), daily_remain)
        else:
            effective_buy_amt = int(buy_amt)

        if current_price <= 0:
            self.log_callback(f"[매수제한] {stk_cd} 서버 현재가 미수신(<=0). 주문 차단.")
            return False

        # ── 지수 가드 (설정값 기반, 시장별 독립 적용) ──────────────────────
        _kospi_on = bool(raw_all.get("buy_index_guard_kospi_on", False))
        _kosdaq_on = bool(raw_all.get("buy_index_guard_kosdaq_on", False))
        if _kospi_on or _kosdaq_on:
            try:
                import app.services.engine_service as _es_idx
                from app.services.engine_sector_score import check_index_guard
                from app.services.engine_symbol_utils import get_stock_market as _get_mkt
                _idx_triggered, _idx_reason, _k_hit, _kd_hit = check_index_guard(
                    dict(_es_idx._latest_index),
                    kospi_on=_kospi_on,
                    kosdaq_on=_kosdaq_on,
                    kospi_drop=float(raw_all.get("buy_index_kospi_drop", 2.0)),
                    kosdaq_drop=float(raw_all.get("buy_index_kosdaq_drop", 2.0)),
                )
                if _idx_triggered:
                    _mkt = _get_mkt(stk_cd) or ""
                    _block = False
                    if _mkt == "0" and _k_hit:
                        _block = True
                    elif _mkt == "10" and _kd_hit:
                        _block = True
                    elif not _mkt:
                        _block = True  # 시장 미확인 → 안전하게 차단
                    if _block:
                        self.log_callback(f"[지수가드] {stk_cd} 매수 차단 -- {_idx_reason}")
                        return False
            except Exception:
                pass

        # ── 등락률 + 거래대금 가드 (설정값 기반) ──────────────────────────────
        _change_rate_for_guard: float | None = None
        _trade_amount_for_guard: float | None = None
        _pend = (self.get_pending_fn(stk_cd) if hasattr(self, "get_pending_fn") and self.get_pending_fn else None)
        if _pend is None:
            try:
                import app.services.engine_service as _es
                _row = _es._pending_stock_details.get(stk_cd)
                if _row:
                    _change_rate_for_guard = float(_row.get("change_rate") or 0.0)
                    _trade_amount_for_guard = float(_row.get("trade_amount") or 0.0)
            except Exception:
                pass
        # 등락률 가드
        if _change_rate_for_guard is not None:
            _rise_limit = float(raw_all.get("buy_block_rise_pct", 7.0))
            _fall_limit = float(raw_all.get("buy_block_fall_pct", 7.0))
            _blocked = False
            _block_reason = ""
            if _change_rate_for_guard >= _rise_limit:
                _blocked = True
                _block_reason = f"상승률 {_change_rate_for_guard:+.1f}%"
            elif _change_rate_for_guard <= -_fall_limit:
                _blocked = True
                _block_reason = f"하락률 {abs(_change_rate_for_guard):.1f}%"
            if _blocked:
                stk_nm_g = data_manager.get_stock_name(stk_cd, access_token)
                self.log_callback(
                    f"[등락률가드] {stk_nm_g}({stk_cd}) 등락률 {_block_reason} -- 매수 차단"
                )
                return False

        # 체결강도 가드
        _min_strength = float(raw_all.get("buy_min_strength", 0))
        if _min_strength > 0:
            _strength_val: float | None = None
            if _pend is None:
                try:
                    import app.services.engine_service as _es_str
                    _str_raw = _es_str._latest_strength.get(stk_cd)
                    if _str_raw is not None:
                        _strength_val = float(_str_raw)
                except Exception:
                    pass
            if _strength_val is not None and _strength_val < _min_strength:
                stk_nm_s = data_manager.get_stock_name(stk_cd, access_token)
                self.log_callback(
                    f"[체결강도가드] {stk_nm_s}({stk_cd}) 체결강도 {_strength_val:.0f} < {_min_strength:.0f} -- 매수 차단"
                )
                return False

        buy_qty = effective_buy_amt // int(current_price)
        if buy_qty <= 0:
            return False

        # 시장가 단일 운용
        trde_tp = "3"
        order_price = 0
        order_type = "시장가"

        self._buy_state[stk_cd] = {"last_req_ts": now, "has_open_buy": True}
        stk_nm = data_manager.get_stock_name(stk_cd, access_token)

        self.log_callback(f"[매수주문] {stk_nm}({stk_cd}) 매수신호 감지. {order_type} {buy_qty}주 주문전송.")
        _fire_and_forget_telegram(f"🚀 [자동매매] {stk_nm} {buy_qty}주 매수 주문 전송 완료.", self.get_settings_fn())

        base_settings = self.get_settings_fn()

        # ── 테스트모드: 예수금 검증 (Settlement Engine) ────────────────────────
        if is_test_mode(base_settings):
            from app.services.engine_strategy_core import check_test_buy_power
            _check_price = int(order_price) if order_price > 0 else int(current_price)
            ok, reason = check_test_buy_power(
                settings, _check_price, buy_qty, self._daily_buy_spent,
            )
            if not ok:
                logger.info("[전략] 매수 거부: %s (%s)", stk_cd, reason)
                self._buy_state[stk_cd]["has_open_buy"] = False
                return False

        # ── 테스트모드 가드: 테스트모드면 실전 서버에 절대 주문 안 보냄 ─────────
        if is_test_mode(base_settings):
            _dry_price = int(order_price) if order_price > 0 else int(current_price)
            res = dry_run.fake_send_order_sync(
                base_settings, access_token, "BUY", stk_cd, buy_qty, _dry_price, trde_tp,
            )
            dry_run.set_stock_name(stk_cd, stk_nm)
        else:
            res = get_router(base_settings).order.send_order(base_settings, access_token, "BUY", stk_cd, buy_qty, int(order_price), trde_tp)

        if not (res and res.get("success")):
            self._buy_state[stk_cd]["has_open_buy"] = False
            self.log_callback(f" [매수실패] {stk_nm} 주문 전송 실패. 잠금 해제.")
            _fire_and_forget_telegram(f"⚠️ [매수실패] {stk_nm}({stk_cd}) 주문 전송 실패. 잠금 해제.", base_settings)
            return False

        fill_price = int(order_price) if order_price > 0 else int(current_price)
        spent = int(buy_qty * fill_price)
        self._daily_buy_spent += max(0, spent)

        # ── 체결 이력 기록 ────────────────────────────────────────────────────
        _buy_reason = reason or "자동매수"
        _mode = "test" if is_test_mode(base_settings) else "real"
        trade_history.record_buy(
            stk_cd=stk_cd, stk_nm=stk_nm,
            price=fill_price, qty=buy_qty,
            reason=_buy_reason, trade_mode=_mode,
        )

        # ── 매수 성공 즉시 _checked_stocks 반영 -- 다음 매수 신호에서 한도 초과 차단 ──
        checked_stocks.add(stk_cd)

        # ── 테스트모드: 매수 후 UI 즉시 갱신 (매도탭 보유종목 카드 반영) ──────
        if is_test_mode(base_settings):
            _dryrun_post_buy_broadcast(stk_cd, stk_nm)

        t_str = datetime.now().strftime("%H:%M:%S")
        fmt_price = f"{fill_price:,}"
        self.log_callback(
            f"[{t_str}] [매수주문] {stk_nm} | {order_type} | {buy_qty:,}주 | 단가: {fmt_price}원 | "
            f"일일누적매수 {self._daily_buy_spent:,}원"
        )

        # ── 매수 한도 상태 WS 브로드캐스트 ──────────────────────────────────
        try:
            import app.services.engine_service as _es_limit
            _es_limit._broadcast_buy_limit_status()
        except Exception:
            pass

        return True

    def on_fill_update(
        self, stk_cd: str, side: str, unex_qty: int, access_token: str | None = None
    ) -> None:
        nk = _format_kiwoom_reg_stk_cd(str(stk_cd or ""))
        state = self._buy_state.get(stk_cd, {"last_req_ts": 0.0, "has_open_buy": False})
        state["last_req_ts"] = time.time()
        unex = int(unex_qty) if str(unex_qty).lstrip("-").isdigit() else 0

        if str(side) == "1" and unex == 0:
            state["has_open_buy"] = False
            if stk_cd not in self._bought_today:
                self._bought_today.add(stk_cd)
                stk_nm = data_manager.get_stock_name(stk_cd, access_token)
                self.log_callback(f"[매수기억] {stk_nm} 체결 확인! 금일 매수 이력 저장 완료.")
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

        # 테스트모드: WS 체결 콜백 수신 시 dry_run 잔고 현재가 동기화
        if is_test_mode(self.get_settings_fn()):
            cur = dry_run.get_position(nk)
            if cur:
                logger.debug("[테스트모드] on_fill_update side=%s code=%s unex=%s", side, nk, unex)

    def execute_sell(
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
                _pos = dry_run.get_position(stk_cd)
                _avg_buy = int(_pos.get("avg_price", 0)) if _pos else 0
            else:
                import app.services.engine_service as _es
                for _p in _es.get_positions():
                    if _format_kiwoom_reg_stk_cd(str(_p.get("stk_cd", ""))) == stk_cd:
                        _avg_buy = int(_p.get("avg_price", 0))
                        break
        except Exception:
            pass

        # ── 테스트모드 가드: 테스트모드면 실전 서버에 절대 주문 안 보냄 ─────────
        if is_test_mode(base_settings):
            _dry_sell_price = int(order_price) if order_price > 0 else int(cur_price)
            result = dry_run.fake_send_order_sync(
                base_settings, access_token, "SELL", stk_cd, qty, _dry_sell_price, trde_tp,
            )
        else:
            result = get_router(base_settings).order.send_order(base_settings, access_token, "SELL", stk_cd, qty, int(order_price), trde_tp)

        if not result.get("success"):
            self._recent_sells.discard(stk_cd)
            self.log_callback(f"[매도] {stk_nm} 주문 전송 실패: {result.get('msg', '알 수 없음')}")
            _fire_and_forget_telegram(f"⚠️ [매도실패] {stk_nm}({stk_cd}) 주문 전송 실패: {result.get('msg', '알 수 없음')}", base_settings)
            return

        t_str = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{t_str}] [매도주문] {stk_nm} | {reason} | {order_type} | {qty:,}주 | 평가손익: {pnl_rate}%")

        # ── 체결 이력 기록 ────────────────────────────────────────────────────
        _sell_price = int(order_price) if order_price > 0 else int(cur_price)
        trade_history.record_sell(
            stk_cd=stk_cd, stk_nm=stk_nm,
            price=_sell_price, qty=qty,
            avg_buy_price=_avg_buy, reason=reason,
            pnl_rate=pnl_rate, trade_mode=_mode,
        )

        # 테스트 모드: dry_run이 이미 가상 잔고를 갱신했으므로 UI 브로드캐스트만 트리거
        if is_test_mode(base_settings):
            _dryrun_post_sell_broadcast(stk_cd, stk_nm, base_settings)

    def check_sell_conditions(self, stock_list: list, base_settings: dict, access_token: str) -> None:
        settings = self._to_trade_settings(base_settings)
        if not settings.get("is_sell_auto", False):
            return

        # ── 실시간 지연 중단 게이트 ────────────────────────────────────────────
        try:
            import app.services.engine_service as _es_latency
            if _es_latency._realtime_latency_exceeded:
                self.log_callback("[실시간지연] 매도 조건 전체 차단 — WS 지연 200ms 초과")
                return
        except Exception:
            pass

        for stock in stock_list:
            s = dict(settings)
            stk_cd = _format_kiwoom_reg_stk_cd(str(stock.get("stk_cd", "") or ""))
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
                        self.execute_sell(stk_cd, cur_price, stk_nm, "손절 발동", sell_qty, pnl_rate, s, base_settings, access_token)
                    except Exception:
                        pass
                    continue

            if s.get("chk_tp", False):
                tp_val = float(s.get("tp_val") or 0)
                hit_tp = pnl_rate >= tp_val
                if hit_tp:
                    try:
                        self.execute_sell(stk_cd, cur_price, stk_nm, "익절 발동", sell_qty, pnl_rate, s, base_settings, access_token)
                    except Exception:
                        pass
                    continue

            if s.get("chk_ts", False):
                ts_start_val = float(s.get("ts_start_val") or 0)
                ts_drop_val = float(s.get("ts_drop_val") or 0)

                if max_reached["pnl_rate"] >= ts_start_val:
                    drop_rate = ((highest_price - cur_price) / highest_price * 100) if highest_price > 0 else 0
                    if drop_rate >= ts_drop_val:
                        self.execute_sell(stk_cd, cur_price, stk_nm, "T/S 익절", sell_qty, pnl_rate, s, base_settings, access_token)

    def _to_trade_settings(self, raw: dict) -> dict:
        """engine_settings 형식을 logic_auto_trade 호환 형식으로 변환."""
        r = raw or {}
        tp_val = float(r.get("tp_val") or 0)
        tp_on = bool(r.get("tp_apply", True))
        return {
            "is_auto": auto_buy_effective(r),
            "is_sell_auto": auto_sell_effective(r),
            "max_limit": int(r.get("max_stock_cnt") or 5),
            "buy_amt": int(r.get("buy_amt") or 0),
            "max_daily_total_buy_amt": int(r.get("max_daily_total_buy_amt") or 0),
            "is_sell_mkt": (r.get("sell_price_type") or "mkt") == "mkt",
            "sell_offset": int(r.get("sell_offset") or 0),
            "sell_custom_qty": int(r.get("sell_custom_qty") or 0),
            "sell_qty_type": r.get("sell_qty_type") or "%",
            "tp_val": tp_val,
            "tp_apply": tp_on,
            "chk_tp": tp_on and tp_val > 0,
            "chk_loss": bool(r.get("loss_apply")),
            "loss_val": float(r.get("loss_val") or 0),
            "ts_apply": bool(r.get("ts_apply")),
            "chk_ts": bool(r.get("ts_apply")),
            "ts_start_val": float(r.get("ts_start_val") or 0),
            "ts_drop_val": float(r.get("ts_drop_val") or 0),
        }

# ── 테스트 모드 전용: 매수 후 UI 브로드캐스트 ────────────────────────────────
# dry_run 모듈이 가상 잔고를 이미 갱신했으므로, UI 갱신만 트리거.

_DRYRUN_BUY_BROADCAST_DELAY: float = 0.15


def _dryrun_post_buy_broadcast(stk_cd: str, stk_nm: str) -> None:
    """테스트모드 매수 후 UI 잔고 브로드캐스트 -- 매도탭 보유종목 카드 즉시 반영."""
    try:
        from app.services import engine_service as es
        es._refresh_account_snapshot_meta()
        es._broadcast_account(reason="dryrun_buy")
        logger.info("[테스트모드] 매수 후 UI 갱신 완료 -- %s(%s)", stk_nm, stk_cd)
    except Exception as e:
        logger.warning("[테스트모드] 매수 후 UI 갱신 실패: %s", e)


def _dryrun_post_sell_broadcast(stk_cd: str, stk_nm: str, settings: dict) -> None:
    """테스트모드 매도 후 UI 잔고 브로드캐스트."""
    try:
        from app.services import engine_service as es

        # 가상 잔고에서 매도 완료된 종목 -- _recent_sells 차단 해제
        if es._auto_trade:
            dry_codes = dry_run.position_codes()
            sold_out = set(es._auto_trade._recent_sells) - dry_codes
            es._auto_trade._recent_sells -= sold_out
            if sold_out:
                logger.info("[테스트모드] 매도 체결 확인 -- 차단 해제: %s", sold_out)

        es._broadcast_account(reason="dryrun_sell")
        logger.info("[테스트모드] 매도 후 UI 갱신 완료 -- %s(%s)", stk_nm, stk_cd)
    except Exception as e:
        logger.warning("[테스트모드] 매도 후 UI 갱신 실패: %s", e)
