# -*- coding: utf-8 -*-
"""
엔진 전용 설정 로더 -- SQLite integrated_system_settings 테이블에서 읽어 복호화 후 반환.

포함: 브로커 자격·스케줄·매수 전략 필드 -- 디스크에 있는 영속 설정.
미포함: 레이더/대기 큐 -- engine_service 메모리·WebSocket 전용(휘발성).
"""
from backend.app.core.settings_file import load_integrated_system_settings
from backend.app.core.encryption import decrypt_value
from backend.app.core.trade_mode import effective_trade_mode
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS


async def get_engine_settings(user_id: str | None = None, profile: str = "default") -> dict:
    """
    SQLite integrated_system_settings 테이블 로드 후 복호화 dict 반환.
    user_id / profile 인자는 호환용으로 무시됨.
    """
    flat = await load_integrated_system_settings()
    return build_engine_settings_dict(flat)


def build_engine_settings_dict(flat: dict) -> dict:
    """flat 설정 딕셔너리로부터 복호화 및 타입 캐스팅 가공 처리가 완료된 엔진 설정을 빌드합니다."""
    def _dec(v) -> str:
        if not v:
            return ""
        s = str(v)
        if s.startswith("gAAAA"):
            return decrypt_value(s) or ""
        return s

    # 단일 소스 진리: DEFAULT_USER_SETTINGS를 기본값으로 사용
    merged = {**DEFAULT_USER_SETTINGS, **flat}

    tm = effective_trade_mode(merged)

    def _pick_kiwoom_cred(mode: str) -> tuple[str, str, str]:
        """mode: test | real -- real 키 우선, 없으면 레거시 kiwoom_* 단일 필드."""
        k = _dec(merged.get("kiwoom_app_key_real")) or _dec(merged.get("kiwoom_app_key"))
        s = _dec(merged.get("kiwoom_app_secret_real")) or _dec(merged.get("kiwoom_app_secret"))
        a = str(merged.get("kiwoom_account_no_real") or merged.get("kiwoom_account_no") or "").strip()
        return k, s, a

    k_woom, s_woom, acnt_woom = _pick_kiwoom_cred(tm)

    result: dict = {
        # 운영 설정
        "broker":               merged.get("broker", "kiwoom"),
        "trade_mode":           tm,
        "time_scheduler_on":    bool(merged.get("time_scheduler_on")),
        # 헤더 상태칩/자동매매 유효성 판정에서 직접 사용
        "auto_buy_on":          bool(merged.get("auto_buy_on")),
        "auto_sell_on":         bool(merged.get("auto_sell_on")),
        "buy_time_start":       str(merged["buy_time_start"])[:5],
        "buy_time_end":         str(merged["buy_time_end"])[:5],
        "sell_time_start":      str(merged["sell_time_start"])[:5],
        "sell_time_end":        str(merged["sell_time_end"])[:5],
        # WS 구독 스케줄러
        "ws_subscribe_start":   str(merged["ws_subscribe_start"])[:5],
        "ws_subscribe_end":     str(merged["ws_subscribe_end"])[:5],
        # 매수 설정 (엔진 내부 필드명)
        "buy_amount":           int(merged.get("buy_amt", 0) or 0),
        "max_stock_count":      int(merged.get("max_stock_cnt", 5) or 5),
        # 매도/손절/트레일링 (엔진 내부 필드명)
        "loss_cut_apply":       bool(merged.get("loss_apply")),
        "loss_cut_value":       float(merged.get("loss_val", 0) or 0),
        "trailing_stop_apply":  bool(merged.get("ts_apply")),
        "trailing_start_value": float(merged.get("ts_start_val", 0) or 0),
        "trailing_drop_value":  float(merged.get("ts_drop_val", 0) or 0),
        "sell_price_type":      merged.get("sell_price_type", "mkt"),
        "sell_offset":          int(merged.get("sell_offset", 0) or 0),
        "sell_qty_type":        merged.get("sell_qty_type", "%"),
        "sell_custom_qty":      int(merged.get("sell_custom_qty", 0) or 0),
        # 리스크
        "rate_limit_per_sec":   int(merged.get("rate_limit_per_sec", 3) or 3),
        "max_position_size":    (lambda raw: 0 if raw is None or raw == "None" or raw == "" else int(raw))(merged.get("max_position_size")),
        "max_daily_loss_limit": int(merged.get("max_daily_loss_limit", -500000) or -500000),
        "max_single_stock_exposure": int(merged.get("max_single_stock_exposure", 20000000) or 20000000),
        "max_total_exposure_ratio": float(merged.get("max_total_exposure_ratio", 0.95) or 0.95),
        # 텔레그램 (복호화)
        "tele_on":              bool(merged.get("tele_on")),
        "telegram_on":          bool(merged.get("tele_on")),
        "telegram_bot_token_test": _dec(merged.get("telegram_bot_token_test")),
        "telegram_bot_token_real": _dec(merged.get("telegram_bot_token_real")),
        "telegram_chat_id":     merged.get("telegram_chat_id"),
        # 키움 자격증명 -- trade_mode에 맞는 키·계좌(모드별 필드 없으면 레거시 단일 필드)
        "kiwoom_app_key":       k_woom,
        "kiwoom_app_secret":    s_woom,
        "kiwoom_account_no":    acnt_woom,
        # UI 표시용 _real 키 (마스킹 상태 유지)
        "kiwoom_app_key_real":    merged.get("kiwoom_app_key_real") or "",
        "kiwoom_app_secret_real": merged.get("kiwoom_app_secret_real") or "",
        "kiwoom_account_no_real": str(merged.get("kiwoom_account_no_real") or "").strip(),
    }

    # 모든 증권사 API 키/시크릿/계좌번호 동적 수집 및 복호화 (real 키 우선)
    broker_names = {k.split("_")[0] for k in merged if k.endswith("_app_key") or k.endswith("_app_key_real")}
    for b_name in broker_names:
        if b_name == "kiwoom":
            continue
        k = _dec(merged.get(f"{b_name}_app_key_real")) or _dec(merged.get(f"{b_name}_app_key"))
        s = _dec(merged.get(f"{b_name}_app_secret_real")) or _dec(merged.get(f"{b_name}_app_secret"))
        a = str(merged.get(f"{b_name}_account_no_real") or merged.get(f"{b_name}_account_no") or "").strip()
        result[f"{b_name}_app_key"] = k
        result[f"{b_name}_app_secret"] = s
        result[f"{b_name}_account_no"] = a
        # UI 표시용 _real 유지
        result[f"{b_name}_app_key_real"] = merged.get(f"{b_name}_app_key_real") or ""
        result[f"{b_name}_app_secret_real"] = merged.get(f"{b_name}_app_secret_real") or ""
        result[f"{b_name}_account_no_real"] = str(merged.get(f"{b_name}_account_no_real") or "").strip()
    # logic_auto_trade / AutoTradeManager 호환 키 (merged 필드명 그대로)
    # _to_trade_settings()가 merged 키를 직접 참조하므로 반드시 원본 키명으로 포함해야 한다.
    result["buy_amt"] = int(merged.get("buy_amt", 0) or 0)
    result["max_daily_total_buy_on"] = bool(merged.get("max_daily_total_buy_on", False))
    result["max_daily_total_buy_amt"] = int(merged.get("max_daily_total_buy_amt", 0) or 0)
    result["max_stock_cnt"] = int(merged.get("max_stock_cnt", 5) or 5)
    result["tp_val"] = float(merged.get("tp_val") or 0)
    result["tp_apply"] = bool(merged.get("tp_apply"))
    result["loss_apply"] = bool(merged.get("loss_apply"))
    result["loss_val"] = float(merged.get("loss_val", 0) or 0)
    result["ts_apply"] = bool(merged.get("ts_apply"))
    result["ts_start_val"] = float(merged.get("ts_start_val", 0) or 0)
    result["ts_drop_val"] = float(merged.get("ts_drop_val", 0) or 0)
    result["sell_per_symbol"] = merged.get("sell_per_symbol") or {}

    # ── 섹터 매수가드 설정 (매수설정 카드 ↔ 엔진 동기화) ────────
    result["sector_sort_keys"]            = merged.get("sector_sort_keys") or ["score"]
    # 기존 설정에서 foreign_net / institution_net 제거 마이그레이션
    result["sector_sort_keys"] = [k for k in result["sector_sort_keys"] if k not in ("foreign_net", "institution_net")]
    result["sector_rank_primary"]         = str(merged.get("sector_rank_primary") or "rise_ratio")
    result["sector_weights"]              = merged["sector_weights"]
    result["sector_max_targets"]          = int(merged.get("sector_max_targets", 3) or 3)
    result["sector_min_rise_ratio_pct"]   = float(merged.get("sector_min_rise_ratio_pct", 60.0) or 60.0)
    result["sector_min_trade_amt"]        = float(merged.get("sector_min_trade_amt", 0.0) or 0.0)
    _v = merged.get("buy_block_rise_pct")
    result["buy_block_rise_pct"]          = float(_v if _v is not None else 7.0)
    _v = merged.get("buy_block_fall_pct")
    result["buy_block_fall_pct"]          = float(_v if _v is not None else 7.0)
    _v = merged.get("buy_min_strength")
    result["buy_min_strength"]            = float(_v if _v is not None else 0)
    # 업종 내 종목 트리밍 비율 (%)
    _v = merged.get("sector_trim_trade_amt_pct")
    result["sector_trim_trade_amt_pct"]    = float(_v if _v is not None else 10.0)
    _v = merged.get("sector_trim_change_rate_pct")
    result["sector_trim_change_rate_pct"]  = float(_v if _v is not None else 10.0)
    _v = merged.get("sector_start_threshold_pct")
    result["sector_start_threshold_pct"]   = float(_v if _v is not None else 70.0)

    # ── 매수 주문 간격 (1순위 종목만 매수 후 사용자 설정 간격 대기) ────────
    result["buy_interval_on"]              = bool(merged.get("buy_interval_on", False))
    result["buy_interval_min"]             = int(merged.get("buy_interval_min", 0) or 0)

    # ── 매수 가산점 설정 ────────
    # 5일 전고가 돌파 가산점
    result["boost_high_breakout_on"]       = bool(merged.get("boost_high_breakout_on"))
    _v = merged.get("boost_high_breakout_score")
    result["boost_high_breakout_score"]    = max(float(_v if _v is not None else 1.0), 0)
    # 잔량비율 가산점
    result["boost_order_ratio_on"]         = bool(merged.get("boost_order_ratio_on"))
    # 레거시 마이그레이션: boost_order_ratio_side 키가 존재하면 부호 변환
    _legacy_side = merged.get("boost_order_ratio_side")
    _v = merged.get("boost_order_ratio_pct")
    _raw_pct = int(float(_v if _v is not None else 20))
    if _legacy_side is not None:
        _side = str(_legacy_side).strip().lower()
        _abs = abs(_raw_pct)
        _raw_pct = -_abs if _side == "sell" else _abs
    result["boost_order_ratio_pct"]        = max(-100, min(100, _raw_pct))
    # boost_order_ratio_side는 result에 포함하지 않음
    _v = merged.get("boost_order_ratio_score")
    result["boost_order_ratio_score"]      = max(float(_v if _v is not None else 1.0), 0)
    # 프로그램 순매수 가산점
    result["boost_program_net_buy_on"]     = bool(merged.get("boost_program_net_buy_on"))
    _v = merged.get("boost_program_net_buy_score")
    result["boost_program_net_buy_score"]  = max(float(_v if _v is not None else 1.0), 0)
    # 거래대금 순위 가산점
    result["boost_trade_amount_rank_on"]   = bool(merged.get("boost_trade_amount_rank_on"))
    _v = merged.get("boost_trade_amount_rank_score")
    result["boost_trade_amount_rank_score"] = max(float(_v if _v is not None else 1.0), 0)
    # ── 공휴일 자동매매 가드 ────────
    result["holiday_guard_on"]             = bool(merged.get("holiday_guard_on"))
    result["auto_off_by_holiday"]          = bool(merged.get("auto_off_by_holiday"))

    # ── WS 구독 마스터 스위치 ────────
    result["ws_subscribe_on"]              = bool(merged.get("ws_subscribe_on"))
    result["confirmed_download_time"]      = str(merged.get("confirmed_download_time", "20:40"))[:5]

    # ── 장마감 후 스케줄러 토글 ────────
    # DEFAULT_USER_SETTINGS 기본값: True (활성화)
    # 미설정 시 bool(None)=False로 처리되던 버그 수정 → 방어 기본값 True 명시
    result["scheduler_market_close_on"]    = bool(merged.get("scheduler_market_close_on", True))
    result["scheduler_5d_download_on"]     = bool(merged.get("scheduler_5d_download_on", True))

    # ── WS 구독 자동 스위치 ────────
    result["quote_auto_subscribe"]         = bool(merged.get("quote_auto_subscribe"))

    # ── 테스트모드 가상 예수금 ────────
    result["test_virtual_deposit"]         = int(merged.get("test_virtual_deposit", 10_000_000) or 0)
    result["test_virtual_balance"]         = int(merged.get("test_virtual_balance", 10_000_000) or 0)

    # ── 브로커 기능별 매핑 ────────
    def _normalize_broker_config(settings: dict) -> dict:
        broker = settings.get("broker", "kiwoom")
        return {
            "websocket": broker,
            "order": broker,
            "account": broker,
            "sector": broker,
            "auth": broker,
        }

    result["broker_config"] = _normalize_broker_config(merged)

    # ── broker_specs 복사 (app.py에서 미리 로드된 데이터) ────────
    if "_broker_specs" in merged:
        result["_broker_specs"] = merged["_broker_specs"]

    return result
