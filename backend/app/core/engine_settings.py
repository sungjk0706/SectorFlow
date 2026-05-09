# -*- coding: utf-8 -*-
"""
엔진 전용 설정 로더 -- 로컬 settings.json 파일에서 읽어 복호화 후 반환.

포함: 브로커 자격·스케줄·매수 전략 필드 -- 디스크에 있는 영속 설정.
미포함: 레이더/대기 큐 -- engine_service 메모리·WebSocket 전용(휘발성).
"""
from app.core.settings_file import load_settings
from app.core.encryption import decrypt_value
from app.core.trade_mode import effective_trade_mode


async def get_engine_settings(user_id: str = None, profile: str = "default") -> dict:
    """
    data/settings.json 로드 후 복호화 dict 반환 (단일 파일).
    user_id / profile 인자는 호환용으로 무시됨.
    """
    flat = load_settings()

    def _dec(v) -> str:
        if not v:
            return ""
        s = str(v)
        if s.startswith("gAAAA"):
            return decrypt_value(s) or ""
        return s

    tm = effective_trade_mode(flat)
    _is_test = tm == "test"

    def _pick_kiwoom_cred(mode: str) -> tuple[str, str, str]:
        """mode: test | real -- real 키 우선, 없으면 레거시 kiwoom_* 단일 필드."""
        k = _dec(flat.get("kiwoom_app_key_real")) or _dec(flat.get("kiwoom_app_key"))
        s = _dec(flat.get("kiwoom_app_secret_real")) or _dec(flat.get("kiwoom_app_secret"))
        a = str(flat.get("kiwoom_account_no_real") or flat.get("kiwoom_account_no") or "").strip()
        return k, s, a

    k_woom, s_woom, acnt_woom = _pick_kiwoom_cred(tm)

    result: dict = {
        # 운영 설정
        "broker":               flat.get("broker", "kiwoom"),
        "trade_mode":           tm,
        "mode_real":            tm == "real",
        "time_scheduler_on":    bool(flat.get("time_scheduler_on", False)),
        # 헤더 상태칩/자동매매 유효성 판정에서 직접 사용
        "auto_buy_on":          bool(flat.get("auto_buy_on", True)),
        "auto_sell_on":         bool(flat.get("auto_sell_on", True)),
        "buy_time_start":       str(flat.get("buy_time_start", "09:00"))[:5],
        "buy_time_end":         str(flat.get("buy_time_end", "15:20"))[:5],
        "sell_time_start":      str(flat.get("sell_time_start", "09:00"))[:5],
        "sell_time_end":        str(flat.get("sell_time_end", "15:20"))[:5],
        # WS 구독 스케줄러
        "ws_subscribe_start":   str(flat.get("ws_subscribe_start", "07:50"))[:5],
        "ws_subscribe_end":     str(flat.get("ws_subscribe_end", "20:00"))[:5],
        # 매수 설정 (엔진 내부 필드명)
        "buy_amount":           int(flat.get("buy_amt", 0) or 0),
        "max_stock_count":      int(flat.get("max_stock_cnt", 5) or 5),
        # 매도/손절/트레일링 (엔진 내부 필드명)
        "loss_cut_apply":       bool(flat.get("loss_apply", False)),
        "loss_cut_value":       float(flat.get("loss_val", 0) or 0),
        "trailing_stop_apply":  bool(flat.get("ts_apply", False)),
        "trailing_start_value": float(flat.get("ts_start_val", 0) or 0),
        "trailing_drop_value":  float(flat.get("ts_drop_val", 0) or 0),
        "sell_price_type":      flat.get("sell_price_type", "mkt"),
        "sell_offset":          int(flat.get("sell_offset", 0) or 0),
        "sell_qty_type":        flat.get("sell_qty_type", "%"),
        "sell_custom_qty":      int(flat.get("sell_custom_qty", 0) or 0),
        # 리스크
        "rate_limit_per_sec":   int(flat.get("rate_limit_per_sec", 3) or 3),
        "max_position_size":    int(flat.get("max_position_size") or 0),
        # 텔레그램 (복호화)
        "tele_on":              bool(flat.get("tele_on", False)),
        "telegram_on":          bool(flat.get("tele_on", False)),
        "telegram_bot_token":   _dec(flat.get("telegram_bot_token")),
        "telegram_chat_id":     flat.get("telegram_chat_id"),
        # 키움 자격증명 -- trade_mode에 맞는 키·계좌(모드별 필드 없으면 레거시 단일 필드)
        "kiwoom_app_key":       k_woom,
        "kiwoom_app_secret":    s_woom,
        "kiwoom_account_no":    acnt_woom,
        # UI 표시용 _real 키 (마스킹 상태 유지)
        "kiwoom_app_key_real":    flat.get("kiwoom_app_key_real") or "",
        "kiwoom_app_secret_real": flat.get("kiwoom_app_secret_real") or "",
        "kiwoom_account_no_real": str(flat.get("kiwoom_account_no_real") or "").strip(),
        "test_mode":            _is_test,
        "kiwoom_mock_mode":     _is_test,   # 하위 호환
    }
    # logic_auto_trade / AutoTradeManager 호환 키 (flat 필드명 그대로)
    # _to_trade_settings()가 flat 키를 직접 참조하므로 반드시 원본 키명으로 포함해야 한다.
    result["buy_amt"] = int(flat.get("buy_amt", 0) or 0)
    result["max_daily_total_buy_amt"] = int(flat.get("max_daily_total_buy_amt", 0) or 0)
    result["max_stock_cnt"] = int(flat.get("max_stock_cnt", 5) or 5)
    result["tp_val"] = float(flat.get("tp_val") or 0)
    result["tp_apply"] = bool(flat.get("tp_apply", True))
    result["loss_apply"] = bool(flat.get("loss_apply", False))
    result["loss_val"] = float(flat.get("loss_val", 0) or 0)
    result["ts_apply"] = bool(flat.get("ts_apply", False))
    result["ts_start_val"] = float(flat.get("ts_start_val", 0) or 0)
    result["ts_drop_val"] = float(flat.get("ts_drop_val", 0) or 0)
    result["sell_per_symbol"] = flat.get("sell_per_symbol") or {}

    # ── 섹터 매수가드 설정 (매수설정 카드 ↔ 엔진 동기화) ────────
    result["sector_sort_keys"]            = flat.get("sector_sort_keys") or ["change_rate", "trade_amount", "strength"]
    # 기존 설정에서 foreign_net / institution_net 제거 마이그레이션
    result["sector_sort_keys"] = [k for k in result["sector_sort_keys"] if k not in ("foreign_net", "institution_net")]
    result["sector_rank_primary"]         = str(flat.get("sector_rank_primary") or "rise_ratio")
    result["sector_weights"]              = flat.get("sector_weights") or {"total_trade_amount": 0.5, "rise_ratio": 0.5}
    result["sector_max_targets"]          = int(flat.get("sector_max_targets", 3) or 3)
    result["sector_min_rise_ratio_pct"]   = float(flat.get("sector_min_rise_ratio_pct", 60.0) or 60.0)
    result["sector_min_trade_amt"]        = float(flat.get("sector_min_trade_amt", 0.0) or 0.0)
    result["buy_block_rise_pct"]          = float(flat.get("buy_block_rise_pct") if flat.get("buy_block_rise_pct") is not None else 7.0)
    result["buy_block_fall_pct"]          = float(flat.get("buy_block_fall_pct") if flat.get("buy_block_fall_pct") is not None else 7.0)
    result["buy_min_strength"]            = float(flat.get("buy_min_strength") if flat.get("buy_min_strength") is not None else 0)
    result["buy_index_guard_kospi_on"]    = bool(flat.get("buy_index_guard_kospi_on", False))
    result["buy_index_guard_kosdaq_on"]   = bool(flat.get("buy_index_guard_kosdaq_on", False))
    result["buy_index_kospi_drop"]        = float(flat.get("buy_index_kospi_drop") if flat.get("buy_index_kospi_drop") is not None else 2.0)
    result["buy_index_kosdaq_drop"]       = float(flat.get("buy_index_kosdaq_drop") if flat.get("buy_index_kosdaq_drop") is not None else 2.0)
    # 업종 내 종목 트리밍 비율 (%)
    result["sector_trim_trade_amt_pct"]    = float(flat.get("sector_trim_trade_amt_pct") if flat.get("sector_trim_trade_amt_pct") is not None else 10.0)
    result["sector_trim_change_rate_pct"]  = float(flat.get("sector_trim_change_rate_pct") if flat.get("sector_trim_change_rate_pct") is not None else 10.0)

    # ── 매수 가산점 설정 ────────
    # 5일 전고가 돌파 가산점
    result["boost_high_breakout_on"]       = bool(flat.get("boost_high_breakout_on", False))
    result["boost_high_breakout_score"]    = max(float(flat.get("boost_high_breakout_score") if flat.get("boost_high_breakout_score") is not None else 1.0), 0)
    # 잔량비율 가산점
    result["boost_order_ratio_on"]         = bool(flat.get("boost_order_ratio_on", False))
    # 레거시 마이그레이션: boost_order_ratio_side 키가 존재하면 부호 변환
    _legacy_side = flat.get("boost_order_ratio_side")
    _raw_pct = int(float(flat.get("boost_order_ratio_pct") if flat.get("boost_order_ratio_pct") is not None else 20))
    if _legacy_side is not None:
        _side = str(_legacy_side).strip().lower()
        _abs = abs(_raw_pct)
        _raw_pct = -_abs if _side == "sell" else _abs
    result["boost_order_ratio_pct"]        = max(-100, min(100, _raw_pct))
    # boost_order_ratio_side는 result에 포함하지 않음
    result["boost_order_ratio_score"]      = max(float(flat.get("boost_order_ratio_score") if flat.get("boost_order_ratio_score") is not None else 1.0), 0)
    # ── 공휴일 자동매매 가드 ────────
    result["holiday_guard_on"]             = bool(flat.get("holiday_guard_on", True))

    # ── WS 구독 마스터 스위치 ────────
    result["ws_subscribe_on"]              = bool(flat.get("ws_subscribe_on", True))

    # ── 장마감 후 스케줄러 토글 ────────
    result["scheduler_market_close_on"]    = bool(flat.get("scheduler_market_close_on", True))
    result["scheduler_5d_download_on"]     = bool(flat.get("scheduler_5d_download_on", True))

    # ── 장마감 후 지수 폴링 스위치 ────────
    result["index_poll_after_close"]       = bool(flat.get("index_poll_after_close", False))

    # ── WS 구독 자동 스위치 ────────
    result["index_auto_subscribe"]         = bool(flat.get("index_auto_subscribe", True))
    result["quote_auto_subscribe"]         = bool(flat.get("quote_auto_subscribe", False))

    # ── 테스트모드 가상 예수금 ────────
    result["test_virtual_deposit"]         = int(flat.get("test_virtual_deposit", 10_000_000) or 0)
    result["test_virtual_balance"]         = int(flat.get("test_virtual_balance", 10_000_000) or 0)

    # ── 브로커 기능별 매핑 (단일 브로커로 강제 동기화) ────────
    def _normalize_broker_config(settings: dict) -> dict:
        broker = settings.get("broker", "kiwoom")
        return {
            "websocket": broker,
            "order": broker,
            "account": broker,
            "sector": broker,
            "auth": broker,
        }

    result["broker_config"] = _normalize_broker_config(flat)

    return result
