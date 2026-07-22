# -*- coding: utf-8 -*-
"""
설정 변경 동기화 — apply_settings_change 단일 함수 유지.
파사드 재내보내기는 제거됨. 각 모듈에서 직접 import할 것.
"""
import logging
from backend.app.services import engine_state
from backend.app.services.engine_account import (
    _refresh_account_snapshot_meta,
    _broadcast_account,
)
from backend.app.services.engine_config import (
    get_settings_snapshot,
    refresh_engine_integrated_system_settings_cache,
    _mask_sensitive_settings,
    TRADE_MODE_KEYS,
)
from backend.app.services.engine_lifecycle import (
    is_engine_running,
    schedule_engine_task,
    on_trade_mode_switched,
)
from backend.app.services.sector_data_provider import (
    recompute_sector_summary_now,
)

logger = logging.getLogger(__name__)


async def apply_settings_change(changed_keys: set[str]) -> None:
    """설정 변경 후 엔진 동기화 (settings_store.py에서 이관).

    흐름: 캐시 갱신 → broker 변경(조기 종료) → 투자모드 전환(조기 종료) →
    일반 설정 브로드캐스트 → 그룹별 후속 처리 → 매수 스냅샷 무효화.
    """
    from backend.app.services.engine_account_notify import (
        notify_desktop_header_refresh,
        notify_desktop_settings_toggled,
    )

    if not changed_keys:
        await notify_desktop_header_refresh()
        return

    # ── 1) RAM 캐시 갱신 — PATCH 저장 직후 DB 최신값을 캐시에 반영 ──────────────
    # [핵심] DB 저장 후 브로드캐스트 전에 반드시 캐시를 갱신해야 최신 값이 전송됨.
    await refresh_engine_integrated_system_settings_cache(None, use_root=True)

    # ── 2) broker 변경 → 엔진 재기동 (단일 진입점 보장, 조기 종료) ────────────
    if await _handle_broker_change(changed_keys):
        return

    # ── 3) 투자모드 전환 → 캐시 갱신 + 계좌 구독 전환 (조기 종료) ──────────────
    if await _handle_trade_mode_change(changed_keys):
        return

    # ── 4) 일반 설정 변경 (증분 브로드캐스트 전송) ────────────────────────
    await notify_desktop_header_refresh()
    changed_dict = _build_changed_dict(changed_keys)
    await notify_desktop_settings_toggled(changed_dict)

    # ── 5) 설정 키 그룹별 후속 처리 (각 헬퍼가 조건 분기 담당) ────────────────
    await _apply_virtual_balance_change(changed_keys)
    await _apply_5d_download_toggle(changed_keys)
    await _apply_time_schedule_change(changed_keys)
    await _apply_timetable_change(changed_keys)
    await _apply_sector_ui_change(changed_keys)
    await _apply_telegram_toggle(changed_keys)
    await _apply_order_time_guard_change(changed_keys)

    # ── 매수 조건 스냅샷 무효화 — 설정 변경 시 매수 재평가 허용 ──
    try:
        from backend.app.services.buy_order_executor import invalidate_buy_snapshot
        invalidate_buy_snapshot()
    except Exception:
        logger.warning("[설정] 매수 재평가 무효화 실패 — 설정 변경 후 매수 후보가 갱신되지 않을 수 있음", exc_info=True)


async def _handle_broker_change(changed_keys: set[str]) -> bool:
    """broker 변경 시 엔진 재기동. 처리했으면 True(조기 종료), 아니면 False."""
    from backend.app.services.engine_account_notify import (
        notify_desktop_header_refresh,
        notify_desktop_settings_toggled,
    )
    if "broker" not in changed_keys:
        return False
    from backend.app.core.broker_factory import reset_router
    if is_engine_running():
        from backend.app.services.engine_lifecycle import stop_engine, start_engine, reset_broker_session_state
        logger.info("[설정] 증권사 변경 감지 — 엔진 재기동 (단일 진입점 보장)")
        await stop_engine()
        reset_broker_session_state()
        reset_router()
        await start_engine()
    else:
        reset_router()
    await notify_desktop_header_refresh()
    await notify_desktop_settings_toggled()
    return True


