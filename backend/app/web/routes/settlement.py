# -*- coding: utf-8 -*-
"""정산 엔진 라우터 — 충전."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.web.deps import get_current_user

router = APIRouter(prefix="/api/settlement", tags=["settlement"])


@router.post("/charge")
async def charge_settlement(body: dict, _: str = Depends(get_current_user)):
    """투자금 충전. amount(원) 만큼 누적투자금과 주문가능금액 증가."""
    amount = int(body.get("amount", 0))
    if amount <= 0:
        return {"ok": False, "reason": "금액은 0보다 커야 합니다"}
    from app.services import settlement_engine
    new_balance = settlement_engine.charge(amount)
    return {"ok": True, "balance": new_balance}
