# -*- coding: utf-8 -*-
"""
계좌/잔고 관련 모듈
- 계좌 스냅샷
- 잔고 관리
- REST 계좌 데이터 조회
- 브로드캐스트
"""
import asyncio
import sys
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode

logger = get_logger("engine_account")


# ── engine_service 모듈 상태 접근 ─────────────────────────────────────────

def _get_es_module():
    """engine_service 모듈 참조 반환 (순환 참조 방지)."""
    return sys.modules.get("backend.app.services.engine_service")


# ── 계좌 스냅샷/잔고 조회 ─────────────────────────────────────────────────

async def get_account_snapshot() -> dict:
    """계좌 스냅샷 반환."""
    from backend.app.services import settlement_engine
    
    es = _get_es_module()
    if not es:
        return {}
    
    _shared_lock = getattr(es, "_shared_lock", None)
    _account_snapshot = getattr(es, "_account_snapshot", {})
    _settings_cache = getattr(es, "_settings_cache", {})
    
    async with _shared_lock:
        snap = dict(_account_snapshot)
    
    if not snap or "trade_mode" not in snap:
        _is_test = is_test_mode(_settings_cache)
        snap.setdefault("trade_mode", "test" if _is_test else "real")
        if _is_test:
            snap.setdefault("accumulated_investment", settlement_engine.get_accumulated_investment())
            snap.setdefault("orderable", settlement_engine.get_orderable())
            snap.setdefault("initial_deposit", settlement_engine.get_accumulated_investment())
        for k in ("total_buy", "total_eval", "total_pnl",
                   "total_buy_amount", "total_eval_amount"):
            snap.setdefault(k, 0)
        for k in ("total_rate", "total_pnl_rate"):
            snap.setdefault(k, 0.0)
        snap.setdefault("position_count", 0)
    return snap


def get_trade_mode() -> str:
    """거래 모드 반환."""
    es = _get_es_module()
    if not es:
        return "real"
    _settings_cache = getattr(es, "_settings_cache", {})
    return "test" if is_test_mode(_settings_cache) else "real"


async def get_positions() -> list:
    """보유 종목 목록 반환."""
    from backend.app.services import dry_run
    
    es = _get_es_module()
    if not es:
        return []
    
    _shared_lock = getattr(es, "_shared_lock", None)
    _positions = getattr(es, "_positions", [])
    _settings_cache = getattr(es, "_settings_cache", {})
    
    if is_test_mode(_settings_cache):
        return await dry_run.get_positions()
    async with _shared_lock:
        return list(_positions)


async def get_total_buy_amount() -> int:
    """총 매입금액 반환."""
    from backend.app.services import dry_run

    es = _get_es_module()
    if not es:
        return 0

    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _settings_cache = getattr(es, "_settings_cache", {})

    if is_test_mode(_settings_cache):
        return sum(int(p.get("buy_amt", 0) or 0) for p in await dry_run.get_positions())
    return int(_broker_rest_totals.get("total_buy", 0) or 0)


async def get_total_eval_amount() -> int:
    """총 평가금액 반환."""
    from backend.app.services import dry_run

    es = _get_es_module()
    if not es:
        return 0

    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _settings_cache = getattr(es, "_settings_cache", {})

    if is_test_mode(_settings_cache):
        return sum(int(p.get("eval_amt", 0) or 0) for p in await dry_run.get_positions())
    return int(_broker_rest_totals.get("total_eval", 0) or 0)


async def get_total_pnl() -> int:
    """총 손익 반환."""
    from backend.app.services import dry_run

    es = _get_es_module()
    if not es:
        return 0

    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _settings_cache = getattr(es, "_settings_cache", {})

    if is_test_mode(_settings_cache):
        return sum(int(p.get("pnl_amount", 0) or 0) for p in await dry_run.get_positions())
    return int(_broker_rest_totals.get("total_pnl", 0) or 0)


