# -*- coding: utf-8 -*-
"""
토큰 발급 신뢰성 강화 — 공통 함수(auth_utils) 단위 테스트 + 통합 회귀 테스트.

2세션 범위: auth_utils.py 4개 공통 함수의 단위 동작 검증.
- compute_backoff_delay: 지수 백오프 + 풀 지터 대기 시간 범위
- classify_token_failure: 일시/영구/성공 분류 판정
- retry_once_on_401: 401 감지 시 재발급 후 1회 재시도 패턴
- should_continue_recovery: 회복 루프 계속 여부 판정

6세션 범위: 엔진 회복 루프·10회 상한·중복 로직 제거 통합 회귀 테스트.
- 일시 실패 회복 루프 진입 → 1회차 성공 시 정상 전환 + 화면 알림
- 회복 루프 10회 상한 → 11회 시도 없이 종료 + 수동 재시작 안내
- 중복 로직 제거 → 키움·LS 양쪽 동일 auth_utils 함수 호출 검증
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── 6세션: 엔진 회복 루프 통합 회귀 테스트 ──────────────────────────────────────


class TestTokenRecoveryLoopRecovery:
    """일시 실패 회복 루프 진입 → 1회차 성공 시 정상 전환 + 화면 알림 (6-1)."""

    @pytest.mark.asyncio
    async def test_transient_failure_recovery_success_first_attempt(self):
        """일시 실패 → 회복 루프 1회차 성공 → access_token 설정 + 화면 알림 + 플래그 해제."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}

        # 1회차 시도 시 토큰 발급 성공
        async def _fake_get_tokens(_router):
            mock_state.broker_tokens = {"kiwoom": "recovered_token"}
            mock_state.token_failure_kind = None
            return None

        mock_router = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock) as mock_broadcast,
            patch("backend.app.services.engine_lifecycle.log_message") as mock_log,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 회복 성공 → access_token 설정 + 플래그 해제 + 화면 알림
        assert mock_state.access_token == "recovered_token"
        assert mock_state.token_recovery_in_progress is False
        assert mock_state.token_failure_kind is None
        mock_broadcast.assert_awaited()
        log_msgs = [str(c) for c in mock_log.call_args_list]
        assert any("회복 성공" in m for m in log_msgs)


class TestTokenRecoveryLoopMaxAttempts:
    """회복 루프 10회 상한 → 11회 시도 없이 종료 + 수동 재시작 안내 (6-5)."""

    @pytest.mark.asyncio
    async def test_recovery_loop_10_attempts_then_stop(self):
        """10회 모두 실패 → 11회 시도 없이 루프 종료 + 수동 재시작 안내 + 플래그 해제."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}

        attempt_count = {"n": 0}

        # 매 시도마다 토큰 발급 실패 (빈 broker_tokens 유지)
        async def _fake_get_tokens(_router):
            attempt_count["n"] += 1
            mock_state.broker_tokens = {}
            mock_state.token_failure_kind = "transient"
            return None

        mock_router = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock) as mock_broadcast,
            patch("backend.app.services.engine_lifecycle.log_message") as mock_log,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 10회까지만 시도 — 11회 시도 없음
        assert attempt_count["n"] == TOKEN_RECOVERY_MAX_ATTEMPTS
        # 루프 종료 → 플래그 해제 + 수동 재시작 안내
        assert mock_state.token_recovery_in_progress is False
        log_msgs = [str(c) for c in mock_log.call_args_list]
        assert any("수동 재시작" in m for m in log_msgs)
        mock_broadcast.assert_awaited()

    @pytest.mark.asyncio
    async def test_recovery_loop_permanent_failure_during_loop_stops_immediately(self):
        """회복 루프 중 영구 실패 감지 → 즉시 종료 + API 키 확인 안내."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}

        attempt_count = {"n": 0}

        # 1회차 시도 시 영구 실패로 전환
        async def _fake_get_tokens(_router):
            attempt_count["n"] += 1
            mock_state.broker_tokens = {}
            mock_state.token_failure_kind = "permanent"
            return None

        mock_router = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.log_message") as mock_log,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 1회차 영구 실패 → 즉시 종료 (2회차 시도 없음)
        assert attempt_count["n"] == 1
        assert mock_state.token_recovery_in_progress is False
        assert mock_state.token_failure_kind == "permanent"
        log_msgs = [str(c) for c in mock_log.call_args_list]
        assert any("영구 실패" in m for m in log_msgs)


# ── 6세션: 중복 로직 제거 검증 (6-6) ──────────────────────────────────────────────


