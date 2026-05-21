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
