# -*- coding: utf-8 -*-
"""정산 엔진 라우터 — 미정산 목록 조회, 충전, 인출."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.web.deps import get_current_user

router = APIRouter(prefix="/api/settlement", tags=["settlement"])


@router.get("/pending-withdrawals")
async def get_pending_withdrawals(_: str = Depends(get_current_user)):
    """미정산 매도대금 목록 반환. 각 항목: sell_date, stk_cd, stk_nm, amount, settlement_date."""
    from app.services import settlement_engine
    return settlement_engine.get_pending_withdrawals()


@router.post("/charge")
async def charge_settlement(body: dict, _: str = Depends(get_current_user)):
    """예수금 충전. amount(원) 만큼 Available_Cash 증가."""
    amount = int(body.get("amount", 0))
    if amount <= 0:
        return {"success": False, "reason": "금액은 0보다 커야 합니다"}
    from app.services import settlement_engine
    new_balance = settlement_engine.charge(amount)
    return {"success": True, "balance": new_balance}


@router.post("/withdraw")
async def withdraw_settlement(body: dict, _: str = Depends(get_current_user)):
    """예수금 인출. Withdrawable_Cash 범위 내에서만 차감."""
    amount = int(body.get("amount", 0))
    if amount <= 0:
        return {"success": False, "reason": "금액은 0보다 커야 합니다"}
    from app.services import settlement_engine
    success, balance = settlement_engine.withdraw(amount)
    if not success:
        return {"success": False, "balance": balance, "reason": "인출 가능 금액 초과"}
    return {"success": True, "balance": balance}
