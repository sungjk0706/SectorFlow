# -*- coding: utf-8 -*-
"""
매수 파이프라인 핵심 로직: 시장가 즉시 매수, 모니터링 종목 등록, 스냅샷·매도 검사, WS 연결 시도.

`engine_service` 모듈 객체 `es`로 엔진 상태에 접근한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import ModuleType

from app.core.logger import get_logger
from app.core.trade_mode import is_test_mode
from app.services import data_manager
from app.services import dry_run
from app.services import settlement_engine
from app.services.auto_trading_effective import auto_sell_effective

logger = get_logger("engine")


def _is_placeholder_stock_name(nm: str) -> bool:
    s = (nm or "").strip()
    if not s or s == "알수없음":
        return True
    if len(s) >= 4 and s.startswith("종목(") and s.endswith(")"):
        return True
    return False


def resolve_radar_display_name(stk_cd: str, ws_stk_nm: str, access_token) -> str:
    """
    WS FID 302 등과 불일치 시 로컬 stock_name_cache로 보강.

    WS 힌트(FID 302)는 종목코드와 짝이 어긋날 수 있어, 로컬 종목명과 다르면 로컬을 우선한다.
    """
    hint = (ws_stk_nm or "").strip()
    rest_nm = ""
    try:
        rest_nm = (data_manager.get_stock_name(stk_cd, access_token) or "").strip()
    except Exception:
        rest_nm = ""

    if hint and hint != stk_cd:
        if not _is_placeholder_stock_name(rest_nm) and rest_nm and rest_nm != hint:
            return rest_nm
        return hint
    if rest_nm:
        return rest_nm
    return stk_cd


def make_detail(stk_cd: str, stk_nm: str, cur_price: int,
                 sign: str, change: int, change_rate: float,
                 prev_close: int = 0, trade_amount: int = 0, strength: str = "-") -> dict:
    """대기 종목 상세 딕셔너리 생성 헬퍼."""
    return {
        "code":        stk_cd,
        "name":        stk_nm if stk_nm else stk_cd,
        "cur_price":   cur_price,
        "sign":        sign,        # "1"상한 "2"상승 "3"보합 "4"하한 "5"하락
        "change":      change,
        "change_rate": change_rate,
        "prev_close":  prev_close,
        "trade_amount": trade_amount,
        "strength":    str(strength or "-"),
    }


async def register_pending_stock(
    stk_cd: str,
    detail: dict | None,
    reason: str,
    es: ModuleType,
) -> None:
    """
    종목을 모니터링에 등록.
    - detail 없으면 기본값으로 채운다(보강 조회 없음).
    """
    if stk_cd not in es._pending_stock_details:
        cur_price = detail.get("cur_price", 0) if detail else 0
        if detail:
            nm = detail.get("name", stk_cd) or stk_cd
            if not detail.get("name") or nm == stk_cd:
                nm = resolve_radar_display_name(stk_cd, detail.get("name") or "", es._access_token)
        else:
            nm = resolve_radar_display_name(stk_cd, "", es._access_token)
        entry = make_detail(
            stk_cd,
            nm,
            cur_price,
            detail.get("sign", "3") if detail else "3",
            detail.get("change", 0) if detail else 0,
            detail.get("change_rate", 0.0) if detail else 0.0,
            prev_close=detail.get("prev_close", 0) if detail else 0,
            trade_amount=detail.get("trade_amount", 0) if detail else 0,
            strength=detail.get("strength", "-") if detail else "-",
        )
        # ── 모니터링 추가 필드 ─────────────────────────────────────────────
        entry["status"]       = "active"
        entry["base_price"]   = cur_price
        entry["target_price"] = cur_price
        entry["captured_at"]  = datetime.now().strftime("%H:%M:%S")
        entry["reason"]       = reason
        # ──────────────────────────────────────────────────────────────────
        async with es._shared_lock:
            es._pending_stock_details[stk_cd] = entry
            es._radar_cnsr_order.append(stk_cd)
        es._invalidate_sector_stocks_cache()

        # 실시간 체결 구독 -- REG만. 시세는 REAL 01 우선.
        try:
            _task = asyncio.get_running_loop().create_task(es._subscribe_stock_realtime_when_ready(stk_cd))
            _task.add_done_callback(lambda t: logger.warning("[구독등록] 구독 실패: %s", t.exception()) if t.exception() else None)
        except RuntimeError:
            pass
    elif detail:
        # 이미 모니터링에 등록된 종목 -> 최신 시세만 업데이트 (이탈 상태면 갱신 안 함)
        need_resolve = False
        async with es._shared_lock:
            entry = es._pending_stock_details[stk_cd]
            if entry.get("status") == "exited":
                return
            if detail.get("cur_price"):
                prev_px = int(entry.get("cur_price") or 0)
                new_px = int(detail["cur_price"])
                entry["cur_price"]   = new_px
                entry["sign"]        = detail.get("sign", entry.get("sign", "3"))
                entry["change"]      = detail.get("change", entry.get("change", 0))
                entry["change_rate"] = detail.get("change_rate", entry.get("change_rate", 0.0))
                if prev_px <= 0 < new_px:
                    entry["base_price"]   = new_px
                    entry["target_price"] = new_px
            if detail.get("prev_close"):
                entry["prev_close"] = detail["prev_close"]
            if "trade_amount" in detail:
                entry["trade_amount"] = detail["trade_amount"]
            if detail.get("name") and detail["name"] != stk_cd:
                entry["name"] = detail["name"]
            else:
                need_resolve = (entry.get("name") == stk_cd)
        # REST 조회는 Lock 밖에서 수행 (네트워크 호출)
        if need_resolve:
            rest_nm = resolve_radar_display_name(stk_cd, detail.get("name") or "", es._access_token)
            async with es._shared_lock:
                entry["name"] = rest_nm


async def run_snapshot_and_sell_check(force_rest: bool, es: ModuleType) -> None:
    """
    매도 조건 검사 + (선택) REST 부트스트랩.
    - force_rest=True: 수동 동기화 -- kt00001/18 (예수금·수량·매입).
    - WS 구독 구간(장중): REST 생략, 스냅샷 메타만 갱신.
    - WS 구독 구간 외: REST 조회.
    """
    try:
        from app.services.daily_time_scheduler import is_ws_subscribe_window
        in_window = is_ws_subscribe_window(getattr(es, "_settings_cache", None))
        ws_ok = bool(es._kiwoom_connector and es._kiwoom_connector.is_connected() and es._login_ok)
        # 장중(구독 구간)이면 force_rest여도 REST 생략 -- 실시간 데이터 우선
        if in_window and not force_rest:
            es._refresh_account_snapshot_meta()
        elif not in_window or force_rest:
            if not es._account_rest_bootstrapped or not ws_ok or force_rest:
                await es._update_account_memory(es._settings_cache)
            else:
                es._refresh_account_snapshot_meta()
        for s in es._positions:
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0)) > 0:
                es._checked_stocks.add(cd)
        # 테스트모드: dry_run 가상 잔고 기준으로 매도 조건 검사
        _sell_positions = dry_run.get_positions() if is_test_mode(getattr(es, "_settings_cache", {})) else es._positions
        # _checked_stocks를 현재 보유 종목 기준으로 재구성 -- 매도 완료 종목 제거 반영
        _live_codes: set[str] = set()
        for s in (dry_run.get_positions() if is_test_mode(getattr(es, "_settings_cache", {})) else es._positions):
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0)) > 0:
                _live_codes.add(cd)
        if is_test_mode(getattr(es, "_settings_cache", {})):
            for cd in dry_run.position_codes():
                _live_codes.add(cd)
        es._checked_stocks = _live_codes
        if _sell_positions and es._auto_trade and auto_sell_effective(es._settings_cache) and es._access_token:
            es._auto_trade.check_sell_conditions(_sell_positions, es._settings_cache, es._access_token)
    except Exception as e:
        logger.warning("[확정데이터] 처리 중 오류: %s", e)


def check_test_buy_power(settings: dict, price: int, qty: int, daily_spent: int) -> tuple[bool, str]:
    """
    테스트모드: 매수 전 예수금 검증.
    Settlement Engine의 check_buy_power를 호출하여 매수 가능 여부를 확인한다.
    반환: (ok, reason) -- ok=False이면 매수 거부 사유를 reason에 포함.
    """
    order_amount = price * qty
    daily_limit = int(settings.get("max_daily_total_buy_amt", 0) or 0)
    ok, reason = settlement_engine.check_buy_power(order_amount, daily_limit, daily_spent)
    return ok, reason