def get_total_pnl_rate() -> float:
    """총 수익률 반환."""
    es = _get_es_module()
    if not es:
        return 0.0
    
    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _settings_cache = getattr(es, "_settings_cache", {})
    
    if is_test_mode(_settings_cache):
        total_buy = get_total_buy_amount()
        total_pnl = get_total_pnl()
        return round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0
    return float(_broker_rest_totals.get("total_rate", 0.0) or 0.0)


def get_snapshot_history() -> list:
    """스냅샷 이력 반환."""
    es = _get_es_module()
    if not es:
        return []
    _snapshot_history = getattr(es, "_snapshot_history", [])
    return list(_snapshot_history)


async def get_buy_limit_status() -> dict:
    """매수 한도 상태를 dict로 반환 (프론트 배지용)."""
    es = _get_es_module()
    if not es:
        return {"daily_buy_spent": 0}
    
    _settings_cache = getattr(es, "_settings_cache", {})
    _auto_trade = getattr(es, "_auto_trade", None)
    
    settings = _settings_cache or {}
    daily_buy_spent = 0
    if _auto_trade:
        await _auto_trade._ensure_daily_buy_counter()
        daily_buy_spent = _auto_trade._daily_buy_spent
    return {"daily_buy_spent": daily_buy_spent}


async def _broadcast_buy_limit_status() -> None:
    """매수 한도 상태를 WS로 브로드캐스트."""
    es = _get_es_module()
    if not es:
        return
    
    _buy_targets_snapshot_cache = getattr(es, "_buy_targets_snapshot_cache", None)
    _buy_targets_snapshot_cache = None  # 일일한도 상태 변경 → 매수후보 캐시 무효화
    setattr(es, "_buy_targets_snapshot_cache", _buy_targets_snapshot_cache)
    
    try:
        from backend.app.services.engine_account_notify import _broadcast, notify_buy_targets_update
        _broadcast("buy-limit-status", await get_buy_limit_status())
        notify_buy_targets_update()
    except Exception as e:
        logger.warning("[연결] 매수한도 화면전송 실패: %s", e, exc_info=True)


# ── REST 계좌 데이터 조회 ─────────────────────────────────────────────────

async def _fetch_account_data(settings: dict) -> dict:
    """
    브로커 REST API로 실계좌 잔고/평가 조회.
    - 영속 _rest_api 인스턴스를 재사용해 토큰 중복 발급 방지
    - 토큰 없으면 즉시 실패 반환 (0원 stub 금지)
    - deposit -> balance 순차 호출 + 0.5초 간격으로 429 예방
    """
    from backend.app.services.engine_account_rest import parse_kt00001_deposit, parse_kt00018_balance
    
    es = _get_es_module()
    if not es:
        return {"success": False, "summary": {}, "stock_list": []}
    
    _EMPTY = {"success": False, "summary": {}, "stock_list": []}
    _rest_api = getattr(es, "_rest_api", None)
    _get_rest_api_thread_sem = getattr(es, "_get_rest_api_thread_sem", None)
    
    if _rest_api is None:
        logger.warning("[계좌] _rest_api 없음 -- 엔진 기동 완료 전 호출. 계좌 조회 건너뜀.")
        return _EMPTY

    # ── 토큰 유효성 먼저 확인 ─────────────────────────────────────────────
    async with _get_rest_api_thread_sem():
        token_ok = await _rest_api._ensure_token()
    if not token_ok:
        logger.warning(
            "[계좌] 유효한 토큰 없음 (au10001 발급 실패) -- 계좌 조회 건너뜀. "
            "이전 값을 그대로 유지합니다. (0원 표시 방지)"
        )
        return _EMPTY

    token_preview = (_rest_api._token_info.token[:10] + "...") if _rest_api._token_info else "?"
    logger.info("[계좌] 토큰 유효 확인 (%s) -- 계좌 조회 시작", token_preview)

    acnt_no = str(getattr(_rest_api, "_acnt_no", "") or "")

    # ── deposit -> (0.5초 대기) -> balance 순차 호출로 429 예방 ─────────────
    try:
        async with _get_rest_api_thread_sem():
            deposit_raw = await _rest_api.get_deposit_detail(acnt_no)
        await asyncio.sleep(0.5)
        async with _get_rest_api_thread_sem():
            balance_raw = await _rest_api.get_balance_detail()
    except Exception as e:
        logger.warning("[계좌] API 호출 예외: %s", e, exc_info=True)
        return _EMPTY

    if not deposit_raw:
        logger.warning("[계좌] 예수금 응답 없음 (kt00001 실패함) -- 조회 중단")
        return _EMPTY

    ok_dep, dep_body, deposit, orderable, _withdrawable = parse_kt00001_deposit(deposit_raw)
    if not ok_dep:
        logger.warning(
            "[계좌] kt00001 오류 return_code=%s 메시지=%s",
            dep_body.get("return_code"), dep_body.get("return_msg", ""),
        )
        return _EMPTY

    deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_kt00018_balance(
        balance_raw, deposit
    )

    logger.info(
        "[계좌] 조회 완료 -- 총평가 %s원 | 손익 %s원 | 매입 %s원 | 예수금 %s원 | 종목 %d개",
        f"{tot_eval:,}", f"{tot_pnl:,}", f"{tot_buy:,}", f"{deposit:,}", len(stock_list),
    )

    return {
        "success": True,
        "summary": {
            "tot_eval":     tot_eval,
            "tot_pnl":      tot_pnl,
            "tot_buy":      tot_buy,
            "deposit":      deposit,
            "orderable":    orderable,
            "total_rate":   total_rate,
        },
        "stock_list": stock_list,
        "raw_data":   dep_body,
    }


