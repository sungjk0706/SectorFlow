# -*- coding: utf-8 -*-
"""
엔진 전용 설정 로더 -- SQLite integrated_system_settings 테이블에서 읽어 복호화 후 반환.

포함: 브로커 자격·스케줄·매수 전략 필드 -- 디스크에 있는 영속 설정.
미포함: 레이더/대기 큐 -- engine_service 메모리·WebSocket 전용(휘발성).

P10 (SSOT): 모든 기본값은 settings_defaults.DEFAULT_USER_SETTINGS가 단일 소스 진리.
            _build_* 함수는 하드코딩 기본값을 두지 않고 merged[key] 직접 접근.
            merged = {**DEFAULT_USER_SETTINGS, **flat_clean} 이후 DEFAULT 키는 항상 존재.
P16 (살아있는 경로): flat의 None 값은 진입점에서 제거 (근본 원인 차단).
                    _load_db_settings()가 프로덕션에서 None을 이미 치환하므로
                    이 정규화는 테스트/직접 호출 시 방어 역할.
"""
import logging
from backend.app.core.settings_file import load_integrated_system_settings
from backend.app.core.encryption import decrypt_secret, SecretValueState
from backend.app.core.trade_mode import effective_trade_mode
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS

logger = logging.getLogger(__name__)


def _decrypt_field(v) -> tuple[str, SecretValueState]:
    """암호문(gAAAA) 복호화 — 상태 기반 처리 (B21-01 세션 4, P20 폴백 제거).

    반환: (평문값, 상태).
    - 빈 값 → ("", EMPTY)
    - gAAAA 접두 아님 → (원문, PLAINTEXT_LEGACY)  # 레거시 평문 호환 (재저장 시 암호화)
    - gAAAA 접두 + 복호화 성공 → (평문, ENCRYPTED)
    - gAAAA 접두 + KEY_UNAVAILABLE/DECRYPT_FAILED → ("", 상태) + 상태별 경고 로그 (P21)
      엔진 기동 차단 아님 (P25) — 빈값 유지, 연결·주문 차단은 세션 5에서.
    """
    if not v:
        return "", SecretValueState.EMPTY
    s = str(v)
    if not s.startswith("gAAAA"):
        return s, SecretValueState.PLAINTEXT_LEGACY
    result = decrypt_secret(s)
    if result.state is SecretValueState.ENCRYPTED and result.plaintext is not None:
        return result.plaintext, SecretValueState.ENCRYPTED
    # 복호화 불가 — 빈값 유지 + 상태별 경고 로그 (P21 사용자 투명성, P25 기동 차단 없음).
    if result.state is SecretValueState.KEY_UNAVAILABLE:
        logger.warning("[설정] 복호화 불가 — 암호화 키 없음/오류. cipher 앞 10자: %s...", s[:10])
    elif result.state is SecretValueState.DECRYPT_FAILED:
        logger.warning("[설정] 복호화 실패 — 암호문 손상 또는 다른 키로 암호화됨. cipher 앞 10자: %s...", s[:10])
    return "", result.state


