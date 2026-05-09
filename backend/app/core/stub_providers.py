# -*- coding: utf-8 -*-
"""
Stub Provider 구현

미지원 증권사용 빈 껍데기 Provider.
모든 abstract 메서드 호출 시 NotImplementedError("{broker_label} API 미구현") 발생.
API 승인 후 실제 로직만 채우면 됨.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.core.broker_providers import (
    AccountProvider,
    AuthProvider,
    OrderProvider,
    SectorProvider,
    UnifiedStockRecord,
    WebSocketProvider,
)


class StubAuthProvider(AuthProvider):
    """Stub 인증 Provider."""

    def __init__(self, settings: dict, *, broker_label: str = "", **_kw: Any):
        self._label = broker_label

    def get_access_token(self) -> Optional[str]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def ensure_token(self) -> bool:
        raise NotImplementedError(f"{self._label} API 미구현")

    @property
    def broker_name(self) -> str:
        return self._label


class StubAccountProvider(AccountProvider):
    """Stub 계좌 Provider."""

    def __init__(self, settings: dict, *, broker_label: str = "", **_kw: Any):
        self._label = broker_label

    def get_account_number(self) -> Optional[str]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def get_account_balance(self, acnt_no: str = "") -> dict:
        raise NotImplementedError(f"{self._label} API 미구현")

    def get_balance_detail(
        self, qry_tp: str = "1", dmst_stex_tp: str = "KRX"
    ) -> Optional[dict]:
        raise NotImplementedError(f"{self._label} API 미구현")


class StubOrderProvider(OrderProvider):
    """Stub 주문 Provider."""

    def __init__(self, settings: dict, *, broker_label: str = "", **_kw: Any):
        self._label = broker_label

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
        raise NotImplementedError(f"{self._label} API 미구현")


class StubSectorProvider(SectorProvider):
    """Stub 업종 Provider."""

    def __init__(self, settings: dict, *, broker_label: str = "", **_kw: Any):
        self._label = broker_label

    def fetch_daily_price(self, stk_cd: str, qry_dt: str) -> Optional[dict]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_sector_all_daily(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.1,
        on_progress: Callable[[int, int], None] | None = None,
        resume_codes: set[str] | None = None,
    ) -> dict[str, dict]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_industry_stocks(self, inds_cd: str) -> list[dict]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_avg_amt_5d(self, stk_cd: str) -> int:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_daily_amounts_5d(self, stk_cd: str) -> list[int]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_daily_5d_data(self, stk_cd: str) -> tuple[list[int], list[int]]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_market_code_list(self, mrkt_tp: str) -> list[str]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_eligible_stocks(self) -> dict[str, str]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_stock_name_map(self) -> dict[str, str]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_index(self, mrkt_tp: str, inds_cd: str) -> Optional[dict]:
        raise NotImplementedError(f"{self._label} API 미구현")

    def fetch_unified_stock_data(self) -> list[UnifiedStockRecord]:
        raise NotImplementedError(f"{self._label} API 미구현")


class StubWebSocketProvider(WebSocketProvider):
    """Stub WebSocket Provider."""

    def __init__(self, settings: dict, *, broker_label: str = "", **_kw: Any):
        self._label = broker_label

    def get_ws_uri(self) -> str:
        raise NotImplementedError(f"{self._label} API 미구현")

