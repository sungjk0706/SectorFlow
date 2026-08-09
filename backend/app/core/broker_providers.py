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


@dataclass(frozen=True)
class RawStockFetchResult:
    """증권사 일봉 조회 결과 — 원자료를 전달하는 공통 계약.

    설계서 4.1(응답 보존)·4.3(부분 성공) 반영.
    증권사별 해석은 각 Provider 영역에 유지하고, 이 계약을 통해 공통 흐름으로 전달.
    수신 실패 시 raw_payload=None 으로 구분 (W8 폴백 금지).
    """
    code: str                              # 종목코드
    raw_payload: dict | None = None        # 해석 전 원문 (증권사 응답 원본)


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


# ── Account Provider ──────────────────────────────────────────────────────
class AccountProvider(ABC):
    """계좌 데이터 파싱 — 증권사별 응답 구조에 의존하는 파싱을 전용 계층에 위임.

    공통 로직(services/)은 이 인터페이스만 호출하여 증권사 식별자 없이
    계좌 잔고·보유 종목·실시간 체결을 처리한다.
    파싱 로직 자체는 각 증권사 전용 모듈에 유지 — Provider는 호출만 위임.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """증권사 식별자 (예: 'kiwoom')."""
        ...

    @abstractmethod
    def parse_deposit(self, raw: dict) -> tuple:
        """예수금 조회 응답 파싱.

        반환값은 증권사별 기존 파싱 함수의 반환 튜플을 그대로 유지
        (공통 데이터 모델 재설계는 비목표).
        """
        ...

    @abstractmethod
    def parse_balance(self, raw: dict, deposit) -> tuple:
        """잔고·보유 종목 조회 응답 파싱.

        deposit 은 parse_deposit 결과 중 예수금 값을 보완용으로 전달.
        반환값은 증권사별 기존 파싱 함수의 반환 튜플을 그대로 유지.
        """
        ...

    @abstractmethod
    def is_realtime_stock_item(self, item: dict) -> bool:
        """실시간 메시지 item 필드가 종목코드인지 계좌번호인지 구분."""
        ...

    @abstractmethod
    def apply_realtime_position_line(self, item, vals, positions, extra) -> None:
        """실시간 종목 단위 레코드를 보유 종목 리스트에 반영 (in-place)."""
        ...

    @abstractmethod
    def compute_realtime_account_delta(self, vals: dict) -> dict:
        """실시간 계좌 단위 레코드에서 부분 갱신할 계좌 필드 딕셔너리 반환."""
        ...

    @abstractmethod
    def parse_unfilled_orders(self, raw: dict) -> list:
        """미체결 주문 조회 응답 파싱 — 공통 미체결 주문 dict 리스트 반환.

        공통 dict 키: ord_no·stk_cd·stk_nm·ord_qty·ord_price·unfilled_qty·
                     ord_status·orig_ord_no·ord_type(매도/매수).
        파싱 로직 자체는 각 증권사 전용 파싱 모듈에 위임 (P10 SSOT · P23 일관성).
        """
        ...
