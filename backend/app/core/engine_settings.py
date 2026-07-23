# -*- coding: utf-8 -*-
"""
엔진 전용 설정 로더 -- SQLite integrated_system_settings 테이블에서 읽어 복호화 후 반환.

포함: 브로커 자격·스케줄·매수 전략 필드 -- 디스크에 있는 영속 설정.
미포함: 레이더/대기 큐 -- engine_service 메모리·WebSocket 전용(휘발성).
"""
import logging
from backend.app.core.settings_file import load_integrated_system_settings
from backend.app.core.encryption import decrypt_value
from backend.app.core.trade_mode import effective_trade_mode
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS

logger = logging.getLogger(__name__)


def _dec(v) -> str:
    """암호문(gAAAA) 복호화, 실패 시 경고 로그 + 빈문자열 반환."""
    if not v:
        return ""
    s = str(v)
    if s.startswith("gAAAA"):
        _plain = decrypt_value(s)
        if _plain is None:
            # 복호화 실패 — 빈문자열 폴백하되 실패 사실을 로그에 명시 (P21 사용자 투명성)
            logger.warning("[설정] 복호화 실패 — 빈문자열로 폴백. cipher 앞 10자: %s...", s[:10])
            return ""
        return _plain
    return s


def _pick_broker_credentials(merged: dict) -> dict:
    """동적으로 발견된 모든 증권사의 자격증명을 수집 (복호화 + 타입 정규화).
    kiwoom 특수 분기 없이 모든 증권사를 균일하게 처리 (P4 준수).
    현재 선택된 증권사(broker)는 자격증명 키가 없어도 빈 값으로 포함 —
    connector가 키 존재 여부에 관계없이 현재 증권사 자격을 참조할 수 있도록 보장."""
    result: dict = {}
    broker_names = {k.split("_")[0] for k in merged if k.endswith("_app_key")}
    current_broker = str(merged.get("broker", "")).strip().lower()
    if current_broker:
        broker_names.add(current_broker)
    for b_name in broker_names:
        result[f"{b_name}_app_key"] = _dec(merged.get(f"{b_name}_app_key"))
        result[f"{b_name}_app_secret"] = _dec(merged.get(f"{b_name}_app_secret"))
        result[f"{b_name}_account_no"] = str(merged.get(f"{b_name}_account_no") or "").strip()
    return result


def _build_operation_settings(merged: dict, tm: str) -> dict:
    """운영 설정: 증권사, 투자모드, 자동매매 토글, 매수/매도 시간대."""
    return {
        "broker": merged.get("broker", "kiwoom"),
        "trade_mode": tm,
        "time_scheduler_on": bool(merged.get("time_scheduler_on")),
        "auto_buy_on": bool(merged.get("auto_buy_on")),
        "auto_sell_on": bool(merged.get("auto_sell_on")),
        "buy_time_start": str(merged["buy_time_start"])[:5],
        "buy_time_end": str(merged["buy_time_end"])[:5],
        "sell_time_start": str(merged["sell_time_start"])[:5],
        "sell_time_end": str(merged["sell_time_end"])[:5],
    }


def _build_telegram_settings(merged: dict) -> dict:
    """텔레그램 알림 설정 (토큰은 복호화)."""
    return {
        "tele_on": bool(merged.get("tele_on")),
        "telegram_on": bool(merged.get("tele_on")),
        "telegram_bot_token_test": _dec(merged.get("telegram_bot_token_test")),
        "telegram_bot_token_real": _dec(merged.get("telegram_bot_token_real")),
        "telegram_chat_id": merged.get("telegram_chat_id"),
    }


