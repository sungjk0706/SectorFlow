# -*- coding: utf-8 -*-
"""
계좌/잔고 관련 모듈
- 계좌 스냅샷
- 잔고 관리
- REST 계좌 데이터 조회
- 브로드캐스트
"""
import asyncio
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
import backend.app.services.engine_state as engine_state
from backend.app.services.engine_state import state, _get_rest_api_thread_sem as _ensure_rest_api_thread_sem

logger = get_logger("engine_account")


# ── 계좌 스냅샷/잔고 조회 ─────────────────────────────────────────────────

async def get_account_snapshot() -> dict:
    """계좌 스냅샷 반환."""
    from backend.app.services import settlement_engine
    
    snap = dict(state.account_snapshot)
    
    if not snap or "trade_mode" not in snap:
        _is_test = is_test_mode(state.integrated_system_settings_cache)
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
    return "test" if is_test_mode(state.integrated_system_settings_cache) else "real"


async def get_positions() -> list:
    """보유 종목 목록 반환."""
    from backend.app.services import dry_run
    
    if is_test_mode(state.integrated_system_settings_cache):
        return await dry_run.get_positions()
    return list(state.positions)


async def get_total_buy_amount() -> int:
    """총 매입금액 반환."""
    from backend.app.services import dry_run

    if is_test_mode(state.integrated_system_settings_cache):
        return sum(int(p.get("buy_amt", 0) or 0) for p in await dry_run.get_positions())
    return int(state.broker_rest_totals.get("total_buy", 0) or 0)


async def get_total_eval_amount() -> int:
    """총 평가금액 반환."""
    from backend.app.services import dry_run

    if is_test_mode(state.integrated_system_settings_cache):
        return sum(int(p.get("eval_amt", 0) or 0) for p in await dry_run.get_positions())
    return int(state.broker_rest_totals.get("total_eval", 0) or 0)


async def get_total_pnl() -> int:
    """총 손익 반환."""
    from backend.app.services import dry_run

    if is_test_mode(state.integrated_system_settings_cache):
        return sum(int(p.get("pnl_amount", 0) or 0) for p in await dry_run.get_positions())
    return int(state.broker_rest_totals.get("total_pnl", 0) or 0)


async def get_total_pnl_rate() -> float:
    """총 수익률 반환."""
    if is_test_mode(state.integrated_system_settings_cache):
        total_buy = await get_total_buy_amount()
        total_pnl = await get_total_pnl()
        return round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0
    return float(state.broker_rest_totals.get("total_rate", 0.0) or 0.0)


def get_snapshot_history() -> list:
    """스냅샷 이력 반환."""
    return list(state.snapshot_history)


async def get_buy_limit_status() -> dict:
    """매수 한도 상태를 dict로 반환 (프론트 배지용)."""
    daily_buy_spent = 0
    if state.auto_trade:
        await state.auto_trade._ensure_daily_buy_counter()
        daily_buy_spent = state.auto_trade._daily_buy_spent
    return {"daily_buy_spent": daily_buy_spent}


async def _broadcast_buy_limit_status() -> None:
    """매수 한도 상태를 WS로 브로드캐스트."""
    try:
        from backend.app.services.engine_account_notify import _broadcast, notify_buy_targets_update
        await _broadcast("buy-limit-status", await get_buy_limit_status())
        await notify_buy_targets_update()
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

    _EMPTY = {"success": False, "summary": {}, "stock_list": []}
    # 증권사별 REST API 분리
    broker = str(settings.get("broker", "") or "").lower().strip()
    _rest_api = state.broker_rest_apis.get(broker)
    _rest_api_thread_sem = state.rest_api_thread_sem or _ensure_rest_api_thread_sem()
    
    if _rest_api is None:
        logger.warning("[계좌] _rest_api 없음 -- 엔진 기동 완료 전 호출. 계좌 조회 건너뜀.")
        return _EMPTY

    # ── 토큰 유효성 먼저 확인 ─────────────────────────────────────────────
    async with _rest_api_thread_sem:
        token_ok = await _rest_api._ensure_token()
    if not token_ok:
        logger.warning(
            "[계좌] 유효한 토큰 없음 (au10001 발급 실패) -- 계좌 조회 건너뜀. "
            "이전 값을 그대로 유지합니다. (0원 표시 방지)"
        )
        return _EMPTY

    if _rest_api._token_info and _rest_api._token_info.token:
        t = _rest_api._token_info.token
        token_preview = t[:4] + "****" + t[-2:] if len(t) > 6 else "****"
    else:
        token_preview = "?"
    logger.info("[계좌] 토큰 유효 확인 (%s) -- 계좌 조회 시작", token_preview)

    acnt_no = str(getattr(_rest_api, "_acnt_no", "") or "")

    # ── deposit -> (0.5초 대기) -> balance 순차 호출로 429 예방 ─────────────
    try:
        async with _rest_api_thread_sem:
            deposit_raw = await _rest_api.get_deposit_detail(acnt_no)
        await asyncio.sleep(0.5)
        async with _rest_api_thread_sem:
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
    lock = engine_state._get_account_rest_lock()
    if lock.locked():
        logger.info("[계좌] REST 조회 중복 요청 -- 선행 조회 완료까지 대기")
    async with lock:
        # lock 대기 중 선행 조회가 완료됐으면 중복 호출 스킵
        if state.account_rest_bootstrapped:
            logger.info("[계좌] REST 조회 -- 선행 조회에서 이미 완료됨, 중복 생략")
            return
        await _update_account_memory_inner(settings)


