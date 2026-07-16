# -*- coding: utf-8 -*-
"""설정 라우터 — RESTful 아키텍처 (GET 조회, PATCH 개별 수정)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from backend.app.web.deps import get_current_user
import logging
router = APIRouter(prefix="/api", tags=["settings"])
logger = logging.getLogger(__name__)


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
        from backend.app.services.engine_lifecycle import is_engine_running
        from backend.app.services.engine_service import apply_settings_change

        data = {field_name: body["value"]}
        changed_keys = await apply_settings_updates(data)

        # 엔진 인메모리 캐시 동기화 및 후처리 실행 (services 레이어로 직접 명시 호출)
        if is_engine_running():
            if changed_keys:
                await apply_settings_change(changed_keys)
        else:
            from backend.app.core.sector_stock_cache import save_pending_settings
            await save_pending_settings(changed_keys)
            # 엔진 미실행 시에도 캐시 갱신 + WS settings-changed 브로드캐스트
            from backend.app.services.engine_config import refresh_engine_integrated_system_settings_cache
            from backend.app.services.engine_account_notify import notify_desktop_settings_toggled
            await refresh_engine_integrated_system_settings_cache(None, use_root=True)
            changed_dict = {}
            try:
                from backend.app.services.engine_config import _mask_sensitive_settings
                from backend.app.services.engine_state import state
                display_settings = dict(state.integrated_system_settings_cache)
                masked_settings = _mask_sensitive_settings(display_settings)
                for k in changed_keys:
                    if k in masked_settings:
                        changed_dict[k] = masked_settings[k]
            except Exception:
                pass
            await notify_desktop_settings_toggled(changed_dict)

            # tele_on은 엔진 실행 여부와 무관하게 폴링 태스크에 즉시 반영 (원칙 17)
            if "tele_on" in changed_keys:
                from backend.app.services.telegram_bot import telegram_bot
                _tele_on = bool(state.integrated_system_settings_cache.get("tele_on", False))
                if _tele_on:
                    telegram_bot.start()
                else:
                    await telegram_bot.stop_async()

        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error("[설정] 설정 변경 %s 실패: %s", field_name, e, exc_info=True)
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
        from backend.app.services.engine_state import state

        default_deposit = 10_000_000
        settings = state.integrated_system_settings_cache
        default_deposit = int(
            settings.get("test_virtual_deposit", default_deposit) or default_deposit
        )

        # 1. 테스트 매매 이력 초기화 (실전 이력은 보존) — trades가 SSOT이므로 먼저 삭제
        await clear_test_history()
        # 2. 가상 보유종목 메모리 초기화 (trades 삭제 후이므로 빈 상태로 복원됨)
        await clear()
        # 3. 가상 예수금 초기화 (기본예수금으로 리셋)
        await set_virtual_deposit(default_deposit)
        # 4. Settlement Engine 초기화 (예수금 리셋 + 미정산 삭제 + 타이머 취소)
        await settlement_engine.reset(default_deposit)
        # 5. 초기화된 매매 이력 브로드캐스트 → 프론트 테이블 갱신
        from backend.app.services.trade_history import broadcast_history
        await broadcast_history("test")
        # 7. 보유종목 메모리 리스트 및 캐시 초기화 + 계좌 스냅샷 갱신 + WS account-update 발송
        import logging
        from backend.app.services.engine_state import state
        from backend.app.services.engine_account_notify import _rebuild_positions_cache, notify_cache
        from backend.app.services.engine_account import _refresh_account_snapshot_meta, _broadcast_account, _broadcast_buy_limit_status
        _logger = logging.getLogger(__name__)
        subscribed_count = sum(1 for entry in state.master_stocks_cache.values() if entry.get("_subscribed", False))
        _logger.info(
            "[디버그] 초기화 직전 구독목록 보유종목=%d 구독중=%d 레이아웃=%d 종목코드=%d",
            len(state.positions), subscribed_count,
            len(state.integrated_system_settings_cache["sector_stock_layout"]),
            len(notify_cache.positions_code_set),
        )
        state.positions = []
        for entry in state.master_stocks_cache.values():
            entry.pop("_subscribed", None)
        state.snapshot_history.clear()
        _rebuild_positions_cache([])
        subscribed_count_after = sum(1 for entry in state.master_stocks_cache.values() if entry.get("_subscribed", False))
        _logger.info(
            "[디버그] 초기화 직후 구독목록 보유종목=%d 구독중=%d 레이아웃=%d 종목코드=%d",
            len(state.positions), subscribed_count_after,
            len(state.integrated_system_settings_cache["sector_stock_layout"]),
            len(notify_cache.positions_code_set),
        )
        await _refresh_account_snapshot_meta()
        await _broadcast_account(reason="test_data_reset")
        _logger.info("[연산] 보유종목, 실시간 필드 및 REST 보완 저장데이터, 수익 이력 초기화 완료")
        # 8. 수익 이력 초기화 WS 브로드캐스트
        from backend.app.services.engine_account_notify import notify_snapshot_history_update
        await notify_snapshot_history_update()
        # 9. 일일매수 누적 인메모리 상태 리셋 + 매수 쿨다운/쓰로틀 기록 초기화 + WS buy-limit-status 발송
        if state.auto_trade:
            state.auto_trade._daily_buy_spent = 0
            state.auto_trade._bought_today = {}
            state.auto_trade._symbol_daily_buy_spent = {}
            state.auto_trade._buy_state.clear()
        # 주문 간격 타이머 리셋 (매수/매도)
        state._last_global_buy_ts = 0.0
        state._last_global_sell_ts = 0.0
        # buy_targets 메모리 초기화 (매수 후보 테이블 동기화)
        if state.sector_summary_cache and hasattr(state.sector_summary_cache, 'buy_targets'):
            state.sector_summary_cache.buy_targets = []
        await _broadcast_buy_limit_status()
        # 10. 통합 초기화 완료 신호 (모든 클라이언트 일괄 동기화)
        from backend.app.services.engine_account_notify import _broadcast
        await _broadcast("test-data-reset-completed", {"_v": 1})

        return {"ok": True, "message": "테스트 데이터 전체 초기화 완료"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"테스트 데이터 초기화 실패: {e}",
        )