def _pick_broker_credentials(merged: dict) -> dict:
    """동적으로 발견된 모든 증권사의 자격증명을 수집 (복호화 + 타입 정규화).
    kiwoom 특수 분기 없이 모든 증권사를 균일하게 처리 (P4 준수).
    현재 선택된 증권사(broker)는 자격증명 키가 없어도 빈 값으로 포함 —
    connector가 키 존재 여부에 관계없이 현재 증권사 자격을 참조할 수 있도록 보장.

    _credential_states (B21-01 세션 4): 각 증권사의 app_key/app_secret 복호화 상태를
    SecretValueState.name 문자열로 수집. 세션 5의 broker_router.validate()가
    연결·주문 차단 판정에 활용 (설계 8.2/8.3).

    B21-01 bugfix: _decrypt_encrypt_fields()가 평문 치환 후 기록한 원본 상태
    (_secret_field_states)가 있으면 이를 사용 — 이미 복호화된 평문을
    _decrypt_field() 재호출 시 PLAINTEXT_LEGACY로 오분류하는 문제 해결.
    원본 상태가 없으면 (테스트/직접 호출) 기존 _decrypt_field() 경로 사용."""
    result: dict = {}
    credential_states: dict[str, dict[str, str]] = {}
    broker_names = {k.split("_")[0] for k in merged if k.endswith("_app_key")}
    current_broker = str(merged["broker"]).strip().lower()
    if current_broker:
        broker_names.add(current_broker)
    pre_computed = merged.get("_secret_field_states")
    for b_name in broker_names:
        if pre_computed is not None:
            key_state_name = pre_computed.get(f"{b_name}_app_key", "EMPTY")
            sec_state_name = pre_computed.get(f"{b_name}_app_secret", "EMPTY")
            key_val = str(merged.get(f"{b_name}_app_key") or "")
            sec_val = str(merged.get(f"{b_name}_app_secret") or "")
            if key_state_name in ("KEY_UNAVAILABLE", "DECRYPT_FAILED"):
                key_val = ""
            if sec_state_name in ("KEY_UNAVAILABLE", "DECRYPT_FAILED"):
                sec_val = ""
        else:
            key_val, key_state = _decrypt_field(merged.get(f"{b_name}_app_key"))
            sec_val, sec_state = _decrypt_field(merged.get(f"{b_name}_app_secret"))
            key_state_name = key_state.name
            sec_state_name = sec_state.name
        result[f"{b_name}_app_key"] = key_val
        result[f"{b_name}_app_secret"] = sec_val
        result[f"{b_name}_account_no"] = str(merged.get(f"{b_name}_account_no") or "").strip()
        credential_states[b_name] = {
            "app_key": key_state_name,
            "app_secret": sec_state_name,
        }
    result["_credential_states"] = credential_states
    return result


# ── 자격 상태 판정 SSOT (B21-01 세션 5, 설계 8.2/8.3) ──────────────────────────
# broker_router.validate() / create_*_connector() / trading.py 주문 게이트가
# 모두 이 헬퍼를 호출 — 상태 판정·메시지 매핑의 단일 진실 소스 (P10/P24).

# 차단 상태 우선순위 (심각도 높은 순) — app_key/app_secret 중 더 심각한 상태 채택.
# ENCRYPTED는 정상이므로 제외. EMPTY는 값 미설정.
_CREDENTIAL_BLOCK_PRIORITY: tuple[str, ...] = (
    "KEY_UNAVAILABLE",   # 암호화 키 없음/오류 — 가장 심각
    "DECRYPT_FAILED",    # 복호화 실패 (암호문 손상/다른 키)
    "PLAINTEXT_LEGACY",  # 평문 레거시 — 재입력 필요
    "EMPTY",             # 값 없음 — 미설정
)

# 상태 → 사용자용 차단 사유 메시지 (설계 7.2 표시 상태와 정렬).
_CREDENTIAL_BLOCK_MESSAGES: dict[str, str] = {
    "KEY_UNAVAILABLE":  "암호화 키가 없어 저장된 인증정보를 읽을 수 없습니다.",
    "DECRYPT_FAILED":   "저장된 인증정보를 복호화할 수 없습니다. 인증정보를 다시 입력하세요.",
    "PLAINTEXT_LEGACY": "기존 인증정보가 안전하게 암호화되지 않았습니다. 인증정보를 다시 입력해 저장하세요.",
    "EMPTY":            "증권사 API 키가 설정되지 않았습니다. 일반설정에서 입력하세요.",
    "UNKNOWN":          "자격증명 상태를 확인할 수 없습니다. 설정을 다시 확인하세요.",
}


def broker_credential_state(broker_name: str) -> str:
    """브로커 자격증명 종합 상태 반환 (SecretValueState.name 문자열).

    ENCRYPTED=정상 (app_key/app_secret 모두 ENCRYPTED).
    그 외=차단 (둘 중 더 심각한 상태 채택).
    _credential_states 누락 시 UNKNOWN (fail-closed — P20 폴백 금지).
    """
    from backend.app.services.engine_state import state
    states = state.integrated_system_settings_cache.get("_credential_states") or {}
    broker_states = states.get(broker_name)
    if not broker_states:
        return "UNKNOWN"
    key_state = str(broker_states.get("app_key", "UNKNOWN"))
    sec_state = str(broker_states.get("app_secret", "UNKNOWN"))
    # 둘 다 ENCRYPTED면 정상
    if key_state == "ENCRYPTED" and sec_state == "ENCRYPTED":
        return "ENCRYPTED"
    # 차단 상태 중 더 심각한 것 (우선순위 테이블 기준)
    for block_state in _CREDENTIAL_BLOCK_PRIORITY:
        if key_state == block_state or sec_state == block_state:
            return block_state
    # 알 수 없는 상태 — 보수적 차단 (P20)
    return "UNKNOWN"