async def _update_account_memory(settings: dict) -> None:
    """
    브로커 REST(kt00001/18)로 예수금·주문가능·잔고·증권사 합계(tot_*)를 부트스트랩한다.
    합계는 포지션 합산하지 않고 API 루트 합계만 _broker_rest_totals 에 저장한다.
    Lock으로 동시 호출 직렬화 -- 기동 시 _run_snapshot_and_sell_check + _login_post_pipeline 경쟁 방지.
    """
    es = _get_es_module()
    if not es:
        return
    
    _account_snapshot = getattr(es, "_account_snapshot", {})
    _positions = getattr(es, "_positions", [])
    _snapshot_history = getattr(es, "_snapshot_history", [])
    _account_rest_bootstrapped = getattr(es, "_account_rest_bootstrapped", False)
    _get_account_rest_lock = getattr(es, "_get_account_rest_lock", None)
    
    lock = _get_account_rest_lock()
    if lock.locked():
        logger.info("[계좌] REST 조회 중복 요청 -- 선행 조회 완료까지 대기")
    async with lock:
        # lock 대기 중 선행 조회가 완료됐으면 중복 호출 스킵
        _account_rest_bootstrapped = getattr(es, "_account_rest_bootstrapped", False)
        if _account_rest_bootstrapped:
            logger.info("[계좌] REST 조회 -- 선행 조회에서 이미 완료됨, 중복 생략")
            return
        await _update_account_memory_inner(settings)


