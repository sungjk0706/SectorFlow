"""boost_order_ratio_pct 설정 저장 시 422 오류 수정 검증 테스트.

검증 대상:
- Step 1: apply_settings_change에서 notify_desktop_sector_scores 예외 분리
- Step 3: settings.py catch-all 422 세분화 (HTTPException re-raise)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


class TestApplySettingsChangeSectorBroadcast:
    """Step 1: _SECTOR_UI_KEYS 변경 시 notify_desktop_sector_scores 예외 분리 검증."""

    @pytest.mark.asyncio
    async def test_broadcast_exception_does_not_propagate(self):
        """notify_desktop_sector_scores 예외 시 apply_settings_change 정상 반환."""
        from backend.app.services.engine_service import apply_settings_change

        changed_keys = {"boost_order_ratio_pct"}

        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_service.is_engine_running",
                return_value=False,
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_sector_scores",
                AsyncMock(side_effect=KeyError("sector_max_targets")),
            ),
        ):
            result = await apply_settings_change(changed_keys)

        assert result is None

    @pytest.mark.asyncio
    async def test_broadcast_success_normal_flow(self):
        """notify_desktop_sector_scores 정상 시 apply_settings_change 정상 반환."""
        from backend.app.services.engine_service import apply_settings_change

        changed_keys = {"boost_order_ratio_pct"}

        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_service.is_engine_running",
                return_value=False,
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_sector_scores",
                AsyncMock(),
            ),
        ):
            result = await apply_settings_change(changed_keys)

        assert result is None

    @pytest.mark.asyncio
    async def test_engine_running_sector_key_triggers_recompute(self):
        """엔진 실행 중 sector_min_trade_amt 변경 시 on_filter_settings_changed 호출."""
        from backend.app.services.engine_service import apply_settings_change
        from backend.app.services.engine_state import state

        changed_keys = {"sector_min_trade_amt"}

        mock_filter_changed = AsyncMock()
        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_service.is_engine_running",
                return_value=True,
            ),
            patch(
                "backend.app.services.engine_service.schedule_engine_task",
            ) as mock_schedule,
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_sector_scores",
                AsyncMock(),
            ),
            patch.object(state, "on_filter_settings_changed", mock_filter_changed),
        ):
            await apply_settings_change(changed_keys)

        assert mock_schedule.call_count >= 2
        schedule_contexts = [c.kwargs.get("context", "") for c in mock_schedule.call_args_list]
        assert "필터 설정 변경" in schedule_contexts
        assert "업종 설정 변경" in schedule_contexts

    @pytest.mark.asyncio
    async def test_rebuy_block_on_triggers_recompute(self):
        """rebuy_block_on 변경 시 엔진 실행 중이면 recompute_sector_summary_now 호출."""
        from backend.app.services.engine_service import apply_settings_change

        changed_keys = {"rebuy_block_on"}

        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_service.is_engine_running",
                return_value=True,
            ),
            patch(
                "backend.app.services.engine_service.schedule_engine_task",
            ) as mock_schedule,
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_sector_scores",
                AsyncMock(),
            ),
        ):
            await apply_settings_change(changed_keys)

        schedule_contexts = [c.kwargs.get("context", "") for c in mock_schedule.call_args_list]
        assert "업종 설정 변경" in schedule_contexts

    @pytest.mark.asyncio
    async def test_rebuy_block_on_no_recompute_when_engine_stopped(self):
        """엔진 미실행 시 rebuy_block_on 변경은 recompute 호출하지 않음."""
        from backend.app.services.engine_service import apply_settings_change

        changed_keys = {"rebuy_block_on"}

        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_service.is_engine_running",
                return_value=False,
            ),
            patch(
                "backend.app.services.engine_service.schedule_engine_task",
            ) as mock_schedule,
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_sector_scores",
                AsyncMock(),
            ),
        ):
            await apply_settings_change(changed_keys)

        # 엔진 미실행 → schedule_engine_task가 호출되지 않아야 함
        recompute_calls = [
            c for c in mock_schedule.call_args_list
            if c.kwargs.get("context", "") == "업종 설정 변경"
        ]
        assert recompute_calls == []


class TestSettingsPyHttpExceptionReraise:
    """Step 3: settings.py catch-all에서 HTTPException re-raise 검증."""

    @pytest.mark.asyncio
    async def test_http_exception_reraised_not_converted_to_422(self):
        """HTTPException(400)이 catch-all에 의해 422로 변환되지 않는지 확인."""
        from fastapi import HTTPException
        from backend.app.web.routes.settings import patch_setting_field

        with (
            patch(
                "backend.app.core.settings_store.apply_settings_updates",
                AsyncMock(side_effect=HTTPException(status_code=400, detail="bad value")),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await patch_setting_field("boost_order_ratio_pct", {"value": 999})

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "bad value"

    @pytest.mark.asyncio
    async def test_generic_exception_converted_to_422(self):
        """일반 예외는 여전히 422로 변환됨."""
        from fastapi import HTTPException
        from backend.app.web.routes.settings import patch_setting_field

        with (
            patch(
                "backend.app.core.settings_store.apply_settings_updates",
                AsyncMock(side_effect=ValueError("invalid")),
            ),
            patch(
                "backend.app.services.engine_lifecycle.is_engine_running",
                return_value=False,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await patch_setting_field("boost_order_ratio_pct", {"value": 999})

        assert exc_info.value.status_code == 422
        assert "invalid" in exc_info.value.detail