def _build_sell_settings(merged: dict) -> dict:
    """매도/손절/트레일링 설정 — 0도 유효값이므로 or 폴백 금지 (P20)."""
    _v = merged.get("loss_val")
    loss_val = float(_v if _v is not None else 0)
    _v = merged.get("ts_start_val")
    ts_start = float(_v if _v is not None else 0)
    _v = merged.get("ts_drop_val")
    ts_drop = float(_v if _v is not None else 0)
    _v = merged.get("sell_offset")
    sell_offset = int(_v if _v is not None else 0)
    _v = merged.get("sell_custom_qty")
    sell_custom_qty = int(_v if _v is not None else 0)
    return {
        "loss_cut_apply": bool(merged.get("loss_apply")),
        "trailing_stop_apply": bool(merged.get("ts_apply")),
        "sell_price_type": merged.get("sell_price_type", "mkt"),
        "sell_qty_type": merged.get("sell_qty_type", "%"),
        "loss_cut_value": loss_val,
        "trailing_start_value": ts_start,
        "trailing_drop_value": ts_drop,
        "sell_offset": sell_offset,
        "sell_custom_qty": sell_custom_qty,
    }


def _build_risk_settings(merged: dict) -> dict:
    """리스크/리스크매니저 설정 — 0도 유효값이므로 or 폴백 금지 (P20)."""
    _v = merged.get("max_position_size")
    max_position_size = 0 if _v is None or _v == "None" or _v == "" else int(_v)
    _v = merged.get("max_daily_loss_limit")
    max_daily_loss = int(_v if _v is not None else -500000)
    _v = merged.get("max_single_stock_exposure")
    max_single_exposure = int(_v if _v is not None else 20000000)
    _v = merged.get("daily_loss_limit")
    daily_loss = int(_v if _v is not None else -500000)
    _v = merged.get("daily_loss_rate_limit")
    daily_loss_rate = float(_v if _v is not None else -5.0)
    _v = merged.get("daily_profit_limit")
    daily_profit = int(_v if _v is not None else 500000)
    _v = merged.get("daily_profit_rate_limit")
    daily_profit_rate = float(_v if _v is not None else 5.0)
    _v = merged.get("consecutive_loss_limit")
    consecutive_loss = int(_v if _v is not None else 3)
    return {
        "max_position_size": max_position_size,
        "max_daily_loss_limit": max_daily_loss,
        "max_single_stock_exposure": max_single_exposure,
        "risk_manager_on": bool(merged.get("risk_manager_on", False)),
        "daily_loss_limit_on": bool(merged.get("daily_loss_limit_on", True)),
        "daily_loss_limit": daily_loss,
        "daily_loss_rate_limit_on": bool(merged.get("daily_loss_rate_limit_on", False)),
        "daily_loss_rate_limit": daily_loss_rate,
        "daily_profit_limit_on": bool(merged.get("daily_profit_limit_on", False)),
        "daily_profit_limit": daily_profit,
        "daily_profit_rate_limit_on": bool(merged.get("daily_profit_rate_limit_on", False)),
        "daily_profit_rate_limit": daily_profit_rate,
        "risk_block_buy_on": bool(merged.get("risk_block_buy_on", True)),
        "risk_block_sell_on": bool(merged.get("risk_block_sell_on", False)),
        "consecutive_loss_limit_on": bool(merged.get("consecutive_loss_limit_on", False)),
        "consecutive_loss_limit": consecutive_loss,
    }


def _build_buy_settings(merged: dict, flat: dict) -> dict:
    """매수 설정 + AutoTradeManager 호환 키 — _on 키 마이그레이션 포함."""
    _v = merged.get("buy_amt")
    _buy_amt_raw = int(_v if _v is not None else 0)
    _v = merged.get("max_stock_cnt")
    _max_stock_cnt_raw = int(_v) if _v is not None else 5
    _v = merged.get("max_daily_total_buy_amt")
    max_daily_total_buy = int(_v if _v is not None else 0)
    _v = merged.get("tp_val")
    tp_val = float(_v if _v is not None else 0)
    _v = merged.get("loss_val")
    loss_val = float(_v if _v is not None else 0)
    _v = merged.get("ts_start_val")
    ts_start = float(_v if _v is not None else 0)
    _v = merged.get("ts_drop_val")
    ts_drop = float(_v if _v is not None else 0)
    _v = merged.get("sell_per_symbol")
    sell_per_symbol = _v if _v is not None else {}
    return {
        "buy_amount": _buy_amt_raw,
        "buy_amount_on": bool(flat.get("buy_amt_on")) if "buy_amt_on" in flat else (_buy_amt_raw > 0),
        "max_stock_count": _max_stock_cnt_raw,
        "max_stock_count_on": bool(flat.get("max_stock_cnt_on")) if "max_stock_cnt_on" in flat else (_max_stock_cnt_raw > 0),
        "max_daily_total_buy_on": bool(merged.get("max_daily_total_buy_on", False)),
        "max_daily_total_buy_amt": max_daily_total_buy,
        "buy_amt_on": bool(flat.get("buy_amt_on")) if "buy_amt_on" in flat else (_buy_amt_raw > 0),
        "buy_amt": _buy_amt_raw,
        "max_stock_cnt_on": bool(flat.get("max_stock_cnt_on")) if "max_stock_cnt_on" in flat else (_max_stock_cnt_raw > 0),
        "max_stock_cnt": _max_stock_cnt_raw,
        "tp_val": tp_val,
        "tp_apply": bool(merged.get("tp_apply")),
        "loss_apply": bool(merged.get("loss_apply")),
        "loss_val": loss_val,
        "ts_apply": bool(merged.get("ts_apply")),
        "ts_start_val": ts_start,
        "ts_drop_val": ts_drop,
        "sell_per_symbol": sell_per_symbol,
    }