async def _update_account_memory_inner(settings: dict) -> None:
    """_update_account_memory 실제 구현 (Lock 내부에서 호출)."""
    from backend.app.services.engine_account_rest import (
        apply_last_price_to_positions_inplace,
        broker_totals_from_summary,
        build_account_snapshot_meta,
        merge_positions_from_rest,
        recalc_broker_totals_from_positions,
    )
    from backend.app.services.engine_account_notify import _rebuild_positions_cache
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    from backend.app.services import dry_run
    from backend.app.core.engine_settings import get_engine_settings
    
    es = _get_es_module()
    if not es:
        return
    
    _account_snapshot = getattr(es, "_account_snapshot", {})
    _positions = getattr(es, "_positions", [])
    _snapshot_history = getattr(es, "_snapshot_history", [])
    _account_rest_bootstrapped = getattr(es, "_account_rest_bootstrapped", False)
    _shared_lock = getattr(es, "_shared_lock", None)
    _engine_user_id = getattr(es, "_engine_user_id", "")
    _ws_live = getattr(es, "_ws_live", None)
    _sweep_unreg_subscribed_except_positions_and_tracked = getattr(es, "_sweep_unreg_subscribed_except_positions_and_tracked", None)
    _refresh_account_snapshot_meta = getattr(es, "_refresh_account_snapshot_meta", None)
    notify_desktop_account_tabs_refresh = getattr(es, "notify_desktop_account_tabs_refresh", None)
    _log = getattr(es, "_log", None)

    s = settings or {}
    broker = str(s.get("broker", "") or "").lower().strip()
    need_reload = False
    if broker:
        if not s.get(f"{broker}_app_key") or not s.get(f"{broker}_app_secret"):
            need_reload = True
    if need_reload:
        s = await get_engine_settings(_engine_user_id or None)

    yield_data = await _fetch_account_data(s)

    if not yield_data.get("success"):
        logger.warning(
            "[계좌] 조회 실패함 -- 기존 스냅샷 유지 (총평가=%s원)",
            f"{_account_snapshot.get('total_eval', 0):,}",
        )
        return

    stock_list = yield_data.get("stock_list", [])
    summary    = yield_data.get("summary", {})

    _apply_broker_totals_from_summary(summary)
    # 테스트모드: 실전 잔고로 _positions 덮어쓰지 않음 -- dry_run 가상 잔고 격리
    if is_test_mode(s):
        logger.info("[계좌] 테스트모드 -- 실전 잔고 %d건 무시, dry_run 가상 잔고 유지", len(stock_list))
    else:
        # 수량·매입은 REST 기준
        merged = _merge_positions_from_rest(stock_list)
        async with _shared_lock:
            _positions = merged
            setattr(es, "_positions", _positions)
        _rebuild_positions_cache(merged)

    _account_rest_bootstrapped = True
    setattr(es, "_account_rest_bootstrapped", _account_rest_bootstrapped)
    
    async with _shared_lock:
        _account_snapshot["broker"] = broker
        _account_snapshot["deposit"] = int(summary.get("deposit", 0) or 0)
        _account_snapshot["orderable"] = int(summary.get("orderable", 0) or 0)
        setattr(es, "_account_snapshot", _account_snapshot)

    # WS 구독 보강은 _login_post_pipeline / _run_snapshot_and_sell_check 에서 명시적으로 호출.
    # 여기서 호출하면 _account_rest_lock 안에서 _reg_seq_lock 을 잡는 중첩 락 -> 데드락 위험.
    if _ws_live and _ws_live():
        try:
            n_unreg = await _sweep_unreg_subscribed_except_positions_and_tracked()
            if n_unreg:
                logger.info(
                    "[구독정리] 잔고 반영 후 미보유·미추적 종목 구독해지 %d건 (추적 종목 제외)",
                    n_unreg,
                )
        except Exception as e:
            logger.warning("[연결] 웹소켓 실시간 구독 정리 실패함: %s", e, exc_info=True)

    if _refresh_account_snapshot_meta:
        await _refresh_account_snapshot_meta()

    if notify_desktop_account_tabs_refresh:
        notify_desktop_account_tabs_refresh()
    
    _ps = _account_snapshot.get("price_source", "?")
    _ps_kr = (
        "웹소켓(실시간)"
        if _ps == "websocket"
        else "REST초기화"
        if _ps == "rest_bootstrap"
        else str(_ps)
    )
    if _log:
        _log(
            f"[계좌] 갱신 완료 -- 평가금: {_account_snapshot.get('total_eval', 0):,}원 | "
            f"손익: {_account_snapshot.get('total_pnl', 0):,}원 | 포지션: {_account_snapshot.get('position_count', 0)}개 | "
            f"가격소스: {_ps_kr}"
        )


def _merge_positions_from_rest(stock_list: list) -> list:
    """
    REST kt00018 잔고 반영. 수량·매입·종목명은 REST 기준.
    change/change_rate: _pending_stock_details 캐시에서 보완 (첫 틱 전 0 표시 방지).
    """
    from backend.app.services.engine_account_rest import merge_positions_from_rest
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    
    es = _get_es_module()
    if not es:
        return stock_list

    _pending_stock_details = getattr(es, "_pending_stock_details", {})

    result = merge_positions_from_rest(stock_list, None)
    for pos in result:
        cd = _format_broker_reg_stk_cd(str(pos.get("stk_cd", "") or ""))
        if not cd:
            continue
        src = _pending_stock_details.get(cd)
        if src:
            if "change" not in pos or pos.get("change") == 0:
                pos["change"] = src.get("change", 0)
            if "change_rate" not in pos or pos.get("change_rate") == 0:
                pos["change_rate"] = src.get("change_rate", 0.0)
            if "sign" not in pos:
                pos["sign"] = src.get("sign", "3")
    return result


