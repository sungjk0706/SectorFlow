# -*- coding: utf-8 -*-
"""
설정(SQLite DB) 읽기·저장·엔진 동기화 -- HTTP 레이어 없이 데스크톱/UI에서 직접 사용.
"""
from __future__ import annotations
import asyncio
import logging
import re as _re
from typing import Any
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS
from backend.app.core.settings_file import (
    load_integrated_system_settings,
    load_selected_settings,
    save_selected_settings,
    _ENCRYPT_FIELDS as ENCRYPT_FIELDS,
    _decrypt_encrypt_fields,
    _encrypt_field_or_raise,
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
            logger.info("[설정] %s 작업 취소됨", context)
        except Exception:
            logger.warning("[설정] %s 작업 실패", context, exc_info=True)

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
        "timetable.confirmed_download": str(d["timetable.confirmed_download"]).strip(),
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


# 타임테이블 시간 순서 검증 대상 키 (P20/P22) — 2그룹 분리
# 그룹1: 장 전 사전 준비 3개 키 (rt <= ws <= krx < 09:00)
_TIMETABLE_PRE_OPEN_KEYS = (
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
)
# 그룹2: 장 후 확정 다운로드 1개 키 (confirmed_download > 20:00, NXT 종료 이후만 허용)
_TIMETABLE_POST_CLOSE_KEYS = (
    "timetable.confirmed_download",
)
# 하위 호환: 기존 _TIMETABLE_ORDER_KEYS 참조 유지 (전체 합집합)
_TIMETABLE_ORDER_KEYS = _TIMETABLE_PRE_OPEN_KEYS + _TIMETABLE_POST_CLOSE_KEYS


async def _validate_timetable_order(data: dict, before: dict) -> None:
    """타임테이블 시간 순서 검증 (P20/P22) — 2그룹 분리.

    그룹1 (장 전 사전 준비): realtime_reset <= ws_prestart <= krx_pre_subscribe < "09:00"
    그룹2 (장 후 확정 다운로드): confirmed_download > "20:00" (NXT 종료 이후만 허용)
    - data: 이번 요청에서 변경하려는 키/값
    - before: load_selected_settings()로 로드한 기존 DB 값 (나머지 키 보충용)

    실패 시 ValueError 발생 → apply_settings_updates 호출자가 HTTP 422로 변환 (기존 패턴).
    형식 오류(_TIME_RE 위반)는 이미 apply_settings_updates 상단에서 무시+경고 처리되므로
    본 함수에서는 형식 통과한 값만 순서 검증.
    """
    def _to_min(v: str) -> int:
        h, m = v.split(":")
        return int(h) * 60 + int(m)

    # ── 그룹1: 장 전 사전 준비 3개 키 순서 검증 ──
    if set(data.keys()) & set(_TIMETABLE_PRE_OPEN_KEYS):
        values: dict[str, str] = {}
        for k in _TIMETABLE_PRE_OPEN_KEYS:
            if k in data and data[k]:
                values[k] = str(data[k]).strip()
            elif k in before and before[k]:
                values[k] = str(before[k]).strip()
            else:
                values[k] = str(DEFAULT_USER_SETTINGS.get(k, "")).strip()

        # 3개 모두 값이 있어야 검증 (빈 값이면 기본값 폴백이 아니라 P20 위반 → ValueError)
        missing = [k for k in _TIMETABLE_PRE_OPEN_KEYS if not values.get(k)]
        if missing:
            raise ValueError(f"타임테이블 시각 누락: {missing} — 기본값 폴백 금지 (P20)")

        rt = _to_min(values["timetable.realtime_reset"])
        ws = _to_min(values["timetable.ws_prestart"])
        krx = _to_min(values["timetable.krx_pre_subscribe"])
        open_min = 9 * 60  # 09:00

        if not (rt <= ws <= krx < open_min):
            raise ValueError(
                f"타임테이블 시간 순서 오류: "
                f"실시간 초기화({values['timetable.realtime_reset']}) <= "
                f"구독 시작({values['timetable.ws_prestart']}) <= "
                f"정규장 사전 구독({values['timetable.krx_pre_subscribe']}) < 09:00 이어야 합니다"
            )

    # ── 그룹2: 장 후 확정 다운로드 1개 키 하한선 검증 ──
    if set(data.keys()) & set(_TIMETABLE_POST_CLOSE_KEYS):
        cd_values: dict[str, str] = {}
        for k in _TIMETABLE_POST_CLOSE_KEYS:
            if k in data and data[k]:
                cd_values[k] = str(data[k]).strip()
            elif k in before and before[k]:
                cd_values[k] = str(before[k]).strip()
            else:
                cd_values[k] = str(DEFAULT_USER_SETTINGS.get(k, "")).strip()

        missing_cd = [k for k in _TIMETABLE_POST_CLOSE_KEYS if not cd_values.get(k)]
        if missing_cd:
            raise ValueError(f"타임테이블 시각 누락: {missing_cd} — 기본값 폴백 금지 (P20)")

        cd = _to_min(cd_values["timetable.confirmed_download"])
        nxt_close_min = 20 * 60  # 20:00 (NXT 마켓 종료)

        if not (cd > nxt_close_min):
            raise ValueError(
                f"타임테이블 시간 오류: 확정 데이터 다운로드({cd_values['timetable.confirmed_download']})는 "
                f"20:00 이후여야 합니다 (NXT 마켓 종료 후 확정 데이터 준비)"
            )


_TIME_RE = _re.compile(r"^\d{2}:\d{2}$")
_TIME_FIELDS = frozenset({
    "buy_time_start", "buy_time_end",
    "sell_time_start", "sell_time_end",
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
    "timetable.confirmed_download",
})

# 리스크 매니저 설정 검증 (P20/P22) — 범위/부호 검증
_RISK_INT_KEYS = {
    "daily_loss_limit": (-1_000_000_000, 0),        # 음수만 허용 (손실 한도)
    "daily_profit_limit": (0, 1_000_000_000),       # 양수만 허용 (수익 한도)
    "consecutive_loss_limit": (1, 100),             # 1~100회
}
_RISK_FLOAT_KEYS = {
    "daily_loss_rate_limit": (-100.0, 0.0),         # 음수만 허용
    "daily_profit_rate_limit": (0.0, 100.0),        # 양수만 허용
}


def _compute_select_keys(data: dict) -> set[str]:
    """변경 대상 키 + broker 키 + 타임테이블 그룹 키를 SELECT 대상으로 수집.
    타임테이블 키 중 하나라도 data에 있으면 해당 그룹의 모든 키를 추가 (순서 검증 시 나머지 키의 기존 DB 값이 필요)."""
    select_keys = set(data.keys()) | {"broker"}
    if set(data.keys()) & set(_TIMETABLE_PRE_OPEN_KEYS):
        select_keys = select_keys | set(_TIMETABLE_PRE_OPEN_KEYS)
    if set(data.keys()) & set(_TIMETABLE_POST_CLOSE_KEYS):
        select_keys = select_keys | set(_TIMETABLE_POST_CLOSE_KEYS)
    return select_keys


def _prepare_save_payload(data: dict, before: dict) -> tuple[dict, dict]:
    """저장할 값 준비 + 검증. (to_save, after) 반환.
    - None/빈문자열 무시, broker 허용값 검증, 시간 필드 형식 검증
    - 암호화 필드 평문 → 암호화
    - trade_mode 변경 시 로깅"""
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
                enc = _encrypt_field_or_raise(k, str(v))
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

    return to_save, after


def _validate_numeric_fields(data: dict) -> None:
    """구독 한도(1~1000) + 리스크 매니저 필드(범위/부호) 검증 (P20/P22). 위반 시 ValueError."""
    if "subscribe.max_0b_count" in data:
        _v = data["subscribe.max_0b_count"]
        try:
            _n = int(_v)
        except (TypeError, ValueError):
            raise ValueError("구독 한도는 정수여야 합니다")
        if _n < 1 or _n > 1000:
            raise ValueError("구독 한도는 1~1000 사이여야 합니다")

    for _k, (_lo, _hi) in _RISK_INT_KEYS.items():
        if _k in data:
            try:
                _n = int(data[_k])
            except (TypeError, ValueError):
                raise ValueError(f"{_k}는 정수여야 합니다")
            if _n < _lo or _n > _hi:
                raise ValueError(f"{_k}는 {_lo}~{_hi} 사이여야 합니다")
    for _k, (_lo, _hi) in _RISK_FLOAT_KEYS.items():
        if _k in data:
            try:
                _f = float(data[_k])
            except (TypeError, ValueError):
                raise ValueError(f"{_k}는 숫자여야 합니다")
            if _f < _lo or _f > _hi:
                raise ValueError(f"{_k}는 {_lo}~{_hi} 사이여야 합니다")


def _compute_changed_keys(data: dict, before: dict, after: dict) -> set[str]:
    """before와 after 비교하여 실제로 값이 달라진 키 집합 반환."""
    changed_keys: set[str] = set()
    for k in data.keys():
        if k in before and before[k] != after.get(k):
            changed_keys.add(k)
        elif k not in before and k in after:
            changed_keys.add(k)
    return changed_keys


async def apply_settings_updates(data: dict, username: str = "admin", profile: str | None = None) -> set[str]:
    """업데이트 데이터를 SQLite integrated_system_settings 테이블에 증분 저장.
    전체 설정 로드/저장 대신 변경된 필드만 로드/저장."""
    select_keys = _compute_select_keys(data)
    before = await load_selected_settings(select_keys)

    to_save, after = _prepare_save_payload(data, before)

    # 타임테이블 시간 순서 검증 (P20/P22) — 저장 전 차단
    await _validate_timetable_order(data, before)

    # 구독 한도 + 리스크 매니저 필드 검증 (P20/P22)
    _validate_numeric_fields(data)

    # 증분 저장 (전체 설정 덮어쓰기 없이 변경된 필드만 저장)
    await save_selected_settings(to_save)

    # 저널링: 변경된 키 추적
    changed_keys = _compute_changed_keys(data, before, after)
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
        if v:
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
    _decrypt_encrypt_fields(out)
    return out