async def _handle_trade_mode_change(changed_keys: set[str]) -> bool:
    """투자모드 전환 시 캐시 갱신 + 계좌 구독 전환. 처리했으면 True(조기 종료), 아니면 False."""
    from backend.app.services.engine_account_notify import (
        notify_desktop_header_refresh,
        notify_desktop_settings_toggled,
    )
    if not (changed_keys & TRADE_MODE_KEYS):
        return False
    if is_engine_running():
        schedule_engine_task(on_trade_mode_switched(), context="투자모드 전환")
        logger.info("[설정] 투자모드 전환 감지 — 저장데이터 갱신 + 계좌 구독 전환 (엔진 재기동 없음)")
    await notify_desktop_header_refresh()
    await notify_desktop_settings_toggled()
    return True


def _build_changed_dict(changed_keys: set[str]) -> dict:
    """변경된 설정 키의 마스킹된 값을 dict로 추출 (증분 브로드캐스트용)."""
    changed_dict = {}
    try:
        display_settings = dict(engine_state.state.integrated_system_settings_cache)
        masked_settings = _mask_sensitive_settings(display_settings)
        for k in changed_keys:
            if k in masked_settings:
                changed_dict[k] = masked_settings[k]
    except Exception as e:
        logger.warning("[설정] 마스킹 델타 추출 실패: %s", e)
    return changed_dict


async def _apply_virtual_balance_change(changed_keys: set[str]) -> None:
    """테스트모드 가상 예수금 변경 시 Settlement Engine 동기화 + 계좌 스냅샷 갱신."""
    from backend.app.services import settlement_engine as _se
    _VIRTUAL_BALANCE_KEYS = {"test_virtual_balance", "test_virtual_deposit"}
    if not (changed_keys & _VIRTUAL_BALANCE_KEYS):
        return
    try:
        _s = engine_state.state.integrated_system_settings_cache
        _deposit = int(_s.get("test_virtual_balance", _s.get("test_virtual_deposit", 10_000_000)) or 0)
        await _se.reset(_deposit)
        # 계좌 스냅샷 갱신 + WS account-update 발송
        await _refresh_account_snapshot_meta()
        await _broadcast_account(reason="virtual_balance_changed")
    except Exception:
        logger.warning("[설정] 가상 예수금 동기화 실패", exc_info=True)


async def _apply_5d_download_toggle(changed_keys: set[str]) -> None:
    """5일봉 다운로드 토글 ON 시 즉시 다운로드 트리거."""
    if "scheduler_5d_download_on" not in changed_keys:
        return
    _5d_on = bool(get_settings_snapshot().get("scheduler_5d_download_on", True))
    if _5d_on:
        try:
            engine_state.state.avg_amt_needs_bg_refresh = True
            logger.info("[설정] 5일봉 다운로드 설정=ON → 5일봉 다운로드 트리거")
        except Exception:
            logger.warning("[설정] 5일봉 다운로드 트리거 실패", exc_info=True)


async def _apply_time_schedule_change(changed_keys: set[str]) -> None:
    """자동매매 시간 관련 설정 변경 시 타이머 재예약 + Connector 플래그 동기화."""
    _TIME_SCHEDULE_KEYS = {
        "time_scheduler_on", "auto_buy_on", "auto_sell_on",
        "buy_time_start", "buy_time_end", "sell_time_start", "sell_time_end",
    }
    if not (changed_keys & _TIME_SCHEDULE_KEYS):
        return
    try:
        from backend.app.services.daily_time_scheduler import schedule_auto_trade_timers
        new_settings = get_settings_snapshot()
        await schedule_auto_trade_timers(new_settings)
    except Exception:
        logger.warning("[설정] 자동매매 타이머 재예약 실패", exc_info=True)


