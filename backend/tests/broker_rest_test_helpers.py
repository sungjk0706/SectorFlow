# -*- coding: utf-8 -*-
"""테스트 전용 REST API 헬퍼 — 생산 경로에서 미사용 메서드의 테스트 검증용.

전수 조사(2026-07-31)에서 생산 코드 0참조·테스트만 호출로 확인된 3건:
  - KiwoomRestAPI.fetch_ka10099_full     (시장별 종목코드+NXT 중복상장 조회)
  - KiwoomRestAPI.fetch_ka10001_nxt_enable (종목 기본정보로 NXT 중복상장 여부)
  - LsRestAPI.call_api                    (범용 REST API 호출, 재시도 포함)

P16(살아있는 경로) 준수 — 생산 코드에서 제거하고 테스트 헬퍼로 이동.
각 함수는 첫 인자로 API 인스턴스를 받아 인스턴스 속성/메서드에 접근.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── KiwoomRestAPI 테스트 헬퍼 ──────────────────────────────────────────────────

async def fetch_ka10099_full(api, mrkt_tp: str) -> list[tuple[str, bool, str]]:
    """ka10099 -- 시장별 종목 코드 + NXT 중복상장 여부 + 시장구분코드 동시 조회.

    mrkt_tp: "0"=코스피, "10"=코스닥
    반환: [(종목코드 6자리, nxt_enable: bool, market_code: str), ...]
           market_code: 키움 응답의 marketCode 필드 ("0"=코스피, "10"=코스닥)
    실패 시 빈 리스트.
    """
    from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
    broker_display = BROKER_DISPLAY_NAMES["kiwoom"]

    url = f"{api.base_url}/api/dostk/stkinfo"
    resp, _ = await api._call_api(url, "ka10099", {"mrkt_tp": mrkt_tp},
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
        logger.warning("[연결] %s 전종목 통합 조회(ka10099) 오류 (시장구분=%s): %s", broker_display, mrkt_tp, e, exc_info=True)
        return []


async def fetch_ka10001_nxt_enable(api, stk_cd: str) -> str:
    """ka10001 -- 종목 기본정보 조회로 NXT 중복상장 여부 확인.

    반환: 'Y' = KRX+NXT 중복상장, 'N' = KRX 단독, '' = 조회 실패
    """
    url = f"{api.base_url}/api/dostk/stkinfo"
    resp, _ = await api._call_api(url, "ka10001", {"stk_cd": str(stk_cd).strip()},
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


# ── LsRestAPI 테스트 헬퍼 ──────────────────────────────────────────────────────

async def ls_call_api(
    api,
    url: str,
    method: str = "GET",
    body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 15.0,
    max_retries: int = 3,
) -> Optional[dict]:
    """범용 REST API 호출 (재시도 로직 포함).

    특징:
    - 429 exponential backoff
    - 일반 예외 linear backoff
    - 토큰 자동 갱신
    """
    from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
    broker_display = BROKER_DISPLAY_NAMES["ls"]

    await api.ensure_client()
    if api._client is None:
        logger.warning("[연결] %s HTTP 클라이언트 초기화 안됨", broker_display)
        return None

    if not await api.ensure_token():
        logger.warning("[연결] %s 토큰 없음", broker_display)
        return None

    assert api._token_info is not None
    default_headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": f"Bearer {api._token_info.access_token}",
    }
    if headers:
        default_headers.update(headers)

    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                resp = await api._client.get(url, headers=default_headers, timeout=timeout)
            else:
                resp = await api._client.post(url, headers=default_headers, json=body, timeout=timeout)

            if resp.status_code == 429:
                wait_sec = 8 * (attempt + 1)
                logger.warning(
                    f"[연결] {broker_display} 요청 과다 — {wait_sec:.0f}초 대기 후 재시도 ({attempt+1}/{max_retries})"
                )
                await asyncio.sleep(wait_sec)
                continue

            if resp.status_code != 200:
                logger.info(f"[연결] {broker_display} 응답 코드 {resp.status_code} - 본문: {resp.text}")
                return None

            return resp.json()

        except Exception as e:
            logger.warning(f"[연결] {broker_display} 오류 (시도={attempt+1}): {e}", exc_info=True)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            return None

    logger.warning(f"[연결] {broker_display} {max_retries}번 재시도 모두 실패")
    return None
