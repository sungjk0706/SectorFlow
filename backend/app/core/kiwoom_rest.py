# -*- coding: utf-8 -*-
"""
키움증권 REST API 통신 클래스 (64비트 호환)
- 순수 HTTP/JSON (httpx.AsyncClient 사용, OCX/COM 미사용)
- OAuth2 client_credentials: App Key, App Secret -> Access Token
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging
import time
from dataclasses import dataclass
import httpx
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES, KIWOOM_REST_REAL

logger = logging.getLogger(__name__)

_BROKER_DISPLAY = BROKER_DISPLAY_NAMES["kiwoom"]


@dataclass
class TokenInfo:
    token: str
    expires_dt: str  # YYYYMMDDHHmmss
    token_type: str = "bearer"

    def is_expired_soon(self, buffer_seconds: int = 3600) -> bool:
        """만료 buffer_seconds 초 전이면 True (기본 1시간 여유)"""
        try:
            dt = self.expires_dt
            if len(dt) < 14:
                return True
            from datetime import datetime, timezone, timedelta
            year = int(dt[0:4])
            month = int(dt[4:6])
            day = int(dt[6:8])
            hour = int(dt[8:10])
            minute = int(dt[10:12])
            second = int(dt[12:14])
            exp = datetime(year, month, day, hour, minute, second, tzinfo=timezone(timedelta(hours=9)))
            return (exp.timestamp() - buffer_seconds) <= time.time()
        except (ValueError, IndexError):
            return True


class KiwoomRestAPI:
    """
    키움증권 REST API 클라이언트
    - HTTP POST, JSON 주고받기
    - OAuth2: grant_type=client_credentials, appkey, secretkey
    """

    TOKEN_URL = "/oauth2/token"
    REVOKE_URL = "/oauth2/revoke"
    ACCOUNT_URL = "/api/dostk/acnt"
    API_ID_ACCOUNT = "ka00001"
    API_ID_DEPOSIT = "kt00001"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = KIWOOM_REST_REAL,
        settings: Optional[dict] = None,
    ):
        self.app_key = (app_key or "").strip()
        self.app_secret = (app_secret or "").strip()
        self.base_url = (base_url or KIWOOM_REST_REAL).rstrip("/")
        self._token_info: Optional[TokenInfo] = None
        self._token_lock = asyncio.Lock()   # 토큰 갱신 전용
        self._client_lock = asyncio.Lock()  # 클라이언트 재생성 전용
        self._client: Optional[httpx.AsyncClient] = None
        self._acnt_no: str = ""

    async def __aenter__(self) -> "KiwoomRestAPI":
        return self

    async def __aexit__(self, *_) -> None:
        await self._reset_client()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                return self._client
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=50,
                    keepalive_expiry=3.0,
                ),
            )
            return self._client

    async def _reset_client(self) -> None:
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    async def _ensure_token(self) -> bool:
        if self._token_info and not self._token_info.is_expired_soon():
            return True
        async with self._token_lock:
            if self._token_info and not self._token_info.is_expired_soon():
                return True
            return await self._issue_token()

    # ── 공통 REST 호출 (429 adaptive backoff) ────────────────────────────────
    # 모든 키움 REST API 호출은 이 함수를 경유하여 일관된 429 처리를 보장한다.
    #
    # adaptive delay: 429 발생 시 _api_delay 자동 증가, 성공 시 자동 축소.
    # 호출자(_sync_poll 등)는 _api_delay를 참조하여 inter-request 간격을 조절.
    _api_delay: float = 0.3           # 현재 inter-request 딜레이 (초)
    _API_DELAY_MIN: float = 0.3
    _API_DELAY_MAX: float = 5.0
    _API_MAX_RETRIES: int = 3
    _API_BACKOFF_BASE: float = 8.0    # 429 시 대기 = base * (attempt+1)

    async def _call_api(
        self,
        url: str,
        api_id: str,
        body: Optional[dict] = None,
        *,
        timeout: float = 15.0,
        max_retries: Optional[int] = None,
        cont_yn: str = "N",
        next_key: str = "",
        label: str = "",
    ) -> tuple[Optional[httpx.Response], bool]:
        """범용 키움 REST POST 호출 — 429 exponential backoff + adaptive delay.

        반환: (Optional[Response], hit_429: bool)
        - Response: 성공(200) 시 httpx.Response, 실패 시 None
        - hit_429: 이번 호출에서 429를 한 번이라도 만났으면 True

        호출자는 resp.json() 등으로 데이터를 직접 파싱한다.
        """
        retries = max_retries if max_retries is not None else self._API_MAX_RETRIES
        tag = label or api_id
        hit_429 = False

        if not await self._ensure_token():
            logger.warning("[연결] %s %s 토큰 없음 — 생략", _BROKER_DISPLAY, tag)
            return None, False

        assert self._token_info is not None
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self._token_info.token}",
            "api-id": api_id,
            "cont-yn": cont_yn,
            "next-key": next_key,
        }
        payload = body or {}

        for attempt in range(retries):
            try:
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=payload, timeout=timeout)

                if resp.status_code == 429:
                    hit_429 = True
                    wait_sec = self._API_BACKOFF_BASE * (attempt + 1)
                    logger.warning(
                        "[연결] %s %s 요청 과다 — %.0f초 대기 후 재시도 (%d/%d)",
                        _BROKER_DISPLAY, tag, wait_sec, attempt + 1, retries,
                    )
                    # adaptive delay 증가
                    self._api_delay = min(self._api_delay * 2, self._API_DELAY_MAX)
                    await asyncio.sleep(wait_sec)
                    continue

                if resp.status_code != 200:
                    logger.info("[연결] %s %s 응답 코드 %s", _BROKER_DISPLAY, tag, resp.status_code)
                    return None, hit_429

                # 성공 — adaptive delay 축소
                self._api_delay = max(self._api_delay * 0.8, self._API_DELAY_MIN)
                return resp, hit_429

            except Exception as e:
                logger.warning("[연결] %s %s 오류 (시도=%d): %s: %s", _BROKER_DISPLAY, tag, attempt + 1, type(e).__name__, str(e), exc_info=True)
                await self._reset_client()
                if attempt < retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                return None, hit_429

        logger.warning("[연결] %s %s %d번 재시도 모두 실패", _BROKER_DISPLAY, tag, retries)
        return None, hit_429

    async def _issue_token(self) -> bool:
        """OAuth2 접근 토큰 발급 (키움 REST API 명세 au10001). 429 시 최대 3회 재시도."""
        if not self.app_key or not self.app_secret:
            logger.warning("[연결] %s 토큰 발급 불가 — API 키 또는 시크릿 키 없음", _BROKER_DISPLAY)
            return False
        url = f"{self.base_url}{self.TOKEN_URL}"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }
        for attempt in range(3):
            try:
                if attempt > 0:
                    wait_sec = 5 * attempt
                    logger.warning(
                        "[연결] %s 토큰 발급 재시도 %d/3 — %d초 대기",
                        _BROKER_DISPLAY, attempt + 1, wait_sec,
                    )
                    await asyncio.sleep(wait_sec)
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=body, timeout=15)
                data = resp.json() if resp.text else {}
                if resp.status_code == 429:
                    wait_sec = 10 * (attempt + 1)
                    logger.warning(
                        "[연결] %s 요청 과다 — %d초 대기 후 재시도 (%d/3)",
                        _BROKER_DISPLAY, wait_sec, attempt + 1,
                    )
                    await asyncio.sleep(wait_sec)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        "[연결] %s 토큰 발급 실패 (응답코드=%s)",
                        _BROKER_DISPLAY, resp.status_code,
                    )
                    return False
                token = data.get("token") or data.get("access_token")
                expires_dt = data.get("expires_dt", "")
                if not token:
                    msg = str(data.get("return_msg") or "")
                    rc = data.get("return_code")
                    if "8030" in msg or "투자구분" in msg:
                        logger.warning(
                            "[연결] %s 인증 거부(응답코드=%s) %s — "
                            "AppKey가 유효하지 않습니다. "
                            "키움 Open API+에서 발급한 Key/Secret을 확인하세요. "
                            "연결 서버: %s",
                            _BROKER_DISPLAY, rc,
                            msg,
                            self.base_url,
                        )
                    else:
                        logger.warning(
                            "[연결] %s 응답 성공이지만 토큰 없음",
                            _BROKER_DISPLAY,
                        )
                    return False
                self._token_info = TokenInfo(token=token, expires_dt=expires_dt)
                logger.info("[연결] %s 토큰 발급 완료", _BROKER_DISPLAY)
                return True
            except Exception as e:
                logger.warning("[연결] %s 토큰 발급 오류 (시도=%d): %s: %s", _BROKER_DISPLAY, attempt + 1, type(e).__name__, e, exc_info=True)
                await self._reset_client()
                continue
        logger.warning("[연결] %s 토큰 발급 3번 모두 실패 (요청 과다 초과)", _BROKER_DISPLAY)
        return False

    async def revoke_token(self) -> bool:
        """OAuth2 접근 토큰 폐기 (키움 REST API 명세 au10002). 실패해도 예외 전파 안 함."""
        if not self._token_info or not self._token_info.token:
            logger.info("[연결] %s 토큰 폐기 생략 — 발급된 토큰 없음", _BROKER_DISPLAY)
            return True
        token = self._token_info.token
        url = f"{self.base_url}{self.REVOKE_URL}"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        body = {
            "appkey": self.app_key,
            "secretkey": self.app_secret,
            "token": token,
        }
        try:
            client = await self._get_client()
            resp = await client.post(url, headers=headers, json=body, timeout=5)
            if resp.status_code == 200:
                logger.info("[연결] %s 토큰 폐기 완료", _BROKER_DISPLAY)
            else:
                logger.warning("[연결] %s 토큰 폐기 실패 (응답코드=%s)", _BROKER_DISPLAY, resp.status_code)
        except Exception as e:
            logger.warning("[연결] %s 토큰 폐기 오류: %s: %s", _BROKER_DISPLAY, type(e).__name__, e, exc_info=True)
        finally:
            self._token_info = None
        return True

    async def get_access_token(self) -> Optional[str]:
        if not await self._ensure_token():
            return None
        return self._token_info.token if self._token_info else None

    async def _request(self, api_id: str, body: Optional[dict] = None,
                 cont_yn: str = "N", next_key: str = "") -> Optional[dict]:
        if not await self._ensure_token():
            logger.warning("[연결] %s 요청 건너뜀 — 유효한 토큰 없음 (요청ID=%s)", _BROKER_DISPLAY, api_id)
            return None
        assert self._token_info is not None
        url = f"{self.base_url}{self.ACCOUNT_URL}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self._token_info.token}",
            "api-id": api_id,
            "cont-yn": cont_yn,
            "next-key": next_key,
        }
        payload = body or {}
        for attempt in range(3):
            try:
                if attempt > 0:
                    await asyncio.sleep(3 * attempt)
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 429:
                    wait_sec = 10 * (attempt + 1)
                    logger.warning(
                        "[연결] %s 요청 과다 (요청ID=%s) — %d초 대기 후 재시도 (%d/3)",
                        _BROKER_DISPLAY, api_id, wait_sec, attempt + 1,
                    )
                    await asyncio.sleep(wait_sec)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        "[연결] %s API 응답 실패 (응답코드=%s, 요청ID=%s)",
                        _BROKER_DISPLAY, resp.status_code, api_id,
                    )
                    return None
                return resp.json()
            except Exception as e:
                logger.warning("[연결] %s 요청 오류 (요청ID=%s, 시도=%d): %s: %s", _BROKER_DISPLAY, api_id, attempt + 1, type(e).__name__, e, exc_info=True)
                await self._reset_client()
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                return None
        return None

    async def _paginated_request(self, api_id: str, body: Optional[dict] = None) -> Optional[dict]:
        """연속 조회(cont-yn=Y)를 처리하여 전체 페이지를 합산 반환. 페이지간 0.3초 대기."""
        if not await self._ensure_token():
            logger.warning("[연결] %s 연속 조회 요청 건너뜀 — 유효한 토큰 없음 (요청ID=%s)", _BROKER_DISPLAY, api_id)
            return None
        assert self._token_info is not None
        url = f"{self.base_url}{self.ACCOUNT_URL}"
        base_headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self._token_info.token}",
            "api-id": api_id,
        }
        payload = body or {}
        all_items: list = []
        cont_yn = "N"
        next_key = ""
        result: Optional[dict] = None
        page = 0
        while True:
            if page > 0:
                await asyncio.sleep(0.3)  # 연속 조회 페이지 간 요청 간격
            page += 1
            headers = {**base_headers, "cont-yn": cont_yn, "next-key": next_key}
            retry_429 = 0
            while True:
                try:
                    client = await self._get_client()
                    resp = await client.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code == 429:
                        retry_429 += 1
                        wait_sec = 10 * retry_429
                        logger.warning(
                            "[연결] %s 요청 과다 (요청ID=%s, 페이지=%d) — %d초 대기 후 재시도 (%d/3)",
                            _BROKER_DISPLAY, api_id, page, wait_sec, retry_429,
                        )
                        if retry_429 >= 3:
                            return result
                        await asyncio.sleep(wait_sec)
                        continue
                    if resp.status_code != 200:
                        logger.warning(
                            "[연결] %s 연속 조회 응답 실패 (응답코드=%s, 요청ID=%s, 페이지=%d)",
                            _BROKER_DISPLAY, resp.status_code, api_id, page,
                        )
                        return result
                    data = resp.json()
                    if result is None:
                        result = data
                    items = (data.get("body") or data).get("acnt_evlt_remn_indv_tot", [])
                    if isinstance(items, list):
                        all_items.extend(items)
                    cont_yn = resp.headers.get("cont-yn", "N")
                    next_key = resp.headers.get("next-key", "")
                    break
                except Exception as e:
                    logger.warning("[연결] %s 연속 조회 요청 오류 (요청ID=%s, 페이지=%d): %s: %s", _BROKER_DISPLAY, api_id, page, type(e).__name__, e, exc_info=True)
                    await self._reset_client()
                    return result
            if cont_yn != "Y" or not next_key:
                break
        if result is not None:
            target = result.get("body") or result
            target["acnt_evlt_remn_indv_tot"] = all_items
        return result

    async def get_deposit_detail(self, acnt_no: str = "", qry_tp: str = "3") -> Optional[dict]:
        """
        kt00001 예수금상세현황 조회.
        qry_tp: '3'=추정조회(기본), '2'=일반조회  -- 키움 API 필수 파라미터.
        """
        api_id = getattr(self, "_deposit_tr_id", self.API_ID_DEPOSIT)
        body: dict = {"qry_tp": qry_tp}   # 필수 파라미터 -- 없으면 return_code=2 오류
        resolved_acnt = acnt_no or getattr(self, "_acnt_no", "")
        if resolved_acnt:
            body["acnt_no"] = resolved_acnt
        return await self._request(api_id, body=body)

    async def get_balance_detail(
        self, qry_tp: str = "1", dmst_stex_tp: str = "KRX"
    ) -> Optional[dict]:
        """계좌평가잔고내역 조회 (api-id: kt00018). 연속 조회 자동 처리."""
        api_id = getattr(self, "_balance_tr_id", "kt00018")
        body = {"qry_tp": qry_tp, "dmst_stex_tp": dmst_stex_tp}
        return await self._paginated_request(api_id, body=body)

    async def fetch_ka10099_full(self, mrkt_tp: str) -> list[tuple[str, bool, str]]:
        """
        ka10099 -- 시장별 종목 코드 + NXT 중복상장 여부 + 시장구분코드 동시 조회.
        mrkt_tp: "0"=코스피, "10"=코스닥
        반환: [(종목코드 6자리, nxt_enable: bool, market_code: str), ...]
               market_code: 키움 응답의 marketCode 필드 ("0"=코스피, "10"=코스닥)
        실패 시 빈 리스트.

        키움 공식 응답 구조:
          { "list": [{"code": "005930", "nxtEnable": "Y", "marketCode": "0", ...}, ...] }
        엔드포인트: /api/dostk/stkinfo
        """
        url = f"{self.base_url}/api/dostk/stkinfo"
        resp, _ = await self._call_api(url, "ka10099", {"mrkt_tp": mrkt_tp},
                                  label=f"ka10099/{mrkt_tp}")
        if resp is None:
            return []
        try:
            data = resp.json()
            items = data.get("list") or []
            result: list[tuple[str, bool, str]] = []
            for item in items:
                cd = str(item.get("code") or "").strip().lstrip("A")
                if not cd:
                    continue
                # 알파벳 포함 여부에 따라 정규화 분기 (2024년 신규 종목코드 대응)
                if cd.isdigit():
                    c6 = cd.zfill(6)[-6:]  # 기존 숫자코드: 6자리 패딩
                else:
                    c6 = cd.upper()  # 알파벳 코드: 원문 대문자 유지
                nxt = str(item.get("nxtEnable") or "N").strip().upper() == "Y"
                mkt_code = str(item.get("marketCode") or mrkt_tp).strip()
                result.append((c6, nxt, mkt_code))
            return result
        except Exception as e:
            logger.warning("[연결] %s 전종목 통합 조회(ka10099) 오류 (시장구분=%s): %s", _BROKER_DISPLAY, mrkt_tp, e, exc_info=True)
            return []


    async def fetch_ka10001_nxt_enable(self, stk_cd: str) -> str:
        """
        ka10001 -- 종목 기본정보 조회로 NXT 중복상장 여부 확인.
        반환: 'Y' = KRX+NXT 중복상장, 'N' = KRX 단독, '' = 조회 실패
        """
        url = f"{self.base_url}/api/dostk/stkinfo"
        resp, _ = await self._call_api(url, "ka10001", {"stk_cd": str(stk_cd).strip()},
                                  timeout=10.0, label=f"ka10001/{stk_cd}")
        if resp is None:
            return ""
        try:
            data = resp.json()
            nxt_val = data.get("nxtEnable")
            if nxt_val is None:
                for sub_key in ("output", "output1", "Output", "Output1"):
                    sub = data.get(sub_key)
                    if isinstance(sub, dict):
                        nxt_val = sub.get("nxtEnable")
                        if nxt_val is not None:
                            break
                    elif isinstance(sub, list) and sub:
                        nxt_val = sub[0].get("nxtEnable")
                        if nxt_val is not None:
                            break
            return str(nxt_val or "N").strip().upper()
        except Exception as e:
            logger.debug("[연결] 전체 종목 조회(ka10001) 실패 %s: %s", stk_cd, e, exc_info=True)
            return ""