def broker_credential_block_reason(broker_name: str) -> str:
    """브로커 자격증명 차단 사유 메시지 — 빈 문자열=정상, 비어있지 않음=차단.

    broker_router.validate() / create_*_connector() / trading.py 주문 게이트가
    공통 호출 (P10 SSOT, P24 중복 제거).
    """
    cred_state = broker_credential_state(broker_name)
    if cred_state == "ENCRYPTED":
        return ""
    return _CREDENTIAL_BLOCK_MESSAGES.get(cred_state, _CREDENTIAL_BLOCK_MESSAGES["UNKNOWN"])


def _build_operation_settings(merged: dict, tm: str) -> dict:
    """운영 설정: 증권사, 투자모드, 자동매매 토글, 매수/매도 시간대."""
    return {
        "broker": merged["broker"],
        "trade_mode": tm,
        "time_scheduler_on": bool(merged["time_scheduler_on"]),
        "auto_buy_on": bool(merged["auto_buy_on"]),
        "auto_sell_on": bool(merged["auto_sell_on"]),
        "buy_time_start": str(merged["buy_time_start"])[:5],
        "buy_time_end": str(merged["buy_time_end"])[:5],
        "sell_time_start": str(merged["sell_time_start"])[:5],
        "sell_time_end": str(merged["sell_time_end"])[:5],
    }


def _build_telegram_settings(merged: dict) -> dict:
    """텔레그램 알림 설정 (토큰은 복호화). tele_on 단일 키 (P10 SSOT)."""
    return {
        "tele_on": bool(merged["tele_on"]),
        "telegram_bot_token_test": _decrypt_field(merged["telegram_bot_token_test"])[0],
        "telegram_bot_token_real": _decrypt_field(merged["telegram_bot_token_real"])[0],
        "telegram_chat_id": merged["telegram_chat_id"],
    }


def _build_sell_settings(merged: dict) -> dict:
    """매도/손절/트레일링 설정 — DEFAULT_USER_SETTINGS가 단일 소스 진리 (P10)."""
    return {
        "loss_cut_apply": bool(merged["loss_apply"]),
        "trailing_stop_apply": bool(merged["ts_apply"]),
        "sell_price_type": merged["sell_price_type"],
        "sell_qty_type": merged["sell_qty_type"],
        "loss_cut_value": float(merged["loss_val"]),
        "trailing_start_value": float(merged["ts_start_val"]),
        "trailing_drop_value": float(merged["ts_drop_val"]),
        "sell_offset": int(merged["sell_offset"]),
        "sell_custom_qty": int(merged["sell_custom_qty"]),
    }


def _build_risk_settings(merged: dict) -> dict:
    """리스크/리스크매니저 설정 — DEFAULT_USER_SETTINGS가 단일 소스 진리 (P10)."""
    return {
        "max_daily_loss_limit": int(merged["max_daily_loss_limit"]),
        "max_single_stock_exposure": int(merged["max_single_stock_exposure"]),
        "risk_manager_on": bool(merged["risk_manager_on"]),
        "daily_loss_limit_on": bool(merged["daily_loss_limit_on"]),
        "daily_loss_limit": int(merged["daily_loss_limit"]),
        "daily_loss_rate_limit_on": bool(merged["daily_loss_rate_limit_on"]),
        "daily_loss_rate_limit": float(merged["daily_loss_rate_limit"]),
        "risk_block_buy_on": bool(merged["risk_block_buy_on"]),
        "risk_block_sell_on": bool(merged["risk_block_sell_on"]),
        "consecutive_loss_limit_on": bool(merged["consecutive_loss_limit_on"]),
        "consecutive_loss_limit": int(merged["consecutive_loss_limit"]),
    }


