# -*- coding: utf-8 -*-
"""
브로커 Provider 서브 인터페이스 (ABC)

기능별 독립 인터페이스 정의:
  - AuthProvider     : 인증 토큰 발급/관리
  - AccountProvider  : 계좌 조회 (예수금, 잔고, 보유종목)
  - OrderProvider    : 주문 실행 (매수, 매도)
  - SectorProvider   : 업종 데이터 (업종별 종목, 시세, 5일 평균 거래대금)
  - WebSocketProvider: 실시간 WebSocket 연결

엔진/서비스 코드는 이 인터페이스만 참조하여 증권사 독립적으로 동작.
BrokerRouter가 설정 기반으로 기능별 Provider 구현체를 매핑한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional


# ── 공통 데이터 구조체 ───────────────────────────────────────────────

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
    def get_access_token(self) -> Optional[str]:
        """OAuth2 액세스 토큰 발급/반환 (캐싱 포함)."""
        ...

    @abstractmethod
    def ensure_token(self) -> bool:
        """토큰 유효성 확인, 만료 시 자동 갱신. True=유효."""
        ...

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """증권사 식별자 (예: 'kiwoom')."""
        ...


# ── Account Provider ──────────────────────────────────────────────────
class AccountProvider(ABC):
    """계좌 조회: 예수금, 잔고, 보유종목."""

    @abstractmethod
    def get_account_number(self) -> Optional[str]:
        """계좌번호 조회."""
        ...

    @abstractmethod
    def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        """예수금 상세 조회."""
        ...

    @abstractmethod
    def get_account_balance(self, acnt_no: str = "") -> dict:
        """
        계좌 잔고 통합 조회 -- 공통 표준 반환 구조.

        반환:
        {
            "success": bool,
            "summary": {
                "tot_eval": int, "tot_pnl": int, "tot_buy": int,
                "deposit": int, "orderable": int, "total_rate": float,
            },
            "stock_list": [
                {"stk_cd": str, "stk_nm": str, "qty": int, "buy_price": int, ...}
            ],
            "raw_data": dict,
        }
        """
        ...

    @abstractmethod
    def get_balance_detail(
        self, qry_tp: str = "1", dmst_stex_tp: str = "KRX"
    ) -> Optional[dict]:
        """계좌평가잔고내역 조회 (연속조회 포함)."""
        ...


# ── Order Provider ────────────────────────────────────────────────────
class OrderProvider(ABC):
    """주문 실행: 매수, 매도, 정정, 취소."""

    @abstractmethod
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
        """
        매수/매도/정정/취소 주문.
        반환: {"success": bool, "msg": str, "data": dict | None}
        """
        ...


# ── Sector Provider ───────────────────────────────────────────────────
class SectorProvider(ABC):
    """업종 데이터: 업종별 종목, 시세 스냅샷, 5일 평균 거래대금."""

    @abstractmethod
    def fetch_daily_price(
        self, stk_cd: str, qry_dt: str
    ) -> Optional[dict]:
        """일별 주가 조회 (확정 종가/등락률/거래대금)."""
        ...

    @abstractmethod
    def fetch_sector_all_daily(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.1,
        on_progress: Callable[[int, int], None] | None = None,
        resume_codes: set[str] | None = None,
    ) -> dict[str, dict]:
        """전체 종목 일별 주가 순차 조회."""
        ...

    @abstractmethod
    def fetch_industry_stocks(self, inds_cd: str) -> list[dict]:
        """업종별 종목 시세 조회."""
        ...

    @abstractmethod
    def fetch_avg_amt_5d(self, stk_cd: str) -> int:
        """단일 종목 5일 평균 거래대금 (백만원)."""
        ...

    @abstractmethod
    def fetch_daily_amounts_5d(self, stk_cd: str) -> list[int]:
        """단일 종목 5일치 거래대금 배열 (백만원, 최신→과거)."""
        ...

    @abstractmethod
    def fetch_daily_5d_data(self, stk_cd: str) -> tuple[list[int], list[int]]:
        """단일 종목 5일치 거래대금 배열 + 고가 배열 동시 반환.

        Returns:
            (amounts_5d, highs_5d)
            amounts_5d: [백만원, ...] 최신→과거 (최대 5개)
            highs_5d:   [원, ...]   최신→과거 (최대 5개)
            실패 시 ([], []).
        """
        ...

    @abstractmethod
    def fetch_market_code_list(self, mrkt_tp: str) -> list[str]:
        """시장별 종목 코드 리스트."""
        ...

    @abstractmethod
    def fetch_eligible_stocks(self) -> dict[str, str]:
        """적격 종목코드 수집 {종목코드: ""}."""
        ...

    @abstractmethod
    def fetch_stock_name_map(self) -> dict[str, str]:
        """전체 종목명 매핑 {6자리 종목코드: 종목명}."""
        ...

    @abstractmethod
    def fetch_index(self, mrkt_tp: str, inds_cd: str) -> Optional[dict]:
        """업종 지수 현재가 조회."""
        ...

    @abstractmethod
    def fetch_unified_stock_data(self) -> list[UnifiedStockRecord]:
        """통합 파싱 — 종목코드·종목명·업종명·시장구분을 한꺼번에 추출."""
        ...


# ── WebSocket Provider ────────────────────────────────────────────────
class WebSocketProvider(ABC):
    """실시간 WebSocket 연결."""

    @abstractmethod
    def get_ws_uri(self) -> str:
        """WebSocket 접속 URI."""
        ...
