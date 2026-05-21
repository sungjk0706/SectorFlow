# -*- coding: utf-8 -*-
"""
Phase 4.3: Observability 고도화 테스트
- latency.py end_to_end_ms 메트릭
- backend_coalescing.py Drop 패킷 모니터링
- metrics.py Drop 카운트 엔드포인트
"""
import pytest
import time

from backend.app.core.metrics.latency import LatencyMetrics, get_latency_metrics
from backend.app.services.backend_coalescing import BackendCoalescing


# ── latency.py 테스트 ──────────────────────────────────────────────────────


def test_end_to_end_metric_threshold():
    """end_to_end_ms 메트릭 threshold 존재 확인"""
    metrics = LatencyMetrics()
    assert "end_to_end_ms" in metrics.THRESHOLDS
    assert metrics.THRESHOLDS["end_to_end_ms"] == 200


def test_end_to_end_metric_record():
    """end_to_end_ms 메트릭 기록 테스트"""
    metrics = LatencyMetrics()
    metrics.record("end_to_end_ms", 150.0)
    
    summary = metrics.get_summary("end_to_end_ms")
    assert summary is not None
    assert summary["count"] == 1
    assert summary["min"] == 150.0
    assert summary["max"] == 150.0
    assert summary["avg"] == 150.0


def test_end_to_end_metric_threshold_alert():
    """end_to_end_ms 메트릭 threshold 초과 시 alert 테스트"""
    metrics = LatencyMetrics()
    metrics.record("end_to_end_ms", 250.0)  # threshold 200 초과
    
    alerts = metrics.get_recent_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0]["metric_name"] == "end_to_end_ms"
    assert alerts[0]["value"] == 250.0
    assert alerts[0]["threshold"] == 200


# ── backend_coalescing.py 테스트 ───────────────────────────────────────────


def test_dropped_count_initial():
    """Drop 카운트 초기값 확인"""
    coalescing = BackendCoalescing()
    assert coalescing.get_dropped_count() == 0


def test_dropped_count_increment():
    """동일 종목 코드 추가 시 Drop 카운트 증가 확인"""
    coalescing = BackendCoalescing()
    
    # 첫 번째 추가 - Drop 없음
    coalescing.add_event("005930", {"type": "tick", "data": {"price": 50000}})
    assert coalescing.get_dropped_count() == 0
    
    # 동일 종목 코드 두 번째 추가 - Drop 증가
    coalescing.add_event("005930", {"type": "tick", "data": {"price": 50100}})
    assert coalescing.get_dropped_count() == 1
    
    # 동일 종목 코드 세 번째 추가 - Drop 증가
    coalescing.add_event("005930", {"type": "tick", "data": {"price": 50200}})
    assert coalescing.get_dropped_count() == 2
    
    # 다른 종목 코드 추가 - Drop 증가 없음
    coalescing.add_event("000660", {"type": "tick", "data": {"price": 100000}})
    assert coalescing.get_dropped_count() == 2


def test_dropped_count_reset():
    """Drop 카운트 리셋 테스트"""
    coalescing = BackendCoalescing()
    
    coalescing.add_event("005930", {"type": "tick", "data": {"price": 50000}})
    coalescing.add_event("005930", {"type": "tick", "data": {"price": 50100}})
    assert coalescing.get_dropped_count() == 1
    
    coalescing.reset_dropped_count()
    assert coalescing.get_dropped_count() == 0


def test_dropped_count_singleton():
    """싱글톤 인스턴스 확인"""
    instance1 = BackendCoalescing.get_instance()
    instance2 = BackendCoalescing.get_instance()
    
    assert instance1 is instance2
    
    # 인스턴스 공유 확인
    instance1.add_event("005930", {"type": "tick", "data": {"price": 50000}})
    instance1.add_event("005930", {"type": "tick", "data": {"price": 50100}})
    
    assert instance2.get_dropped_count() == 1


# ── 통합 테스트 ───────────────────────────────────────────────────────────


def test_latency_metrics_global():
    """전역 LatencyMetrics 인스턴스 테스트"""
    metrics = get_latency_metrics()
    
    # end_to_end_ms 메트릭 기록
    metrics.record("end_to_end_ms", 100.0)
    
    summary = metrics.get_summary("end_to_end_ms")
    assert summary is not None
    assert summary["count"] >= 1  # 이전 테스트에서 기록된 데이터가 있을 수 있음