def _apply_broker_totals_from_summary(summary: dict) -> None:
    """REST kt00018 루트 합계 -- 실시간 이벤트에서 임의 합산하지 않고 이 값만 갱신."""
    from backend.app.services.engine_account_rest import broker_totals_from_summary
    
    es = _get_es_module()
    if not es:
        return
    
    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _broker_rest_totals = broker_totals_from_summary(summary)
    setattr(es, "_broker_rest_totals", _broker_rest_totals)


async def _refresh_account_snapshot_meta() -> None:
    """
    스냅샷 시각·보유종목수·가격소스만 갱신.
    총평가·총손익·총매입·총수익률은 _broker_rest_totals만 사용(REST kt00018 또는 REAL 04 공식 FID 932~934) -- 포지션 합산 없음.
    테스트모드: 가상 예수금을 deposit/orderable에 반영.
    """
    from backend.app.services.engine_account_rest import build_account_snapshot_meta
    from backend.app.services import dry_run, settlement_engine
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    
    es = _get_es_module()
    if not es:
        return
    
    _account_snapshot = getattr(es, "_account_snapshot", {})
    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _settings_cache = getattr(es, "_settings_cache", {})
    _positions = getattr(es, "_positions", [])
    _ws_live = getattr(es, "_ws_live", None)
    
    _is_test = is_test_mode(_settings_cache)
    pos = await dry_run.get_positions() if _is_test else _positions

    if _is_test:
        # 테스트모드: settlement_engine 누적투자금/주문가능금액 반영 + 포지션 합산으로 totals 구성
        accumulated_investment = settlement_engine.get_accumulated_investment()
        orderable = settlement_engine.get_orderable()
        total_buy = sum(int(p.get("buy_amt", 0) or 0) for p in pos)
        total_eval = sum(int(p.get("eval_amt", 0) or 0) for p in pos)
        total_pnl = total_eval - total_buy
        total_rate = round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0

        _account_snapshot["accumulated_investment"] = accumulated_investment
        _account_snapshot["orderable"] = orderable
        _account_snapshot["initial_deposit"] = accumulated_investment
        
        test_totals = {
            "total_eval": total_eval,
            "total_pnl": total_pnl,
            "total_buy": total_buy,
            "total_rate": total_rate,
        }
        snap = build_account_snapshot_meta(
            _account_snapshot, test_totals, pos, _ws_live() if _ws_live else False,
            trade_mode="test",
        )
    else:
        snap = build_account_snapshot_meta(
            _account_snapshot, _broker_rest_totals, pos, _ws_live() if _ws_live else False,
            trade_mode="real",
        )
    
    _account_snapshot = snap
    setattr(es, "_account_snapshot", _account_snapshot)


async def _apply_last_price_to_positions(stk_cd: str, price: int) -> bool:
    """실시간 체결(REAL 01) -- 체결가 반영 + 평가손익·수익률·평가금액 실시간 재계산. 보유에 반영되면 True."""
    from backend.app.services.engine_account_rest import (
        apply_last_price_to_positions_inplace,
        recalc_broker_totals_from_positions,
    )
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    from backend.app.services import dry_run
    
    es = _get_es_module()
    if not es:
        return False
    
    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _positions = getattr(es, "_positions", [])
    _settings_cache = getattr(es, "_settings_cache", {})
    
    # 테스트모드: dry_run 가상 잔고에 현재가 반영 (6자리 정규화)
    if is_test_mode(_settings_cache):
        nk = _format_broker_reg_stk_cd(str(stk_cd or "").strip())
        return await dry_run.update_price(nk, price) if nk else False
    
    hit = apply_last_price_to_positions_inplace(_positions, stk_cd, price)
    if hit:
        _broker_rest_totals = recalc_broker_totals_from_positions(_positions, _broker_rest_totals)
        setattr(es, "_broker_rest_totals", _broker_rest_totals)
    return hit