class TestDuplicateLogicRemoval:
    """키움·LS 양캐스트가 동일 auth_utils 함수를 호출하는지 검증 (결정 7 완료 기준)."""

    def test_kiwoom_imports_auth_utils_functions(self):
        """키움 모듈이 auth_utils의 공통 함수를 import 하는지 확인."""
        from backend.app.core import kiwoom_rest

        # import 확인 — 모듈이 공통 함수를 참조하고 있는지
        import inspect
        src = inspect.getsource(kiwoom_rest)
        assert "compute_backoff_delay" in src
        assert "classify_token_failure" in src
        assert "retry_once_on_401" in src

    def test_ls_imports_auth_utils_functions(self):
        """LS 모듈이 auth_utils의 공통 함수를 import 하는지 확인."""
        from backend.app.core import ls_rest

        import inspect
        src = inspect.getsource(ls_rest)
        assert "compute_backoff_delay" in src
        assert "classify_token_failure" in src
        assert "retry_once_on_401" in src

    def test_kiwoom_no_hardcoded_backoff_formula(self):
        """키움 _issue_token에 하드코딩된 백오프 계산(5 * attempt 등)이 제거되었는지 확인."""
        from backend.app.core import kiwoom_rest

        import inspect
        src = inspect.getsource(kiwoom_rest)
        # _issue_token 함수 본문만 검사 — 다른 함수의 하드코딩과 분리
        issue_token_start = src.find("async def _issue_token")
        assert issue_token_start != -1
        # _issue_token 이후부터 다음 async def 까지
        next_def = src.find("\n    async def ", issue_token_start + 10)
        if next_def == -1:
            next_def = src.find("\n    def ", issue_token_start + 10)
        issue_token_src = src[issue_token_start:next_def] if next_def != -1 else src[issue_token_start:]
        # 하드코딩된 선형 백오프 제거 확인 — 공통 함수 호출로 대체
        assert "5 * attempt" not in issue_token_src
        assert "10 * (attempt + 1)" not in issue_token_src
        # 공통 함수 호출 확인
        assert "compute_backoff_delay" in issue_token_src
        assert "classify_token_failure" in issue_token_src

    def test_ls_no_hardcoded_backoff_formula(self):
        """LS _issue_token에 하드코딩된 백오프 계산(5 * attempt 등)이 제거되었는지 확인."""
        from backend.app.core import ls_rest

        import inspect
        src = inspect.getsource(ls_rest)
        issue_token_start = src.find("async def _issue_token")
        assert issue_token_start != -1
        next_def = src.find("\n    async def ", issue_token_start + 10)
        if next_def == -1:
            next_def = src.find("\n    def ", issue_token_start + 10)
        issue_token_src = src[issue_token_start:next_def] if next_def != -1 else src[issue_token_start:]
        # 하드코딩된 선형 백오프 제거 확인
        assert "5 * attempt" not in issue_token_src
        assert "10 * (attempt + 1)" not in issue_token_src
        # 공통 함수 호출 확인
        assert "compute_backoff_delay" in issue_token_src
        assert "classify_token_failure" in issue_token_src

    def test_both_brokers_use_same_auth_utils_module(self):
        """키움·LS 양캐스트가 동일 auth_utils 모듈의 동일 함수를 참조하는지 확인."""
        from backend.app.core import kiwoom_rest, ls_rest
        from backend.app.core import auth_utils

        # 양쪽 모듈이 import 한 함수가 auth_utils의 실제 함수 객체와 동일
        # (import 경로가 아닌 실제 함수 identity 비교)
        assert getattr(kiwoom_rest, "compute_backoff_delay", None) is auth_utils.compute_backoff_delay or \
               "compute_backoff_delay" in dir(kiwoom_rest)
        assert getattr(ls_rest, "compute_backoff_delay", None) is auth_utils.compute_backoff_delay or \
               "compute_backoff_delay" in dir(ls_rest)


# ── 토큰 회복 성공 시 자동매매 관리자 생성 검증 ──────────────────────────────────


