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
            _plain = decrypt_value(s)
            if _plain is None:
                # 복호화 실패 — 빈문자열 폴백하되 실패 사실을 로그에 명시 (P21 사용자 투명성)
                logger.warning("[설정] 복호화 실패 — 빈문자열로 폴백. cipher 앞 10자: %s...", s[:10])
                return ""
            return _plain
        return s

    # 단일 소스 진리: DEFAULT_USER_SETTINGS를 기본값으로 사용
    merged = {**DEFAULT_USER_SETTINGS, **flat}

    tm = effective_trade_mode(merged)

    def _pick_real_or_legacy(real_key: str, legacy_key: str, field_name: str) -> str:
        """real 키 우선, real 키가 None/빈값이면 레거시 폴백 (정상 마이그레이션).
        real 키가 암호문인데 복호화 실패 → 레거시 폴백 금지 + 에러 로그 (P21 사용자 투명성)."""
        _raw_real = merged.get(real_key)
        if _raw_real is not None and str(_raw_real).strip() != "":
            _dec_real = _dec(_raw_real)
            if _dec_real != "":
                return _dec_real
            # real 키 존재하지만 복호화 결과 빈문자열
            if str(_raw_real).startswith("gAAAA"):
                logger.error(
                    "[설정] %s real 키 복호화 실패 — 레거시 폴백 금지 (P21). "
                    "사용자가 real 키를 설정했으나 복호화 불가 → 인증 차단 필요.",
                    field_name,
                )
                return ""
            # real 키가 빈문자열/공백 → 레거시 폴백 (정상 마이그레이션)
        return _dec(merged.get(legacy_key))

    def _pick_kiwoom_cred(mode: str) -> tuple[str, str, str]:
        """mode: test | real -- real 키 우선, 없으면 레거시 kiwoom_* 단일 필드.
        real 키가 암호문인데 복호화 실패 → 레거시 폴백 금지 (P21)."""
        k = _pick_real_or_legacy("kiwoom_app_key_real", "kiwoom_app_key", "kiwoom_app_key")
        s = _pick_real_or_legacy("kiwoom_app_secret_real", "kiwoom_app_secret", "kiwoom_app_secret")
        _ra = merged.get("kiwoom_account_no_real")
        a = str(_ra).strip() if _ra is not None and str(_ra).strip() != "" else str(merged.get("kiwoom_account_no") or "").strip()
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
        # 매수 설정 (엔진 내부 필드명) — 값은 merged(기본값 포함), _on 마이그레이션은 flat 기반
        # P20: 0도 유효값이므로 or 폴백 금지 — dict 블록 뒤에서 _v if _v is not None else 기본값 패턴으로 처리
        # 매도/손절/트레일링 (엔진 내부 필드명)
        "loss_cut_apply":       bool(merged.get("loss_apply")),
        "trailing_stop_apply":  bool(merged.get("ts_apply")),
        "sell_price_type":      merged.get("sell_price_type", "mkt"),
        "sell_qty_type":        merged.get("sell_qty_type", "%"),
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
        # UI 표시용 _real 키 (마스킹 상태 유지) — P20: 빈문자열도 유효값이므로 dict 블록 뒤에서 처리
    }

    # 매수 설정 (이어서) — 0도 유효값이므로 or 폴백 금지 (P20)
    _v = merged.get("buy_amt")
    result["buy_amount"] = int(_v if _v is not None else 0)
    result["buy_amount_on"] = bool(flat.get("buy_amt_on")) if "buy_amt_on" in flat else (int(_v if _v is not None else 0) > 0)
    _v = merged.get("max_stock_cnt")
    result["max_stock_count"] = int(_v if _v is not None else 5)
    result["max_stock_count_on"] = bool(flat.get("max_stock_cnt_on")) if "max_stock_cnt_on" in flat else (int(_v if _v is not None else 5) > 0)

    # 매도/손절/트레일링 (이어서) — 0도 유효값이므로 or 폴백 금지 (P20)
    _v = merged.get("loss_val")
    result["loss_cut_value"] = float(_v if _v is not None else 0)
    _v = merged.get("ts_start_val")
    result["trailing_start_value"] = float(_v if _v is not None else 0)
    _v = merged.get("ts_drop_val")
    result["trailing_drop_value"] = float(_v if _v is not None else 0)
    _v = merged.get("sell_offset")
    result["sell_offset"] = int(_v if _v is not None else 0)
    _v = merged.get("sell_custom_qty")
    result["sell_custom_qty"] = int(_v if _v is not None else 0)

    # UI 표시용 _real 키 (이어서) — 빈문자열도 유효값이므로 or 폴백 금지 (P20)
    _v = merged.get("kiwoom_app_key_real")
    result["kiwoom_app_key_real"] = _v if _v is not None else ""
    _v = merged.get("kiwoom_app_secret_real")
    result["kiwoom_app_secret_real"] = _v if _v is not None else ""
    _v = merged.get("kiwoom_account_no_real")
    result["kiwoom_account_no_real"] = str(_v if _v is not None else "").strip()

    # 리스크 (이어서) — 0도 유효값이므로 or 폴백 금지 (P20)
    # max_position_size: 0=제한 없음(유효값). None/빈문자열/"None" 문자열(레거시 DB)만 0으로 치환
    _v = merged.get("max_position_size")
    result["max_position_size"] = 0 if _v is None or _v == "None" or _v == "" else int(_v)
    _v = merged.get("max_daily_loss_limit")
    result["max_daily_loss_limit"] = int(_v if _v is not None else -500000)
    _v = merged.get("max_single_stock_exposure")
    result["max_single_stock_exposure"] = int(_v if _v is not None else 20000000)

    # 모든 증권사 API 키/시크릿/계좌번호 동적 수집 및 복호화 (real 키 우선)
    broker_names = {k.split("_")[0] for k in merged if k.endswith("_app_key") or k.endswith("_app_key_real")}
    for b_name in broker_names:
        if b_name == "kiwoom":
            continue
        k = _pick_real_or_legacy(f"{b_name}_app_key_real", f"{b_name}_app_key", f"{b_name}_app_key")
        s = _pick_real_or_legacy(f"{b_name}_app_secret_real", f"{b_name}_app_secret", f"{b_name}_app_secret")
        _ra = merged.get(f"{b_name}_account_no_real")
        a = str(_ra).strip() if _ra is not None and str(_ra).strip() != "" else str(merged.get(f"{b_name}_account_no") or "").strip()
        result[f"{b_name}_app_key"] = k
        result[f"{b_name}_app_secret"] = s
        result[f"{b_name}_account_no"] = a
        # UI 표시용 _real 유지 — 빈문자열도 유효값이므로 or 폴백 금지 (P20)
        _rv = merged.get(f"{b_name}_app_key_real")
        result[f"{b_name}_app_key_real"] = _rv if _rv is not None else ""
        _rv = merged.get(f"{b_name}_app_secret_real")
        result[f"{b_name}_app_secret_real"] = _rv if _rv is not None else ""
        _rv = merged.get(f"{b_name}_account_no_real")
        result[f"{b_name}_account_no_real"] = str(_rv if _rv is not None else "").strip()
    # logic_auto_trade / AutoTradeManager 호환 키 (merged 필드명 그대로)
    # _to_trade_settings()가 merged 키를 직접 참조하므로 반드시 원본 키명으로 포함해야 한다.
    # ── 마이그레이션: _on 키가 flat에 없으면 기존 값으로 추론 (P10 SSOT) ──
    # buy_amt_on: 기존 buy_amt > 0 → True, buy_amt = 0 → False (한도 없음)
    _v = merged.get("buy_amt")
    _buy_amt_raw = int(_v if _v is not None else 0)
    result["buy_amt_on"] = bool(flat.get("buy_amt_on")) if "buy_amt_on" in flat else (_buy_amt_raw > 0)
    result["buy_amt"] = _buy_amt_raw
    result["max_daily_total_buy_on"] = bool(merged.get("max_daily_total_buy_on", False))
    _v = merged.get("max_daily_total_buy_amt")
    result["max_daily_total_buy_amt"] = int(_v if _v is not None else 0)
    # max_stock_cnt_on: 기존 max_stock_cnt > 0 → True, = 0 → False (제한 없음)
    _msc_v = merged.get("max_stock_cnt")
    _max_stock_cnt_raw = int(_msc_v) if _msc_v is not None else 5
    result["max_stock_cnt_on"] = bool(flat.get("max_stock_cnt_on")) if "max_stock_cnt_on" in flat else (_max_stock_cnt_raw > 0)
    result["max_stock_cnt"] = _max_stock_cnt_raw
    _v = merged.get("tp_val")
    result["tp_val"] = float(_v if _v is not None else 0)
    result["tp_apply"] = bool(merged.get("tp_apply"))
    result["loss_apply"] = bool(merged.get("loss_apply"))
    _v = merged.get("loss_val")
    result["loss_val"] = float(_v if _v is not None else 0)
    result["ts_apply"] = bool(merged.get("ts_apply"))
    _v = merged.get("ts_start_val")
    result["ts_start_val"] = float(_v if _v is not None else 0)
    _v = merged.get("ts_drop_val")
    result["ts_drop_val"] = float(_v if _v is not None else 0)
    _v = merged.get("sell_per_symbol")
    result["sell_per_symbol"] = _v if _v is not None else {}

    # ── 업종 매수가드 설정 (매수설정 카드 ↔ 엔진 동기화) ────────
    _v = merged.get("sector_sort_keys")
    result["sector_sort_keys"]            = _v if _v is not None else ["score"]
    # 기존 설정에서 foreign_net / institution_net 제거 마이그레이션
    result["sector_sort_keys"] = [k for k in result["sector_sort_keys"] if k not in ("foreign_net", "institution_net")]
    result["sector_weights"]              = merged["sector_weights"]
    # sector_weights 키 정합성 검증 (P22) — total_trade_amount 키 누락 시 경고
    _sw = merged["sector_weights"]
    if isinstance(_sw, dict) and "total_trade_amount" not in _sw:
        logger.warning("[설정] sector_weights에 total_trade_amount 키 없음: %s — 마이그레이션 누락 가능", _sw)
    _v = merged.get("sector_max_targets")
    result["sector_max_targets"]          = int(_v if _v is not None else 3)
    _v = merged.get("sector_min_rise_ratio_pct")
    result["sector_min_rise_ratio_pct"]   = float(_v if _v is not None else 60.0)
    _v = merged.get("sector_min_trade_amt")
    result["sector_min_trade_amt"]        = float(_v if _v is not None else 0.0)
    # ── 매수 차단 토글 (_on 키 마이그레이션: flat에 없으면 기존 값 > 0 → True) ──
    _v = flat.get("buy_block_rise_pct")
    _rise_pct = float(_v) if _v is not None else 7.0
    result["buy_block_rise_on"]           = bool(flat.get("buy_block_rise_on")) if "buy_block_rise_on" in flat else (_rise_pct > 0)
    result["buy_block_rise_pct"]          = _rise_pct
    _v = flat.get("buy_block_fall_pct")
    _fall_pct = float(_v) if _v is not None else 7.0
    result["buy_block_fall_on"]           = bool(flat.get("buy_block_fall_on")) if "buy_block_fall_on" in flat else (_fall_pct > 0)
    result["buy_block_fall_pct"]          = _fall_pct
    _v = flat.get("buy_min_strength")
    _strength = float(_v) if _v is not None else 0
    result["buy_block_strength_on"]       = bool(flat.get("buy_block_strength_on")) if "buy_block_strength_on" in flat else (_strength > 0)
    result["buy_min_strength"]            = _strength
    # 업종 내 종목 트리밍 비율 (%)
    _v = merged.get("sector_trim_trade_amt_pct")
    result["sector_trim_trade_amt_pct"]    = float(_v if _v is not None else 10.0)
    _v = merged.get("sector_trim_change_rate_pct")
    result["sector_trim_change_rate_pct"]  = float(_v if _v is not None else 10.0)
    _v = merged.get("sector_start_threshold_pct")
    result["sector_start_threshold_pct"]   = float(_v if _v is not None else 70.0)

    # ── 매수 주문 간격 (1순위 종목만 매수 후 사용자 설정 간격 대기) ────────
    result["buy_interval_on"]              = bool(merged.get("buy_interval_on", False))
    _v = merged.get("buy_interval_min")
    result["buy_interval_min"]             = int(_v if _v is not None else 0)

    # ── 재매수 차단 (보유/금일매수 종목 매수 허용 여부 + 차단 기간) ────────
    result["rebuy_block_on"]               = bool(merged.get("rebuy_block_on", True))
    result["rebuy_block_period"]           = str(merged.get("rebuy_block_period", "today"))

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

    # ── 확정 데이터 브로커 ────────
    # _get_all_tokens_async가 토큰 발급 대상 증권사를 수집할 때 사용.
    # build_engine_settings_dict 결과에 포함하지 않으면 캐시에서 사라져
    # 주 사용 증권사와 다른 확정 데이터 브로커의 토큰이 발급되지 않음 (P10 SSOT).
    # P20: 빈문자열도 유효값이므로 or 폴백 금지
    _v = merged.get("confirmed_data_broker")
    result["confirmed_data_broker"]        = str(_v if _v is not None else "").strip()

    # ── 테스트모드 가상 예수금 ────────
    # P20: None → 기본값 10_000_000, 0 → 0 (유효값)
    _v = merged.get("test_virtual_deposit")
    result["test_virtual_deposit"]         = int(_v) if _v is not None else 10_000_000
    _v = merged.get("test_virtual_balance")
    result["test_virtual_balance"]         = int(_v) if _v is not None else 10_000_000

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
