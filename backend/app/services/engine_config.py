# -*- coding: utf-8 -*-
"""
설정 관련 모듈
- 설정 조회
- 설정 캐시 갱신
- 민감 정보 마스킹
- 연결 레벨 설정 키
"""
from backend.app.core.logger import get_logger
from backend.app.core.engine_settings import get_engine_settings
from backend.app.services.engine_state import state

logger = get_logger("engine_config")


# ── 설정 조회 ─────────────────────────────────────────────────────────

def _get_settings() -> dict:
    """설정 캐시 반환."""
    return state.integrated_system_settings_cache


def get_settings_snapshot() -> dict:
    """설정 스냅샷 반환 (민감 정보 마스킹 포함)."""
    # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
    if isinstance(state.integrated_system_settings_cache, dict) and state.integrated_system_settings_cache:
        d = dict(state.integrated_system_settings_cache)
    else:
        d = dict(state.integrated_system_settings_cache)

    if "tele_on" not in d:
        d["tele_on"] = bool(d.get("telegram_on", False))
    if "telegram_on" not in d:
        d["telegram_on"] = bool(d.get("tele_on", False))

    # 헤더 칩용: 백엔드 실제 유효 상태 (시간 범위 + 공휴일 + 마스터 스위치 반영)
    from backend.app.services.auto_trading_effective import (
        auto_buy_effective, auto_sell_effective, auto_trading_effective,
    )
    d["auto_buy_effective"] = auto_buy_effective(d)
    d["auto_sell_effective"] = auto_sell_effective(d)
    d["auto_trading_effective"] = auto_trading_effective(d)

    return _mask_sensitive_settings(d)


# ── 설정 캐시 갱신 ─────────────────────────────────────────────────────

async def refresh_engine_integrated_system_settings_cache(user_id: str | None = None, *, use_root: bool = False) -> None:
    """
    설정 파일 저장 직후 호출: 디스크와 동일한 내용으로 state.integrated_system_settings_cache 를 갱신한다.
    주기적 파일 재로드는 하지 않으며, UI/텔레그램 등 저장 이벤트에서만 동기화한다.

    use_root=True: 루트 data/settings.json 기준으로 갱신 (단일 프로필 데스크톱 기본).

    [핵심 원칙] 캐시 갱신(step 1)은 엔진 실행 여부와 무관하게 항상 수행한다.
    필터 콜백(step 2: on_filter_settings_changed)은 엔진 실행 중일 때만 호출한다.
    이로써 PATCH 후 브로드캐스트 시 항상 최신 설정값이 반영된다.
    """
    uid_engine = (state.engine_user_id or "").strip()

    if use_root:
        load_user = None
    else:
        uid_save = (user_id or "").strip()
        if uid_engine and uid_save and uid_engine != uid_save:
            return
        load_user = uid_save if uid_save else (uid_engine or None)

    try:
        # ── step 1) 항상 수행: DB → 메모리 캐시 갱신 ──────────────────────────
        # 필터 설정 변경 감지용 -- 갱신 전 값 보존
        old_min_amt = state.integrated_system_settings_cache["sector_min_trade_amt"] if state.integrated_system_settings_cache else 0.0

        fresh = await get_engine_settings(load_user if load_user else None)
        # 런타임 전용 상태 보존 (build_engine_settings_dict 결과에 없는 캐시 B 전용 런타임 상태)
        _RUNTIME_ONLY_KEYS = ("sector_stock_layout",)
        preserved = {
            k: state.integrated_system_settings_cache.get(k)
            for k in _RUNTIME_ONLY_KEYS
            if k in state.integrated_system_settings_cache
        }
        state.integrated_system_settings_cache.clear()
        state.integrated_system_settings_cache.update(fresh)
        state.integrated_system_settings_cache.update(preserved)
        logger.info("[설정] 설정 캐시 갱신 완료")

        # ── step 2) 엔진 실행 중일 때만: 필터 콜백 트리거 ──────────────────────
        if state.running:
            new_min_amt = fresh.get("sector_min_trade_amt", 0.0)
            if old_min_amt != new_min_amt:
                logger.info("[설정] sector_min_trade_amt 변경: %.0f억 → %.0f억", old_min_amt, new_min_amt)
                if state.on_filter_settings_changed:
                    await state.on_filter_settings_changed()
    except Exception as e:
        logger.warning("[설정] 설정 캐시 갱신 실패: %s", e, exc_info=True)


async def reload_engine_settings() -> None:
    """엔진 런타임 중 설정 재로드 (필터 변경 등)."""
    await refresh_engine_integrated_system_settings_cache(state.engine_user_id or None, use_root=True)
    # broker 설정 변경 시 BrokerRouter 캐시 초기화
    from backend.app.core.broker_factory import reset_router
    reset_router()
    logger.info("[설정] 엔진 재기동 -> BrokerRouter 캐시 초기화")
    
    # 엔진 재시작 완료 후 engine-reload-complete 이벤트 전송
    from backend.app.services.engine_account_notify import _broadcast
    _broadcast("engine-reload-complete", {"status": "complete"})
    logger.info("[설정] 엔진 재시작 완료 -> engine-reload-complete 전송")


# ── 민감 정보 마스킹 ─────────────────────────────────────────────────

_SENSITIVE_SETTINGS_KEYS: frozenset[str] = frozenset({
    "telegram_bot_token_test", "telegram_bot_token_real",
})


def _mask_sensitive_settings(settings: dict) -> dict:
    """설정 딕셔너리에서 API 키·시크릿·토큰 등 민감 필드를 '***'로 마스킹한 복사본을 반환한다."""
    masked = dict(settings)
    broker_nm = str(settings.get("broker", "") or "").lower().strip()
    
    # broker 기반 동적 키 마스킹
    for suffix in ["_app_key", "_app_secret", "_account_no"]:
        key = f"{broker_nm}{suffix}"
        if key in masked and masked[key]:
            masked[key] = "***"
    
    # 고정 키 마스킹
    for key in _SENSITIVE_SETTINGS_KEYS:
        if key in masked and masked[key]:
            masked[key] = "***"
    
    return masked


# ── 연결 레벨 설정 키 ─────────────────────────────────────────────────

def get_connection_level_keys(broker_nm: str) -> frozenset[str]:
    """broker 기반 연결 레벨 설정 키를 동적으로 생성한다."""
    base_keys = {"broker", "broker_config"}
    broker_keys = {
        f"{broker_nm}_app_key",
        f"{broker_nm}_app_secret",
        f"{broker_nm}_account_no",
    }
    return frozenset(base_keys | broker_keys)


# 거래 모드 전환 키 -- 엔진 재기동 없이 캐시 갱신 + 계좌 구독 전환만 수행한다.
TRADE_MODE_KEYS: frozenset[str] = frozenset({
    "trade_mode",
})
