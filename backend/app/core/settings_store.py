# -*- coding: utf-8 -*-
"""
설정 파일(settings.json) 읽기·저장·엔진 동기화 -- HTTP 레이어 없이 데스크톱/UI에서 직접 사용.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.encryption import decrypt_value, encrypt_value
from app.core.settings_file import load_settings, save_settings
from app.services import engine_service
from app.services.engine_account_notify import (
    notify_desktop_header_refresh,
    notify_desktop_sector_scores,
    notify_desktop_settings_toggled,
)
from app.services.auto_trading_effective import auto_trading_effective

logger = logging.getLogger(__name__)


ENCRYPT_FIELDS = frozenset({
    "kiwoom_app_key",
    "kiwoom_app_secret",
    "kiwoom_app_key_real",
    "kiwoom_app_secret_real",
    "telegram_bot_token",
})


def normalize_stk_cd_key(code: str) -> str:
    s = str(code).strip()
    if s.isdigit():
        return s.zfill(6)
    return s


def normalize_symbol_override_map(v: dict) -> dict:
    out: dict = {}
    for k, row in v.items():
        if not isinstance(row, dict):
            continue
        out[normalize_stk_cd_key(str(k))] = row
    return out


def _account_field_or_legacy_flat(d: dict, key: str, legacy: str) -> str:
    """모드별 계좌번호: SettingsWidget.load / _save 와 동일 규칙."""
    if key not in d:
        return legacy
    v = d.get(key)
    if v is None:
        return ""
    return str(v)


def general_save_payload_from_flat(d: dict) -> dict[str, Any]:
    """
    일반설정 저장 버튼이 보내는 payload와 동일한 규칙으로 dict를 구성한다.
    load_settings_for_editing() 스냅샷과 현재 위젯 payload를 비교할 때 사용.
    """
    legacy_k = str(d.get("kiwoom_app_key") or "")
    legacy_s = str(d.get("kiwoom_app_secret") or "")
    legacy_a = str(d.get("kiwoom_account_no") or "")
    mode = d.get("trade_mode")
    if mode not in ("test", "mock", "real"):
        mode = "test" if bool(d.get("test_mode", d.get("kiwoom_mock_mode", True))) else "real"
    if mode == "mock":
        mode = "test"
    data: dict[str, Any] = {
        "ws_subscribe_start": str(d.get("ws_subscribe_start") or "07:50").strip(),
        "ws_subscribe_end": str(d.get("ws_subscribe_end") or "20:00").strip(),
        "time_scheduler_on": bool(d.get("time_scheduler_on", True)),
        "auto_buy_on": bool(d.get("auto_buy_on", True)),
        "auto_sell_on": bool(d.get("auto_sell_on", True)),
        "buy_time_start": str(d.get("buy_time_start") or "09:00").strip(),
        "buy_time_end": str(d.get("buy_time_end") or "15:20").strip(),
        "sell_time_start": str(d.get("sell_time_start") or "09:00").strip(),
        "sell_time_end": str(d.get("sell_time_end") or "15:20").strip(),
        "telegram_chat_id": str(d.get("telegram_chat_id") or "").strip(),
        "tele_on": bool(d.get("tele_on", False)),
        "trade_mode": mode,
        "test_mode": mode == "test",
        "kiwoom_mock_mode": mode == "test",   # 하위 호환
        "mode_real": mode == "real",
        "kiwoom_account_no_real": _account_field_or_legacy_flat(
            d, "kiwoom_account_no_real", legacy_a
        ).strip(),
    }
    tok = str(d.get("telegram_bot_token") or "").strip()
    if tok:
        data["telegram_bot_token"] = tok
    # 키움 레거시 호환 (kiwoom_app_key → kiwoom_app_key_real)
    rk = str(d.get("kiwoom_app_key_real") or "") or legacy_k
    rs = str(d.get("kiwoom_app_secret_real") or "") or legacy_s
    for field, val in (
        ("kiwoom_app_key_real", rk),
        ("kiwoom_app_secret_real", rs),
    ):
        s = val.strip()
        if s:
            data[field] = s
    # 모든 증권사 API 키/시크릿/계좌번호 동적 수집 (증권사 추가 시 코드 수정 불필요)
    for key in d:
        if key.startswith("kiwoom_"):
            continue  # 키움은 위에서 레거시 호환 처리 완료
        if key.endswith(("_app_key", "_app_secret", "_account_no")):
            val = str(d.get(key) or "").strip()
            if val:
                data[key] = val
    return data


def _payload_values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if a == b:
        return True
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return str(a).strip() == str(b).strip()


def changed_keys_general_save(before_editing: dict, new_payload: dict) -> set[str]:
    """일반설정 저장 직전 스냅샷과 비교해 실제로 값이 달라진 키만 반환."""
    prev = general_save_payload_from_flat(before_editing)
    return {
        k
        for k in new_payload
        if not _payload_values_equal(prev.get(k), new_payload[k])
    }


def apply_settings_updates(data: dict, username: str = "admin", profile: Optional[str] = None) -> None:
    """업데이트 데이터를 data/settings.json 에 병합 저장."""
    import re
    _TIME_RE = re.compile(r"^\d{2}:\d{2}$")
    _TIME_FIELDS = frozenset({
        "ws_subscribe_start", "ws_subscribe_end",
        "buy_time_start", "buy_time_end",
        "sell_time_start", "sell_time_end",
    })

    current = load_settings()

    for k, v in data.items():
        if v is None:
            continue
        # 시간 필드: HH:MM 형식이 아니면 무시 (입력 중간 상태 방어)
        if k in _TIME_FIELDS:
            sv = str(v).strip()
            if not _TIME_RE.match(sv):
                logger.warning("[설정] 시간 필드 %s 값 '%s' 무효 -- 무시", k, sv)
                continue
        if k in ("sell_per_symbol",) and isinstance(v, dict):
            v = normalize_symbol_override_map(v)
        if k in ENCRYPT_FIELDS and v and v != "***":
            if not str(v).startswith("gAAAA"):
                enc = encrypt_value(str(v))
                if enc:
                    current[k] = enc
                    continue
        current[k] = v

    mode_keys = {"trade_mode", "kiwoom_mock_mode", "mode_real"}
    if set(data.keys()) & mode_keys:
        logger.info(
            "[설정] 투자모드 업데이트 요청: trade_mode=%s kiwoom_mock_mode=%s mode_real=%s keys=%s",
            current.get("trade_mode"),
            current.get("kiwoom_mock_mode"),
            current.get("mode_real"),
            sorted(list(set(data.keys()) & mode_keys)),
        )

    save_settings(current)


def build_masked_settings_dict(username: str = "admin", profile: Optional[str] = None) -> dict[str, Any]:
    """민감 필드 마스킹된 설정 dict (UI 표시용)."""
    flat = load_settings()
    display_id = "root"
    masked = dict(flat)

    for f in ENCRYPT_FIELDS:
        v = masked.get(f)
        if v and str(v).startswith("gAAAA"):
            masked[f] = "***"
        elif v:
            masked[f] = "***"

    if masked.get("telegram_bot_token"):
        masked["telegram_bot_token"] = "***"

    masked["id"] = display_id
    masked["profile_name"] = display_id

    masked["auto_trading_effective"] = auto_trading_effective(masked)
    return masked


def load_settings_for_editing() -> dict:
    """
    로컬 편집용: 암호화 필드를 복호화한 dict.
    데스크톱 단일 사용자 전용 -- 메모리에 평문이 올라감.
    """
    flat = load_settings()
    out = dict(flat)
    for f in ENCRYPT_FIELDS:
        v = out.get(f)
        if v and str(v).startswith("gAAAA"):
            out[f] = decrypt_value(v) or ""
    return out


async def after_settings_persisted(
    username: str,
    changed_keys: set,
    profile: Optional[str] = None,
) -> None:
    """파일 저장 후 엔진·스케줄러와 동기화 -- 어떤 설정이든 저장되면 WS settings-changed 를 보낸다."""
    if not changed_keys:
        notify_desktop_header_refresh()
        return

    # ── 1) 캐시 갱신 (모든 경로 공통) ────────────────────────────────────
    await engine_service.refresh_engine_settings_cache(None, use_root=True)

    # ── 2) 연결 레벨 키 → 엔진 재기동 ───────────────────────────────────
    if changed_keys & engine_service.CONNECTION_LEVEL_KEYS:
        if engine_service.is_running():
            asyncio.create_task(engine_service.reload_engine_settings())
            logger.info(
                "[설정] 연결 레벨 설정 변경 감지 -> 엔진 재기동 예약 (키=%s)",
                changed_keys & engine_service.CONNECTION_LEVEL_KEYS,
            )
        notify_desktop_header_refresh()
        notify_desktop_settings_toggled()
        return

    # ── 3) 거래모드 전환 → 캐시 갱신 + 계좌 구독 전환 ────────────────────
    if changed_keys & engine_service.TRADE_MODE_KEYS:
        if engine_service.is_running():
            asyncio.create_task(engine_service.on_trade_mode_switched())
            logger.info("[설정] 거래모드 전환 감지 -> 저장데이터 갱신 + 계좌 구독 전환 (엔진 재기동 없음)")
        notify_desktop_header_refresh()
        notify_desktop_settings_toggled()
        return

    # ── 4) 일반 설정 변경 ────────────────────────────────────────────────
    notify_desktop_header_refresh()
    # 어떤 키든 저장되면 무조건 WS settings-changed 발송
    notify_desktop_settings_toggled()

    # 테스트모드 가상 예수금 변경 시 Settlement Engine 동기화 + 계좌 스냅샷 갱신
    _VIRTUAL_BALANCE_KEYS = {"test_virtual_balance", "test_virtual_deposit"}
    if changed_keys & _VIRTUAL_BALANCE_KEYS:
        try:
            from app.core.settings_file import load_settings_async as _ls_async
            from app.services import settlement_engine as _se
            _s = await _ls_async()
            _deposit = int(_s.get("test_virtual_balance", _s.get("test_virtual_deposit", 10_000_000)) or 0)
            _se.reset(_deposit)
            # 계좌 스냅샷 갱신 + WS account-update 발송
            engine_service._refresh_account_snapshot_meta()
            engine_service._broadcast_account(reason="virtual_balance_changed")
        except Exception:
            logger.warning("[설정] 가상 예수금 동기화 실패", exc_info=True)

    # 5일봉 다운로드 토글 ON 시 즉시 다운로드 트리거
    if "scheduler_5d_download_on" in changed_keys:
        _5d_on = bool(engine_service.get_settings_snapshot().get("scheduler_5d_download_on", True))
        if _5d_on:
            try:
                engine_service._avg_amt_needs_bg_refresh = True
                engine_service._broadcast_avg_amt_progress(0, 0, status="requested")
                asyncio.create_task(engine_service.refresh_avg_amt_5d_cache())
                logger.info("[설정] scheduler_5d_download_on=ON → 5일봉 다운로드 트리거")
            except Exception:
                logger.warning("[설정] 5일봉 다운로드 트리거 실패", exc_info=True)

    # 자동매매 시간 관련 설정 변경 시 타이머 재예약 + KiwoomConnector 플래그 동기화
    _TIME_SCHEDULE_KEYS = {
        "time_scheduler_on", "auto_buy_on", "auto_sell_on",
        "buy_time_start", "buy_time_end", "sell_time_start", "sell_time_end",
    }
    if changed_keys & _TIME_SCHEDULE_KEYS:
        try:
            from app.services.daily_time_scheduler import schedule_auto_trade_timers
            new_settings = engine_service.get_settings_snapshot()
            schedule_auto_trade_timers(new_settings)
            # KiwoomConnector 자동매매 플래그 동기화
            ws = getattr(engine_service, "_kiwoom_connector", None)
            if ws and "time_scheduler_on" in changed_keys:
                ws.set_auto_trade_enabled(bool(new_settings.get("time_scheduler_on", True)))
        except Exception:
            pass

    # WS 구독 시간/스위치 변경 시 → 즉시 구간 재판정 + 타이머 재예약
    _WS_SCHEDULE_KEYS = {"ws_subscribe_start", "ws_subscribe_end", "ws_subscribe_on"}
    if changed_keys & _WS_SCHEDULE_KEYS:
        try:
            from app.services import daily_time_scheduler as _dts
            new_settings = engine_service.get_settings_snapshot()
            now_in_window = _dts.is_ws_subscribe_window(new_settings)
            was_active = bool(_dts._ws_subscribe_window_active)

            # 1) 타이머 재예약 (항상)
            _dts.schedule_ws_subscribe_timers(new_settings)

            # 2) KiwoomConnector 실시간 연결 플래그 업데이트
            ws = getattr(engine_service, "_kiwoom_connector", None)
            if ws:
                ws.set_realtime_enabled(bool(new_settings.get("ws_subscribe_on", True)))
                ws.set_holiday_block_enabled(bool(new_settings.get("holiday_guard_on", True)))

            # 3) 활성→구간밖: 즉시 구독 해제 + WS 끊기 (장마감 후처리 없이)
            if was_active and not now_in_window:
                logger.info("[설정] 실시간 구독 구간 변경 → 현재 구간 밖 — 즉시 구독 해제")
                _dts._fire_ws_disconnect_only()

            # 4) 비활성→구간안: 즉시 WS 연결 + 구독 시작
            elif not was_active and now_in_window:
                logger.info("[설정] 실시간 구독 구간 변경 → 현재 구간 안 — 즉시 구독 시작")
                import asyncio
                asyncio.create_task(_dts._on_ws_subscribe_start())
        except Exception:
            pass

    # 공휴일 자동 차단 설정 변경 시 KiwoomConnector 플래그 업데이트
    if "holiday_guard_on" in changed_keys:
        try:
            ws = getattr(engine_service, "_kiwoom_connector", None)
            if ws:
                new_settings = engine_service.get_settings_snapshot()
                ws.set_holiday_block_enabled(bool(new_settings.get("holiday_guard_on", True)))
        except Exception:
            pass

    # 섹터 정렬/필터 관련 설정 변경 시 업종 점수만 재계산 (종목 시세는 WS delta로만 전송)
    _SECTOR_UI_KEYS = {
        "sector_sort_keys", "sector_rank_primary", "sector_weights",
        "sector_min_rise_ratio_pct", "sector_min_trade_amt",
        "sector_max_targets", "buy_block_rise_pct", "buy_block_fall_pct",
        "buy_min_strength",
        "buy_index_guard_kospi_on", "buy_index_guard_kosdaq_on",
        "buy_index_kospi_drop", "buy_index_kosdaq_drop",
        "sector_trim_trade_amt_pct", "sector_trim_change_rate_pct",
        # 가산점 설정
        "boost_high_breakout_on", "boost_high_breakout_score",
        "boost_order_ratio_on",
        "boost_order_ratio_pct", "boost_order_ratio_score",
    }
    if changed_keys & _SECTOR_UI_KEYS:
        if engine_service.is_running():
            engine_service.recompute_sector_summary_now()
        notify_desktop_sector_scores(force=True)

    # WS 구독 제어 설정 변경 시 즉시 반영 (구독 시작/해지)
    _WS_SUBSCRIBE_CONTROL_KEYS = {"index_auto_subscribe", "quote_auto_subscribe"}
    _ws_changed = changed_keys & _WS_SUBSCRIBE_CONTROL_KEYS
    if _ws_changed:
        try:
            from app.services.ws_subscribe_control import on_setting_changed
            from app.core.settings_file import load_settings_async
            raw = await load_settings_async()
            for key in _ws_changed:
                asyncio.create_task(
                    on_setting_changed(key, bool(raw.get(key)), engine_service)
                )
        except Exception:
            logger.warning("[설정] ws_subscribe_control 설정 변경 반영 실패", exc_info=True)


async def after_buy_settings_persisted(username: str, changed_keys: set, data: dict, profile: Optional[str] = None) -> None:
    await after_settings_persisted(username, changed_keys, profile)
