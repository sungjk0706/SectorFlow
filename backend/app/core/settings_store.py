# -*- coding: utf-8 -*-
"""
설정(SQLite DB) 읽기·저장·엔진 동기화 -- HTTP 레이어 없이 데스크톱/UI에서 직접 사용.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from backend.app.core.encryption import decrypt_value, encrypt_value
from backend.app.core.settings_file import (
    load_integrated_system_settings,
    load_selected_settings,
    save_selected_settings,
    save_settings,
    _ENCRYPT_FIELDS as ENCRYPT_FIELDS,
)
from backend.app.core import journal as _journal
from backend.app.services.auto_trading_effective import auto_trading_effective
logger = logging.getLogger(__name__)


def _schedule_settings_task(coro, context: str) -> None:
    task = asyncio.create_task(coro)

    def _log_task_error(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.info("[설정] %s 태스크 취소됨", context)
        except Exception:
            logger.warning("[설정] %s 태스크 실패", context, exc_info=True)

    task.add_done_callback(_log_task_error)


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
    load_integrated_system_settings_for_editing() 스냅샷과 현재 위젯 payload를 비교할 때 사용.
    """
    legacy_a = str(d.get("kiwoom_account_no") or "")
    mode = d.get("trade_mode")
    if mode not in ("test", "mock", "real"):
        mode = "test"
    if mode == "mock":
        mode = "test"
    data: dict[str, Any] = {
        "ws_subscribe_start": str(d["ws_subscribe_start"]).strip(),
        "ws_subscribe_end": str(d["ws_subscribe_end"]).strip(),
        "confirmed_download_time": str(d["confirmed_download_time"]).strip(),
        "time_scheduler_on": bool(d["time_scheduler_on"]),
        "auto_buy_on": bool(d["auto_buy_on"]),
        "auto_sell_on": bool(d["auto_sell_on"]),
        "buy_time_start": str(d["buy_time_start"]).strip(),
        "buy_time_end": str(d["buy_time_end"]).strip(),
        "sell_time_start": str(d["sell_time_start"]).strip(),
        "sell_time_end": str(d["sell_time_end"]).strip(),
        "telegram_chat_id": str(d.get("telegram_chat_id") or "").strip(),
        "tele_on": bool(d["tele_on"]),
        "trade_mode": mode,
        "kiwoom_account_no": _account_field_or_legacy_flat(
            d, "kiwoom_account_no", legacy_a
        ).strip(),
        "broker": str(d["broker"]).strip(),
    }
    for tok_field in ("telegram_bot_token_test", "telegram_bot_token_real"):
        tok = str(d.get(tok_field) or "").strip()
        if tok:
            data[tok_field] = tok
    # 키움 레거시 호환 제거 (단일 소스 진리 준수)
    rk = str(d.get("kiwoom_app_key") or "")
    rs = str(d.get("kiwoom_app_secret") or "")
    for field, val in (
        ("kiwoom_app_key", rk),
        ("kiwoom_app_secret", rs),
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


async def apply_settings_updates(data: dict, username: str = "admin", profile: str | None = None) -> set[str]:
    """업데이트 데이터를 SQLite integrated_system_settings 테이블에 증분 저장.
    전체 설정 로드/저장 대신 변경된 필드만 로드/저장."""
    import re
    _TIME_RE = re.compile(r"^\d{2}:\d{2}$")
    _TIME_FIELDS = frozenset({
        "ws_subscribe_start", "ws_subscribe_end",
        "confirmed_download_time",
        "buy_time_start", "buy_time_end",
        "sell_time_start", "sell_time_end",
    })

    # 변경 대상 키 + broker 키만 SELECT (전체 로드 대신 증분 로드)
    select_keys = set(data.keys()) | {"broker"}
    before = await load_selected_settings(select_keys)

    # 검증 + 저장할 값 준비
    to_save: dict = {}
    after: dict = {}

    for k, v in data.items():
        if v is None:
            continue
        if v == "":
            logger.warning("[설정] 필드 %s에 빈 문자열 전달 — 무시 (기존 값 유지)", k)
            continue
        # broker 필드: 허용된 값만 저장
        if k == "broker":
            from backend.app.core.broker_registry import PROVIDER_REGISTRY
            broker_val = str(v).strip().lower()
            allowed_brokers = set(PROVIDER_REGISTRY.keys())
            if broker_val not in allowed_brokers:
                raise ValueError(f"지원하지 않는 증권사: {v} (허용된 값: {sorted(allowed_brokers)})")
            to_save[k] = broker_val
            after[k] = broker_val
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
                    to_save[k] = enc
                    after[k] = enc
                    continue
        to_save[k] = v
        after[k] = v

    mode_keys = {"trade_mode"}
    if set(data.keys()) & mode_keys:
        logger.info(
            "[설정] 투자모드 업데이트 요청: trade_mode=%s keys=%s",
            after.get("trade_mode", before.get("trade_mode")),
            sorted(list(set(data.keys()) & mode_keys)),
        )

    # 증분 저장 (전체 설정 덮어쓰기 없이 변경된 필드만 저장)
    await save_selected_settings(to_save)

    # 저널링: 변경된 키 추적
    changed_keys = set()
    for k in data.keys():
        if k in before and before[k] != after.get(k):
            changed_keys.add(k)
        elif k not in before and k in after:
            changed_keys.add(k)

    if changed_keys:
        journal_before = {k: before.get(k) for k in changed_keys if k in before}
        journal_after = {k: after.get(k) for k in changed_keys}
        await _journal.record_settings_change(changed_keys, journal_before, journal_after)

    return changed_keys


async def build_masked_settings_dict(username: str = "admin", profile: str | None = None) -> dict[str, Any]:
    """민감 필드 마스킹된 설정 dict (UI 표시용)."""
    flat = await load_integrated_system_settings()
    display_id = "root"
    masked = dict(flat)

    for f in ENCRYPT_FIELDS:
        v = masked.get(f)
        if v and str(v).startswith("gAAAA"):
            masked[f] = "***"
        elif v:
            masked[f] = "***"

    masked["id"] = display_id
    masked["profile_name"] = display_id

    masked["auto_trading_effective"] = auto_trading_effective(masked)
    return masked


async def load_integrated_system_settings_for_editing() -> dict:
    """
    로컬 편집용: 암호화 필드를 복호화한 dict.
    데스크톱 단일 사용자 전용 -- 메모리에 평문이 올라감.
    """
    flat = await load_integrated_system_settings()
    out = dict(flat)
    for f in ENCRYPT_FIELDS:
        v = out.get(f)
        if v and str(v).startswith("gAAAA"):
            out[f] = decrypt_value(v) or ""
    return out
