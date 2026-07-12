# -*- coding: utf-8 -*-
"""
메모리 모니터링 — tracemalloc 기반 할당 추적.

장중 GC 비활성화 구간 중 메모리 증가 추적,
장마감 배치 파이프라인 실행 후 누수 감지.
"""

import logging
import tracemalloc

logger = logging.getLogger(__name__)

_started = False


def start_memory_monitor() -> None:
    """메모리 추적 시작 — 앱 기동 최초 1회만 호출."""
    global _started
    if _started:
        return
    tracemalloc.start(25)
    _started = True
    logger.info("[시스템] 메모리 추적 시작 — 할당 추적 활성화 (frames=25)")


def log_memory_snapshot(label: str = "") -> None:
    """현재 메모리 할당 상태 로그 — 상위 10개 할당 지점 출력.

    label: 로그 식별용 라벨 (예: "장마감 배치 완료", "엔진 종료")
    """
    if not _started:
        return
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")

    total = sum(s.size for s in top_stats)
    logger.info("[시스템] %s — 총 할당: %.1f MB", label or "스냅샷", total / 1024 / 1024)

    for stat in top_stats[:10]:
        logger.info("[시스템]   %s: %.1f KB (%d 블록)",
                     stat.traceback, stat.size / 1024, stat.count)


def stop_memory_monitor() -> None:
    """메모리 추적 종료 — 앱 종료 시 호출."""
    global _started
    if not _started:
        return
    tracemalloc.stop()
    _started = False
    logger.info("[시스템] 메모리 추적 종료")
