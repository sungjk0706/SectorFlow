# -*- coding: utf-8 -*-
"""
키움증권 Provider 구현체

기존 코드를 최대한 재사용하며, 각 Provider가 해당 기능만 캡슐화:
  - KiwoomAuthProvider      : KiwoomRestAPI 토큰 관리 위임
  - KiwoomOrderProvider     : kiwoom_order.send_order 캡슐화
  - KiwoomStockProvider     : kiwoom_stock_rest + kiwoom_daily_avg_volume 캡슐화
  - KiwoomWebSocketProvider : broker_urls 기반 WS URI 제공
"""
from __future__ import annotations
import logging
from typing import Callable, Optional
from backend.app.core.broker_providers import (
    AuthProvider,
    OrderProvider,
    WebSocketProvider,
)
from backend.app.core.kiwoom_rest import KiwoomRestAPI
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES

logger = logging.getLogger(__name__)

_BROKER_DISPLAY = BROKER_DISPLAY_NAMES["kiwoom"]


# ── Auth Provider ─────────────────────────────────────────────────────
class KiwoomAuthProvider(AuthProvider):
    """기존 KiwoomRestAPI의 토큰 관리 로직 위임."""

    def __init__(self):
        from backend.app.services.engine_state import state
        # broker_rest_apis에 이미 존재하면 재사용 (엔진 루프에서 초기화됨)
        _existing = state.broker_rest_apis.get("kiwoom")
        if _existing is None:
            app_key = (state.integrated_system_settings_cache.get("kiwoom_app_key") or "").strip()
            app_secret = (state.integrated_system_settings_cache.get("kiwoom_app_secret") or "").strip()
            _existing = KiwoomRestAPI(app_key, app_secret)
            state.broker_rest_apis["kiwoom"] = _existing
        self._rest_api = _existing
        self._rest_api._acnt_no = str(
            state.integrated_system_settings_cache.get("kiwoom_account_no", "") or ""
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


# ── Order Provider ────────────────────────────────────────────────────
class KiwoomOrderProvider(OrderProvider):
    """기존 kiwoom_order.send_order 함수 캡슐화."""

    def __init__(
        self,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        pass

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

    async def fetch_stock_5day_data(
        self, stk_cd: str, qry_dt: str
    ) -> dict | None:
        """ka10081 단건 조회 -- 최근 5개 일봉에서 5일 평균 거래대금 및 최고가 계산 반환."""
        if self._rest_api is None:
            return None
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        return await fetch_ka10081_daily_5d_data(self._rest_api, stk_cd, qry_dt)

    async def fetch_all_stocks_daily_confirmed(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.3,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> dict[str, dict]:
        """전체 종목 ka10081 순차 조회 -- 확정 시세(1일봉) 데이터 채우기용."""
        if self._rest_api is None:
            return {}
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        return await fetch_ka10081_all_stocks_daily_confirmed(
            self._rest_api, krx_codes, qry_dt, interval_sec=interval_sec, on_progress=on_progress
        )


# ── WebSocket Provider ────────────────────────────────────────────────
class KiwoomWebSocketProvider(WebSocketProvider):
    """기존 broker_urls 기반 WS URI 제공."""

    def __init__(
        self,
        auth_provider: Optional[KiwoomAuthProvider] = None,
    ):
        pass

