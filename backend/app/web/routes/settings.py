from __future__ import annotations
# -*- coding: utf-8 -*-
"""설정 라우터 — RESTful 아키텍처 (GET 조회, PATCH 개별 수정)."""

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.web.deps import get_current_user

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
async def get_settings(_: str = Depends(get_current_user)):
    """전체 설정 조회 (마스킹된 민감 필드 포함)."""
    try:
        from backend.app.core.settings_store import build_masked_settings_dict
        return await build_masked_settings_dict(username="admin")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"설정 조회 실패: {e}",
        )


@router.patch("/settings/{field_name}")
async def patch_setting_field(field_name: str, body: dict, _: str = Depends(get_current_user)):
    """개별 필드 수정 (RESTful 표준)."""
    try:
        if "value" not in body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="value 필드가 필요합니다",
            )

        from backend.app.core.settings_store import apply_settings_updates
        from backend.app.services import engine_service

        data = {field_name: body["value"]}
        changed_keys = {field_name}
        await apply_settings_updates(data)

        # 엔진 인메모리 캐시 동기화 및 후처리 실행 (services 레이어로 직접 명시 호출)
        if engine_service.is_running():
            await engine_service.apply_settings_change(changed_keys)

        return {"ok": True}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"유효하지 않은 설정값: {e}",
        )


@router.post("/test-data/reset")
async def reset_test_data(_: str = Depends(get_current_user)):
    """테스트 데이터 전체 초기화 (가상 보유종목 + 예수금 + 테스트 매매 이력)."""
    try:
        from backend.app.services.dry_run import clear, set_virtual_deposit
        from backend.app.services.trade_history import clear_test_history
        from backend.app.services import settlement_engine
        import backend.app.services.engine_state as _st

        default_deposit = 10_000_000
        settings = _st._integrated_system_settings_cache
        default_deposit = int(
            settings.get("test_virtual_deposit", default_deposit) or default_deposit
        )

        # 1. 가상 보유종목 초기화
        await clear()
        # 2. 가상 예수금 초기화 (기본예수금으로 리셋)
        await set_virtual_deposit(default_deposit)
        # 3. Settlement Engine 초기화 (예수금 리셋 + 미정산 삭제 + 타이머 취소)
        await settlement_engine.reset(default_deposit)
        # 4. 테스트 매매 이력 초기화 (실전 이력은 보존)
        await clear_test_history()
        # 5. 초기화된 매매 이력 브로드캐스트 → 프론트 테이블 갱신
        from backend.app.services.trade_history import broadcast_history
        await broadcast_history("test")
        # 7. 보유종목 메모리 리스트 및 캐시 초기화 + 계좌 스냅샷 갱신 + WS account-update 발송
        from backend.app.services import engine_service as es
        from backend.app.services.engine_account_notify import _rebuild_positions_cache, notify_cache
        subscribed_count = sum(1 for entry in es._master_stocks_cache.values() if entry.get("_subscribed", False))
        es.logger.info(
            "[디버그] 초기화 직전 구독목록 positions=%d subscribed=%d layout=%d pos_codes=%d",
            len(es._positions), subscribed_count,
            len(es._integrated_system_settings_cache["sector_stock_layout"]),
            len(notify_cache.positions_code_set),
        )
        es._positions = []
        for entry in es._master_stocks_cache.values():
            entry.pop("_subscribed", None)
        es._snapshot_history.clear()
        es._checked_stocks.clear()
        _rebuild_positions_cache([])
        subscribed_count_after = sum(1 for entry in es._master_stocks_cache.values() if entry.get("_subscribed", False))
        es.logger.info(
            "[디버그] 초기화 직후 구독목록 positions=%d subscribed=%d layout=%d pos_codes=%d",
            len(es._positions), subscribed_count_after,
            len(es._integrated_system_settings_cache["sector_stock_layout"]),
            len(notify_cache.positions_code_set),
        )
        await es._refresh_account_snapshot_meta()
        es._broadcast_account(reason="test_data_reset")
        es.logger.info("[엔진] 보유종목, 실시간 필드 및 REST 보완 저장데이터, 수익 이력 초기화 완료")
        # 8. 수익 이력 초기화 WS 브로드캐스트
        from backend.app.services.engine_account_notify import notify_snapshot_history_update
        notify_snapshot_history_update()
        # 9. 일일매수 누적 인메모리 상태 리셋 + 매수 쿨다운/쓰로틀 기록 초기화 + WS buy-limit-status 발송
        if es._auto_trade:
            es._auto_trade._daily_buy_spent = 0
            es._auto_trade._bought_today = set()
            es._auto_trade._buy_state.clear()
        # buy_targets 메모리 초기화 (매수후보 테이블 동기화)
        if es._sector_summary_cache and hasattr(es._sector_summary_cache, 'buy_targets'):
            es._sector_summary_cache.buy_targets = []
        await es._broadcast_buy_limit_status()
        # 10. 통합 초기화 완료 신호 (모든 클라이언트 일괄 동기화)
        from backend.app.services.engine_account_notify import _broadcast
        _broadcast("test-data-reset-completed", {"_v": 1})

        return {"ok": True, "message": "테스트 데이터 전체 초기화 완료"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"테스트 데이터 초기화 실패: {e}",
        )


