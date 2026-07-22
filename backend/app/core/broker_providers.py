# -*- coding: utf-8 -*-
"""
브로커 Provider 서브 인터페이스 (ABC)

기능별 독립 인터페이스 정의:
  - AuthProvider     : 인증 토큰 발급/관리
  - OrderProvider    : 주문 실행 (매수, 매도)
  - WebSocketProvider: 실시간 WebSocket 연결

엔진/서비스 코드는 이 인터페이스만 참조하여 증권사 독립적으로 동작.
BrokerRouter가 설정 기반으로 기능별 Provider 구현체를 매핑한다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
@dataclass(frozen=True)
class UnifiedStockRecord:
    """통합 종목 파싱 결과 — 종목코드·종목명·시장구분을 한꺼번에 보관."""
    code: str          # 6자리 종목코드
    name: str          # 종목명
    market_code: str   # 시장구분 (marketCode 원본값)
    nxt_enable: bool   # NXT 중복상장 여부 (nxtEnable 원본값)
    raw_item: dict     # 원본 item dict (is_excluded 판정용)


# ── Auth Provider ─────────────────────────────────────────────────────
class AuthProvider(ABC):
    """인증 토큰 발급/관리. 동일 증권사의 모든 Provider가 공유."""

    @abstractmethod
    async def get_access_token(self) -> str | None:
        """OAuth2 액세스 토큰 발급/반환 (캐싱 포함)."""
        ...

    @abstractmethod
    async def ensure_token(self) -> bool:
        """토큰 유효성 확인, 만료 시 자동 갱신. True=유효."""
        ...

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """증권사 식별자 (예: 'kiwoom')."""
        ...


# ── Order Provider ────────────────────────────────────────────────────
class OrderProvider(ABC):
    """주문 실행: 매수, 매도, 정정, 취소."""

    @abstractmethod
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
        """
        매수/매도/정정/취소 주문.
        반환: {"success": bool, "msg": str, "data": dict | None}
        """
        ...


# ── WebSocket Provider ────────────────────────────────────────────────
class WebSocketProvider(ABC):
    """실시간 WebSocket 연결."""

    @abstractmethod
    def get_ws_uri(self) -> str:
        """WebSocket 접속 URI."""
        ...
