# -*- coding: utf-8 -*-
"""계좌/잔고/수익 라우터 — GET 엔드포인트는 WS initial-snapshot으로 대체됨."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["account"])
