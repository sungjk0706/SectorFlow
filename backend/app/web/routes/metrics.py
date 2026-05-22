# -*- coding: utf-8 -*-
"""Metrics API 라우터 — Latency metrics 조회."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/summary")
async def get_metrics_summary():
    """전체 메트릭 요약 조회."""
    from backend.app.core.metrics.latency import get_latency_metrics

    metrics = get_latency_metrics()
    return metrics.get_all_summaries()


@router.get("/latency")
async def get_latency_metrics():
    """Latency 메트릭 요약 조회 (별칭)."""
    from backend.app.core.metrics.latency import get_latency_metrics

    metrics = get_latency_metrics()
    return metrics.get_all_summaries()


@router.get("/alerts")
async def get_metrics_alerts(limit: int = 20):
    """최근 alert 목록 조회."""
    from backend.app.core.metrics.latency import get_latency_metrics
    
    metrics = get_latency_metrics()
    return metrics.get_recent_alerts(limit=limit)


@router.post("/clear")
async def clear_metrics():
    """메트릭 초기화 (개발용)."""
    from backend.app.core.metrics.latency import get_latency_metrics
    
    metrics = get_latency_metrics()
    metrics.clear()
    return {"status": "cleared"}


@router.get("/dropped")
async def get_dropped_count():
    """Coalescing으로 Drop된 패킷 수 조회."""
    from backend.app.services.backend_coalescing import BackendCoalescing
    
    coalescing = BackendCoalescing.get_instance()
    return {"dropped_count": coalescing.get_dropped_count()}


@router.post("/dropped/reset")
async def reset_dropped_count():
    """Drop 카운트 초기화."""
    from backend.app.services.backend_coalescing import BackendCoalescing
    
    coalescing = BackendCoalescing.get_instance()
    coalescing.reset_dropped_count()
    return {"status": "dropped_count_reset"}
