# -*- coding: utf-8 -*-
"""
OMS Circuit Breaker - 주문 실패 시 계좌 보호

상태:
- CLOSED: 정상 상태 (주문 허용)
- OPEN: 차단 상태 (주문 거부, 계좌 보호)
- HALF_OPEN: 복구 시도 상태 (단일 테스트 주문 허용)

상태 전이:
- CLOSED → OPEN: 주문 실패 5회 연속
- OPEN → HALF_OPEN: 60초 경과
- HALF_OPEN → CLOSED: 테스트 주문 성공
- HALF_OPEN → OPEN: 테스트 주문 실패
"""
import time
import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """OMS용 서킷 브레이커 - 주문 실패 시 계좌 보호."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """
        서킷 브레이커 초기화.

        Args:
            failure_threshold: OPEN 상태 전이 실패 임계치 (기본값: 5)
            recovery_timeout: 복구 시도 타임아웃 (초, 기본값: 60)
        """
        self.state = "CLOSED"
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time: float | None = None

    def record_failure(self) -> None:
        """주문 실패 기록."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(
            "[CircuitBreaker] 주문 실패 기록 - failure_count=%d, threshold=%d",
            self.failure_count,
            self.failure_threshold,
        )

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                "[CircuitBreaker] 상태 전이: CLOSED → OPEN (실패 %d회 누적)",
                self.failure_count,
            )

    def record_success(self) -> None:
        """주문 성공 기록."""
        self.failure_count = 0
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            logger.info("[CircuitBreaker] 상태 전이: HALF_OPEN → CLOSED (복구 완료)")

    def allow_request(self) -> bool:
        """
        주문 요청 허용 여부 확인.

        Returns:
            True: 주문 허용, False: 주문 거부
        """
        if self.state == "CLOSED":
            return True
        elif self.state == "OPEN":
            if self.last_failure_time is not None:
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    logger.info(
                        "[CircuitBreaker] 상태 전이: OPEN → HALF_OPEN (복구 시도)"
                    )
                    return True
            return False
        elif self.state == "HALF_OPEN":
            return True
        return False

    def get_state(self) -> str:
        """현재 상태 반환."""
        return self.state

    def reset(self) -> None:
        """서킷 브레이커 초기화 (테스트용)."""
        self.state = "CLOSED"
        self.failure_count = 0
        self.last_failure_time = None
        logger.info("[CircuitBreaker] 초기화 완료")


# 전역 인스턴스 (OMS 루프에서 공유)
_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """서킷 브레이커 인스턴스 반환."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


def reset_circuit_breaker() -> None:
    """서킷 브레이커 초기화."""
    global _circuit_breaker
    if _circuit_breaker is not None:
        _circuit_breaker.reset()