def _build_sector_and_order_settings(merged: dict, flat: dict) -> dict:
    """업종 매수가드, 구독 한도, 슬라이더, 주문 간격, 재매수 차단, 매수 차단 토글."""
    _v = merged.get("sector_sort_keys")
    sector_sort_keys = _v if _v is not None else ["score"]
    sector_sort_keys = [k for k in sector_sort_keys if k not in ("foreign_net", "institution_net")]
    _v = merged.get("sector_max_targets")
    sector_max_targets = int(_v if _v is not None else 3)
    _v = merged.get("sector_min_rise_ratio_pct")
    sector_min_rise = float(_v if _v is not None else 60.0)
    _v = merged.get("sector_min_trade_amt")
    sector_min_trade = float(_v if _v is not None else 0.0)
    _v = merged.get("sector_start_threshold_pct")
    sector_start_threshold = float(_v if _v is not None else 70.0)
    _v = merged.get("subscribe.max_0b_count")
    subscribe_max_0b = int(_v if _v is not None else 200)

    _v = flat.get("buy_block_rise_pct")
    _rise_pct = float(_v) if _v is not None else 7.0
    _v = flat.get("buy_block_fall_pct")
    _fall_pct = float(_v) if _v is not None else 7.0

    result = {
        "sector_sort_keys": sector_sort_keys,
        "sector_max_targets": sector_max_targets,
        "sector_min_rise_ratio_pct": sector_min_rise,
        "sector_min_trade_amt": sector_min_trade,
        "sector_start_threshold_pct": sector_start_threshold,
        "subscribe.max_0b_count": subscribe_max_0b,
        "buy_block_rise_on": bool(flat.get("buy_block_rise_on")) if "buy_block_rise_on" in flat else (_rise_pct > 0),
        "buy_block_rise_pct": _rise_pct,
        "buy_block_fall_on": bool(flat.get("buy_block_fall_on")) if "buy_block_fall_on" in flat else (_fall_pct > 0),
        "buy_block_fall_pct": _fall_pct,
        "sector_bonus_rise_ratio_slider": int(merged.get("sector_bonus_rise_ratio_slider", 0)),
        "sector_bonus_relative_strength_slider": int(merged.get("sector_bonus_relative_strength_slider", 0)),
        "sector_bonus_trade_amount_slider": int(merged.get("sector_bonus_trade_amount_slider", 0)),
        "rebuy_block_on": bool(merged.get("rebuy_block_on", True)),
        "rebuy_block_period": str(merged.get("rebuy_block_period", "today")),
    }

    # 주문 간격 — 매수: 분→초 마이그레이션
    result["buy_interval_on"] = bool(merged.get("buy_interval_on", False))
    if "buy_interval_sec" in flat:
        _v = merged.get("buy_interval_sec")
        result["buy_interval_sec"] = int(_v if _v is not None else 30)
    elif "buy_interval_min" in flat:
        _legacy = merged.get("buy_interval_min")
        result["buy_interval_sec"] = int(_legacy) * 60 if _legacy is not None and str(_legacy).strip() != "" else 30
    else:
        result["buy_interval_sec"] = 30

    result["sell_interval_on"] = bool(merged.get("sell_interval_on", False))
    _v = merged.get("sell_interval_sec")
    result["sell_interval_sec"] = int(_v if _v is not None else 30)

    return result


