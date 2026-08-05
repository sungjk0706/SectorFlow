# -*- coding: utf-8 -*-
"""
토큰 발급 신뢰성 강화 — 공통 함수(auth_utils) 단위 테스트.

2세션 범위: auth_utils.py 4개 공통 함수의 단위 동작 검증.
- compute_backoff_delay: 지수 백오프 + 풀 지터 대기 시간 범위
- classify_token_failure: 일시/영구/성공 분류 판정
- retry_once_on_401: 401 감지 시 재발급 후 1회 재시도 패턴
- should_continue_recovery: 회복 루프 계속 여부 판정

기존 키움·LS 클래스 적용 회귀 테스트는 6세션에서 추가.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.app.core.auth_utils import (
    classify_token_failure,
    compute_backoff_delay,
    retry_once_on_401,
    should_continue_recovery,
)
from backend.app.core.constants import (
    TOKEN_BACKOFF_BASE_SEC,
    TOKEN_RECOVERY_MAX_ATTEMPTS,
)


# ── compute_backoff_delay ─────────────────────────────────────────────────────


class TestComputeBackoffDelay:
    def test_attempt_0_range(self):
        """attempt=0 → 0 ~ base*1 범위 (random 모킹으로 결정적 검증)."""
        with patch("backend.app.core.auth_utils.random.uniform", return_value=0.7) as mock_uniform:
            delay = compute_backoff_delay(attempt=0)
        assert delay == 0.7
        # uniform(0, base * 2^0 * jitter) = uniform(0, 1.0 * 1 * 1.0)
        mock_uniform.assert_called_once_with(0, TOKEN_BACKOFF_BASE_SEC * 1.0)

    def test_attempt_2_range(self):
        """attempt=2 → 0 ~ base*4 범위."""
        with patch("backend.app.core.auth_utils.random.uniform", return_value=3.3) as mock_uniform:
            delay = compute_backoff_delay(attempt=2)
        assert delay == 3.3
        # base * 2^2 = 1.0 * 4 = 4.0, * jitter_ratio(1.0) = 4.0
        mock_uniform.assert_called_once_with(0, TOKEN_BACKOFF_BASE_SEC * 4.0)

    def test_custom_base_and_jitter(self):
        """사용자 지정 base·jitter_ratio 적용 확인."""
        with patch("backend.app.core.auth_utils.random.uniform", return_value=1.5) as mock_uniform:
            delay = compute_backoff_delay(attempt=1, base=2.0, jitter_ratio=0.5)
        assert delay == 1.5
        # base * 2^1 = 2.0 * 2 = 4.0, * 0.5 = 2.0
        mock_uniform.assert_called_once_with(0, 2.0)

    def test_returns_nonnegative(self):
        """풀 지터는 항상 0 이상 — 음수 대기 시간 방지."""
        for attempt in range(5):
            delay = compute_backoff_delay(attempt=attempt)
            assert delay >= 0

    def test_upper_bound_grows_exponentially(self):
        """상한이 attempt 에 따라 지수적으로 증가 — 최대값이 base*2^attempt 를 넘지 않음."""
        for attempt in range(4):
            upper = TOKEN_BACKOFF_BASE_SEC * (2 ** attempt)
            # uniform 가 [0, upper] 범위이므로 delay 는 항상 upper 이하
            with patch("backend.app.core.auth_utils.random.uniform", side_effect=lambda lo, hi: hi):
                delay = compute_backoff_delay(attempt=attempt)
            assert delay == pytest.approx(upper)


# ── classify_token_failure ────────────────────────────────────────────────────


class TestClassifyTokenFailure:
    def test_success_200_no_exception(self):
        assert classify_token_failure(status_code=200, exception=None) == "success"

    def test_permanent_401(self):
        assert classify_token_failure(status_code=401) == "permanent"

    def test_permanent_403(self):
        assert classify_token_failure(status_code=403) == "permanent"

    def test_transient_429(self):
        assert classify_token_failure(status_code=429) == "transient"

    def test_transient_500(self):
        assert classify_token_failure(status_code=500) == "transient"

    def test_transient_502_503_504(self):
        for code in (502, 503, 504):
            assert classify_token_failure(status_code=code) == "transient"

    def test_permanent_response_keyword_8030(self):
        """키움 인증 거부 코드 '8030' 포함 응답 → 영구 실패."""
        assert classify_token_failure(
            status_code=200, response_text="error 8030 invalid appkey"
        ) == "permanent"

    def test_permanent_response_keyword_invalid_client(self):
        """LS 'invalid_client' 키워드 포함 응답 → 영구 실패."""
        assert classify_token_failure(
            status_code=400, response_text='{"error":"invalid_client"}'
        ) == "permanent"

    def test_permanent_response_keyword_invalid_grant(self):
        assert classify_token_failure(
            status_code=400, response_text="invalid_grant provided"
        ) == "permanent"

    def test_permanent_response_keyword_unauthorized_client(self):
        assert classify_token_failure(
            status_code=400, response_text="unauthorized_client"
        ) == "permanent"

    def test_transient_network_exception_timeout(self):
        """네트워크 타임아웃 예외 → 일시 실패."""
        exc = asyncio.TimeoutError("operation timed out")
        assert classify_token_failure(status_code=None, exception=exc) == "transient"

    def test_transient_network_exception_connection_refused(self):
        """연결 거부 예외 → 일시 실패."""
        exc = ConnectionRefusedError("Connection refused")
        assert classify_token_failure(status_code=None, exception=exc) == "transient"

    def test_transient_network_exception_dns(self):
        """DNS 해석 실패 예외 → 일시 실패 (2026-08-05 발생 사례)."""
        exc = OSError("nodename nor servname provided, or not known")
        assert classify_token_failure(status_code=None, exception=exc) == "transient"

    def test_transient_other_exception_safe_default(self):
        """기타 예외 → 안전 쪽(일시 실패) 분류 — 회복 루프 진입 허용."""
        exc = RuntimeError("unknown failure")
        assert classify_token_failure(status_code=None, exception=exc) == "transient"

    def test_transient_other_status_code_safe_default(self):
        """분류 집합에 속하지 않는 기타 HTTP 코드 → 안전 쪽(일시)."""
        assert classify_token_failure(status_code=418) == "transient"

    def test_success_with_response_text_no_keywords(self):
        """200 + 예외 없음 + 키워드 미포함 응답 → 성공 (response_text 무관)."""
        assert classify_token_failure(
            status_code=200, response_text="some body without keywords"
        ) == "success"

    def test_custom_permanent_keywords(self):
        """사용자 지정 영구 키워드 집합 적용 확인."""
        custom = frozenset({"custom_auth_error"})
        assert classify_token_failure(
            status_code=200, response_text="custom_auth_error occurred",
            permanent_keywords=custom,
        ) == "permanent"

    def test_exception_overrides_status_code(self):
        """예외 존재 시 status_code 보다 예외 분류가 우선 — 네트워크 예외는 일시."""
        exc = ConnectionError("connection reset")
        # status_code=500 이더라도 예외가 있으면 예외 경로 우선
        assert classify_token_failure(status_code=500, exception=exc) == "transient"


# ── retry_once_on_401 ─────────────────────────────────────────────────────────


class TestRetryOnceOn401:
    @pytest.mark.asyncio
    async def test_first_request_success_no_reissue(self):
        """첫 요청이 401 아닌 성공 응답 → 재발급 호출 없이 그대로 반환."""
        call_count = {"request": 0, "issue": 0, "callback": 0}

        async def request_fn():
            call_count["request"] += 1
            return ({"data": "ok"}, 200)

        async def issue_token_fn():
            call_count["issue"] += 1
            return True

        async def on_reissue_success():
            call_count["callback"] += 1

        result = await retry_once_on_401(
            issue_token_fn=issue_token_fn,
            request_fn=request_fn,
            on_reissue_success=on_reissue_success,
        )
        assert result == ({"data": "ok"}, 200)
        assert call_count == {"request": 1, "issue": 0, "callback": 0}

    @pytest.mark.asyncio
    async def test_401_reissue_success_then_retry_success(self):
        """첫 요청 401 → 재발급 성공 → 콜백 → 1회 재시도 성공."""
        call_count = {"request": 0, "issue": 0, "callback": 0}

        async def request_fn():
            call_count["request"] += 1
            if call_count["request"] == 1:
                return (None, 401)
            return ({"data": "ok"}, 200)

        async def issue_token_fn():
            call_count["issue"] += 1
            return True

        async def on_reissue_success():
            call_count["callback"] += 1

        result = await retry_once_on_401(
            issue_token_fn=issue_token_fn,
            request_fn=request_fn,
            on_reissue_success=on_reissue_success,
        )
        assert result == ({"data": "ok"}, 200)
        assert call_count == {"request": 2, "issue": 1, "callback": 1}

    @pytest.mark.asyncio
    async def test_401_reissue_failure_returns_original(self):
        """첫 요청 401 → 재발급 실패 → 원 실패 응답 반환 (재시도 없음)."""
        call_count = {"request": 0, "issue": 0, "callback": 0}

        async def request_fn():
            call_count["request"] += 1
            return (None, 401)

        async def issue_token_fn():
            call_count["issue"] += 1
            return False

        async def on_reissue_success():
            call_count["callback"] += 1

        result = await retry_once_on_401(
            issue_token_fn=issue_token_fn,
            request_fn=request_fn,
            on_reissue_success=on_reissue_success,
        )
        assert result == (None, 401)
        assert call_count == {"request": 1, "issue": 1, "callback": 0}

    @pytest.mark.asyncio
    async def test_401_reissue_success_retry_only_once(self):
        """재시도는 1회만 — 재시도 응답이 다시 401 이어도 추가 재발급 안 함 (무한 루프 방지)."""
        call_count = {"request": 0, "issue": 0, "callback": 0}

        async def request_fn():
            call_count["request"] += 1
            return (None, 401)  # 항상 401

        async def issue_token_fn():
            call_count["issue"] += 1
            return True

        async def on_reissue_success():
            call_count["callback"] += 1

        result = await retry_once_on_401(
            issue_token_fn=issue_token_fn,
            request_fn=request_fn,
            on_reissue_success=on_reissue_success,
        )
        # 1회 재시도 후 다시 401 → 그대로 반환 (추가 재발급 없음)
        assert result == (None, 401)
        assert call_count == {"request": 2, "issue": 1, "callback": 1}

    @pytest.mark.asyncio
    async def test_no_callback_when_none(self):
        """on_reissue_success=None 이어도 정상 동작."""
        call_count = {"request": 0, "issue": 0}

        async def request_fn():
            call_count["request"] += 1
            if call_count["request"] == 1:
                return (None, 401)
            return ({"data": "ok"}, 200)

        async def issue_token_fn():
            call_count["issue"] += 1
            return True

        result = await retry_once_on_401(
            issue_token_fn=issue_token_fn,
            request_fn=request_fn,
        )
        assert result == ({"data": "ok"}, 200)
        assert call_count == {"request": 2, "issue": 1}

    @pytest.mark.asyncio
    async def test_non_401_error_status_no_reissue(self):
        """401 아닌 오류 상태(예: 500) → 재발급 호출 없이 그대로 반환."""
        call_count = {"request": 0, "issue": 0}

        async def request_fn():
            call_count["request"] += 1
            return (None, 500)

        async def issue_token_fn():
            call_count["issue"] += 1
            return True

        result = await retry_once_on_401(
            issue_token_fn=issue_token_fn,
            request_fn=request_fn,
        )
        assert result == (None, 500)
        assert call_count == {"request": 1, "issue": 0}


# ── should_continue_recovery ──────────────────────────────────────────────────


class TestShouldContinueRecovery:
    def test_below_max_returns_true(self):
        """attempt=9 (최대 10) → 계속 진행."""
        assert should_continue_recovery(attempt=9) is True

    def test_at_max_returns_false(self):
        """attempt=10 (최대 10) → 종료."""
        assert should_continue_recovery(attempt=10) is False

    def test_above_max_returns_false(self):
        """attempt=11 (최대 10) → 종료."""
        assert should_continue_recovery(attempt=11) is False

    def test_zero_returns_true(self):
        """attempt=0 → 계속 진행."""
        assert should_continue_recovery(attempt=0) is True

    def test_custom_max_attempts(self):
        """사용자 지정 max_attempts 적용 확인."""
        assert should_continue_recovery(attempt=4, max_attempts=5) is True
        assert should_continue_recovery(attempt=5, max_attempts=5) is False

    def test_default_max_matches_constant(self):
        """기본값이 상수와 일치 — 단일 진실 소스 확인."""
        # attempt = max-1 → True, attempt = max → False
        assert should_continue_recovery(attempt=TOKEN_RECOVERY_MAX_ATTEMPTS - 1) is True
        assert should_continue_recovery(attempt=TOKEN_RECOVERY_MAX_ATTEMPTS) is False
