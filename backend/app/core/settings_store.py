from __future__ import annotations
# -*- coding: utf-8 -*-
"""
설정(SQLite DB) 읽기·저장·엔진 동기화 -- HTTP 레이어 없이 데스크톱/UI에서 직접 사용.
"""

import asyncio
import logging
from typing import Any

from backend.app.core.encryption import decrypt_value, encrypt_value
from backend.app.core.settings_file import load_integrated_system_settings, save_settings
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


def get_encrypt_fields(broker_nm: str) -> frozenset[str]:
    """모든 증권사의 암호화 필드 목록을 반환 (단일 소스 진리 준수)."""
    base_fields = {"telegram_bot_token"}
    # 모든 증권사의 암호화 필드 포함
    broker_fields = {
        "kiwoom_app_key", "kiwoom_app_secret",
        "ls_app_key", "ls_app_secret",
    }
    return frozenset(base_fields | broker_fields)


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
    legacy_k = str(d.get("kiwoom_app_key") or "")
    legacy_s = str(d.get("kiwoom_app_secret") or "")
    legacy_a = str(d.get("kiwoom_account_no") or "")
    mode = d.get("trade_mode")
    if mode not in ("test", "mock", "real"):
        mode = "test" if bool(d.get("test_mode", d.get("mock_mode", True))) else "real"
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
        "mock_mode": mode == "test",   # 하위 호환
        "mode_real": mode == "real",
        "kiwoom_account_no": _account_field_or_legacy_flat(
            d, "kiwoom_account_no", legacy_a
        ).strip(),
        "broker": str(d.get("broker") or "kiwoom").strip(),
    }
    tok = str(d.get("telegram_bot_token") or "").strip()
    if tok:
        data["telegram_bot_token"] = tok
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


async def apply_settings_updates(data: dict, username: str = "admin", profile: str | None = None) -> None:
    """업데이트 데이터를 SQLite integrated_system_settings 테이블에 병합 저장."""
    import re
    _TIME_RE = re.compile(r"^\d{2}:\d{2}$")
    _TIME_FIELDS = frozenset({
        "ws_subscribe_start", "ws_subscribe_end",
        "buy_time_start", "buy_time_end",
        "sell_time_start", "sell_time_end",
    })

    current = await load_integrated_system_settings()
    before_snapshot = dict(current)  # 저널링용 before 상태 캡처

    for k, v in data.items():
        if v is None:
            continue  # 아무것도 안 함 (기존 값 유지)
        if v == "":
            # 빈 문자열은 삭제 요청으로 간주
            current[k] = ""
            continue
        # broker 필드: 허용된 값만 저장
        if k == "broker":
            from backend.app.core.broker_registry import PROVIDER_REGISTRY
            broker_val = str(v).strip().lower()
            allowed_brokers = set(PROVIDER_REGISTRY.keys())
            if broker_val not in allowed_brokers:
                raise ValueError(f"지원하지 않는 증권사: {v} (허용된 값: {sorted(allowed_brokers)})")
            current[k] = broker_val
            continue
        # 시간 필드: HH:MM 형식이 아니면 무시 (입력 중간 상태 방어)
        if k in _TIME_FIELDS:
            sv = str(v).strip()
            if not _TIME_RE.match(sv):
                logger.warning("[설정] 시간 필드 %s 값 '%s' 무효 -- 무시", k, sv)
                continue
        if k in ("sell_per_symbol",) and isinstance(v, dict):
            v = normalize_symbol_override_map(v)
        broker_nm = str(current.get("broker", "") or "").lower().strip()
        encrypt_fields = get_encrypt_fields(broker_nm)
        if k in encrypt_fields and v and v != "***":
            if not str(v).startswith("gAAAA"):
                enc = encrypt_value(str(v))
                if enc:
                    current[k] = enc
                    continue
        current[k] = v

    mode_keys = {"trade_mode", "mock_mode", "mode_real"}
    if set(data.keys()) & mode_keys:
        logger.info(
            "[설정] 투자모드 업데이트 요청: trade_mode=%s mock_mode=%s mode_real=%s keys=%s",
            current.get("trade_mode"),
            current.get("mock_mode"),
            current.get("mode_real"),
            sorted(list(set(data.keys()) & mode_keys)),
        )

    await save_settings(current)
    
    # 저널링: 변경된 키 추적
    changed_keys = set()
    for k in data.keys():
        if k in before_snapshot and before_snapshot[k] != current.get(k):
            changed_keys.add(k)
        elif k not in before_snapshot:
            changed_keys.add(k)
    
    if changed_keys:
        await _journal.record_settings_change(changed_keys, before_snapshot, dict(current))
    
    return changed_keys


async def build_masked_settings_dict(username: str = "admin", profile: str | None = None) -> dict[str, Any]:
    """민감 필드 마스킹된 설정 dict (UI 표시용)."""
    flat = await load_integrated_system_settings()
    display_id = "root"
    masked = dict(flat)

    broker_nm = str(flat.get("broker", "") or "").lower().strip()
    encrypt_fields = get_encrypt_fields(broker_nm)
    for f in encrypt_fields:
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


async def load_integrated_system_settings_for_editing() -> dict:
    """
    로컬 편집용: 암호화 필드를 복호화한 dict.
    데스크톱 단일 사용자 전용 -- 메모리에 평문이 올라감.
    """
    flat = await load_integrated_system_settings()
    out = dict(flat)
    broker_nm = str(flat.get("broker", "") or "").lower().strip()
    encrypt_fields = get_encrypt_fields(broker_nm)
    for f in encrypt_fields:
        v = out.get(f)
        if v and str(v).startswith("gAAAA"):
            out[f] = decrypt_value(v) or ""
    return out
