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
    recompute_buy_targets_only,
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

    # ── 2) broker / confirmed_data_broker 변경 → 엔진 재기동 (단일 진입점 보장, 조기 종료) ────────────
    # confirmed_data_broker: 확정 시세 다운로드 증권사 — startup 토큰 발급 대상은 아니나
    # (engine_loop._get_all_tokens_async는 settings["broker"] 단일 항목만 발급),
    # 배치 경로(market_close_pipeline)가 integrated_system_settings_cache에서 값을 읽어
    # 자체 Lazy Auth로 토큰을 발급받으므로 설정 캐시 갱신 + broker와 동일 재기동 처리 (P21/P23).
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
    await _apply_time_schedule_change(changed_keys)
    await _apply_timetable_change(changed_keys)
    await _apply_sector_ui_change(changed_keys)
    await _apply_telegram_toggle(changed_keys)
    await _apply_risk_block_toggle_change(changed_keys)

    # ── 매수 조건 스냅샷 무효화 — 설정 변경 시 매수 재평가 허용 ──
    try:
        from backend.app.services.buy_order_executor import invalidate_buy_snapshot
        invalidate_buy_snapshot()
    except Exception:
        logger.warning("[설정] 매수 재평가 무효화 실패 — 설정 변경 후 매수 후보가 갱신되지 않을 수 있음", exc_info=True)

    # ── 설정 화면 구독 대상 갱신 + 활성 연결 갱신 (태스크 2세션) ──
    # 설정 변경 시 마스킹 설정 스냅샷이 바뀌므로 설정 화면 활성 연결에 재전송.
    # 업종·매수 후보 관련 설정 변경은 _apply_sector_ui_change → recompute 경로에서 이미 갱신됨.
    try:
        from backend.app.services.page_subscription_targets import refresh_active_connections
        await refresh_active_connections("설정 변경", {"settings"})
    except Exception:
        logger.warning("[설정] 설정 화면 구독 대상 갱신 실패", exc_info=True)


async def _handle_broker_change(changed_keys: set[str]) -> bool:
    """broker / confirmed_data_broker 변경 시 엔진 재기동. 처리했으면 True(조기 종료), 아니면 False.

    confirmed_data_broker는 확정 시세 다운로드 증권사로 startup 토큰 발급 대상은 아니나
    (engine_loop._get_all_tokens_async는 settings["broker"] 단일 항목만 발급),
    배치 경로(market_close_pipeline)가 integrated_system_settings_cache에서 값을 읽어
    자체 Lazy Auth로 토큰을 발급받으므로 broker와 동일 재기동 처리 (P21/P23).
    """
    from backend.app.services.engine_account_notify import (
        notify_desktop_header_refresh,
        notify_desktop_settings_toggled,
    )
    if not (changed_keys & {"broker", "confirmed_data_broker"}):
        return False
    from backend.app.core.broker_factory import reset_router
    if is_engine_running():
        from backend.app.services.engine_lifecycle import stop_engine, start_engine, reset_broker_session_state
        _changed = changed_keys & {"broker", "confirmed_data_broker"}
        logger.info("[설정] 증권사 관련 설정 변경 감지 (%s) — 엔진 재기동 (단일 진입점 보장)", sorted(_changed))
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
        logger.info("[설정] 타임테이블 변경 감지 — 재빌드 + 타이머 재예약")
    except Exception:
        logger.warning("[설정] 타임테이블 재빌드/재예약 실패", exc_info=True)


