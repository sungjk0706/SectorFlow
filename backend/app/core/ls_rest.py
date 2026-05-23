# -*- coding: utf-8 -*-
"""
LS증권 REST API 통신 클래스
- httpx.AsyncClient 기반 비동기 HTTP 클라이언트
- OAuth2 토큰 관리
- 주문 실행 (매수, 매도, 정정, 취소)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.app.core.broker_urls import build_broker_urls

_log = logging.getLogger(__name__)


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

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = "https://openapi.ls-sec.co.kr:8080",
    ):
        self.app_key = (app_key or "").strip()
        self.app_secret = (app_secret or "").strip()
        self.base_url = (base_url or "").rstrip("/")
        self._token_info: Optional[LsTokenInfo] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def __aenter__(self) -> "LsRestAPI":
        self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def ensure_client(self) -> None:
        """클라이언트 초기화"""
        if self._client is None:
            self._client = httpx.AsyncClient()

    async def ensure_token(self) -> bool:
        """토큰 확보 (만료 시 자동 갱신)"""
        async with self._lock:
            if self._token_info and not self._token_info.is_expired():
                return True
            return await self._issue_token()

    def get_token(self) -> Optional[str]:
        """토큰 반환"""
        if self._token_info:
            return self._token_info.access_token
        return None

    async def _issue_token(self) -> bool:
        """OAuth2 토큰 발급 (exponential backoff 재시도)"""
        if not self.app_key or not self.app_secret:
            _log.warning("[LS증권REST] app_key 또는 app_secret 없음")
            return False

        await self.ensure_client()
        if self._client is None:
            _log.warning("[LS증권REST] AsyncClient 초기화 안됨")
            return False

        url = f"{self.base_url}{self.TOKEN_URL}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecretkey": self.app_secret,
            "scope": "oob",
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_sec = 5 * attempt
                    _log.warning(
                        f"[LS증권REST] 토큰 재시도 {attempt+1}/{max_retries} -- {wait_sec}초 대기"
                    )
                    await asyncio.sleep(wait_sec)

                resp = await self._client.post(url, headers=headers, data=body, timeout=15)
                data = resp.json() if resp.text else {}

                if resp.status_code == 429:
                    wait_sec = 10 * (attempt + 1)
                    _log.warning(
                        f"[LS증권REST] 429 요청 과다 -- {wait_sec}초 대기 후 재시도"
                    )
                    await asyncio.sleep(wait_sec)
                    continue

                if resp.status_code != 200:
                    _log.warning(f"[LS증권REST] 토큰 발급 실패 status={resp.status_code}")
                    return False

                access_token = data.get("access_token")
                expires_in = data.get("expires_in", 86400)

                if not access_token:
                    _log.warning("[LS증권REST] 200 응답이지만 토큰 필드 없음")
                    return False

                self._token_info = LsTokenInfo(
                    access_token=access_token,
                    expires_in=expires_in,
                    issued_at=time.time(),
                )
                _log.info(f"[LS증권REST] 토큰 발급 성공 expires_in={expires_in}초")
                return True

            except Exception as e:
                _log.warning(f"[LS증권REST] 토큰 요청 예외 (시도={attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue

        _log.warning(f"[LS증권REST] 토큰 발급 {max_retries}회 모두 실패")
        return False

    async def call_api(
        self,
        url: str,
        method: str = "GET",
        body: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> Optional[dict]:
        """
        범용 REST API 호출 (재시도 로직 포함)

        특징:
        - 429 exponential backoff
        - 일반 예외 linear backoff
        - 토큰 자동 갱신
        """
        await self.ensure_client()
        if self._client is None:
            _log.warning("[LS증권REST] AsyncClient 초기화 안됨")
            return None

        if not await self.ensure_token():
            _log.warning("[LS증권REST] 토큰 없음")
            return None

        default_headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self._token_info.access_token}",
        }
        if headers:
            default_headers.update(headers)

        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    resp = await self._client.get(url, headers=default_headers, timeout=timeout)
                else:
                    resp = await self._client.post(url, headers=default_headers, json=body, timeout=timeout)

                if resp.status_code == 429:
                    wait_sec = 8 * (attempt + 1)
                    _log.warning(
                        f"[LS증권REST] 429 -- {wait_sec:.0f}초 대기 후 재시도 ({attempt+1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_sec)
                    continue

                if resp.status_code != 200:
                    _log.info(f"[LS증권REST] HTTP {resp.status_code}")
                    return None

                return resp.json()

            except Exception as e:
                _log.warning(f"[LS증권REST] 예외 (시도={attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return None

        _log.warning(f"[LS증권REST] {max_retries}회 재시도 모두 실패")
        return None

    # ========== 주문 관련 메서드 ==========

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
        """
        현물 매수 주문 (CSPAT00601)

        Args:
            stock_code: 종목번호 (A+종목코드 형식)
            quantity: 주문수량
            price: 주문가
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
            _log.warning("[LS증권REST] AsyncClient 초기화 안됨")
            return None

        if not await self.ensure_token():
            _log.warning("[LS증권REST] 토큰 없음")
            return None

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
                "BnsTpCode": "2",  # 2:매수
                "OrdprcPtnCode": order_type,
                "MgntrnCode": credit_code,
                "LoanDt": loan_date,
                "OrdCndiTpCode": order_condition,
                "MbrNo": member_code,
            }
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_sec = 2 * attempt
                    _log.warning(
                        f"[LS증권REST] 매수주문 재시도 {attempt+1}/{max_retries} -- {wait_sec}초 대기"
                    )
                    await asyncio.sleep(wait_sec)

                resp = await self._client.post(url, headers=headers, json=body, timeout=15)
                data = resp.json() if resp.text else {}

                if resp.status_code == 429:
                    wait_sec = 8 * (attempt + 1)
                    _log.warning(
                        f"[LS증권REST] 매수주문 429 -- {wait_sec}초 대기 후 재시도"
                    )
                    await asyncio.sleep(wait_sec)
                    continue

                if resp.status_code != 200:
                    _log.warning(f"[LS증권REST] 매수주문 실패 status={resp.status_code}")
                    return data

                rsp_cd = data.get("rsp_cd", "")
                rsp_msg = data.get("rsp_msg", "")

                if rsp_cd == "00040" or rsp_cd == "00000":  # 성공 코드
                    _log.info(f"[LS증권REST] 매수주문 성공: {rsp_msg}")
                else:
                    _log.warning(f"[LS증권REST] 매수주문 실패: {rsp_cd} - {rsp_msg}")

                return data

            except Exception as e:
                _log.warning(f"[LS증권REST] 매수주문 예외 (시도={attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return None

        _log.warning(f"[LS증권REST] 매수주문 {max_retries}회 모두 실패")
        return None

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
        """
        현물 매도 주문 (CSPAT00601)

        Args:
            stock_code: 종목번호 (A+종목코드 형식)
            quantity: 주문수량
            price: 주문가
            order_type: 호가유형코드
            order_condition: 주문조건구분
            credit_code: 신용거래코드
            loan_date: 대출일
            member_code: 회원사번호

        Returns:
            주문 결과 {rsp_cd, rsp_msg, CSPAT00601OutBlock1, CSPAT00601OutBlock2}
        """
        await self.ensure_client()
        if self._client is None:
            _log.warning("[LS증권REST] AsyncClient 초기화 안됨")
            return None

        if not await self.ensure_token():
            _log.warning("[LS증권REST] 토큰 없음")
            return None

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
                "BnsTpCode": "1",  # 1:매도
                "OrdprcPtnCode": order_type,
                "MgntrnCode": credit_code,
                "LoanDt": loan_date,
                "OrdCndiTpCode": order_condition,
                "MbrNo": member_code,
            }
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_sec = 2 * attempt
                    _log.warning(
                        f"[LS증권REST] 매도주문 재시도 {attempt+1}/{max_retries} -- {wait_sec}초 대기"
                    )
                    await asyncio.sleep(wait_sec)

                resp = await self._client.post(url, headers=headers, json=body, timeout=15)
                data = resp.json() if resp.text else {}

                if resp.status_code == 429:
                    wait_sec = 8 * (attempt + 1)
                    _log.warning(
                        f"[LS증권REST] 매도주문 429 -- {wait_sec}초 대기 후 재시도"
                    )
                    await asyncio.sleep(wait_sec)
                    continue

                if resp.status_code != 200:
                    _log.warning(f"[LS증권REST] 매도주문 실패 status={resp.status_code}")
                    return data

                rsp_cd = data.get("rsp_cd", "")
                rsp_msg = data.get("rsp_msg", "")

                if rsp_cd == "00040" or rsp_cd == "00000":  # 성공 코드
                    _log.info(f"[LS증권REST] 매도주문 성공: {rsp_msg}")
                else:
                    _log.warning(f"[LS증권REST] 매도주문 실패: {rsp_cd} - {rsp_msg}")

                return data

            except Exception as e:
                _log.warning(f"[LS증권REST] 매도주문 예외 (시도={attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return None

        _log.warning(f"[LS증권REST] 매도주문 {max_retries}회 모두 실패")
        return None

    # ========== 계좌 관련 메서드 ==========

    async def get_balance(
        self,
        prcgb: str = "1", # 1: 평균단가, 2: BEP단가
        chegb: str = "2", # 0: 결제기준, 2: 체결기준
        dangb: str = "0", # 0: 정규장, 1: 시간외
        charge: str = "1", # 0: 제비용미포함, 1: 제비용포함
        cts_expcode: str = "",
    ) -> Optional[dict]:
        """주식잔고2 (t0424) 조회"""
        url = f"{self.base_url}/stock/accno"
        headers = {
            "tr_cd": "t0424",
            "tr_cont": "N",
            "tr_cont_key": "",
        }
        body = {
            "t0424InBlock": {
                "prcgb": prcgb,
                "chegb": chegb,
                "dangb": dangb,
                "charge": charge,
                "cts_expcode": cts_expcode,
            }
        }
        return await self.call_api(url, method="POST", headers=headers, body=body)

    async def get_daily_history(
        self,
        cts_medosu: str = "0",
        cts_expcode: str = "",
        cts_price: str = "",
        cts_middiv: str = "",
    ) -> Optional[dict]:
        """주식당일매매일지/수수료 (t0150) 조회"""
        url = f"{self.base_url}/stock/accno"
        headers = {
            "tr_cd": "t0150",
            "tr_cont": "N",
            "tr_cont_key": "",
        }
        body = {
            "t0150InBlock": {
                "cts_medosu": cts_medosu,
                "cts_expcode": cts_expcode,
                "cts_price": cts_price,
                "cts_middiv": cts_middiv,
            }
        }
        return await self.call_api(url, method="POST", headers=headers, body=body)

    # ========== 종목/테마 관련 메서드 ==========

    async def get_themes(self) -> Optional[dict]:
        """전체테마 (t8425) 조회"""
        url = f"{self.base_url}/stock/sector"
        headers = {
            "tr_cd": "t8425",
            "tr_cont": "N",
            "tr_cont_key": "",
        }
        body = {
            "t8425InBlock": {
                "dummy": "",
            }
        }
        return await self.call_api(url, method="POST", headers=headers, body=body)

    async def get_stocks(self, gubun: str = "0") -> Optional[dict]:
        """주식종목조회 (t8436) - gubun: 0(전체), 1(코스피), 2(코스닥)"""
        url = f"{self.base_url}/stock/sector"
        headers = {
            "tr_cd": "t8436",
            "tr_cont": "N",
            "tr_cont_key": "",
        }
        body = {
            "t8436InBlock": {
                "gubun": gubun,
            }
        }
        return await self.call_api(url, method="POST", headers=headers, body=body)
