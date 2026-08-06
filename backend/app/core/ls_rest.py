# -*- coding: utf-8 -*-
"""
LS증권 REST API 통신 클래스
- httpx.AsyncClient 기반 비동기 HTTP 클라이언트
- OAuth2 토큰 관리
- 주문 실행 (매수, 매도, 정정, 취소)
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging
import time
from dataclasses import dataclass
import httpx
from backend.app.core.auth_utils import (
    classify_token_failure,
    compute_backoff_delay,
    retry_once_on_401,
)
from backend.app.core.broker_urls import build_broker_urls, BROKER_DISPLAY_NAMES
from backend.app.core.constants import (
    TOKEN_ISSUE_MAX_RETRIES,
    TOKEN_PERMANENT_HTTP_CODES,
    TOKEN_TRANSIENT_HTTP_CODES,
)
logger = logging.getLogger(__name__)

_BROKER_DISPLAY = BROKER_DISPLAY_NAMES["ls"]


@dataclass
class LsTokenInfo:
    """LS증권 토큰 정보"""
    access_token: str
    expires_in: int  # 초
    token_type: str = "Bearer"
    scope: str = "oob"
    issued_at: float = 0.0  # 발급 시간 (unix timestamp)

    def is_expired(self, buffer_seconds: int = 3600) -> bool:
        """토큰 만료 임박 체크"""
        if self.issued_at == 0.0:
            return True
        return (self.issued_at + self.expires_in - buffer_seconds) <= time.time()


class LsRestAPI:
    """
    LS증권 REST API 클라이언트
    - httpx.AsyncClient 기반 완전 비동기
    - OAuth2 토큰 관리
    - 주문 실행 (매수, 매도, 정정, 취소)
    """

    TOKEN_URL = "/oauth2/token"
    REVOKE_URL = "/oauth2/revoke"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = "",
    ):
        self.app_key = (app_key or "").strip()
        self.app_secret = (app_secret or "").strip()
        if not base_url:
            base_url = build_broker_urls("ls")["rest_base"]
        self.base_url = (base_url or "").rstrip("/")
        self._token_info: Optional[LsTokenInfo] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._lock: Optional[asyncio.Lock] = None

    async def __aenter__(self) -> "LsRestAPI":
        self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def ensure_client(self) -> None:
        """클라이언트 초기화 (이벤트 루프 변경 감지 대응)"""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._client is None or getattr(self, '_loop', None) is not current_loop:
            # 루프가 바뀌었거나 클라이언트가 없으면 새로 생성
            try:
                if self._client and not self._client.is_closed:
                    if getattr(self, '_loop', None) and getattr(self, '_loop').is_running():
                        await self._client.aclose()
            except Exception as e:
                logger.warning("[연결] %s 이전 클라이언트 정리 실패: %s", _BROKER_DISPLAY, e, exc_info=True)
            
            self._client = httpx.AsyncClient()
            self._loop = current_loop

    async def ensure_token(self) -> bool:
        """토큰 확보 (만료 시 자동 갱신)"""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if getattr(self, "_lock", None) is None or getattr(self, "_lock_loop", None) is not current_loop:
            self._lock = asyncio.Lock()
            self._lock_loop = current_loop

        assert self._lock is not None
        async with self._lock:
            if self._token_info and not self._token_info.is_expired():
                return True
            ok, _ = await self._issue_token()
            return ok

    def get_token(self) -> Optional[str]:
        """토큰 반환"""
        if self._token_info:
            return self._token_info.access_token
        return None

    async def _issue_token(self) -> tuple[bool, Optional[str]]:
        """OAuth2 토큰 발급 (exponential backoff 재시도).

        공통 백오프·실패 분류 함수 적용 (설계서 결정 1·6·7).
        반환: (성공여부, 실패종류) — 실패종류: "transient"/"permanent"/None(성공).
        영구 실패(키 없음·401/403·인증 거부 코드)는 즉시 반환하여 회복 루프 진입 차단.
        """
        if not self.app_key or not self.app_secret:
            logger.warning("[연결] %s 토큰 발급 불가 — API 키 또는 시크릿 키 없음", _BROKER_DISPLAY)
            return False, "permanent"

        await self.ensure_client()
        if self._client is None:
            logger.warning("[연결] %s HTTP 클라이언트 초기화 안됨", _BROKER_DISPLAY)
            return False, "transient"

        url = f"{self.base_url}{self.TOKEN_URL}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecretkey": self.app_secret,
            "scope": "oob",
        }

        last_failure_kind: Optional[str] = None
        for attempt in range(TOKEN_ISSUE_MAX_RETRIES):
            try:
                if attempt > 0:
                    wait_sec = compute_backoff_delay(attempt)
                    logger.warning(
                        "[연결] %s 토큰 발급 재시도 %d/%d — %.1f초 대기",
                        _BROKER_DISPLAY, attempt + 1, TOKEN_ISSUE_MAX_RETRIES, wait_sec,
                    )
                    await asyncio.sleep(wait_sec)

                resp = await self._client.post(url, headers=headers, data=body, timeout=15)
                data = resp.json() if resp.text else {}

                # 일시 실패 HTTP 코드(429/5xx) — 공통 백오프 후 재시도
                if resp.status_code in TOKEN_TRANSIENT_HTTP_CODES:
                    last_failure_kind = classify_token_failure(resp.status_code)
                    wait_sec = compute_backoff_delay(attempt)
                    logger.warning(
                        "[연결] %s 토큰 발급 일시 실패 (응답코드=%s) — %.1f초 대기 후 재시도 (%d/%d)",
                        _BROKER_DISPLAY, resp.status_code, wait_sec, attempt + 1, TOKEN_ISSUE_MAX_RETRIES,
                    )
                    await asyncio.sleep(wait_sec)
                    continue

                # 영구 실패 HTTP 코드(401/403) — 즉시 반환 (회복 루프 진입 차단)
                if resp.status_code in TOKEN_PERMANENT_HTTP_CODES:
                    failure_kind = classify_token_failure(resp.status_code)
                    logger.warning(
                        "[연결] %s 토큰 발급 영구 실패 (응답코드=%s)",
                        _BROKER_DISPLAY, resp.status_code,
                    )
                    return False, failure_kind

                # 기타 != 200 — 분류 후 반환
                if resp.status_code != 200:
                    failure_kind = classify_token_failure(resp.status_code, response_text=resp.text)
                    logger.warning(
                        "[연결] %s 토큰 발급 실패 (응답코드=%s)",
                        _BROKER_DISPLAY, resp.status_code,
                    )
                    return False, failure_kind

                # 200 — 토큰 파싱
                access_token = data.get("access_token")
                expires_in = data.get("expires_in", 86400)

                if not access_token:
                    # 응답 본문에서 LS 인증 거부 키워드 검사 (invalid_client 등)
                    failure_kind = classify_token_failure(200, response_text=resp.text)
                    if failure_kind == "permanent":
                        logger.warning(
                            "[연결] %s 인증 거부 — AppKey/AppSecret이 유효하지 않습니다. "
                            "LS증권에서 발급한 키를 확인하세요. 응답: %s",
                            _BROKER_DISPLAY, resp.text,
                        )
                    else:
                        failure_kind = "transient"
                        logger.warning(
                            "[연결] %s 응답 성공이지만 토큰 없음",
                            _BROKER_DISPLAY,
                        )
                    return False, failure_kind

                self._token_info = LsTokenInfo(
                    access_token=access_token,
                    expires_in=expires_in,
                    issued_at=time.time(),
                )
                logger.info("[연결] %s 토큰 발급 성공 (유효기간=%s초)", _BROKER_DISPLAY, expires_in)
                return True, None

            except Exception as e:
                logger.warning(
                    "[연결] %s 토큰 발급 오류 (시도=%d): %s: %s",
                    _BROKER_DISPLAY, attempt + 1, type(e).__name__, e, exc_info=True,
                )
                last_failure_kind = classify_token_failure(None, exception=e)
                continue

        logger.warning("[연결] %s 토큰 발급 %d번 모두 실패", _BROKER_DISPLAY, TOKEN_ISSUE_MAX_RETRIES)
        return False, last_failure_kind or "transient"

    async def revoke_token(self) -> bool:
        """OAuth2 접근 토큰 폐기 (LS증권 REST API 명세). 실패해도 예외 전파 안 함."""
        if not self._token_info or not self._token_info.access_token:
            logger.info("[연결] %s 토큰 폐기 생략 — 발급된 토큰 없음", _BROKER_DISPLAY)
            return True
        token = self._token_info.access_token
        url = f"{self.base_url}{self.REVOKE_URL}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        body = {
            "appkey": self.app_key,
            "appsecretkey": self.app_secret,
            "token": token,
            "token_type_hint": "access_token",
        }
        try:
            await self.ensure_client()
            if self._client is None:
                logger.info("[연결] %s 토큰 폐기 생략 — HTTP 클라이언트 없음", _BROKER_DISPLAY)
                return True
            resp = await self._client.post(url, headers=headers, data=body, timeout=5)
            if resp.status_code == 200:
                logger.info("[연결] %s 토큰 폐기", _BROKER_DISPLAY)
            else:
                logger.warning("[연결] %s 토큰 폐기 실패 (응답코드=%s)", _BROKER_DISPLAY, resp.status_code)
        except Exception as e:
            logger.warning("[연결] %s 토큰 폐기 오류: %s: %s", _BROKER_DISPLAY, type(e).__name__, e, exc_info=True)
        finally:
            self._token_info = None
        return True

    # ========== 주문 관련 메서드 ==========

    async def _place_order(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        bns_tp_code: str,  # "1":매도, "2":매수
        order_kind: str,  # "매수" or "매도" (로그용)
        order_type: str = "00",  # 00:지정가, 03:시장가
        order_condition: str = "0",  # 0:없음, 1:IOC, 2:FOK
        credit_code: str = "000",  # 000:보통
        loan_date: str = "",
        member_code: str = "NXT",  # KRX, NXT
    ) -> Optional[dict]:
        """현물 주문 공통 로직 (CSPAT00601). buy_order/sell_order 래퍼에서 호출.

        Args:
            stock_code: 종목번호 (A+종목코드 형식)
            quantity: 주문수량
            price: 주문가
            bns_tp_code: "1"=매도, "2"=매수
            order_kind: 로그용 라벨 ("매수" or "매도")
            order_type: 호가유형코드 (00:지정가, 03:시장가)
            order_condition: 주문조건구분 (0:없음, 1:IOC, 2:FOK)
            credit_code: 신용거래코드 (000:보통)
            loan_date: 대출일 (YYYYMMDD)
            member_code: 회원사번호 (KRX, NXT)

        Returns:
            주문 결과 {rsp_cd, rsp_msg, CSPAT00601OutBlock1, CSPAT00601OutBlock2}
        """
        await self.ensure_client()
        if self._client is None:
            logger.warning("[연결] %s HTTP 클라이언트 초기화 안됨", _BROKER_DISPLAY)
            return None

        if not await self.ensure_token():
            logger.warning("[연결] %s 토큰 없음", _BROKER_DISPLAY)
            return None

        assert self._token_info is not None
        url = f"{self.base_url}/stock/order"
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": f"Bearer {self._token_info.access_token}",
            "tr_cd": "CSPAT00601",
            "tr_cont": "N",
            "tr_cont_key": "",
        }

        body = {
            "CSPAT00601InBlock1": {
                "IsuNo": stock_code,
                "OrdQty": quantity,
                "OrdPrc": price,
                "BnsTpCode": bns_tp_code,
                "OrdprcPtnCode": order_type,
                "MgntrnCode": credit_code,
                "LoanDt": loan_date,
                "OrdCndiTpCode": order_condition,
                "MbrNo": member_code,
            }
        }

        # 주문 재시도 전면 폐지 (설계서 결정 3) — 1회만 시도 후 실패 시 즉시 None 반환.
        # 단, 401(토큰 만료) 시 토큰 재발급 후 1회 재시도는 유지 — 인증 갱신 후 동일 요청 재전송이므로 중복 주문 위험 없음.
        try:
            resp = await self._client.post(url, headers=headers, json=body, timeout=15)
            data = resp.json() if resp.text else {}

            # 401 감지 — 공통 재발급 헬퍼로 토큰 재발급 후 1회 재시도 (설계서 결정 3 예외)
            if resp.status_code == 401:
                logger.info("[연결] %s %s 주문 401 감지 — 토큰 재발급 후 1회 재시도", _BROKER_DISPLAY, order_kind)

                async def _do_post():
                    r = await self._client.post(url, headers=headers, json=body, timeout=15)
                    return r, r.status_code

                async def _reissue_token() -> bool:
                    ok, _ = await self._issue_token()
                    return ok

                async def _refresh_auth_header() -> None:
                    if self._token_info:
                        headers["Authorization"] = f"Bearer {self._token_info.access_token}"

                result = await retry_once_on_401(
                    _reissue_token, _do_post, on_reissue_success=_refresh_auth_header
                )
                if isinstance(result, tuple) and result[1] == 200:
                    r = result[0]
                    data = r.json() if r.text else {}
                    rsp_cd = data.get("rsp_cd", "")
                    rsp_msg = data.get("rsp_msg", "")
                    if rsp_cd == "00040" or rsp_cd == "00000":
                        logger.info(f"[연결] {_BROKER_DISPLAY} {order_kind} 주문 성공: {rsp_msg}")
                    else:
                        logger.warning(f"[연결] {_BROKER_DISPLAY} {order_kind} 주문 실패: {rsp_cd} - {rsp_msg}")
                    return data
                retry_status = result[1] if isinstance(result, tuple) else "?"
                logger.warning(
                    "[연결] %s %s 401 재발급 후에도 실패 (응답코드=%s)",
                    _BROKER_DISPLAY, order_kind, retry_status,
                )
                return None

            if resp.status_code != 200:
                logger.warning(f"[연결] {_BROKER_DISPLAY} {order_kind} 주문 실패 (응답코드={resp.status_code})")
                return data

            rsp_cd = data.get("rsp_cd", "")
            rsp_msg = data.get("rsp_msg", "")

            if rsp_cd == "00040" or rsp_cd == "00000":  # 성공 코드
                logger.info(f"[연결] {_BROKER_DISPLAY} {order_kind} 주문 성공: {rsp_msg}")
            else:
                logger.warning(f"[연결] {_BROKER_DISPLAY} {order_kind} 주문 실패: {rsp_cd} - {rsp_msg}")

            return data

        except Exception as e:
            logger.warning(f"[연결] {_BROKER_DISPLAY} {order_kind} 주문 오류: {e}", exc_info=True)
            return None

    async def buy_order(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        order_type: str = "00",  # 00:지정가, 03:시장가
        order_condition: str = "0",  # 0:없음, 1:IOC, 2:FOK
        credit_code: str = "000",  # 000:보통
        loan_date: str = "",
        member_code: str = "NXT",  # KRX, NXT
    ) -> Optional[dict]:
        """현물 매수 주문 (CSPAT00601). _place_order 래퍼."""
        return await self._place_order(
            stock_code, quantity, price,
            bns_tp_code="2", order_kind="매수",
            order_type=order_type, order_condition=order_condition,
            credit_code=credit_code, loan_date=loan_date, member_code=member_code,
        )

    async def sell_order(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        order_type: str = "00",  # 00:지정가, 03:시장가
        order_condition: str = "0",  # 0:없음, 1:IOC, 2:FOK
        credit_code: str = "000",  # 000:보통
        loan_date: str = "",
        member_code: str = "NXT",  # KRX, NXT
    ) -> Optional[dict]:
        """현물 매도 주문 (CSPAT00601). _place_order 래퍼."""
        return await self._place_order(
            stock_code, quantity, price,
            bns_tp_code="1", order_kind="매도",
            order_type=order_type, order_condition=order_condition,
            credit_code=credit_code, loan_date=loan_date, member_code=member_code,
        )

