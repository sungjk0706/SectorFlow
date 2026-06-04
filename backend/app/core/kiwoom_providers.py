from __future__ import annotations
# -*- coding: utf-8 -*-
"""
키움증권 Provider 구현체

기존 코드를 최대한 재사용하며, 각 Provider가 해당 기능만 캡슐화:
  - KiwoomAuthProvider      : KiwoomRestAPI 토큰 관리 위임
  - KiwoomAccountProvider   : KiwoomRestAPI 계좌 조회 위임
  - KiwoomOrderProvider     : kiwoom_order.send_order 캡슐화
  - KiwoomStockProvider     : kiwoom_stock_rest + kiwoom_daily_avg_volume 캡슐화
  - KiwoomWebSocketProvider : broker_urls 기반 WS URI 제공
"""

import asyncio
import logging
from backend.app.core.trade_mode import is_test_mode
from typing import Callable, Optional

from backend.app.core.broker_providers import (
    AccountProvider,
    AuthProvider,
    OrderProvider,
    WebSocketProvider,
)
from backend.app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)


# ── Auth Provider ─────────────────────────────────────────────────────
class KiwoomAuthProvider(AuthProvider):
    """기존 KiwoomRestAPI의 토큰 관리 로직 위임."""

    def __init__(self):
        from backend.app.services.engine_state import state
        app_key = (state.integrated_system_settings_cache.get("kiwoom_app_key_real") or state.integrated_system_settings_cache.get("kiwoom_app_key") or "").strip()
        app_secret = (state.integrated_system_settings_cache.get("kiwoom_app_secret_real") or state.integrated_system_settings_cache.get("kiwoom_app_secret") or "").strip()
        self._rest_api = KiwoomRestAPI(app_key, app_secret)
        self._rest_api._acnt_no = str(
            state.integrated_system_settings_cache.get("kiwoom_account_no_real") or state.integrated_system_settings_cache.get("kiwoom_account_no", "") or ""
        )

    async def get_access_token(self) -> Optional[str]:
        return await self._rest_api.get_access_token()

    async def ensure_token(self) -> bool:
        return await self._rest_api._ensure_token()

    @property
    def broker_name(self) -> str:
        return "kiwoom"

    @property
    def rest_api(self) -> KiwoomRestAPI:
        """내부 REST API 인스턴스 접근 (키움 전용 확장 메서드용)."""
        return self._rest_api