async def _apply_sector_ui_change(changed_keys: set[str]) -> None:
    """업종 정렬/필터·매수 차단 설정 변경 시 재계산 디스패치 (설계서 섹션 5-8).

    _SECTOR_UI_KEYS 변경 → 업종 재계산 (recompute_sector_summary_now, 업종 스코어·컷오프 갱신).
    _BUY_BLOCK_UI_KEYS 변경 → 경량 재순위 (recompute_buy_targets_only, 업종 스코어 캐시 재사용).
    양쪽 교집합 시 업종 재계산 경로 우선 (안전 — 매수 후보는 전체 재계산에서 함께 갱신됨).
    """
    from backend.app.services.engine_account_notify import notify_desktop_sector_scores
    _SECTOR_UI_KEYS = {
        "sector_sort_keys",
        "sector_min_rise_ratio_pct", "sector_min_trade_amt",
        "sector_max_targets",
        "sector_bonus_rise_ratio_slider",
        "sector_bonus_relative_strength_slider",
        "sector_bonus_trade_amount_slider",
    }
    _BUY_BLOCK_UI_KEYS = {
        "buy_block_rise_on", "buy_block_rise_pct",
        "buy_block_fall_on", "buy_block_fall_pct",
        "rebuy_block_on",
        # 가산점 — 매수 순위에만 영향, 업종 재계산 불필요 (설계 결정 9-2)
        "boost_high_breakout_on", "boost_high_breakout_score",
        "boost_order_ratio_on",
        "boost_order_ratio_pct", "boost_order_ratio_score",
        "boost_program_net_buy_on", "boost_program_net_buy_score",
    }
    _sector_hit = bool(changed_keys & _SECTOR_UI_KEYS)
    _buy_block_hit = bool(changed_keys & _BUY_BLOCK_UI_KEYS)
    if not (_sector_hit or _buy_block_hit):
        return
    if is_engine_running():
        if _sector_hit:
            # 업종 재계산 경로 — 교집합 시 우선 (안전)
            if "sector_min_trade_amt" in changed_keys:
                schedule_engine_task(
                    engine_state.state.on_filter_settings_changed(), context="필터 설정 변경"
                )
            schedule_engine_task(
                recompute_sector_summary_now(), context="업종 설정 변경"
            )
        else:
            # 경량 재순위 경로 — 업종 스코어 캐시 재사용, 매수 후보만 재생성
            schedule_engine_task(
                recompute_buy_targets_only(), context="매수 차단 설정 변경"
            )
    # 업종 재계산 경로만 sector_scores 전송 — 경량 경로는 buy_targets만 갱신 (notify_buy_targets_update)
    if _sector_hit:
        try:
            await notify_desktop_sector_scores(force=True)
        except Exception as e:
            logger.warning("[설정] 업종 점수 전송 실패: %s", e, exc_info=True)


async def _apply_telegram_toggle(changed_keys: set[str]) -> None:
    """텔레그램 설정(tele_on·토큰·chat_id) 변경 시 폴링 start/stop/restart.

    단일 진입: telegram_bot.apply_telegram_polling_change()에 위임 (P10/P24).
    """
    from backend.app.services.telegram_bot import apply_telegram_polling_change

    await apply_telegram_polling_change(changed_keys)


async def _apply_risk_block_toggle_change(changed_keys: set[str]) -> None:
    """리스크 차단 마스터 토글 OFF 시 헤더 칩 즉시 해제 (P21 사용자 투명성, P10 SSOT).

    차단의 마스터 스위치가 OFF되면 해당 side는 무조건 차단 해제이므로 칩 클리어가 P21 준수.
    - risk_manager_on OFF → 매수+매도 칩 모두 클리어 (상위 마스터)
    - risk_block_buy_on OFF → 매수 칩 클리어
    - risk_block_sell_on OFF → 매도 칩 클리어

    하위 조건 토글(market_guard_*, daily_loss_*, consecutive_loss_*)은 클리어하지 않음 —
    다른 조건이 여전히 활성일 수 있어 칩 잔존이 P21 준수.
    P23(일관성): trading.py risk-block-status 브로드캐스트 패턴과 동일 (_safe_broadcast 사용).
    """
    _RISK_BLOCK_MASTER_KEYS = {"risk_manager_on", "risk_block_buy_on", "risk_block_sell_on"}
    if not (changed_keys & _RISK_BLOCK_MASTER_KEYS):
        return
    settings = get_settings_snapshot()
    from backend.app.services.risk_manager import get_risk_manager
    risk_manager = get_risk_manager()
    if not settings.get("risk_manager_on"):  # 상위 마스터 OFF → 매수/매도 모두 해제
        risk_manager.clear_market_block_state("buy")
        risk_manager.clear_market_block_state("sell")
        try:
            from backend.app.services.engine_account_notify import _safe_broadcast
            await _safe_broadcast("risk-block-status", {"blocked": False, "side": "buy"})
            await _safe_broadcast("risk-block-status", {"blocked": False, "side": "sell"})
            logger.info("[설정] 매매 안전장치 마스터 OFF → 리스크 차단 칩 해제")
        except Exception:
            logger.warning("[설정] 리스크 차단 칩 해제 브로드캐스트 실패", exc_info=True)
        return
    if not settings.get("risk_block_buy_on"):
        risk_manager.clear_market_block_state("buy")
        try:
            from backend.app.services.engine_account_notify import _safe_broadcast
            await _safe_broadcast("risk-block-status", {"blocked": False, "side": "buy"})
            logger.info("[설정] 매수 차단 토글 OFF → 매수 리스크 차단 칩 해제")
        except Exception:
            logger.warning("[설정] 매수 리스크 차단 칩 해제 브로드캐스트 실패", exc_info=True)
    if not settings.get("risk_block_sell_on"):
        risk_manager.clear_market_block_state("sell")
        try:
            from backend.app.services.engine_account_notify import _safe_broadcast
            await _safe_broadcast("risk-block-status", {"blocked": False, "side": "sell"})
            logger.info("[설정] 매도 차단 토글 OFF → 매도 리스크 차단 칩 해제")
        except Exception:
            logger.warning("[설정] 매도 리스크 차단 칩 해제 브로드캐스트 실패", exc_info=True)

