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

        from backend.app.core.settings_store import apply_settings_updates, after_settings_persisted
        from backend.app.services.core_queues import get_control_queue

        data = {field_name: body["value"]}
        changed_keys = {field_name}
        await apply_settings_updates(data)

        # control_queue에 설정 변경 신호 전송 (엔진 기동 시만)
        try:
            import time
            control_queue = get_control_queue()
            await control_queue.put((0, time.monotonic(), {
                "type": "UPDATE_CONFIG",
                "payload": data,
                "changed_keys": changed_keys,
            }))
        except RuntimeError:
            # control_queue가 초기화되지 않은 경우 (엔진 미기동) 무시
            pass

        await after_settings_persisted(username="admin", changed_keys=changed_keys)
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
        from backend.app.core.settings_file import load_settings_async

        default_deposit = 10_000_000
        settings = await load_settings_async()
        default_deposit = int(
            settings.get("test_virtual_deposit", default_deposit) or default_deposit
        )

        # 1. 가상 보유종목 초기화
        clear()
        # 2. 가상 예수금 초기화 (기본예수금으로 리셋)
        set_virtual_deposit(default_deposit)
        # 3. Settlement Engine 초기화 (예수금 리셋 + 미정산 삭제 + 타이머 취소)
        settlement_engine.reset(default_deposit)
        # 4. 테스트 매매 이력 초기화 (실전 이력은 보존)
        clear_test_history()
        # 5. 초기화된 매매 이력 브로드캐스트 → 프론트 테이블 갱신
        from backend.app.services.trade_history import broadcast_history
        broadcast_history("test")
        # 6. WS settings-changed 발송 → 프론트 설정 UI 갱신
        from backend.app.core.settings_store import after_settings_persisted
        await after_settings_persisted(
            username="admin",
            changed_keys={"test_virtual_deposit", "test_virtual_balance"},
        )
        # 7. 보유종목 메모리 리스트 및 캐시 초기화 + 계좌 스냅샷 갱신 + WS account-update 발송
        from backend.app.services import engine_service as es
        from backend.app.services.engine_account_notify import _rebuild_positions_cache, _positions_code_set
        es.logger.info(
            "[디버그] 초기화 직전 구독목록 positions=%d subscribed=%d radar=%d layout=%d pos_codes=%d",
            len(es._positions), len(es._subscribed_stocks),
            len(es._radar_cnsr_order), len(es._sector_stock_layout),
            len(_positions_code_set),
        )
        async with es._shared_lock:
            es._positions = []
            es._subscribed_stocks.clear()
            # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_rest_radar_quote_cache)
            es._rest_radar_rest_once.clear()
            es._snapshot_history.clear()
            es._checked_stocks.clear()
        _rebuild_positions_cache([])
        es.logger.info(
            "[디버그] 초기화 직후 구독목록 positions=%d subscribed=%d radar=%d layout=%d pos_codes=%d",
            len(es._positions), len(es._subscribed_stocks),
            len(es._radar_cnsr_order), len(es._sector_stock_layout),
            len(_positions_code_set),
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
        es._sector_buy_last_ts.clear()
        # buy_targets 메모리 초기화 (매수후보 테이블 동기화)
        if es._sector_summary_cache and hasattr(es._sector_summary_cache, 'buy_targets'):
            es._sector_summary_cache.buy_targets = []
        es._broadcast_buy_limit_status()
        # 10. 통합 초기화 완료 신호 (모든 클라이언트 일괄 동기화)
        from backend.app.services.engine_account_notify import _broadcast
        _broadcast("test-data-reset-completed", {"_v": 1})

        return {"ok": True, "message": "테스트 데이터 전체 초기화 완료"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"테스트 데이터 초기화 실패: {e}",
        )


@router.post("/trading-calendar/refresh")
async def refresh_trading_calendar(_: str = Depends(get_current_user)):
    """거래일 캐시 수동 갱신 (pykrx)."""
    try:
        from backend.app.core.trading_calendar import refresh_trading_days_cache

        await refresh_trading_days_cache()

        return {"ok": True, "message": "거래일 캐시 갱신 완료"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"거래일 캐시 갱신 실패: {e}",
        )