async def _update_account_memory_inner(settings: dict) -> None:
    """_update_account_memory 실제 구현 (Lock 내부에서 호출)."""
    from backend.app.services.engine_account_notify import _rebuild_positions_cache
    from backend.app.services.engine_ws import _ws_live, _sweep_unreg_subscribed_except_positions_and_tracked
    from backend.app.core.engine_settings import get_engine_settings

    s = settings or {}
    broker = str(s.get("broker", "") or "").lower().strip()
    need_reload = False
    if broker:
        if not s.get(f"{broker}_app_key") or not s.get(f"{broker}_app_secret"):
            need_reload = True
    if need_reload:
        s = await get_engine_settings(state.engine_user_id or None)

    yield_data = await _fetch_account_data(s)

    if not yield_data.get("success"):
        logger.warning(
            "[계좌] 조회 실패함 -- 기존 스냅샷 유지 (총평가=%s원)",
            f"{state.account_snapshot.get('total_eval', 0):,}",
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
        state.positions = merged
        _rebuild_positions_cache(merged)

    state.account_rest_bootstrapped = True
    
    state.account_snapshot["broker"] = broker
    state.account_snapshot["deposit"] = int(summary.get("deposit", 0) or 0)
    state.account_snapshot["orderable"] = int(summary.get("orderable", 0) or 0)

    # WS 구독 보강은 _login_post_pipeline / _run_snapshot_and_sell_check 에서 명시적으로 호출.
    # 여기서 호출하면 _account_rest_lock 안에서 _reg_seq_lock 을 잡는 중첩 락 -> 데드락 위험.
    if _ws_live():
        try:
            n_unreg = await _sweep_unreg_subscribed_except_positions_and_tracked()
            if n_unreg:
                logger.info(
                    "[구독정리] 잔고 반영 후 미보유·미추적 종목 구독해지 %d건 (추적 종목 제외)",
                    n_unreg,
                )
        except Exception as e:
            logger.warning("[연결] 웹소켓 실시간 구독 정리 실패함: %s", e, exc_info=True)

    if state.refresh_account_snapshot_meta:
        await state.refresh_account_snapshot_meta()

    if state.update_account_memory:
        state.update_account_memory()
    
    _ps = state.account_snapshot.get("price_source", "?")
    _ps_kr = (
        "웹소켓(실시간)"
        if _ps == "websocket"
        else "REST초기화"
        if _ps == "rest_bootstrap"
        else str(_ps)
    )
    logger.info(
        f"[계좌] 갱신 완료 -- 평가금: {state.account_snapshot.get('total_eval', 0):,}원 | "
        f"손익: {state.account_snapshot.get('total_pnl', 0):,}원 | 포지션: {state.account_snapshot.get('position_count', 0)}개 | "
        f"가격소스: {_ps_kr}"
    )


def _merge_positions_from_rest(stock_list: list) -> list:
    """
    REST kt00018 잔고 반영. 수량·매입·종목명은 REST 기준.
    """
    from backend.app.services.engine_account_rest import merge_positions_from_rest
    return merge_positions_from_rest(stock_list, {})


def _apply_broker_totals_from_summary(summary: dict) -> None:
    """REST kt00018 루트 합계 -- 실시간 이벤트에서 임의 합산하지 않고 이 값만 갱신."""
    from backend.app.services.engine_account_rest import broker_totals_from_summary
    state.broker_rest_totals = broker_totals_from_summary(summary)


async def _refresh_account_snapshot_meta() -> None:
    """
    스냅샷 시각·보유종목수·가격소스 갱신.
    실전모드: 총평가·총손익·총매입·총수익률은 _broker_rest_totals(REST kt00018 또는 REAL 04 공식 FID 932~934) 사용.
    테스트모드: positions 합산으로 totals 구성 + 가상 예수금 반영.
    """
    from backend.app.services.engine_account_rest import build_account_snapshot_meta
    from backend.app.services import dry_run, settlement_engine
    from backend.app.services.engine_ws import _ws_live
    
    _is_test = is_test_mode(state.integrated_system_settings_cache)
    pos = await dry_run.get_positions() if _is_test else state.positions

    if _is_test:
        # 테스트모드: settlement_engine 누적투자금/주문가능금액 반영 + 포지션 합산으로 totals 구성
        accumulated_investment = settlement_engine.get_accumulated_investment()
        orderable = settlement_engine.get_orderable()
        total_buy = sum(int(p.get("buy_amt", 0) or 0) for p in pos)
        total_eval = sum(int(p.get("eval_amt", 0) or 0) for p in pos)
        total_pnl = total_eval - total_buy
        total_rate = round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0

        state.account_snapshot["accumulated_investment"] = accumulated_investment
        state.account_snapshot["orderable"] = orderable
        state.account_snapshot["initial_deposit"] = accumulated_investment
        
        test_totals = {
            "total_eval": total_eval,
            "total_pnl": total_pnl,
            "total_buy": total_buy,
            "total_rate": total_rate,
        }
        snap = build_account_snapshot_meta(
            state.account_snapshot, test_totals, pos, _ws_live(),
            trade_mode="test",
        )
    else:
        snap = build_account_snapshot_meta(
            state.account_snapshot, state.broker_rest_totals, pos, _ws_live(),
            trade_mode="real",
        )
    
    state.account_snapshot = snap



async def _apply_last_price_to_positions(stk_cd: str, price: int) -> bool:
    """실시간 체결(REAL 01) -- 체결가 반영 + 평가손익·수익률·평가금액 실시간 재계산. 보유에 반영되면 True."""
    from backend.app.services.engine_account_rest import (
        apply_last_price_to_positions_inplace,
        recalc_broker_totals_from_positions,
    )
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    from backend.app.services import dry_run
    
    # 테스트모드: dry_run 가상 잔고에 현재가 반영 (6자리 정규화)
    if is_test_mode(state.integrated_system_settings_cache):
        nk = _base_stk_cd(str(stk_cd or "").strip())
        return await dry_run.update_price(nk, price) if nk else False
    
    hit = apply_last_price_to_positions_inplace(state.positions, stk_cd, price)
    if hit:
        state.broker_rest_totals = recalc_broker_totals_from_positions(state.positions, state.broker_rest_totals)
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

    if _real04_is_stock_item(item):
        # 종목 단위 레코드 -- 보유수량·매입단가·평가손익 등 갱신
        _prev_len = len(state.positions)
        real04_official_apply_position_line(item, vals, state.positions, {})
        if len(state.positions) != _prev_len:
            _rebuild_positions_cache(state.positions)
    else:
        # 계좌 단위 레코드 -- 예수금·총평가·총손익 등 갱신
        delta = real04_official_account_delta(vals)
        if delta:
            if "deposit" in delta:
                state.account_snapshot["deposit"] = int(delta["deposit"])
            if "total_eval" in delta:
                state.broker_rest_totals["total_eval"] = int(delta["total_eval"])
            if "total_pnl" in delta:
                state.broker_rest_totals["total_pnl"] = int(delta["total_pnl"])
            if "total_rate" in delta:
                state.broker_rest_totals["total_rate"] = float(delta["total_rate"])
    
    if state.refresh_account_snapshot_meta:
        await state.refresh_account_snapshot_meta()
    if state.update_account_memory:
        state.update_account_memory()

    # ── State Gate 회복: 실전모드 잔고 업데이트 시 매수 재평가 ──
    try:
        from backend.app.services.buy_order_executor import _cash_insufficient, evaluate_buy_candidates, invalidate_buy_snapshot
        if _cash_insufficient:
            invalidate_buy_snapshot()
            await evaluate_buy_candidates()
    except Exception:
        pass


async def _on_fill_after_ws() -> None:
    """주문체결(00) 완료 직후 -- REST 없이 메모리·매도조건만 갱신."""
    from backend.app.services.auto_trading_effective import auto_sell_effective
    from backend.app.services import dry_run

    # 1. 계좌 스냅샷 갱신
    await _refresh_account_snapshot_meta()

    # 2. 매도 조건 검사
    if is_test_mode(state.integrated_system_settings_cache):
        pos = await dry_run.get_positions()
    else:
        pos = state.positions
    if pos and state.auto_trade and auto_sell_effective(state.integrated_system_settings_cache) and state.access_token:
        await state.auto_trade.check_sell_conditions(pos, state.integrated_system_settings_cache, state.access_token)


# ── 브로드캐스트 ─────────────────────────────────────────────────────────

async def _broadcast_account(reason: str | None = None) -> None:
    """데이터 갱신 후 UI/WS 계좌 브로드캐스트 — 직접 await 호출."""
    from backend.app.services import dry_run
    from backend.app.services.engine_account_notify import broadcast_account_update

    try:
        pos = await dry_run.get_positions() if is_test_mode(state.integrated_system_settings_cache) else list(state.positions or [])
        await broadcast_account_update(
            positions=pos or [],
            snapshot=dict(state.account_snapshot or {}),
            reason=reason or "update",
        )
    except Exception as e:
        logger.warning("[계좌브로드캐스트] 전송 실패: %s", e, exc_info=True)


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────

async def _position_codes_with_qty() -> set[str]:
    """보유 수량이 있는 종목 코드(레이더·작전 REG 해제 시 유지 대상)."""
    from backend.app.services import dry_run

    if is_test_mode(state.integrated_system_settings_cache):
        return await dry_run.position_codes()
    out: set[str] = set()
    for s in list(state.positions):
        try:
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0) or 0) > 0:
                out.add(cd)
        except (TypeError, ValueError):
            continue
    return out