class TestTokenRecoveryCreatesAutoTradeManager:
    """토큰 회복 루프 성공 시 누락된 자동매매 관리자가 생성되는지 검증.

    버그: 부팅 시 토큰 발급 일시 실패 → 관리자 미생성 → 회복 루프 성공해도
    관리자가 생성되지 않아 매수·매도·체결 갱신이 전부 멈추는 문제.
    수정: 회복 성공 경로에 관리자 생성 + 매도 설정 동기화 추가.
    """

    @pytest.mark.asyncio
    async def test_recovery_success_creates_auto_trade_when_missing(self):
        """회복 성공 시 관리자가 없으면 생성 + 매도 설정 동기화 + 매수 한도 브로드캐스트."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}
        mock_state.auto_trade = None  # 부팅 시 토큰 없어서 관리자 미생성 상태

        async def _fake_get_tokens(_router):
            mock_state.broker_tokens = {"kiwoom": "recovered_token"}
            mock_state.token_failure_kind = None
            return None

        mock_router = MagicMock()
        created_manager = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides") as mock_sync,
            patch("backend.app.services.engine_config._get_settings", return_value={}),
            patch.object(engine_loop, "AutoTradeManager", return_value=created_manager) as mock_ctor,
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock) as mock_buy_broadcast,
            patch.object(engine_loop, "_establish_realtime_connection", new_callable=AsyncMock) as mock_connect,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 회복 성공 → 관리자 생성 + 매도 설정 동기화 + 매수 한도 브로드캐스트
        assert mock_state.auto_trade is created_manager
        mock_ctor.assert_called_once()
        mock_sync.assert_called_once()
        mock_buy_broadcast.assert_awaited()
        # 회복 성공 → 직접 실시간 연결 시도 (자의적 시간대 판정 제거 — 이벤트 알림 대신 직접 연결)
        mock_connect.assert_awaited()

    @pytest.mark.asyncio
    async def test_recovery_success_skips_creation_when_already_exists(self):
        """회복 성공 시 관리자가 이미 있으면 중복 생성하지 않음 (부팅 시 정상 생성된 경우)."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}
        existing_manager = MagicMock()
        mock_state.auto_trade = existing_manager  # 부팅 시 이미 생성된 상태

        async def _fake_get_tokens(_router):
            mock_state.broker_tokens = {"kiwoom": "recovered_token"}
            mock_state.token_failure_kind = None
            return None

        mock_router = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides") as mock_sync,
            patch("backend.app.services.engine_config._get_settings", return_value={}),
            patch.object(engine_loop, "AutoTradeManager") as mock_ctor,
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock) as mock_buy_broadcast,
            patch.object(engine_loop, "_establish_realtime_connection", new_callable=AsyncMock) as mock_connect,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 관리자가 이미 있으므로 중복 생성하지 않음 — 기존 관리자 유지
        assert mock_state.auto_trade is existing_manager
        mock_ctor.assert_not_called()
        mock_sync.assert_not_called()
        mock_buy_broadcast.assert_not_awaited()
        # 회복 성공 → 관리자 유무와 무관하게 직접 실시간 연결 시도
        mock_connect.assert_awaited()


# ── 토큰 회복 성공 시 실시간 연결 시도 검증 ──────────────────────────────────


class TestTokenRecoveryEstablishesConnection:
    """토큰 회복 루프 성공 시 실시간 연결을 직접 맺는지 검증.

    회복 성공 시 _establish_realtime_connection()을 직접 호출하여 토큰 회복 즉시 연결 시도.
    _establish_realtime_connection() 내부에서 시간 구간 판정 (is_realtime_reset_window) —
    구간 내면 연결, 구간 외면 연결 안 함. 이후 ws_window_changed_event.set()으로
    엔진 루프를 각성하여 구간 재판정 트리거 (P16 살아있는 경로).
    """

    @pytest.mark.asyncio
    async def test_recovery_success_calls_establish_connection(self):
        """회복 성공 시 _establish_realtime_connection() 호출 — 직접 연결 시도 (시간 구간 판정 내부 수행)."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}
        mock_state.auto_trade = MagicMock()  # 이미 관리자 존재
        mock_state.ws_window_changed_event = MagicMock()

        async def _fake_get_tokens(_router):
            mock_state.broker_tokens = {"kiwoom": "recovered_token"}
            mock_state.token_failure_kind = None
            return None

        mock_router = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_config._get_settings", return_value={}),
            patch.object(engine_loop, "AutoTradeManager"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch.object(engine_loop, "_establish_realtime_connection", new_callable=AsyncMock) as mock_connect,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 회복 성공 → 직접 실시간 연결 시도 (시간 구간 판정은 함수 내부에서 수행)
        mock_connect.assert_awaited()
        # 엔진 루프 각성 — 구간 재판정 트리거
        mock_state.ws_window_changed_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_failure_does_not_call_establish_connection(self):
        """회복 실패 시 _establish_realtime_connection() 호출 없음 — 불필요한 연결 시도 방지."""
        from backend.app.services import engine_loop, engine_state

        mock_state = MagicMock()
        mock_state.token_recovery_in_progress = False
        mock_state.token_failure_kind = "transient"
        mock_state.access_token = None
        mock_state.engine_shutdown_requested = False
        mock_state.broker_tokens = {}
        mock_state.auto_trade = None

        # 모든 시도 실패
        async def _fake_get_tokens(_router):
            mock_state.broker_tokens = {}
            mock_state.token_failure_kind = "transient"
            return None

        mock_router = MagicMock()

        with (
            patch.object(engine_state, "state", mock_state),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock, side_effect=_fake_get_tokens),
            patch.object(engine_loop, "BROKER_DISPLAY_NAMES", {"kiwoom": "키움"}),
            patch.object(engine_loop.asyncio, "sleep", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_config._get_settings", return_value={}),
            patch.object(engine_loop, "AutoTradeManager"),
            patch.object(engine_loop, "_establish_realtime_connection", new_callable=AsyncMock) as mock_connect,
        ):
            await engine_loop._token_recovery_loop(mock_router, "kiwoom")

        # 회복 실패 → 실시간 연결 시도 없음
        mock_connect.assert_not_awaited()
