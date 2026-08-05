# -*- coding: utf-8 -*-
"""
토큰 발급 전용 공통 함수 — 적용 범위: 토큰 발급·재발급·회복 루프 (범용 라이브러리 아님, P24).

키움·LS 양쪽에 중복된 토큰 발급 재시도·백오프·실패 분류·401 재발급 로직을
공통 함수로 추출 (설계서 결정 7). API 호출부(URL·요청/응답 포맷·인증 에러 코드)는
각 증권사 모듈에 잔류.

참조 상수: backend.app.core.constants 의 TOKEN_* 상수.
"""
from __future__ import annotations

import random
from typing import Awaitable, Callable, Optional

from backend.app.core.constants import (
    TOKEN_BACKOFF_BASE_SEC,
    TOKEN_BACKOFF_JITTER_RATIO,
    TOKEN_PERMANENT_HTTP_CODES,
    TOKEN_PERMANENT_RESPONSE_KEYWORDS,
    TOKEN_RECOVERY_MAX_ATTEMPTS,
    TOKEN_TRANSIENT_HTTP_CODES,
)

# 네트워크 계열 예외 타입 이름 — 일시 실패로 분류 (DNS·연결 거부·타임아웃)
_TRANSIENT_EXCEPTION_KEYWORDS = frozenset({
    "connecterror",
    "connection",
    "dns",
    "getaddrinfo",
    "nodename",
    "readtimeout",
    "refused",
    "resolve",
    "timeout",
    "timedout",
})


def compute_backoff_delay(
    attempt: int,
    base: float = TOKEN_BACKOFF_BASE_SEC,
    jitter_ratio: float = TOKEN_BACKOFF_JITTER_RATIO,
) -> float:
    """지수 백오프 + 풀 지터 대기 시간 계산 (설계서 결정 1).

    base_delay = base * (2 ** attempt)
    반환 = random.uniform(0, base_delay * jitter_ratio)  # 풀 지터

    attempt=0 → 0 ~ base*1 범위
    attempt=1 → 0 ~ base*2 범위
    attempt=2 → 0 ~ base*4 범위
    """
    base_delay = base * (2 ** attempt)
    return random.uniform(0, base_delay * jitter_ratio)


def classify_token_failure(
    status_code: Optional[int],
    exception: Optional[Exception] = None,
    response_text: str = "",
    permanent_keywords: frozenset = TOKEN_PERMANENT_RESPONSE_KEYWORDS,
) -> str:
    """실패 분류 판정 (설계서 결정 6 기준).

    반환: "permanent" / "transient" / "success"

    판정 순서:
    1. 예외 존재 + 네트워크 계열 → "transient"
    2. status_code in 영구 HTTP 코드 → "permanent"
    3. status_code in 일시 HTTP 코드 → "transient"
    4. 응답 본문에 영구 키워드 포함 → "permanent"
    5. 기타 예외 → "transient" (안전 쪽: 회복 루프 진입)
    6. status_code 200 + 예외 없음 → "success"
    """
    # (1) 예외 존재 + 네트워크 계열 → 일시 실패
    if exception is not None:
        exc_name = type(exception).__name__.lower()
        exc_msg = str(exception).lower()
        if any(kw in exc_name or kw in exc_msg for kw in _TRANSIENT_EXCEPTION_KEYWORDS):
            return "transient"
        # (5) 기타 예외 → 안전 쪽(일시 실패)으로 분류하여 회복 루프 진입
        return "transient"

    # (2) 영구 HTTP 코드
    if status_code is not None and status_code in TOKEN_PERMANENT_HTTP_CODES:
        return "permanent"

    # (3) 일시 HTTP 코드
    if status_code is not None and status_code in TOKEN_TRANSIENT_HTTP_CODES:
        return "transient"

    # (4) 응답 본문에 영구 키워드 포함 — 200 이더라도 키워드 포함 시 영구 실패
    if response_text:
        text_lower = response_text.lower()
        if any(kw.lower() in text_lower for kw in permanent_keywords):
            return "permanent"

    # (6) status_code 200 + 예외 없음 → 성공
    if status_code == 200:
        return "success"

    # status_code 가 있으나 분류 집합에 속하지 않는 기타 코드 — 안전 쪽(일시)
    return "transient"


async def retry_once_on_401(
    issue_token_fn: Callable[[], Awaitable[bool]],
    request_fn: Callable[[], Awaitable[tuple]],
    *,
    on_reissue_success: Optional[Callable[[], Awaitable[None]]] = None,
) -> tuple:
    """401 감지 시 재발급 후 1회 재시도 패턴 (설계서 결정 3).

    흐름:
    1. 첫 요청(request_fn) 호출 → (response, status_code) 반환
    2. status_code == 401 → issue_token_fn() 재발급 시도
       - 재발급 성공 → on_reissue_success() 콜백(헤더 갱신 등) → request_fn() 1회 재시도 → 결과 반환
       - 재발급 실패 → 원 실패 응답 반환
    3. 401 아닌 응답 → 그대로 반환 (재발급 호출 없음)

    1회만 재시도 — 무한 루프 방지 (P24).

    반환: request_fn 이 반환하는 tuple (원 요청 응답 또는 재시도 응답).
    """
    result = await request_fn()
    # result 가 (response, status_code) 형태 — 두 번째 값이 status_code
    if not isinstance(result, tuple) or len(result) < 2:
        return result

    status_code = result[1]
    if status_code != 401:
        return result

    # 401 감지 → 재발급 시도
    reissue_ok = await issue_token_fn()
    if not reissue_ok:
        # 재발급 실패 → 원 실패 응답 반환
        return result

    # 재발급 성공 → 콜백(헤더 갱신 등)
    if on_reissue_success is not None:
        await on_reissue_success()

    # 1회 재시도
    return await request_fn()


def should_continue_recovery(
    attempt: int,
    max_attempts: int = TOKEN_RECOVERY_MAX_ATTEMPTS,
) -> bool:
    """회복 루프 계속 여부 판정 (설계서 결정 2).

    회복 루프(5세션)에서 호출 — 최대 횟수 도달 여부를 공통 함수로 단일화.
    반환: attempt < max_attempts 이면 True (계속), 아니면 False (종료).
    """
    return attempt < max_attempts
