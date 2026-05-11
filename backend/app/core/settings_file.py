# -*- coding: utf-8 -*-
"""
로컬 settings.json 파일 읽기/쓰기 헬퍼.
단일 사용자 모드: backend/data/settings.json 만 사용 (사용자별 폴더 없음).
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_DATA_DIR      = Path(__file__).resolve().parent.parent.parent / "data"
_SETTINGS_PATH = _DATA_DIR / "settings.json"


def is_root_settings_profile(profile: Optional[str]) -> bool:
    """단일 파일 모드: 항상 data/settings.json 만 사용 (쿼리 profile 값은 무시)."""
    return True


def settings_path_for_profile(profile: Optional[str], username: str) -> Path:
    """실제 읽기/쓰기 대상 settings.json 경로 (로깅·진단용). 항상 루트 파일."""
    return _SETTINGS_PATH


_DEFAULTS: dict = {
    "broker": "kiwoom",
    # 키움: "test" | "real" -- 테스트/실전 API·WS·REG·자격증명 분기의 기준
    "trade_mode": "test",
    "mode_real": False,
    "time_scheduler_on": True,
    "auto_buy_on": True,
    "auto_sell_on": True,
    "buy_time_start": "09:00",
    "buy_time_end": "15:20",
    "sell_time_start": "09:00",
    "sell_time_end": "15:20",
    "buy_amt": 0,
    "max_daily_total_buy_amt": 0,
    "max_stock_cnt": 5,
    # 매수 설정 UI -- 0이면 해당 자동 동작 비활성(엔진은 UI·settings.json 값만 사용)
    "tp_val": 5.0,
    "tp_apply": True,
    "loss_apply": False,
    "loss_val": 0.0,
    "ts_apply": False,
    "ts_start_val": 0.0,
    "ts_drop_val": 0.0,
    "sell_price_type": "mkt",
    "sell_offset": 0,
    "sell_custom_qty": 0,
    "sell_qty_type": "%",
    "buy_min_trade_amt": 0.0,
    "max_position_size": None,
    "rate_limit_per_sec": 3,
    "tele_on": False,

    "telegram_bot_token": None,
    "telegram_chat_id": None,
    "kiwoom_app_key": None,
    "kiwoom_app_secret": None,
    "kiwoom_account_no": "",
    "kiwoom_app_key_real": None,
    "kiwoom_app_secret_real": None,
    "kiwoom_account_no_real": "",
    "kiwoom_mock_mode": True,

    "sell_per_symbol": {},
    # 매수/매도 폼 「기본값 저장」 전용 -- 엔진은 사용하지 않음(설정 저장과 별도 스냅샷).
    "buy_form_defaults": None,
    "sell_form_defaults": None,
    "theme_mode": "dark",
    "ui_zoom": 1.15,
    # 섹터 강도 / 매수 필터
    "sector_min_rise_ratio_pct": 60.0,
    "sector_min_trade_amt": 0.0,
    "sector_sort_keys": ["change_rate", "trade_amount", "strength"],
    "sector_rank_primary": "rise_ratio",
    "sector_weights": {"total_trade_amount": 0.5, "rise_ratio": 0.5},
    "sector_max_targets": 3,
    # 업종 내 종목 트리밍 비율 (%)
    "sector_trim_trade_amt_pct": 10.0,
    "sector_trim_change_rate_pct": 10.0,
    "buy_block_rise_pct": 7.0,
    "buy_block_fall_pct": 7.0,
    "buy_min_strength": 0,
    "buy_index_guard_kospi_on": False,
    "buy_index_guard_kosdaq_on": False,
    "buy_index_kospi_drop": 2.0,
    "buy_index_kosdaq_drop": 2.0,
    # 공휴일 자동 OFF
    "holiday_guard_on": True,
    # WS 구독 마스터 스위치
    "ws_subscribe_on": True,
    # 장마감 후 지수 폴링 (15:30~WS구독종료)
    "index_poll_after_close": False,
    # WS 구독 제어 — 지수(0J) / 실시간시세(0B) 자동구독
    "index_auto_subscribe": True,
    "quote_auto_subscribe": True,
    # 테스트모드 가상 예수금 -- 설정 금액(초기값)과 현재 잔액
    "test_virtual_deposit": 10_000_000,
    "test_virtual_balance": 10_000_000,
    # 하이브리드 브로커 -- 기능별 증권사 매핑 (없으면 broker 값으로 폴백)
    # "broker_config": {"quote": "kiwoom", "account": "kiwoom", ...}
}


def migrate_rank_primary_to_weights(sector_rank_primary: str) -> dict[str, float]:
    """
    기존 sector_rank_primary 값을 가중치로 변환.
    - "total_trade_amount" → {"total_trade_amount": 0.7, "rise_ratio": 0.3}
    - "rise_ratio" → {"rise_ratio": 0.7, "total_trade_amount": 0.3}
    알 수 없는 값이면 기본 가중치(0.5/0.5) 반환.
    """
    if sector_rank_primary == "total_trade_amount":
        return {"total_trade_amount": 0.7, "rise_ratio": 0.3}
    if sector_rank_primary == "rise_ratio":
        return {"rise_ratio": 0.7, "total_trade_amount": 0.3}
    return {"total_trade_amount": 0.5, "rise_ratio": 0.5}


def _migrate_sector_weights(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    """
    sector_weights 마이그레이션.
    - raw_data에 sector_weights가 이미 있으면 스킵 (사용자가 명시적으로 저장한 값)
    - sector_weights 없고 sector_rank_primary만 있으면 마이그레이션
    - 둘 다 없으면 기본 가중치 적용 (_DEFAULTS에서 이미 병합됨)
    """
    if "sector_weights" in raw_data:
        return merged, False
    rank_primary = raw_data.get("sector_rank_primary")
    if rank_primary:
        merged["sector_weights"] = migrate_rank_primary_to_weights(rank_primary)
        return merged, True
    # 둘 다 없으면 _DEFAULTS 병합으로 기본 가중치가 이미 적용됨
    return merged, False


def _migrate_legacy_auto_trade_on(merged: dict) -> tuple[dict, bool]:
    """
    예전 auto_trade_on 필드를 제거하고 time_scheduler_on 으로 승격한다.
    반환: (병합 dict, 디스크에 다시 써야 하면 True)
    """
    if "auto_trade_on" not in merged:
        return merged, False
    legacy = bool(merged.pop("auto_trade_on"))
    if not bool(merged.get("time_scheduler_on")):
        merged["time_scheduler_on"] = legacy
    return merged, True


def _migrate_time_range_split(merged: dict) -> tuple[dict, bool]:
    """
    레거시 time_start/time_end -> buy_time_start/buy_time_end + sell_time_start/sell_time_end 분리.
    신규 키가 이미 있으면 스킵. 마이그레이션 후 레거시 키 제거.
    """
    dirty = False
    legacy_start = merged.get("time_start")
    legacy_end = merged.get("time_end")
    if legacy_start and "buy_time_start" not in merged:
        merged["buy_time_start"] = legacy_start
        merged["sell_time_start"] = legacy_start
        dirty = True
    if legacy_end and "buy_time_end" not in merged:
        merged["buy_time_end"] = legacy_end
        merged["sell_time_end"] = legacy_end
        dirty = True
    # 레거시 키 제거
    if "time_start" in merged:
        del merged["time_start"]
        dirty = True
    if "time_end" in merged:
        del merged["time_end"]
        dirty = True
    return merged, dirty


def _migrate_sector_to_industry_index(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    """
    sector_auto_subscribe → index_auto_subscribe 마이그레이션.
    raw_data에 sector_auto_subscribe가 있고 신규 키가 없으면 변환.
    industry_auto_subscribe는 제거됨 (0U 구독 폐지).
    """
    dirty = False
    # industry_auto_subscribe 잔존 키 제거
    if "industry_auto_subscribe" in merged:
        del merged["industry_auto_subscribe"]
        dirty = True
    if "sector_auto_subscribe" not in raw_data:
        return merged, dirty
    # 이미 신규 키가 raw_data에 있으면 스킵 (이미 마이그레이션됨)
    if "index_auto_subscribe" in raw_data:
        # 레거시 키만 제거
        merged.pop("sector_auto_subscribe", None)
        return merged, True
    old_val = bool(raw_data["sector_auto_subscribe"])
    merged["index_auto_subscribe"] = old_val
    merged.pop("sector_auto_subscribe", None)
    return merged, True


def _migrate_broker_config(merged: dict, raw_data: dict) -> tuple[dict, bool]:
    """
    broker_config 마이그레이션.
    - raw_data에 broker_config가 이미 있으면 스킵
    - broker_config 없으면 기본값 생성하지 않음 (BrokerRouter가 broker 값으로 폴백)
    - broker_config 내 일부 키 누락 시에도 BrokerRouter가 폴백 처리
    """
    # broker_config가 이미 있으면 그대로 사용
    if "broker_config" in raw_data:
        return merged, False
    # 없으면 아무것도 하지 않음 -- BrokerRouter가 broker 값으로 폴백
    return merged, False


def _migrate_trade_mode(merged: dict) -> tuple[dict, bool]:
    """
    trade_mode 도입 이전 설정 호환: kiwoom_mock_mode -> trade_mode.
    trade_mode·kiwoom_mock_mode·test_mode·mode_real 필드를 일치시킨다.
    레거시 'mock' 값은 'test'로 자동 변환.
    """
    dirty = False
    tm = merged.get("trade_mode")
    # 레거시 'mock' -> 'test' 자동 변환
    if tm == "mock":
        merged["trade_mode"] = "test"
        tm = "test"
        dirty = True
    if tm not in ("test", "real"):
        merged["trade_mode"] = "test" if bool(merged.get("test_mode", merged.get("kiwoom_mock_mode", True))) else "real"
        dirty = True
    tm = str(merged["trade_mode"])
    # test_mode 불리언 동기화
    if bool(merged.get("test_mode", False)) != (tm == "test"):
        merged["test_mode"] = tm == "test"
        dirty = True
    # kiwoom_mock_mode 하위 호환 동기화
    if bool(merged.get("kiwoom_mock_mode", True)) != (tm == "test"):
        merged["kiwoom_mock_mode"] = tm == "test"
        dirty = True
    if bool(merged.get("mode_real", False)) != (tm == "real"):
        merged["mode_real"] = tm == "real"
        dirty = True
    return merged, dirty


def load_settings() -> dict:
    """settings.json 읽기. 파일이 없거나 파싱 오류 시 기본값 반환."""
    try:
        if _SETTINGS_PATH.is_file():
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = {**_DEFAULTS, **data}
            merged, dirty = _migrate_legacy_auto_trade_on(merged)
            merged, dirty_tm = _migrate_trade_mode(merged)
            merged, dirty_tr = _migrate_time_range_split(merged)
            merged, dirty_sw = _migrate_sector_weights(merged, data)
            merged, dirty_si = _migrate_sector_to_industry_index(merged, data)
            merged, dirty_bc = _migrate_broker_config(merged, data)
            dirty = dirty or dirty_tm or dirty_tr or dirty_sw or dirty_si or dirty_bc
            if dirty:
                save_settings(merged)
            return merged
    except Exception as e:
        logger.warning("settings.json 읽기 실패 (기본값 사용): %s", e)
    return dict(_DEFAULTS)


def save_settings(data: dict) -> None:
    """설정 전체를 settings.json에 저장."""
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("settings.json 저장 실패: %s", e)


def update_settings(updates: dict) -> dict:
    """기존 설정에 업데이트를 병합하여 저장하고 최신 설정 반환."""
    current = load_settings()
    current.update({k: v for k, v in updates.items() if v is not None or k in current})
    save_settings(current)
    return current


def load_user_settings(username: str) -> dict:
    """호환용 -- 사용자별 파일은 사용하지 않고 항상 load_settings() 를 반환."""
    return load_settings()


def save_user_settings(username: str, data: dict) -> None:
    """호환용 -- 항상 루트 settings.json 에 저장."""
    save_settings(data)


def iter_merged_settings_profiles() -> Iterator[tuple[Optional[str], dict]]:
    """루트 data/settings.json 한 개만 순회."""
    yield None, load_settings()


# ── 비동기 버전 (이벤트 루프 블로킹 방지) ────────────────────────────────

async def load_settings_async() -> dict:
    """settings.json 읽기 (비동기 버전). 파일이 없거나 파싱 오류 시 기본값 반환."""
    return await asyncio.to_thread(load_settings)


async def save_settings_async(data: dict) -> None:
    """설정 전체를 settings.json에 저장 (비동기 버전)."""
    await asyncio.to_thread(save_settings, data)


async def update_settings_async(updates: dict) -> dict:
    """기존 설정에 업데이트를 병합하여 저장하고 최신 설정 반환 (비동기 버전)."""
    current = await load_settings_async()
    current.update({k: v for k, v in updates.items() if v is not None or k in current})
    await save_settings_async(current)
    return current
