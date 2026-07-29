# -*- coding: utf-8 -*-
"""
Risk Management Layer - 주문 전 리스크 통제

책임:
  1. 서킷브레이커: 연속 주문 실패 시 계좌 보호
  2. Max Exposure (최대 노출 한도): 잔여 예수금 및 현재 보유 총액 기반 한도 초과 방지
  3. Daily Loss Limit (일일 손실 한도): 당일 실현손실이 임계치 초과 시 매수 차단
  4. Single Stock Limit (단일 종목 한도): 한 종목에 대한 과도한 비중 제한

OMS(Order Management System)로 들어가기 전 필수 관문(Gateway) 역할을 수행합니다.
"""
from __future__ import annotations
from typing import Optional
import logging
from backend.app.services.circuit_breaker import get_circuit_breaker
from backend.app.services.trade_history import get_total_realized_pnl
from backend.app.core.trade_mode import is_test_mode
logger = logging.getLogger(__name__)


def _notify_telegram(message: str, settings: dict | None) -> None:
    """텔레그램 알림을 NotificationWorker 큐로 전송. 예외 격리.

    P23(일관성): trading.py `_fire_and_forget_telegram`·engine_ws_dispatch.py
    `_notify_krx_cb_telegram`과 동일 패턴. risk_manager→trading 순환 import 회피.
    """
    try:
        from backend.app.services.notification_worker import NotificationWorker
        NotificationWorker.get_instance().enqueue({
            "type": "telegram",
            "message": message,
            "settings": settings,
        })
    except Exception as e:
        logger.warning("[리스크] 텔레그램 알림 큐 등록 실패: %s", e, exc_info=True)