async def _apply_balance_realtime(item: dict, vals: dict) -> None:
    """
    실시간 잔고(04) -- item 필드로 계좌/종목 레코드 구분 후 처리.
    계좌 단위(item=계좌번호): FID 930~934 계좌 합계 갱신.
    종목 단위(item=종목코드): FID 930~933·950·8019·10 포지션 갱신.
    """
    from backend.app.services.engine_account_rest import (
        _real04_is_stock_item,
        real04_official_account_delta,
        real04_official_apply_position_line,
    )
    from backend.app.services.engine_account_notify import _rebuild_positions_cache
    
    es = _get_es_module()
    if not es:
        return

    _account_snapshot = getattr(es, "_account_snapshot", {})
    _broker_rest_totals = getattr(es, "_broker_rest_totals", {})
    _positions = getattr(es, "_positions", [])
    _refresh_account_snapshot_meta = getattr(es, "_refresh_account_snapshot_meta", None)
    _broadcast_account = getattr(es, "_broadcast_account", None)

    if _real04_is_stock_item(item):
        # 종목 단위 레코드 -- 보유수량·매입단가·평가손익 등 갱신
        _prev_len = len(_positions)
        real04_official_apply_position_line(item, vals, _positions, None)
        if len(_positions) != _prev_len:
            _rebuild_positions_cache(_positions)
    else:
        # 계좌 단위 레코드 -- 예수금·총평가·총손익 등 갱신
        delta = real04_official_account_delta(vals)
        if delta:
            if "deposit" in delta:
                _account_snapshot["deposit"] = int(delta["deposit"])
            if "total_eval" in delta:
                _broker_rest_totals["total_eval"] = int(delta["total_eval"])
            if "total_pnl" in delta:
                _broker_rest_totals["total_pnl"] = int(delta["total_pnl"])
            if "total_rate" in delta:
                _broker_rest_totals["total_rate"] = float(delta["total_rate"])
    
    if _refresh_account_snapshot_meta:
        await _refresh_account_snapshot_meta()
    if _broadcast_account:
        _broadcast_account(reason="balance_04")


async def _on_fill_after_ws() -> None:
    """주문체결(00) 완료 직후 -- REST 없이 메모리·매도조건만 갱신."""
    from backend.app.services.auto_trading_effective import auto_sell_effective
    from backend.app.services.engine_ws_fill_followup import run_after_order_fill_ws
    from backend.app.services import dry_run
    
    es = _get_es_module()
    if not es:
        return
    
    _settings_cache = getattr(es, "_settings_cache", {})
    _auto_trade = getattr(es, "_auto_trade", None)
    _access_token = getattr(es, "_access_token", None)
    _refresh_account_snapshot_meta = getattr(es, "_refresh_account_snapshot_meta", None)
    _broadcast_account = getattr(es, "_broadcast_account", None)

    async def _sell_if_applicable() -> None:
        if is_test_mode(_settings_cache):
            pos = await dry_run.get_positions()
        else:
            _positions = getattr(es, "_positions", [])
            pos = _positions
        if pos and _auto_trade and auto_sell_effective(_settings_cache) and _access_token:
            await _auto_trade.check_sell_conditions(pos, _settings_cache, _access_token)

    run_after_order_fill_ws(
        0.0,
        _refresh_account_snapshot_meta,
        lambda reason=None: _broadcast_account(reason=reason) if _broadcast_account else None,
        _sell_if_applicable,
        is_dry_run=is_test_mode(_settings_cache),
    )


# ── 브로드캐스트 ─────────────────────────────────────────────────────────

