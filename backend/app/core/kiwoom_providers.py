# -*- coding: utf-8 -*-
"""
키움증권 Provider 구현체

기존 코드를 최대한 재사용하며, 각 Provider가 해당 기능만 캡슐화:
  - KiwoomAuthProvider      : KiwoomRestAPI 토큰 관리 위임
  - KiwoomAccountProvider   : KiwoomRestAPI 계좌 조회 위임
  - KiwoomOrderProvider     : kiwoom_order.send_order 캡슐화
  - KiwoomSectorProvider    : kiwoom_sector_rest + kiwoom_daily_avg_volume 캡슐화
  - KiwoomWebSocketProvider : broker_urls 기반 WS URI 제공
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from app.core.broker_providers import (
    AccountProvider,
    AuthProvider,
    OrderProvider,
    SectorProvider,
    WebSocketProvider,
)
from app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)


# ── Auth Provider ─────────────────────────────────────────────────────
class KiwoomAuthProvider(AuthProvider):
    """기존 KiwoomRestAPI의 토큰 관리 로직 위임."""

    def __init__(self, settings: dict):
        self._settings = settings
        app_key = (settings.get("kiwoom_app_key") or "").strip()
        app_secret = (settings.get("kiwoom_app_secret") or "").strip()
        self._rest_api = KiwoomRestAPI(app_key, app_secret)
        self._rest_api._acnt_no = str(
            settings.get("kiwoom_account_no", "") or ""
        )

    def get_access_token(self) -> Optional[str]:
        return self._rest_api.get_access_token()

    def ensure_token(self) -> bool:
        return self._rest_api._ensure_token()

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
        settings: dict,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        self._settings = settings
        self._auth = auth_provider
        self._rest_api = auth_provider.rest_api if auth_provider else None
        self._acnt_no = str(settings.get("kiwoom_account_no", "") or "")

    def get_account_number(self) -> Optional[str]:
        if self._rest_api is None:
            return None
        return self._rest_api.get_account_number()

    def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        if self._rest_api is None:
            return None
        resolved = acnt_no or self._acnt_no
        self._rest_api._acnt_no = resolved
        return self._rest_api.get_deposit_detail(acnt_no=resolved)

    def get_balance_detail(
        self, qry_tp: str = "1", dmst_stex_tp: str = "KRX"
    ) -> Optional[dict]:
        if self._rest_api is None:
            return None
        return self._rest_api.get_balance_detail(qry_tp, dmst_stex_tp)

    def get_account_balance(self, acnt_no: str = "") -> dict:
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
        if not self._rest_api._ensure_token():
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

        dep_raw = self._rest_api.get_deposit_detail(acnt_no=resolved)
        time.sleep(0.5)  # 429 예방
        bal_raw = self._rest_api.get_balance_detail()

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
        settings: dict,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        self._settings = settings
        self._auth = auth_provider

    def send_order(
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
        from app.core.kiwoom_order import send_order as _kiwoom_send_order

        return _kiwoom_send_order(
            settings,
            access_token,
            order_type,
            code,
            qty,
            price=price,
            trde_tp=trde_tp,
            orig_ord_no=orig_ord_no,
        )


# ── Sector Provider ───────────────────────────────────────────────────
class KiwoomSectorProvider(SectorProvider):
    """기존 kiwoom_sector_rest + kiwoom_daily_avg_volume 캡슐화."""

    def __init__(
        self,
        settings: dict,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        self._settings = settings
        self._auth = auth_provider
        self._rest_api = auth_provider.rest_api if auth_provider else None

    def fetch_daily_price(
        self, stk_cd: str, qry_dt: str
    ) -> Optional[dict]:
        if self._rest_api is None:
            return None
        return self._rest_api.fetch_ka10086_daily_price(stk_cd, qry_dt)

    def fetch_sector_all_daily(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.1,
        on_progress: Callable[[int, int], None] | None = None,
        resume_codes: set[str] | None = None,
    ) -> dict[str, dict]:
        if self._rest_api is None:
            return {}
        return self._rest_api.fetch_ka10086_sector_all(
            krx_codes, qry_dt, interval_sec=interval_sec, on_progress=on_progress,
            resume_codes=resume_codes
        )

    def fetch_industry_stocks(self, inds_cd: str) -> list[dict]:
        # ka20002 삭제됨 — 빈 리스트 반환
        return []

    def fetch_avg_amt_5d(self, stk_cd: str) -> int:
        if self._rest_api is None:
            return 0
        amts, _ = self.fetch_daily_5d_data(stk_cd)
        if not amts:
            return 0
        return sum(amts) // len(amts)

    def fetch_daily_amounts_5d(self, stk_cd: str) -> list[int]:
        if self._rest_api is None:
            return []
        amts, _ = self.fetch_daily_5d_data(stk_cd)
        return amts

    def fetch_daily_5d_data(self, stk_cd: str) -> tuple[list[int], list[int]]:
        if self._rest_api is None:
            return [], []
        from app.core.kiwoom_daily_avg_volume import (
            fetch_daily_5d_data as _fetch,
        )

        return _fetch(self._rest_api, stk_cd)

    def fetch_market_code_list(self, mrkt_tp: str) -> list[str]:
        if self._rest_api is None:
            return []
        return self._rest_api.fetch_ka10099_market_code_list(mrkt_tp)

    def fetch_eligible_stocks(self) -> dict[str, str]:
        if self._rest_api is None:
            return {}
        return self._rest_api.fetch_ka10099_eligible_stocks()

    def fetch_index(self, mrkt_tp: str, inds_cd: str) -> Optional[dict]:
        if self._rest_api is None:
            return None
        return self._rest_api.fetch_ka20001_index(mrkt_tp, inds_cd)

    def fetch_stock_name_map(self) -> dict[str, str]:
        if self._rest_api is None:
            return {}
        return self._rest_api.fetch_ka10099_stock_name_map()

    def fetch_unified_stock_data(self) -> list:
        if self._rest_api is None:
            return []
        from app.core.kiwoom_sector_rest import fetch_ka10099_unified
        return fetch_ka10099_unified(self._rest_api)


# ── WebSocket Provider ────────────────────────────────────────────────
class KiwoomWebSocketProvider(WebSocketProvider):
    """기존 broker_urls 기반 WS URI 제공."""

    def __init__(
        self,
        settings: dict,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        self._settings = settings
        self._auth = auth_provider

    def get_ws_uri(self) -> str:
        from app.core.broker_urls import build_broker_urls

        return build_broker_urls("kiwoom")["ws_uri"]