def _build_buy_settings(merged: dict, flat: dict) -> dict:
    """매수 설정 + AutoTradeManager 호환 키 — _on 키 마이그레이션 포함.

    flat 참조는 _on 키 마이그레이션 로직 전용 (키 존재 여부로 추론 분기).
    나머지 값은 merged[key] 직접 접근 (P10 SSOT)."""
    _buy_amt_raw = int(merged["buy_amt"])
    _max_stock_cnt_raw = int(merged["max_stock_cnt"])
    return {
        "buy_amount": _buy_amt_raw,
        "buy_amount_on": bool(flat.get("buy_amt_on")) if "buy_amt_on" in flat else (_buy_amt_raw > 0),
        "max_stock_count": _max_stock_cnt_raw,
        "max_stock_count_on": bool(flat.get("max_stock_cnt_on")) if "max_stock_cnt_on" in flat else (_max_stock_cnt_raw > 0),
        "max_daily_total_buy_on": bool(merged["max_daily_total_buy_on"]),
        "max_daily_total_buy_amt": int(merged["max_daily_total_buy_amt"]),
        "buy_amt_on": bool(flat.get("buy_amt_on")) if "buy_amt_on" in flat else (_buy_amt_raw > 0),
        "buy_amt": _buy_amt_raw,
        "max_stock_cnt_on": bool(flat.get("max_stock_cnt_on")) if "max_stock_cnt_on" in flat else (_max_stock_cnt_raw > 0),
        "max_stock_cnt": _max_stock_cnt_raw,
        "tp_val": float(merged["tp_val"]),
        "tp_apply": bool(merged["tp_apply"]),
        "loss_apply": bool(merged["loss_apply"]),
        "loss_val": float(merged["loss_val"]),
        "ts_apply": bool(merged["ts_apply"]),
        "ts_start_val": float(merged["ts_start_val"]),
        "ts_drop_val": float(merged["ts_drop_val"]),
        "sell_per_symbol": merged["sell_per_symbol"],
    }


def _build_order_intervals(merged: dict) -> dict:
    """주문 간격 — 매수/매도 (초 단위). DEFAULT_USER_SETTINGS가 단일 소스 진리 (P10).

    레거시 buy_interval_min(분 단위) 변환 분기는 COUPLING-S2 후속에서 제거 —
    DB 마이그레이션이 buy_interval_min을 제거하므로 merged[key] 직접 접근."""
    return {
        "buy_interval_on": bool(merged["buy_interval_on"]),
        "buy_interval_sec": int(merged["buy_interval_sec"]),
        "sell_interval_on": bool(merged["sell_interval_on"]),
        "sell_interval_sec": int(merged["sell_interval_sec"]),
    }


def _build_sector_and_order_settings(merged: dict, flat: dict) -> dict:
    """업종 매수가드, 구독 한도, 슬라이더, 재매수 차단, 매수 차단 토글.

    flat 참조는 _on 키 마이그레이션 + 주문 간격 레거시 변환 전용.
    나머지 값은 merged[key] 직접 접근 (P10 SSOT)."""
    sector_sort_keys = [k for k in merged["sector_sort_keys"] if k not in ("foreign_net", "institution_net")]

    # 매수 차단 토글 — flat에 _on 키가 명시적으로 설정되었는지로 추론 분기 (마이그레이션)
    _rise_pct = float(merged["buy_block_rise_pct"])
    _fall_pct = float(merged["buy_block_fall_pct"])

    return {
        "sector_sort_keys": sector_sort_keys,
        "sector_max_targets": int(merged["sector_max_targets"]),
        "sector_min_rise_ratio_pct": float(merged["sector_min_rise_ratio_pct"]),
        "sector_min_trade_amt": float(merged["sector_min_trade_amt"]),
        "sector_start_threshold_pct": float(merged["sector_start_threshold_pct"]),
        "subscribe.max_0b_count": int(merged["subscribe.max_0b_count"]),
        "buy_block_rise_on": bool(flat.get("buy_block_rise_on")) if "buy_block_rise_on" in flat else (_rise_pct > 0),
        "buy_block_rise_pct": _rise_pct,
        "buy_block_fall_on": bool(flat.get("buy_block_fall_on")) if "buy_block_fall_on" in flat else (_fall_pct < 0),
        "buy_block_fall_pct": _fall_pct,
        "sector_bonus_rise_ratio_slider": int(merged["sector_bonus_rise_ratio_slider"]),
        "sector_bonus_relative_strength_slider": int(merged["sector_bonus_relative_strength_slider"]),
        "sector_bonus_trade_amount_slider": int(merged["sector_bonus_trade_amount_slider"]),
        "rebuy_block_on": bool(merged["rebuy_block_on"]),
        "rebuy_block_period": str(merged["rebuy_block_period"]),
        **_build_order_intervals(merged),
    }


