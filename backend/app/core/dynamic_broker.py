# -*- coding: utf-8 -*-
"""
DynamicBrokerClient
- DB의 broker_api_specs 테이블에 저장된 명세를 읽어 동적으로 REST API 를 호출
- 브로커 전환 시 코드 변경 없이 DB 데이터만 교체하면 동작
- OAuth2 (client_credentials) 토큰 자동 갱신 지원

현재: 키움증권(kiwoom)만 지원.
"""
import json
import logging
import time
from typing import Any, Optional

import httpx as requests

from app.core.broker_urls import build_broker_urls

logger = logging.getLogger(__name__)


class DynamicBrokerClient:
    """
    사용법:
        creds = {"app_key": "...", "app_secret": "...", "account_no": "..."}
        client = DynamicBrokerClient("kiwoom", creds)
        client.load_specs()          # DB 에서 명세 로드
        result = client.call("주식현재가조회", {"fid_cond_mrkt_div_code": "J", ...})
    """

    @property
    def TOKEN_ENDPOINTS(self) -> dict:
        """broker_urls 에서 토큰 URL."""
        return {
            "kiwoom": build_broker_urls("kiwoom")["token_url"],
        }

    def __init__(self, broker: str, credentials: dict):
        self.broker      = broker
        self.creds       = credentials
        self.specs: dict[str, dict] = {}   # spec_name -> row dict
        self._token: Optional[str]  = None
        self._token_exp: float      = 0.0  # unix timestamp

    # ── 명세 로드 ──────────────────────────────────────────────────────

    def load_specs(self, profile: str = "default") -> int:
        """
        로컬 모드: DB 명세 없이 기본 TR ID를 사용하므로 항상 0 반환.
        """
        self.specs = {}
        logger.debug("[%s] 로컬 모드 -- 명세 없음 (기본 TR ID 사용)", self.broker)
        return 0

    def _load_specs_legacy(self, profile: str = "default") -> int:
        """(미사용) 구 DB 기반 명세 로드"""
        try:
            return 0
        except Exception:
            return 0

    def reload_specs(self) -> int:
        self.specs.clear()
        return self.load_specs()

    # ── 인증 토큰 ─────────────────────────────────────────────────────

    def _is_token_valid(self) -> bool:
        return bool(self._token) and time.time() < self._token_exp - 60

    def _fetch_token(self) -> str:
        """OAuth2 client_credentials 방식으로 토큰 발급"""
        endpoint = self.TOKEN_ENDPOINTS.get(self.broker)
        if not endpoint:
            raise ValueError(f"토큰 엔드포인트 미등록: {self.broker}")

        app_key    = self.creds.get("app_key", "")
        app_secret = self.creds.get("app_secret", "")

        if self.broker == "kiwoom":
            payload = {
                "grant_type": "client_credentials",
                "appkey":     app_key,
                "secretkey":  app_secret,
            }
        else:
            payload = {
                "grant_type": "client_credentials",
                "appkey":     app_key,
                "appsecret":  app_secret,
            }

        resp = requests.post(endpoint, json=payload, timeout=10)
        resp.raise_for_status()
        body = resp.json()

        token = body.get("token") or body.get("access_token")
        if not token:
            raise ValueError(f"토큰 발급 실패: {body}")

        expires_in = int(body.get("expires_in", 86400))
        self._token     = token
        self._token_exp = time.time() + expires_in
        logger.info("[%s] 토큰 발급 성공 (만료: %ds)", self.broker, expires_in)
        return token

    def get_token(self) -> str:
        if not self._is_token_valid():
            self._fetch_token()
        return self._token  # type: ignore

    # ── API 호출 ──────────────────────────────────────────────────────

    def call(
        self,
        spec_name: str,
        params: Optional[dict] = None,
        body: Optional[dict]   = None,
        extra_headers: Optional[dict] = None,
        timeout: int = 15,
    ) -> dict[str, Any]:
        """
        spec_name 에 해당하는 명세로 API 를 호출하고 JSON 응답 반환.
        params: URL 쿼리 파라미터 (GET) 또는 추가 필드
        body:   요청 본문 (POST)
        """
        spec = self.specs.get(spec_name)
        if spec is None:
            raise KeyError(f"명세 없음: '{spec_name}' -- load_specs() 를 먼저 호출하세요.")

        method   = spec["method"].upper()
        base_url = spec.get("base_url", "").rstrip("/")
        path     = spec.get("path", "")
        url      = base_url + path

        # 헤더 조합
        headers: dict[str, str] = {"Content-Type": "application/json"}

        auth_type = spec.get("auth_type", "bearer")
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.get_token()}"

        # 키움: 브로커 공통 헤더 (appkey/appsecret)
        if self.broker == "kiwoom":
            headers["appkey"]    = self.creds.get("app_key", "")
            headers["appsecret"] = self.creds.get("app_secret", "")

        # 명세에 정의된 추가 헤더 (tr_id 등)
        spec_headers: dict = spec.get("extra_headers") or {}
        if isinstance(spec_headers, str):
            try:
                spec_headers = json.loads(spec_headers)
            except Exception:
                spec_headers = {}
        headers.update(spec_headers)

        # 호출자가 넘긴 추가 헤더 (tr_id 오버라이드 등)
        if extra_headers:
            headers.update(extra_headers)

        # api-id 가 헤더에 없으면 spec 에서 보충
        if self.broker == "kiwoom" and "api-id" not in headers and spec.get("tr_id"):
            headers["api-id"] = spec["tr_id"]

        logger.debug("[%s] 요청 %s %s", self.broker, method, url)

        if method == "GET":
            resp = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
        else:
            resp = requests.post(url, headers=headers, json=body or params or {}, timeout=timeout)

        resp.raise_for_status()
        return resp.json()

    # ── 편의 메서드 ───────────────────────────────────────────────────

    def list_specs(self) -> list[str]:
        return list(self.specs.keys())

    def spec_info(self, spec_name: str) -> Optional[dict]:
        return self.specs.get(spec_name)

    def __repr__(self) -> str:
        return f"DynamicBrokerClient(broker={self.broker!r}, specs={len(self.specs)})"


# ── 글로벌 인스턴스 캐시 (기동 시 초기화) ────────────────────────────

_client_cache: dict[str, DynamicBrokerClient] = {}


def get_dynamic_client(broker: str, credentials: dict) -> DynamicBrokerClient:
    """
    브로커별 클라이언트를 생성 또는 캐시에서 반환.
    credentials 가 바뀌면 새 인스턴스를 생성한다.
    """
    client = _client_cache.get(broker)
    if client is None or client.creds != credentials:
        client = DynamicBrokerClient(broker, credentials)
        client.load_specs()
        _client_cache[broker] = client
    return client
