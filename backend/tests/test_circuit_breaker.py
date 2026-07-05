"""circuit_breaker.py 단위 테스트 — 서킷 브레이커 상태 전이 및 주문 차단 로직 검증.

CircuitBreaker의 CLOSED → OPEN → HALF_OPEN → CLOSED 상태 전이와
주문 허용/거부 동작을 검증.
"""
from __future__ import annotations

import time
from unittest.mock import patch

from backend.app.services.circuit_breaker import (
    CircuitBreaker,
    get_circuit_breaker,
    reset_circuit_breaker,
)


# ── CircuitBreaker 기본 동작 ─────────────────────────────────────────────────

class TestCircuitBreakerInit:
    def test_default_values(self):
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.last_failure_time is None

    def test_custom_threshold_and_timeout(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30


# ── record_failure ─────────────────────────────────────────────────────────────

class TestRecordFailure:
    def test_single_failure_increments_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == "CLOSED"
        assert cb.last_failure_time is not None

    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.failure_count == 4
        assert cb.state == "CLOSED"

    def test_failure_at_threshold_opens_circuit(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.failure_count == 5

    def test_failures_above_threshold_stay_open(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.failure_count == 5


# ── record_success ─────────────────────────────────────────────────────────────

class TestRecordSuccess:
    def test_success_resets_failure_count_in_closed(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"

    def test_success_in_half_open_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        # Simulate timeout to transition to HALF_OPEN
        with patch("backend.app.services.circuit_breaker.time.time") as mock_time:
            mock_time.return_value = cb.last_failure_time + 2
            cb.allow_request()
        assert cb.state == "HALF_OPEN"
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_success_in_open_does_not_close(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        cb.record_success()
        assert cb.state == "OPEN"


# ── allow_request ──────────────────────────────────────────────────────────────

class TestAllowRequest:
    def test_closed_allows_request(self):
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_open_blocks_request(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_open_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        with patch("backend.app.services.circuit_breaker.time.time") as mock_time:
            mock_time.return_value = cb.last_failure_time + 2
            assert cb.allow_request() is True
        assert cb.state == "HALF_OPEN"

    def test_open_stays_open_before_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        with patch("backend.app.services.circuit_breaker.time.time") as mock_time:
            mock_time.return_value = cb.last_failure_time + 30
            assert cb.allow_request() is False
        assert cb.state == "OPEN"

    def test_half_open_allows_request(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        cb.record_failure()
        cb.record_failure()
        with patch("backend.app.services.circuit_breaker.time.time") as mock_time:
            mock_time.return_value = cb.last_failure_time + 2
            cb.allow_request()
        assert cb.state == "HALF_OPEN"
        assert cb.allow_request() is True

    def test_open_with_no_failure_time_blocks(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        cb.last_failure_time = None
        assert cb.allow_request() is False


# ── get_state ──────────────────────────────────────────────────────────────────

class TestGetState:
    def test_returns_current_state(self):
        cb = CircuitBreaker()
        assert cb.get_state() == "CLOSED"
        cb.state = "OPEN"
        assert cb.get_state() == "OPEN"
        cb.state = "HALF_OPEN"
        assert cb.get_state() == "HALF_OPEN"


# ── reset ──────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_all(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        cb.reset()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0
        assert cb.last_failure_time is None


# ── 싱글톤 인스턴스 ───────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_circuit_breaker_returns_same_instance(self):
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is cb2

    def test_reset_circuit_breaker_resets_global(self):
        cb = get_circuit_breaker()
        cb.record_failure()
        cb.record_failure()
        reset_circuit_breaker()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0


# ── 통합 시나리오 ──────────────────────────────────────────────────────────────

class TestIntegrationScenario:
    def test_full_cycle_closed_to_open_to_half_open_to_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
        # CLOSED → OPEN
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

        # OPEN → HALF_OPEN (after timeout)
        with patch("backend.app.services.circuit_breaker.time.time") as mock_time:
            mock_time.return_value = cb.last_failure_time + 2
            assert cb.allow_request() is True
        assert cb.state == "HALF_OPEN"

        # HALF_OPEN → CLOSED (success)
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_half_open_failure_does_not_directly_open(self):
        """HALF_OPEN 상태에서 record_failure 시 failure_count 증가하지만
        record_failure 내부에서 threshold 체크로 OPEN 전이함."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        with patch("backend.app.services.circuit_breaker.time.time") as mock_time:
            mock_time.return_value = cb.last_failure_time + 2
            cb.allow_request()
        assert cb.state == "HALF_OPEN"
        # HALF_OPEN에서 실패 → failure_count 증가 → threshold 도달 → OPEN
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