def _build_boost_settings(merged: dict) -> dict:
    """매수 가산점 설정 — DEFAULT_USER_SETTINGS가 단일 소스 진리 (P10).

    레거시 boost_order_ratio_side 변환 분기는 COUPLING-S2 후속에서 제거 —
    DB 마이그레이션이 boost_order_ratio_side를 제거하므로 부호는 pct 값 자체에 인코딩."""
    _raw_pct = int(merged["boost_order_ratio_pct"])
    return {
        "boost_high_breakout_on": bool(merged["boost_high_breakout_on"]),
        "boost_high_breakout_score": max(float(merged["boost_high_breakout_score"]), 0),
        "boost_order_ratio_on": bool(merged["boost_order_ratio_on"]),
        "boost_order_ratio_pct": max(-100, min(100, _raw_pct)),
        "boost_order_ratio_score": max(float(merged["boost_order_ratio_score"]), 0),
        "boost_program_net_buy_on": bool(merged["boost_program_net_buy_on"]),
        "boost_program_net_buy_score": max(float(merged["boost_program_net_buy_score"]), 0),
        "boost_news_on": bool(merged["boost_news_on"]),
        "boost_news_score": max(float(merged["boost_news_score"]), 0),
        "news_boost_ttl_sec": int(merged["news_boost_ttl_sec"]),
        "news_keywords": str(merged["news_keywords"] or ""),
    }


def _normalize_broker_config(merged: dict) -> dict:
    """브로커 기능별 매핑 (기본값: 동일 브로커 사용)."""
    broker = merged["broker"]
    return {
        "websocket": broker,
        "order": broker,
        "sector": broker,
        "auth": broker,
    }


def _build_misc_settings(merged: dict) -> dict:
    """확정 시세 다운로드 시간, 스케줄러 토글, 가상 예수금, broker_config, broker_specs."""
    result = {
        "timetable.confirmed_download": str(merged["timetable.confirmed_download"])[:5],
        "scheduler_market_close_on": bool(merged["scheduler_market_close_on"]),
        "scheduler_5d_download_on": bool(merged["scheduler_5d_download_on"]),
        "quote_auto_subscribe": bool(merged["quote_auto_subscribe"]),
        "confirmed_data_broker": str(merged["confirmed_data_broker"]).strip(),
        "test_virtual_deposit": int(merged["test_virtual_deposit"]),
        "test_virtual_balance": int(merged["test_virtual_balance"]),
        "broker_config": _normalize_broker_config(merged),
    }
    if "_broker_specs" in merged:
        result["_broker_specs"] = merged["_broker_specs"]
    return result


def build_engine_settings_dict(flat: dict) -> dict:
    """flat 설정 딕셔너리로부터 복호화 및 타입 캐스팅 가공 처리가 완료된 엔진 설정을 빌드합니다.

    P10 (SSOT): DEFAULT_USER_SETTINGS가 모든 기본값의 단일 소스 진리.
                _build_* 함수는 하드코딩 기본값 없이 merged[key] 직접 접근.
    P16 (살아있는 경로): flat의 None 값은 진입점에서 제거 — None이 들어오는 근본 원인 차단.
                _load_db_settings()가 프로덕션에서 None을 이미 치환하므로
                이 정규화는 테스트/직접 호출 시 방어 역할 (dead code 아님).
    """
    flat_clean = {k: v for k, v in flat.items() if v is not None}
    merged = {**DEFAULT_USER_SETTINGS, **flat_clean}
    tm = effective_trade_mode(merged)

    result: dict = {
        **_build_operation_settings(merged, tm),
        **_build_telegram_settings(merged),
        **_build_sell_settings(merged),
        **_build_risk_settings(merged),
        **_build_buy_settings(merged, flat),
        **_build_sector_and_order_settings(merged, flat),
        **_build_boost_settings(merged),
        **_build_misc_settings(merged),
        **_pick_broker_credentials(merged),
    }
    return result


async def get_engine_settings(user_id: str | None = None, profile: str = "default") -> dict:
    """SQLite integrated_system_settings 테이블 로드 후 복호화 dict 반환.
    user_id / profile 인자는 호환용으로 무시됨."""
    flat = await load_integrated_system_settings()
    return build_engine_settings_dict(flat)