class RiskManager:
    """통합 리스크 관리자"""

    def __init__(self):
        self.circuit_breaker = get_circuit_breaker()
        self._sync_thresholds()

    def _sync_thresholds(self) -> None:
        """engine_state 설정 캐시에서 리스크 임계치 동기화."""
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        self.daily_loss_limit = int(cache.get("daily_loss_limit", -500000) or -500000)
        self.max_single_stock_exposure = int(cache.get("max_single_stock_exposure", 20000000) or 20000000)
        # 신규 — 리스크 매니저 확장 (P13 메모리 상주)
        self.risk_manager_on = bool(cache.get("risk_manager_on", False))
        self.daily_loss_limit_on = bool(cache.get("daily_loss_limit_on", True))
        self.daily_loss_rate_limit_on = bool(cache.get("daily_loss_rate_limit_on", False))
        self.daily_loss_rate_limit = float(cache.get("daily_loss_rate_limit", -5.0) or -5.0)
        self.risk_block_buy_on = bool(cache.get("risk_block_buy_on", True))
        self.risk_block_sell_on = bool(cache.get("risk_block_sell_on", False))
        self.consecutive_loss_limit_on = bool(cache.get("consecutive_loss_limit_on", False))
        self.consecutive_loss_limit = int(cache.get("consecutive_loss_limit", 3) or 3)
        # 시장 지수 급락 가드 (P13 메모리 상주)
        self.market_guard_on = bool(cache.get("market_guard_on", False))
        self.market_guard_buy_block_on = bool(cache.get("market_guard_buy_block_on", True))
        self.market_guard_sell_block_on = bool(cache.get("market_guard_sell_block_on", False))
        self.market_guard_kospi_on = bool(cache.get("market_guard_kospi_on", False))
        self.market_guard_kospi_drop_threshold_pct = float(cache.get("market_guard_kospi_drop_threshold_pct", -5.0) or -5.0)
        self.market_guard_kosdaq_on = bool(cache.get("market_guard_kosdaq_on", False))
        self.market_guard_kosdaq_drop_threshold_pct = float(cache.get("market_guard_kosdaq_drop_threshold_pct", -5.0) or -5.0)

    async def _get_consecutive_loss_count(self, trade_mode: str) -> int:
        """최근 매도 거래 기준 연속 손실 횟수 반환.

        trade_history.get_sell_history()는 DESC 정렬(최신순).
        최신 매도부터 역순으로 realized_pnl < 0인 거래가 연속 몇 건인지 카운트.
        매도 이력이 없거나 최신 거래가 수익이면 0 반환.
        """
        from backend.app.services.trade_history import get_sell_history
        rows = await get_sell_history(trade_mode=trade_mode)
        count = 0
        for r in rows:
            pnl = int(r.get("realized_pnl", 0) or 0)
            if pnl < 0:
                count += 1
            else:
                break  # 연속 손실 끊김
        return count

    async def _check_extended_buy_risk(self, trade_mode: str, today_pnl: int) -> tuple[bool, str]:
        """신규 리스크 조건 검사 (risk_manager_on + risk_block_buy_on 시에만 호출).

        기존 일일 손실 한도/예수금/단일 종목 비중은 check_buy_order_allowed 본문에서
        항상 실행되므로 여기서는 신규 4개 조건만 검사.
        반환: (allowed, reason) — allowed=False 시 차단 사유.
        """
        from backend.app.services.trade_history import get_buy_history
        buy_rows = await get_buy_history(today_only=True, trade_mode=trade_mode)
        today_principal = sum(int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0) for r in buy_rows)

        # 1. 일일 손실률 한도
        if self.daily_loss_rate_limit_on and today_principal > 0:
            today_pnl_rate = today_pnl / today_principal * 100
            if today_pnl_rate <= self.daily_loss_rate_limit:
                logger.warning("[매매] 일일 손실률 한도 초과: 현재 %.2f%%, 한도 %.2f%%", today_pnl_rate, self.daily_loss_rate_limit)
                # P21 사용자 투명성 — 자동매매 중단 상태 텔레그램 알림 (매 건 전송)
                from backend.app.services.engine_state import state as engine_state
                _notify_telegram(
                    f"🛑 [자동매매 중단] 일일 손실률 한도 도달 — 당일 손실률 {today_pnl_rate:.2f}%, 한도 {self.daily_loss_rate_limit:.2f}%. 자동매매가 중단된 상태입니다.",
                    engine_state.integrated_system_settings_cache,
                )
                return False, "일일 손실률 한도 초과"

        # 2. 연속 손실 횟수
        if self.consecutive_loss_limit_on:
            consec_count = await self._get_consecutive_loss_count(trade_mode)
            if consec_count >= self.consecutive_loss_limit:
                logger.warning("[매매] 연속 손실 한도 초과: 현재 %d회, 한도 %d회", consec_count, self.consecutive_loss_limit)
                return False, f"연속 손실 한도 초과 ({consec_count}회)"

        return True, ""

    def _check_market_drop(self) -> tuple[bool, str]:
        """시장 지수 급락 가드 — KOSPI/KOSDAQ 각각 독립 평가.

        P10 SSOT: engine_state.index_data_cache[upcode]["drate"] (등락률 %) 사용.
        upcode: KOSPI="001", KOSDAQ="301" (frontend header.ts SSOT와 동일).
        지수 데이터 수신 불가(캐시 비어있음/변환 실패) 시 차단하지 않음 — P20 준수 (silent pass 금지 → 경고 로그).
        반환: (allowed, reason) — allowed=False 시 차단 사유.
        """
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.index_data_cache

        # KOSPI 검사
        if self.market_guard_kospi_on:
            kospi = cache.get("001")
            if kospi:
                try:
                    drate = float(str(kospi.get("drate", "") or "").strip())
                    if drate <= self.market_guard_kospi_drop_threshold_pct:
                        logger.warning("[매매] 시장 지수 급락 가드 — KOSPI 등락률 %.2f%%, 임계 %.2f%%", drate, self.market_guard_kospi_drop_threshold_pct)
                        _notify_telegram(
                            f"🛑 [자동매매 중단] KOSPI 급락 — 등락률 {drate:.2f}%, 임계 {self.market_guard_kospi_drop_threshold_pct:.2f}%. 자동매매가 중단된 상태입니다.",
                            engine_state.integrated_system_settings_cache,
                        )
                        return False, f"KOSPI 급락 ({drate:.2f}%)"
                except (ValueError, TypeError):
                    logger.warning("[리스크] KOSPI 등락률 변환 실패 — 가드 skip: %r", kospi.get("drate"), exc_info=True)
            else:
                logger.warning("[리스크] KOSPI 지수 데이터 수신 불가 — 가드 skip (차단하지 않음)")

        # KOSDAQ 검사
        if self.market_guard_kosdaq_on:
            kosdaq = cache.get("301")
            if kosdaq:
                try:
                    drate = float(str(kosdaq.get("drate", "") or "").strip())
                    if drate <= self.market_guard_kosdaq_drop_threshold_pct:
                        logger.warning("[매매] 시장 지수 급락 가드 — KOSDAQ 등락률 %.2f%%, 임계 %.2f%%", drate, self.market_guard_kosdaq_drop_threshold_pct)
                        _notify_telegram(
                            f"🛑 [자동매매 중단] KOSDAQ 급락 — 등락률 {drate:.2f}%, 임계 {self.market_guard_kosdaq_drop_threshold_pct:.2f}%. 자동매매가 중단된 상태입니다.",
                            engine_state.integrated_system_settings_cache,
                        )
                        return False, f"KOSDAQ 급락 ({drate:.2f}%)"
                except (ValueError, TypeError):
                    logger.warning("[리스크] KOSDAQ 등락률 변환 실패 — 가드 skip: %r", kosdaq.get("drate"), exc_info=True)
            else:
                logger.warning("[리스크] KOSDAQ 지수 데이터 수신 불가 — 가드 skip (차단하지 않음)")

        return True, ""

    async def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매수 주문 허용 여부 검사. 테스트/실전 모드 공통 호출.
        모드 분기는 돈 I/O(예수금·포지션 조회) 최소 지점에서만 수행 — 원칙 18.

        기존 체크(일일 손실 한도/예수금/단일 종목 비중)는 항상 실행.
        신규 조건(손실률/수익/수익률/연속손실)은 risk_manager_on + risk_block_buy_on 시에만 실행.
        """
        self._sync_thresholds()

        # 1. 서킷브레이커 검사 (공통 — 항상 동작)
        if not self.circuit_breaker.allow_request():
            return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"

        # 2. 일일 손실 한도 검사 (기본 관문 — daily_loss_limit_on ON 시에만, 기본 ON)
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        trade_mode = "test" if is_test_mode(cache) else "real"
        today_pnl = await get_total_realized_pnl(today_only=True, trade_mode=trade_mode)
        if self.daily_loss_limit_on and today_pnl <= self.daily_loss_limit:
            logger.warning("[매매] 일일 손실 한도 초과: 현재 %s, 한도 %s", f"{today_pnl:,}", f"{self.daily_loss_limit:,}")
            # P21 사용자 투명성 — 자동매매 중단 상태 텔레그램 알림 (매 건 전송)
            _notify_telegram(
                f"🛑 [자동매매 중단] 일일 손실 한도 도달 — 당일 손실 {today_pnl:,}원, 한도 {self.daily_loss_limit:,}원. 자동매매가 중단된 상태입니다.",
                cache,
            )
            return False, "일일 손실 한도 초과"

        # 3. 신규 리스크 조건 (risk_manager_on + risk_block_buy_on 시에만)
        if self.risk_manager_on and self.risk_block_buy_on:
            allowed, reason = await self._check_extended_buy_risk(trade_mode, today_pnl)
            if not allowed:
                return False, reason

        # 3-1. 시장 지수 급락 가드 (market_guard_on + market_guard_buy_block_on 시에만)
        if self.market_guard_on and self.market_guard_buy_block_on:
            allowed, reason = self._check_market_drop()
            if not allowed:
                return False, reason

        order_amount = price * qty

        # 4. 예수금 잔액 검사 (모드 분기 — 돈 I/O, 항상 실행)
        withdrawable = self.get_withdrawable_deposit()
        if order_amount > withdrawable:
            logger.warning("[매매] 예수금 부족: 주문액 %s, 출금가능액 %s", f"{order_amount:,}", f"{withdrawable:,}")
            return False, "예수금 잔고 부족"

        # 5. 단일 종목 비중 한도 검사 (모드 분기 — 돈 I/O, 항상 실행)
        existing_position_amount = 0
        if is_test_mode(cache):
            from backend.app.services import dry_run
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            pos = await dry_run.get_position(stk_cd)
            if pos:
                existing_position_amount = int(pos.get("buy_amount", 0) or 0)
        else:
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            nk = _base_stk_cd(stk_cd)
            for p in engine_state.positions:
                if _base_stk_cd(str(p.get("stk_cd", "") or "")) == nk:
                    existing_position_amount = int(p.get("buy_amount", 0) or 0)
                    break
        total_after_buy = existing_position_amount + order_amount
        if self.max_single_stock_exposure > 0 and total_after_buy > self.max_single_stock_exposure:
            logger.warning("[매매] 단일 종목 비중 초과: %s 기존 %s + 주문 %s = %s, 한도 %s",
                           stk_cd, f"{existing_position_amount:,}", f"{order_amount:,}", f"{total_after_buy:,}", f"{self.max_single_stock_exposure:,}")
            return False, f"단일 종목 비중 한도 초과 ({stk_cd})"

        return True, "승인"

    def get_withdrawable_deposit(self) -> int:
        """주문 가능한 예수금/가용금액을 모드에 따라 반환.

        - 테스트모드: settlement_engine.get_available_cash()
        - 실전모드: account_snapshot['orderable']
        """
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        if is_test_mode(cache):
            from backend.app.services.settlement_engine import get_available_cash
            return get_available_cash()
        return int(engine_state.account_snapshot.get("orderable", 0) or 0)

    async def check_sell_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매도 주문 허용 여부 검사.

        매도는 리스크 축소 행위이지만, 사용자가 risk_block_sell_on 활성화 시
        수익/손실 한도 도달 시 매도도 차단 가능.
        서킷브레이커는 항상 동작 (계좌 보호 최소 안전장치).
        """
        self._sync_thresholds()

        # 1. 서킷브레이커 (항상 동작)
        if not self.circuit_breaker.allow_request():
            return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"

        # 2. 신규 매도 리스크 조건 (risk_manager_on + risk_block_sell_on 시에만)
        if self.risk_manager_on and self.risk_block_sell_on:
            from backend.app.services.engine_state import state as engine_state
            cache = engine_state.integrated_system_settings_cache
            trade_mode = "test" if is_test_mode(cache) else "real"
            today_pnl = await get_total_realized_pnl(today_only=True, trade_mode=trade_mode)

            # 일일 손실 한도 (매도 차단 시 손실 확대 위험 — daily_loss_limit_on ON 시에만)
            if self.daily_loss_limit_on and today_pnl <= self.daily_loss_limit:
                return False, "일일 손실 한도 초과 (매도 차단)"

            from backend.app.services.trade_history import get_buy_history
            buy_rows = await get_buy_history(today_only=True, trade_mode=trade_mode)
            today_principal = sum(int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0) for r in buy_rows)

            # 일일 손실률 한도
            if self.daily_loss_rate_limit_on and today_principal > 0:
                today_pnl_rate = today_pnl / today_principal * 100
                if today_pnl_rate <= self.daily_loss_rate_limit:
                    return False, "일일 손실률 한도 초과 (매도 차단)"

            # 연속 손실 횟수
            if self.consecutive_loss_limit_on:
                consec_count = await self._get_consecutive_loss_count(trade_mode)
                if consec_count >= self.consecutive_loss_limit:
                    return False, f"연속 손실 한도 초과 (매도 차단, {consec_count}회)"

        # 2-1. 시장 지수 급락 가드 (market_guard_on + market_guard_sell_block_on 시에만)
        if self.market_guard_on and self.market_guard_sell_block_on:
            allowed, reason = self._check_market_drop()
            if not allowed:
                return False, f"{reason} (매도 차단)"

        return True, "승인"

    def record_order_success(self) -> None:
        """주문 성공 시 서킷브레이커에 보고"""
        self.circuit_breaker.record_success()

    def record_order_failure(self) -> None:
        """주문 실패 시 서킷브레이커에 보고"""
        self.circuit_breaker.record_failure()


# 싱글톤 인스턴스
_risk_manager: Optional[RiskManager] = None

def get_risk_manager() -> RiskManager:
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