def _build_boost_settings(merged: dict) -> dict:
    """매수 가산점 설정."""
    _v = merged.get("boost_high_breakout_score")
    boost_high_breakout_score = max(float(_v if _v is not None else 1.0), 0)
    _legacy_side = merged.get("boost_order_ratio_side")
    _v = merged.get("boost_order_ratio_pct")
    _raw_pct = int(float(_v if _v is not None else 20))
    if _legacy_side is not None:
        _side = str(_legacy_side).strip().lower()
        _abs = abs(_raw_pct)
        _raw_pct = -_abs if _side == "sell" else _abs
    _v = merged.get("boost_order_ratio_score")
    boost_order_ratio_score = max(float(_v if _v is not None else 1.0), 0)
    _v = merged.get("boost_program_net_buy_score")
    boost_program_net_buy_score = max(float(_v if _v is not None else 1.0), 0)
    # ── 4. 뉴스 호재 가산점 (NWS) ──
    _v = merged.get("boost_news_score")
    boost_news_score = max(float(_v if _v is not None else 1.0), 0)
    _v = merged.get("news_boost_ttl_sec")
    news_boost_ttl_sec = int(_v if _v is not None else 300)
    news_keywords = str(merged.get("news_keywords", "") or "")
    return {
        "boost_high_breakout_on": bool(merged.get("boost_high_breakout_on")),
        "boost_high_breakout_score": boost_high_breakout_score,
        "boost_order_ratio_on": bool(merged.get("boost_order_ratio_on")),
        "boost_order_ratio_pct": max(-100, min(100, _raw_pct)),
        "boost_order_ratio_score": boost_order_ratio_score,
        "boost_program_net_buy_on": bool(merged.get("boost_program_net_buy_on")),
        "boost_program_net_buy_score": boost_program_net_buy_score,
        "boost_news_on": bool(merged.get("boost_news_on")),
        "boost_news_score": boost_news_score,
        "news_boost_ttl_sec": news_boost_ttl_sec,
        "news_keywords": news_keywords,
    }


def _normalize_broker_config(settings: dict) -> dict:
    """브로커 기능별 매핑 (기본값: 동일 브로커 사용)."""
    broker = settings.get("broker", "kiwoom")
    return {
        "websocket": broker,
        "order": broker,
        "sector": broker,
        "auth": broker,
    }


def _build_misc_settings(merged: dict) -> dict:
    """확정 시세 다운로드 시간, 스케줄러 토글, 가상 예수금, broker_config, broker_specs."""
    _v = merged.get("test_virtual_deposit")
    test_virtual_deposit = int(_v) if _v is not None else 10_000_000
    _v = merged.get("test_virtual_balance")
    test_virtual_balance = int(_v) if _v is not None else 10_000_000
    _v = merged.get("confirmed_data_broker")
    confirmed_data_broker = str(_v if _v is not None else "").strip()
    result = {
        "timetable.confirmed_download": str(merged.get("timetable.confirmed_download", "20:40"))[:5],
        "scheduler_market_close_on": bool(merged.get("scheduler_market_close_on", True)),
        "scheduler_5d_download_on": bool(merged.get("scheduler_5d_download_on", True)),
        "quote_auto_subscribe": bool(merged.get("quote_auto_subscribe")),
        "confirmed_data_broker": confirmed_data_broker,
        "test_virtual_deposit": test_virtual_deposit,
        "test_virtual_balance": test_virtual_balance,
        "broker_config": _normalize_broker_config(merged),
    }
    if "_broker_specs" in merged:
        result["_broker_specs"] = merged["_broker_specs"]
    return result


def build_engine_settings_dict(flat: dict) -> dict:
    """flat 설정 딕셔너리로부터 복호화 및 타입 캐스팅 가공 처리가 완료된 엔진 설정을 빌드합니다."""
    merged = {**DEFAULT_USER_SETTINGS, **flat}
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
