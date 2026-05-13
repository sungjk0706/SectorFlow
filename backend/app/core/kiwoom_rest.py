# -*- coding: utf-8 -*-
"""
키움증권 REST API 통신 클래스 (64비트 호환)
- 순수 HTTP/JSON (requests 사용, OCX/COM 미사용)
- OAuth2 client_credentials: App Key, App Secret -> Access Token
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import httpx as requests

from app.core.broker_urls import build_broker_urls, KIWOOM_REST_REAL
from app.core.kiwoom_sector_rest import (
    fetch_ka10086_daily_price as _ka10086_fetch_single,
    fetch_ka10086_sector_all as _ka10086_fetch_all,
    fetch_ka10099_stock_name_map as _ka10099_name_map,
)

_log = logging.getLogger(__name__)


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
    ACCOUNT_URL = "/api/dostk/acnt"
    API_ID_ACCOUNT = "ka00001"
    API_ID_DEPOSIT = "kt00001"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = KIWOOM_REST_REAL,
    ):
        self.app_key = (app_key or "").strip()
        self.app_secret = (app_secret or "").strip()
        self.base_url = (base_url or KIWOOM_REST_REAL).rstrip("/")
        self._token_info: Optional[TokenInfo] = None
        self._lock = threading.RLock()  # 스레드 간 REST 호출 직렬화 — access violation 방지 (RLock: _request→_ensure_token 재진입 허용)

    def __enter__(self) -> "KiwoomRestAPI":
        return self

    def __exit__(self, *_) -> None:
        pass

    def _ensure_token(self) -> bool:
        with self._lock:
            if self._token_info and not self._token_info.is_expired_soon():
                return True
            return self._issue_token()

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

    def _call_api(
        self,
        url: str,
        api_id: str,
        body: dict | None = None,
        *,
        timeout: float = 15.0,
        max_retries: int | None = None,
        cont_yn: str = "N",
        next_key: str = "",
        label: str = "",
    ) -> tuple[requests.Response | None, bool]:
        """범용 키움 REST POST 호출 — 429 exponential backoff + adaptive delay.

        반환: (Response | None, hit_429: bool)
        - Response: 성공(200) 시 httpx.Response, 실패 시 None
        - hit_429: 이번 호출에서 429를 한 번이라도 만났으면 True

        호출자는 resp.json() 등으로 데이터를 직접 파싱한다.
        """
        retries = max_retries if max_retries is not None else self._API_MAX_RETRIES
        tag = label or api_id
        hit_429 = False

        if not self._ensure_token():
            _log.warning("[REST] %s 토큰 없음 -- 생략", tag)
            return None, False

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
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

                if resp.status_code == 429:
                    hit_429 = True
                    wait_sec = self._API_BACKOFF_BASE * (attempt + 1)
                    _log.warning(
                        "[REST] %s 429 -- %.0f초 대기 후 재시도 (%d/%d)",
                        tag, wait_sec, attempt + 1, retries,
                    )
                    # adaptive delay 증가
                    self._api_delay = min(self._api_delay * 2, self._API_DELAY_MAX)
                    time.sleep(wait_sec)
                    continue

                if resp.status_code != 200:
                    _log.info("[REST] %s HTTP %s", tag, resp.status_code)
                    return None, hit_429

                # 성공 — adaptive delay 축소
                self._api_delay = max(self._api_delay * 0.8, self._API_DELAY_MIN)
                return resp, hit_429

            except Exception as e:
                _log.warning("[REST] %s 예외 (시도=%d): %s", tag, attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                return None, hit_429

        _log.warning("[REST] %s %d회 재시도 모두 실패", tag, retries)
        return None, hit_429

    def _issue_token(self) -> bool:
        """OAuth2 접근 토큰 발급 (키움 REST API 명세 au10001). 429 시 최대 3회 재시도."""
        if not self.app_key or not self.app_secret:
            _log.warning("[키움증권]  토큰 발급 불가 -- app_key 또는 app_secret 없음")
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
                    _log.warning(
                        "[키움증권] 토큰 재시도 %d/3 -- %d초 대기 후 재요청 (au10001)",
                        attempt + 1, wait_sec,
                    )
                    time.sleep(wait_sec)
                resp = requests.post(url, headers=headers, json=body, timeout=15)
                data = resp.json() if resp.text else {}
                if resp.status_code == 429:
                    wait_sec = 10 * (attempt + 1)
                    _log.warning(
                        "[키움증권]  429 요청 과다(au10001) -- %d초 대기 후 재시도 (%d/3)",
                        wait_sec, attempt + 1,
                    )
                    time.sleep(wait_sec)
                    continue
                if resp.status_code != 200:
                    _log.warning(
                        "[키움증권] 토큰 발급 실패 status=%s url=%s body=%s",
                        resp.status_code, url, data,
                    )
                    return False
                token = data.get("token") or data.get("access_token")
                expires_dt = data.get("expires_dt", "")
                if not token:
                    msg = str(data.get("return_msg") or "")
                    rc = data.get("return_code")
                    if "8030" in msg or "투자구분" in msg:
                        _log.warning(
                            "[키움증권] OAuth 거부(return_code=%s) %s -- "
                            "AppKey가 유효하지 않습니다. "
                            "키움 Open API+에서 발급한 Key/Secret을 확인하세요. "
                            "연결 서버: %s",
                            rc,
                            msg,
                            self.base_url,
                        )
                    else:
                        _log.warning(
                            "[키움증권] 200 응답이지만 토큰 필드 없음 url=%s body=%s",
                            url,
                            data,
                        )
                    return False
                self._token_info = TokenInfo(token=token, expires_dt=expires_dt)
                _log.info(
                    "[키움증권] 키움증권 접속완료 (au10001) token=%s... expires_dt=%s",
                    token[:10], expires_dt,
                )
                return True
            except Exception as e:
                _log.warning("[키움증권] 토큰 요청 예외 (시도=%d): %s", attempt + 1, e)
                continue
        _log.warning("[키움증권]  토큰 발급 3회 모두 실패 (429 초과)")
        return False

    def get_access_token(self) -> Optional[str]:
        if not self._ensure_token():
            return None
        return self._token_info.token if self._token_info else None

    def get_auth_headers(self, api_id: str) -> Optional[dict]:
        """스레드 안전 인증 헤더 생성 — Lock 내에서 토큰 확인/갱신 + 헤더 dict 반환을 원자적으로 수행.

        _post_ka10095_chunk() 등 외부 함수에서 api._ensure_token() + api._token_info.token을
        직접 접근하는 대신 이 메서드를 사용하여 토큰 불일치를 원천 차단한다.
        토큰 확보 실패 시 None 반환.
        """
        with self._lock:
            if not self._ensure_token():
                return None
            return {
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {self._token_info.token}",
                "api-id": api_id,
                "cont-yn": "N",
                "next-key": "",
            }

    def _request(self, api_id: str, body: Optional[dict] = None,
                 cont_yn: str = "N", next_key: str = "") -> Optional[dict]:
        with self._lock:
            if not self._ensure_token():
                _log.warning("[키움증권] 요청 건너뜀 -- 유효한 토큰 없음 (api-id=%s)", api_id)
                return None
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
                        time.sleep(3 * attempt)
                    resp = requests.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code == 429:
                        wait_sec = 10 * (attempt + 1)
                        _log.warning(
                            "[키움증권]  429 요청 과다(api-id=%s) -- %d초 대기 후 재시도 (%d/3)",
                            api_id, wait_sec, attempt + 1,
                        )
                        time.sleep(wait_sec)
                        continue
                    if resp.status_code != 200:
                        _log.warning(
                            "[키움증권] API 응답 실패 status=%s api-id=%s",
                            resp.status_code, api_id,
                        )
                        return None
                    return resp.json()
                except Exception as e:
                    _log.warning("[키움증권] 요청 예외 api-id=%s: %s", api_id, e)
                    return None
            return None

    def _paginated_request(self, api_id: str, body: Optional[dict] = None) -> Optional[dict]:
        """연속조회(cont-yn=Y)를 처리하여 전체 페이지를 합산 반환. 페이지간 0.3초 대기."""
        with self._lock:
            if not self._ensure_token():
                _log.warning("[키움증권] 연속조회 요청 건너뜀 -- 유효한 토큰 없음 (api-id=%s)", api_id)
                return None
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
                    time.sleep(0.3)  # 연속조회 페이지 간 요청 간격
                page += 1
                headers = {**base_headers, "cont-yn": cont_yn, "next-key": next_key}
                retry_429 = 0
                while True:
                    try:
                        resp = requests.post(url, headers=headers, json=payload, timeout=15)
                        if resp.status_code == 429:
                            retry_429 += 1
                            wait_sec = 10 * retry_429
                            _log.warning(
                                "[키움증권]  429 요청 과다(api-id=%s, page=%d) -- %d초 대기 후 재시도 (%d/3)",
                                api_id, page, wait_sec, retry_429,
                            )
                            if retry_429 >= 3:
                                return result
                            time.sleep(wait_sec)
                            continue
                        if resp.status_code != 200:
                            _log.warning(
                                "[키움증권] 연속조회 응답 실패 status=%s api-id=%s page=%d",
                                resp.status_code, api_id, page,
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
                        _log.warning("[키움증권] 연속조회 요청 예외 api-id=%s page=%d: %s", api_id, page, e)
                        return result
                if cont_yn != "Y" or not next_key:
                    break
            if result is not None:
                target = result.get("body") or result
                target["acnt_evlt_remn_indv_tot"] = all_items
            return result

    def get_account_number(self) -> Optional[str]:
        api_id = getattr(self, "_account_tr_id", self.API_ID_ACCOUNT)
        data = self._request(api_id)
        if not data:
            return None
        return data.get("acctNo") or (data.get("body") or {}).get("acctNo")

    def get_deposit_detail(self, acnt_no: str = "", qry_tp: str = "3") -> Optional[dict]:
        """
        kt00001 예수금상세현황 조회.
        qry_tp: '3'=추정조회(기본), '2'=일반조회  -- 키움 API 필수 파라미터.
        """
        api_id = getattr(self, "_deposit_tr_id", self.API_ID_DEPOSIT)
        body: dict = {"qry_tp": qry_tp}   # 필수 파라미터 -- 없으면 return_code=2 오류
        resolved_acnt = acnt_no or getattr(self, "_acnt_no", "")
        if resolved_acnt:
            body["acnt_no"] = resolved_acnt
        return self._request(api_id, body=body)

    def get_balance_detail(
        self, qry_tp: str = "1", dmst_stex_tp: str = "KRX"
    ) -> Optional[dict]:
        """계좌평가잔고내역 조회 (api-id: kt00018). 연속조회 자동 처리."""
        api_id = getattr(self, "_balance_tr_id", "kt00018")
        body = {"qry_tp": qry_tp, "dmst_stex_tp": dmst_stex_tp}
        return self._paginated_request(api_id, body=body)

    def fetch_ka10086_daily_price(self, stk_cd: str, qry_dt: str) -> Optional[dict]:
        """ka10086 단건 조회 -- 장외 시간에도 확정 종가·등락률·거래대금 반환."""
        return _ka10086_fetch_single(self, stk_cd, qry_dt)

    def fetch_ka10086_sector_all(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.1,
        on_progress: "Callable[[int, int], None] | None" = None,
        resume_codes: "set[str] | None" = None,
    ) -> dict[str, dict]:
        """전체 종목 ka10086 순차 조회 -- 장외 시간 확정 데이터 채우기용."""
        return _ka10086_fetch_all(self, krx_codes, qry_dt, interval_sec=interval_sec, on_progress=on_progress, resume_codes=resume_codes)

    def fetch_ka10099_stock_name_map(self) -> dict[str, str]:
        """ka10099 코스피+코스닥 전체 종목명 매핑 조회. {6자리 종목코드: 종목명}."""
        return _ka10099_name_map(self)

    def fetch_ka20001_index(self, mrkt_tp: str, inds_cd: str) -> Optional[dict]:
        """ka20001 -- 업종현재가요청. 지수(현재가·등락률) + 상승/하락 종목수.

        mrkt_tp: "0"=코스피, "1"=코스닥
        inds_cd: 업종코드 (예: "001"=코스피종합, "101"=코스닥종합)
        반환: {"price", "change", "rate", "up_count", "down_count"} 또는 None
        """
        url = f"{self.base_url}/api/dostk/sect"
        resp, _ = self._call_api(url, "ka20001", {"mrkt_tp": mrkt_tp, "inds_cd": inds_cd},
                                  timeout=10.0, label=f"ka20001/{inds_cd}")
        if resp is None:
            return None

        try:
            data = resp.json()
        except Exception:
            _log.info("[지수폴링] ka20001 JSON 파싱 실패 inds_cd=%s", inds_cd)
            return None

        def _f(v) -> float:
            try:
                return float(str(v or "0").replace(",", "").replace("+", "").strip())
            except (ValueError, TypeError):
                return 0.0

        def _i(v) -> int:
            try:
                return int(str(v or "0").replace(",", "").strip())
            except (ValueError, TypeError):
                return 0

        price  = _f(data.get("cur_prc") or data.get("pric") or 0)
        change = _f(data.get("pred_pre") or 0)
        rate   = _f(data.get("flu_rt") or 0)
        sig = str(data.get("pred_pre_sig") or "").strip()
        if sig in ("4", "5", "44", "45"):
            change = -abs(change)
            rate   = -abs(rate)

        return {
            "price": abs(price), "change": change, "rate": rate,
            "up_count": _i(data.get("rising")),
            "down_count": _i(data.get("fall")),
        }

    def fetch_ka10099_market_code_list(self, mrkt_tp: str) -> list[str]:
        """
        ka10099 -- 시장별 종목 코드 리스트 조회.
        mrkt_tp: "0"=코스피, "10"=코스닥
        반환: 종목코드 문자열 리스트 (6자리, 실패 시 빈 리스트)
        """
        result = self.fetch_ka10099_full(mrkt_tp)
        return [cd for cd, _, _ in result]

    def fetch_ka10099_full(self, mrkt_tp: str) -> list[tuple[str, bool, str]]:
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
        resp, _ = self._call_api(url, "ka10099", {"mrkt_tp": mrkt_tp},
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
            _log.warning("[시장구분] ka10099 예외 mrkt_tp=%s: %s", mrkt_tp, e)
            return []

    def fetch_ka10099_eligible_stocks(self) -> dict[str, str]:
        """ka10099 — 적격 종목코드 수집 위임. industry_map 모듈 참조."""
        from app.core.industry_map import fetch_ka10099_eligible_stocks
        return fetch_ka10099_eligible_stocks(self)

    def fetch_ka10101(self, mrkt_tp: str) -> list[dict]:
        """
        ka10101 — 업종코드 목록 조회 (키움 공식 확인: 정상 동작 API).
        엔드포인트: /api/dostk/stkinfo
        mrkt_tp: "0"=코스피, "1"=코스닥
        연속조회(cont-yn/next-key) 지원. _call_api 경유.
        """
        url = f"{self.base_url}/api/dostk/stkinfo"
        body = {"mrkt_tp": mrkt_tp}
        all_items: list[dict] = []
        cont_yn = "N"
        next_key = ""
        page = 0
        try:
            while True:
                if page > 0:
                    time.sleep(0.3)
                page += 1
                resp, _ = self._call_api(
                    url, "ka10101", body,
                    cont_yn=cont_yn, next_key=next_key,
                    label=f"ka10101/{mrkt_tp}/p{page}",
                )
                if resp is None:
                    return all_items
                data = resp.json()
                if page == 1:
                    import json as _json
                    _log.info(
                        "[업종코드] ka10101 mrkt_tp=%s 응답 키: %s",
                        mrkt_tp, list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                    )
                items = data.get("list", [])
                if not isinstance(items, list):
                    _log.warning("[업종코드] ka10101 mrkt_tp=%s 'list' 키 없음 -- 응답: %s", mrkt_tp, str(data)[:500])
                    return all_items
                if page == 1 and items and isinstance(items[0], dict):
                    _log.info("[업종코드] ka10101 mrkt_tp=%s 첫 항목: %s", mrkt_tp, _json.dumps(items[0], ensure_ascii=False)[:300])
                    _log.info("[업종코드] ka10101 mrkt_tp=%s 항목수=%d", mrkt_tp, len(items))
                all_items.extend(items)
                cont_yn = resp.headers.get("cont-yn", "N")
                next_key = resp.headers.get("next-key", "")
                if cont_yn != "Y" or not next_key:
                    break
            _log.info("[업종코드] ka10101 mrkt_tp=%s 전체 %d개 조회 완료", mrkt_tp, len(all_items))
            return all_items
        except Exception as e:
            _log.warning("[업종코드] ka10101 예외 mrkt_tp=%s: %s", mrkt_tp, e)
            return []

    def fetch_ka10001_nxt_enable(self, stk_cd: str) -> str:
        """
        ka10001 -- 종목 기본정보 조회로 NXT 중복상장 여부 확인.
        반환: 'Y' = KRX+NXT 중복상장, 'N' = KRX 단독, '' = 조회 실패
        """
        url = f"{self.base_url}/api/dostk/stkinfo"
        resp, _ = self._call_api(url, "ka10001", {"stk_cd": str(stk_cd).strip()},
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
            _log.debug("[NXT] ka10001 조회 실패 %s: %s", stk_cd, e)
            return ""

    def fetch_nxt_enable_map(self, codes: list[str], interval_sec: float = 0.17) -> dict[str, bool]:
        """
        종목 리스트 전체 ka10001 순차 조회 -> {종목코드: NXT여부} 반환.
        interval_sec: 호출 간격 (초당 ~6건, 키움 제한 안전 마진)
        """
        result: dict[str, bool] = {}
        for i, cd in enumerate(codes):
            if i > 0:
                time.sleep(interval_sec)
            val = self.fetch_ka10001_nxt_enable(cd)
            result[cd] = (val == "Y")
        return result


def kiwoom_try_token(app_key: str, app_secret: str) -> tuple[bool, Optional[str], Optional[dict]]:
    """
    키움 OAuth2 토큰 발급 시도. (success, token, error_detail) 반환.
    error_detail: 실패 시 키움 응답 {err_cd, err_msg, ...} 또는 예외 정보
    """
    urls = build_broker_urls("kiwoom")
    url = urls["token_url"]
    body = {
        "grant_type": "client_credentials",
        "appkey": (app_key or "").strip(),
        "secretkey": (app_secret or "").strip(),
    }
    if not body["appkey"] or not body["secretkey"]:
        return False, None, {"err_msg": "App Key / Secret 없음"}
    try:
        resp = requests.post(url, headers={"Content-Type": "application/json;charset=UTF-8"}, json=body, timeout=15)
        data = resp.json() if resp.text else {}
        if resp.status_code != 200:
            return False, None, {"status": resp.status_code, "url": url, **data}
        token = data.get("token") or data.get("access_token")
        if not token:
            # return_msg / return_code 가 있으면 우선 노출 (8030 등 키움 앱레벨 오류)
            kiwoom_msg = data.get("return_msg", "")
            kiwoom_code = data.get("return_code", "")
            err_msg = f"[{kiwoom_code}] {kiwoom_msg}" if kiwoom_msg else "토큰 필드 없음"
            return False, None, {"err_msg": err_msg, **data}
        return True, token, None
    except Exception as e:
        return False, None, {"err_msg": str(e), "url": url}