# ── Account Provider ──────────────────────────────────────────────────
class KiwoomAccountProvider(AccountProvider):
    """기존 KiwoomRestAPI 계좌 조회 로직 위임."""

    def __init__(
        self,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        from backend.app.services.engine_state import state
        self._auth = auth_provider
        self._rest_api = auth_provider.rest_api if auth_provider else None
        self._acnt_no = str(state.integrated_system_settings_cache.get("kiwoom_account_no", "") or "")

    async def get_account_number(self) -> Optional[str]:
        if self._rest_api is None:
            return None
        return await self._rest_api.get_account_number()

    async def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        if self._rest_api is None:
            return None
        resolved = acnt_no or self._acnt_no
        self._rest_api._acnt_no = resolved
        return await self._rest_api.get_deposit_detail(acnt_no=resolved)

    async def get_balance_detail(
        self, qry_tp: str = "1", dmst_stex_tp: str = "KRX"
    ) -> Optional[dict]:
        if self._rest_api is None:
            return None
        return await self._rest_api.get_balance_detail(qry_tp, dmst_stex_tp)

    async def get_account_balance(self, acnt_no: str = "") -> dict:
        """
        [공통 표준] 계좌 잔고 통합 조회.
        kt00001(예수금) + kt00018(평가잔고) 결합 → 표준 구조 반환.
        기존 KiwoomBroker.get_account_balance() 로직 그대로 이동.
        """
        _empty: dict = {
            "success": False,
            "summary": {
                "tot_eval": 0, "tot_pnl": 0, "tot_buy": 0,
                "deposit": 0, "orderable": 0, "withdrawable": 0,
                "total_rate": 0.0,
            },
            "stock_list": [],
            "raw_data": {},
        }
        if self._rest_api is None:
            return _empty
        if not await self._rest_api._ensure_token():
            _log.warning(
                "[키움증권계좌] 토큰 없음 -- 계좌잔고 조회 중단"
            )
            return _empty

        resolved = acnt_no or self._acnt_no

        def _n(v) -> int:
            try:
                return int(str(v).replace(",", "") or 0)
            except (ValueError, TypeError):
                return 0

        def _f(v) -> float:
            try:
                return float(
                    str(v).replace(",", "").replace("%", "") or 0
                )
            except (ValueError, TypeError):
                return 0.0

        dep_raw = await self._rest_api.get_deposit_detail(acnt_no=resolved)
        await asyncio.sleep(0.5)  # 429 예방
        bal_raw = await self._rest_api.get_balance_detail()

        if not dep_raw:
            _log.warning("[키움증권계좌] kt00001 응답 없음")
            return _empty

        dep_body = dep_raw.get("body") or dep_raw
        if _n(dep_body.get("return_code", 0)) != 0:
            _log.warning(
                "[키움증권계좌] kt00001 오류 return_code=%s msg=%s",
                dep_body.get("return_code"),
                dep_body.get("return_msg", ""),
            )
            return _empty

        deposit = _n(
            dep_body.get("entr", dep_body.get("d2_entra", 0))
        )
        orderable = _n(dep_body.get("ord_alow_amt", 0))
        withdrawable = _n(dep_body.get("pymn_alow_amt", 0))
        tot_eval = 0
        tot_pnl = 0
        total_rate = 0.0
        tot_buy = 0

        stock_list: list = []
        if bal_raw:
            bal = bal_raw.get("body") or bal_raw
            if _n(bal.get("return_code", 0)) == 0:
                tot_eval = _n(bal.get("tot_evlt_amt", 0))
                tot_pnl = _n(bal.get("tot_evlt_pl", 0))
                tot_buy = _n(bal.get("tot_pur_amt", 0))
                total_rate = _f(bal.get("tot_prft_rt", 0))
                if not deposit:
                    deposit = _n(bal.get("prsm_dpst_aset_amt", 0))

            for item in bal.get("acnt_evlt_remn_indv_tot", []):
                stk_cd = str(item.get("stk_cd", "")).strip().lstrip("A")
                if not stk_cd:
                    continue
                qty = _n(item.get("rmnd_qty", 0))
                if qty <= 0:
                    continue
                stock_list.append({
                    "stk_cd": stk_cd,
                    "stk_nm": str(item.get("stk_nm", stk_cd)).strip(),
                    "qty": qty,
                    "buy_price": _n(item.get("buy_uv", 0)),
                    "cur_price": _n(item.get("cur_pric", 0)),
                    "buy_amt": _n(item.get("buy_amt", 0)),
                    "pnl_amt": _n(item.get("evlt_ploss", 0)),
                    "pnl_rate": _f(item.get("prft_rt", 0)),
                    "crd_tp": str(item.get("crd_tp", "") or "").strip(),
                })

        _log.info(
            "[키움증권계좌] 잔고 조회 완료 -- 총평가 %s원 | 손익 %s원 | 종목 %d개",
            f"{tot_eval:,}",
            f"{tot_pnl:,}",
            len(stock_list),
        )
        return {
            "success": True,
            "summary": {
                "tot_eval": tot_eval,
                "tot_pnl": tot_pnl,
                "tot_buy": tot_buy,
                "deposit": deposit,
                "orderable": orderable,
                "withdrawable": withdrawable,
                "total_rate": total_rate,
            },
            "stock_list": stock_list,
            "raw_data": dep_body,
        }


# ── Order Provider ────────────────────────────────────────────────────
class KiwoomOrderProvider(OrderProvider):
    """기존 kiwoom_order.send_order 함수 캡슐화."""

    def __init__(
        self,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        self._auth = auth_provider

    async def send_order(
        self,
        settings: dict,
        access_token: str,
        order_type: str,
        code: str,
        qty: int,
        price: int = 0,
        trde_tp: str = "3",
        orig_ord_no: str = "",
    ) -> dict:
        from backend.app.core.kiwoom_order import send_order as _kiwoom_send_order

        return await _kiwoom_send_order(
            settings,
            access_token,
            order_type,
            code,
            qty,
            price=price,
            trde_tp=trde_tp,
            orig_ord_no=orig_ord_no,
        )


# ── Stock Provider ─────────────────────────────────────────────────────
class KiwoomStockProvider:
    """키움 주식 데이터 Provider (ka10099, ka10081 캡슐화)."""

    def __init__(
        self,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        if auth_provider is not None and not isinstance(auth_provider, KiwoomAuthProvider):
            raise TypeError(
                f"KiwoomStockProvider는 KiwoomAuthProvider만 지원합니다. "
                f"전달된 타입: {type(auth_provider).__name__}"
            )
        self._auth = auth_provider
        self._rest_api = auth_provider.rest_api if auth_provider else None

    async def fetch_all_stocks(
        self,
        *,
        http_timeout: float = 15.0,
    ) -> list:
        """ka10099 코스피+코스닥 2회 호출 → 전체 종목 통합 정보 반환."""
        if self._rest_api is None:
            return []
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        return await fetch_ka10099_unified(self._rest_api, http_timeout=http_timeout)

    async def fetch_stock_daily_price(
        self, stk_cd: str, qry_dt: str
    ) -> dict | None:
        """ka10081 단건 조회 -- 장외 시간 확정 종가·등락률·거래대금 반환 (1일봉)."""
        if self._rest_api is None:
            return None
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        return await fetch_ka10081_daily_price(self._rest_api, stk_cd, qry_dt)

    async def fetch_stock_5day_data(
        self, stk_cd: str, qry_dt: str
    ) -> dict | None:
        """ka10081 단건 조회 -- 최근 5개 일봉에서 5일 평균 거래대금 및 최고가 계산 반환."""
        if self._rest_api is None:
            return None
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        return await fetch_ka10081_daily_5d_data(self._rest_api, stk_cd, qry_dt)

    async def fetch_all_stocks_5day(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.33,
        on_progress: "Callable[[int, int], None] | None" = None,
        resume_codes: "set[str] | None" = None,
    ) -> dict[str, dict]:
        """전체 종목 ka10081 순차 조회 -- 5일봉 데이터 채우기용."""
        if self._rest_api is None:
            return {}
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_5day
        return await fetch_ka10081_all_stocks_5day(
            krx_codes, qry_dt, interval_sec=interval_sec, on_progress=on_progress, resume_codes=resume_codes
        )

    async def fetch_all_stocks_daily_confirmed(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.33,
        on_progress: "Callable[[int, int], None] | None" = None,
        resume_codes: "set[str] | None" = None,
    ) -> dict[str, dict]:
        """전체 종목 ka10081 순차 조회 -- 확정 시세(1일봉) 데이터 채우기용."""
        if self._rest_api is None:
            return {}
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        return await fetch_ka10081_all_stocks_daily_confirmed(
            self._rest_api, krx_codes, qry_dt, interval_sec=interval_sec, on_progress=on_progress, resume_codes=resume_codes
        )


# ── WebSocket Provider ────────────────────────────────────────────────
class KiwoomWebSocketProvider(WebSocketProvider):
    """기존 broker_urls 기반 WS URI 제공."""

    def __init__(
        self,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        self._auth = auth_provider

    def get_ws_uri(self) -> str:
        from backend.app.core.broker_urls import build_broker_urls

        return build_broker_urls("kiwoom")["ws_uri"]