async def _apply_timetable_change(changed_keys: set[str]) -> None:
    """타임테이블 시각/토글 변경 시 _TIMETABLE 재빌드 + 타이머 재예약 (P14 단일 타이머 유지).

    - timetable.confirmed_download: 11번째 항목 시각 변경 (4세션 통합)
    - scheduler_market_close_on: 11번째 항목 스킵/추가 토글 (P16 살아있는 경로)
    """
    _TIMETABLE_KEYS = {
        "timetable.realtime_reset",
        "timetable.ws_prestart",
        "timetable.krx_pre_subscribe",
        "timetable.confirmed_download",
        "scheduler_market_close_on",
    }
    if not (changed_keys & _TIMETABLE_KEYS):
        return
    try:
        import backend.app.services.daily_time_scheduler as _dts_mod
        from backend.app.services.daily_time_scheduler import (
            _schedule_next_timetable_event, build_timetable_from_cache,
        )
        _dts_mod._TIMETABLE = build_timetable_from_cache(
            engine_state.state.integrated_system_settings_cache
        )
        _schedule_next_timetable_event()  # 기존 타이머 취소 후 재예약 (P14)
        logger.info("[설정] 타임테이블 변경 감지 — 재빌드 + 타이머 재예약 완료")
    except Exception:
        logger.warning("[설정] 타임테이블 재빌드/재예약 실패", exc_info=True)


async def _apply_sector_ui_change(changed_keys: set[str]) -> None:
    """업종 정렬/필터 관련 설정 변경 시 업종 점수만 재계산 (종목 시세는 WS delta로만 전송)."""
    from backend.app.services.engine_account_notify import notify_desktop_sector_scores
    _SECTOR_UI_KEYS = {
        "sector_sort_keys",
        "sector_min_rise_ratio_pct", "sector_min_trade_amt",
        "sector_max_targets",
        "sector_bonus_rise_ratio_slider",
        "sector_bonus_relative_strength_slider",
        "sector_bonus_trade_amount_slider",
        "buy_block_rise_on", "buy_block_rise_pct",
        "buy_block_fall_on", "buy_block_fall_pct",
        "buy_block_strength_on", "buy_min_strength",
        # 가산점 설정
        "boost_high_breakout_on", "boost_high_breakout_score",
        "boost_order_ratio_on",
        "boost_order_ratio_pct", "boost_order_ratio_score",
        "boost_program_net_buy_on", "boost_program_net_buy_score",
        "boost_trade_amount_rank_on", "boost_trade_amount_rank_score",
        # 재매수 차단 — 보유/금일매수 종목의 buy_targets/blocked_targets 분류에 영향
        "rebuy_block_on",
    }
    if not (changed_keys & _SECTOR_UI_KEYS):
        return
    if is_engine_running():
        if "sector_min_trade_amt" in changed_keys:
            schedule_engine_task(
                engine_state.state.on_filter_settings_changed(), context="필터 설정 변경"
            )
        schedule_engine_task(
            recompute_sector_summary_now(), context="업종 설정 변경"
        )
    try:
        await notify_desktop_sector_scores(force=True)
    except Exception as e:
        logger.warning("[설정] 업종 점수 전송 실패: %s", e, exc_info=True)


async def _apply_telegram_toggle(changed_keys: set[str]) -> None:
    """텔레그램 토글 시 폴링 start/stop."""
    if "tele_on" not in changed_keys:
        return
    try:
        from backend.app.services.telegram_bot import telegram_bot
        _tele_on = bool(engine_state.state.integrated_system_settings_cache.get("tele_on", False))
        if _tele_on:
            telegram_bot.start()
            logger.info("[설정] 텔레그램 설정=ON → 텔레그램 폴링 시작")
        else:
            await telegram_bot.stop_async()
            logger.info("[설정] 텔레그램 설정=OFF → 텔레그램 폴링 종료")
    except Exception:
        logger.warning("[설정] 텔레그램 폴링 토글 실패", exc_info=True)


async def _apply_order_time_guard_change(changed_keys: set[str]) -> None:
    """order_time_guard_on 토글 변경 시 체결 불가 시간대 배지 즉시 갱신."""
    if "order_time_guard_on" not in changed_keys:
        return
    try:
        from backend.app.services.daily_time_scheduler import get_order_time_block_status
        from backend.app.services.engine_account_notify import _broadcast
        blocked, reason = get_order_time_block_status()
        schedule_engine_task(
            _broadcast("order_time_blocked", {"blocked": blocked, "reason": reason}),
            context="order_time_guard_on 변경",
        )
        logger.info("[설정] 체결 불가 시간대 주문 차단 설정 변경 — 배지 갱신: blocked=%s, reason=%r", blocked, reason)
    except Exception:
        logger.warning("[설정] order_time_guard_on 변경 후 배지 갱신 실패", exc_info=True)