def _broadcast_account(reason: str | None = None) -> None:
    """데이터 갱신 후 UI/WS -- 페이로드 전송은 engine_account_notify.
    
    Phase 2 최적화: 0.5초 coalescing 적용 - 테스트모드에서 매수/매도/정산 
    빈번한 브로드캐스트를 모아서 1회만 전송하여 UI 깜빡임 감소.
    """
    from backend.app.services import dry_run
    from backend.app.services.engine_account_notify import broadcast_account_update
    
    es = _get_es_module()
    if not es:
        return
    
    _account_broadcast_pending_reason = getattr(es, "_account_broadcast_pending_reason", None)
    _account_broadcast_timer = getattr(es, "_account_broadcast_timer", None)
    _ACCOUNT_BROADCAST_COALESCE_SEC = getattr(es, "_ACCOUNT_BROADCAST_COALESCE_SEC", 0.0)
    _apply_delayed_account_broadcast = getattr(es, "_apply_delayed_account_broadcast", None)
    
    # 이유 저장 (마지막 이유만 기록)
    _account_broadcast_pending_reason = reason or "coalesced"
    setattr(es, "_account_broadcast_pending_reason", _account_broadcast_pending_reason)
    
    # 기존 타이머 취소
    if _account_broadcast_timer is not None:
        _account_broadcast_timer.cancel()

    # 0.5초 후 실제 브로드캐스트
    try:
        loop = asyncio.get_running_loop()
        _account_broadcast_timer = loop.call_later(
            _ACCOUNT_BROADCAST_COALESCE_SEC,
            lambda: asyncio.create_task(_apply_delayed_account_broadcast())
        )
        setattr(es, "_account_broadcast_timer", _account_broadcast_timer)
    except RuntimeError:
        # 이벤트 루프 없음 - 즉시 실행 (초기화 시)
        if _apply_delayed_account_broadcast:
            asyncio.run(_apply_delayed_account_broadcast())


async def _apply_delayed_account_broadcast() -> None:
    """0.5초 지연 후 실제 계좌 브로드캐스트 수행."""
    from backend.app.services import dry_run
    from backend.app.services.engine_account_notify import broadcast_account_update
    
    es = _get_es_module()
    if not es:
        return
    
    _account_broadcast_pending_reason = getattr(es, "_account_broadcast_pending_reason", None)
    _account_broadcast_timer = getattr(es, "_account_broadcast_timer", None)
    _account_snapshot = getattr(es, "_account_snapshot", {})
    _positions = getattr(es, "_positions", [])
    _settings_cache = getattr(es, "_settings_cache", {})
    
    reason = _account_broadcast_pending_reason
    _account_broadcast_pending_reason = None
    _account_broadcast_timer = None
    setattr(es, "_account_broadcast_pending_reason", _account_broadcast_pending_reason)
    setattr(es, "_account_broadcast_timer", _account_broadcast_timer)
    
    if reason is None:
        return
    
    try:
        pos = await dry_run.get_positions() if is_test_mode(_settings_cache) else list(_positions or [])
        broadcast_account_update(
            positions=pos or [],
            snapshot=dict(_account_snapshot or {}),
            reason=reason,
        )
    except Exception as e:
        logger.debug("[계좌브로드캐스트] 지연 전송 실패: %s", e, exc_info=True)


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────

async def _position_codes_with_qty() -> set[str]:
    """보유 수량이 있는 종목 코드(레이더·작전 REG 해제 시 유지 대상)."""
    from backend.app.services import dry_run

    es = _get_es_module()
    if not es:
        return set()

    _settings_cache = getattr(es, "_settings_cache", {})
    _positions = getattr(es, "_positions", [])

    if is_test_mode(_settings_cache):
        return await dry_run.position_codes()
    out: set[str] = set()
    for s in list(_positions):
        try:
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0) or 0) > 0:
                out.add(cd)
        except (TypeError, ValueError):
            continue
    return out


def _get_account_rest_lock() -> asyncio.Lock:
    """계좌 REST 조회 Lock 반환."""
    es = _get_es_module()
    if not es:
        return asyncio.Lock()
    
    _account_rest_lock = getattr(es, "_account_rest_lock", None)
    if _account_rest_lock is None:
        _account_rest_lock = asyncio.Lock()
        setattr(es, "_account_rest_lock", _account_rest_lock)
    return _account_rest_lock
