# -*- coding: utf-8 -*-
"""
체결 이력 저장 모듈 -- 매수/매도 체결 기록을 인메모리 + JSON 파일로 관리.

책임:
  1. record_buy()  -- 매수 체결 기록
  2. record_sell() -- 매도 체결 기록 (실현손익 자동 계산)
  3. get_buy_history() / get_sell_history() -- UI 조회용
  4. 일별 요약 (daily_summary) -- 수익현황 탭 좌측 그래프/요약용
  5. 승률 / MDD / 실현손익 집계
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_HISTORY_FILE = _DATA_DIR / "trade_history.json"

# ── Producer-Consumer Queue ─────────────────────────────────────────────────
# 큐 크기 제한: 비정상적 틱 몰림 시 메모리 폭주 방지
_QUEUE_MAXSIZE = 1000
_io_queue: asyncio.Queue[dict] | None = None
_consumer_task: asyncio.Task[None] | None = None
_shutdown_event: asyncio.Event | None = None

# ── 보관 기한 상수 ─────────────────────────────────────────────────────────────
RETENTION_TRADING_DAYS_TEST: int = 60
RETENTION_TRADING_DAYS_REAL: int = 5

# 인메모리 저장소 (Consumer Task만 접근하므로 Lock 불필요)
_buy_history: list[dict] = []
_sell_history: list[dict] = []
_loaded: bool = False


# ── 보관 기한 트림 ─────────────────────────────────────────────────────────────


def _compute_retained_dates(records: list[dict]) -> dict[str, set[str]]:
    """모드별 보관할 날짜 set 계산.

    각 레코드의 trade_mode별로 고유 date를 수집하고,
    최근 N개 날짜만 유지한다 (test=60, real=5).
    trade_mode 누락 시 "test"로 간주.
    """
    dates_by_mode: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        date_val = rec.get("date", "")
        if not date_val:
            continue
        mode = rec.get("trade_mode") or "test"
        dates_by_mode[mode].add(date_val)

    retained: dict[str, set[str]] = {}
    for mode, dates in dates_by_mode.items():
        limit = RETENTION_TRADING_DAYS_TEST if mode == "test" else RETENTION_TRADING_DAYS_REAL
        sorted_dates = sorted(dates, reverse=True)[:limit]
        retained[mode] = set(sorted_dates)
    return retained


def _trim_expired(records: list[dict]) -> list[dict]:
    """보관 기한 초과 레코드 제거. 모드별 독립 적용.

    - date 필드 누락/빈 값 → 제거
    - 해당 모드에 레코드가 전혀 없으면 삭제 없음
    - 원본 불변, 새 리스트 반환, 원래 순서 유지
    """
    retained = _compute_retained_dates(records)
    result: list[dict] = []
    for rec in records:
        date_val = rec.get("date", "")
        if not date_val:
            continue
        mode = rec.get("trade_mode") or "test"
        mode_dates = retained.get(mode)
        if mode_dates is None:
            # 해당 모드에 레코드가 없는 경우 (이론상 도달 불가하지만 안전장치)
            result.append(rec)
            continue
        if date_val in mode_dates:
            result.append(rec)
    return result


# ── 날짜 유틸 ──────────────────────────────────────────────────────────────


def _broadcast_sell_append(rec: dict) -> None:
    """매도 체결 후 단건 + 해당 일자 요약을 브로드캐스트."""
    try:
        from app.web.ws_manager import ws_manager
        trade_mode = rec.get("trade_mode", "test")
        summary = get_daily_summary(days=20, trade_mode=trade_mode)
        ws_manager.broadcast("sell-history-append", {"trade": rec, "daily_summary": summary})
    except Exception as e:
        logger.warning("[체결이력] 매도 단건 실시간 화면전송 실패: %s", e)


def _broadcast_buy_append(rec: dict) -> None:
    """매수 체결 후 단건 브로드캐스트."""
    try:
        from app.web.ws_manager import ws_manager
        ws_manager.broadcast("buy-history-append", {"trade": rec})
    except Exception as e:
        logger.warning("[체결이력] 매수 단건 실시간 화면전송 실패: %s", e)


def _broadcast_full_sell_history(trade_mode: str) -> None:
    """초기 스냅샷용: 해당 trade_mode의 전체 매도 내역 + 일별 요약을 브로드캐스트."""
    try:
        from app.web.ws_manager import ws_manager
        rows = [r for r in _sell_history if r.get("trade_mode") == trade_mode]
        ws_manager.broadcast("sell-history-update", {"sell_history": list(reversed(rows))})
        summary = get_daily_summary(days=20, trade_mode=trade_mode)
        ws_manager.broadcast("daily-summary-update", {"daily_summary": summary})
    except Exception as e:
        logger.warning("[체결이력] 매도 내역 실시간 화면전송 실패: %s", e)


def _broadcast_full_buy_history(trade_mode: str) -> None:
    """초기 스냅샷용: 해당 trade_mode의 전체 매수 내역을 브로드캐스트."""
    try:
        from app.web.ws_manager import ws_manager
        rows = [r for r in _buy_history if r.get("trade_mode") == trade_mode]
        ws_manager.broadcast("buy-history-update", {"buy_history": list(reversed(rows))})
    except Exception as e:
        logger.warning("[체결이력] 매수 내역 실시간 화면전송 실패: %s", e)


def _broadcast_order_filled(fill_data: dict) -> None:
    """체결 이벤트 발행 -- 거래내역 테이블 즉시 갱신용."""
    try:
        from app.web.ws_manager import ws_manager
        ws_manager.broadcast("order-filled", fill_data)
    except Exception as e:
        logger.warning("[체결이력] 체결 이벤트 실시간 화면전송 실패: %s", e)


def _recent_trading_days(days: int) -> list[str]:
    """최근 N영업일 날짜 리스트 반환 (오래된 순, ISO 형식)."""
    from app.core.trading_calendar import recent_business_days
    return [d.isoformat() for d in recent_business_days(days)]


# ── 파일 I/O ─────────────────────────────────────────────────────────────────

def _ensure_loaded() -> None:
    """최초 호출 시 파일에서 로드 + 기존 매도 데이터 보정 + 만료 레코드 트림."""
    global _loaded, _buy_history, _sell_history
    if _loaded:
        return
    _load_from_file()
    _patch_sell_history()
    # 로드 후 트림 적용
    before_buy, before_sell = len(_buy_history), len(_sell_history)
    _buy_history = _trim_expired(_buy_history)
    _sell_history = _trim_expired(_sell_history)
    trimmed = (before_buy - len(_buy_history)) + (before_sell - len(_sell_history))
    if trimmed > 0:
        _enqueue_save_request()
        logger.info("[체결이력] 로드 시 만료 레코드 %d건 정리", trimmed)
    _loaded = True


def _patch_sell_history() -> None:
    """avg_buy_price=0인 기존 매도 건의 실현손익을 매수 이력 기반으로 보정."""
    patched = 0
    for rec in _sell_history:
        abp = int(rec.get("avg_buy_price", 0))
        if abp > 0:
            continue
        stk_cd = rec.get("stk_cd", "")
        avg = _calc_avg_buy_price(stk_cd)
        if avg <= 0:
            continue
        qty = int(rec.get("qty", 0))
        sell_price = int(rec.get("price", 0))
        rec["avg_buy_price"] = avg
        rec["realized_pnl"] = (sell_price - avg) * qty
        patched += 1
    if patched > 0:
        # 비동기 저장은 _schedule_save에서 처리
        pass
        logger.info("[체결이력] 기존 매도 %d건 실현손익 보정 완료", patched)


def _load_from_file() -> None:
    """JSON 파일에서 이력 로드."""
    global _buy_history, _sell_history
    if not _HISTORY_FILE.exists():
        return
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _buy_history = data.get("buy", [])
        _sell_history = data.get("sell", [])
        logger.info(
            "[체결이력] 파일 로드 완료 -- 매수 %d건, 매도 %d건",
            len(_buy_history), len(_sell_history),
        )
    except Exception as e:
        logger.warning("[체결이력] 파일 로드 실패: %s", e)


def _save_to_file(buy_data: list[dict] | None = None, sell_data: list[dict] | None = None) -> None:
    """인메모리 -> JSON 파일 저장. buy_data/sell_data가 주어지면 복사본으로 저장."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        buy = buy_data if buy_data is not None else _buy_history
        sell = sell_data if sell_data is not None else _sell_history
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"buy": buy, "sell": sell},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.warning("[체결이력] 파일 저장 실패: %s", e)


# ── Producer-Consumer Queue API ───────────────────────────────────────────────


def _enqueue_save_request() -> None:
    """저장 요청을 큐에 전달. 메인 엔진에서 호출 (비블로킹)."""
    global _io_queue
    if _io_queue is None:
        logger.warning("[체결이력] Consumer Task 미시작 상태 - 저장 요청 무시")
        return
    try:
        _io_queue.put_nowait({"type": "save"})
    except asyncio.QueueFull:
        logger.warning("[체결이력] I/O 큐 폭주 - 디스크 플러시 지연됨 (메모리에는 안전함)")


def _enqueue_clear_request() -> None:
    """전체 초기화 요청을 큐에 전달."""
    global _io_queue
    if _io_queue is None:
        logger.warning("[체결이력] Consumer Task 미시작 상태 - 초기화 요청 무시")
        return
    try:
        _io_queue.put_nowait({"type": "clear"})
    except asyncio.QueueFull:
        logger.warning("[체결이력] I/O 큐 폭주 - 초기화 요청 드롭")


def _enqueue_clear_test_request() -> None:
    """테스트모드 초기화 요청을 큐에 전달."""
    global _io_queue
    if _io_queue is None:
        logger.warning("[체결이력] Consumer Task 미시작 상태 - 테스트 초기화 요청 무시")
        return
    try:
        _io_queue.put_nowait({"type": "clear_test"})
    except asyncio.QueueFull:
        logger.warning("[체결이력] I/O 큐 폭주 - 테스트 초기화 요청 드롭")


async def _consumer_task_impl() -> None:
    """백그라운드 Consumer Task - 큐에서 요청을 받아 디스크 I/O 처리."""
    global _io_queue, _shutdown_event
    
    while True:
        try:
            # shutdown_event가 설정되면 큐 처리 후 종료
            if _shutdown_event and _shutdown_event.is_set():
                # 큐에 남은 요청 모두 처리
                while not _io_queue.empty():
                    req = await asyncio.wait_for(_io_queue.get(), timeout=1.0)
                    _process_io_request(req)
                logger.info("[체결이력] Consumer Task Graceful Shutdown 완료")
                break
            
            # 타임아웃 1초로 주기적으로 shutdown_event 체크
            req = await asyncio.wait_for(_io_queue.get(), timeout=1.0)
            _process_io_request(req)
        except asyncio.TimeoutError:
            # 타임아웃은 정상 - shutdown_event 체크용
            continue
        except Exception as e:
            logger.error("[체결이력] Consumer Task 오류: %s", e, exc_info=True)
            # 치명적 오류가 아니면 계속 실행
            await asyncio.sleep(0.1)


def _process_io_request(req: dict) -> None:
    """I/O 요청 처리 (Consumer Task에서 실행)."""
    req_type = req.get("type")
    
    if req_type == "save":
        _perform_save()
    elif req_type == "clear":
        _perform_clear()
    elif req_type == "clear_test":
        _perform_clear_test()
    else:
        logger.warning("[체결이력] 알 수 없는 요청 타입: %s", req_type)


def _perform_save() -> None:
    """실제 저장 로직 (Consumer Task에서 실행, Lock 불필요)."""
    global _buy_history, _sell_history
    try:
        buy_copy = _trim_expired(list(_buy_history))
        sell_copy = _trim_expired(list(_sell_history))
        _buy_history[:] = buy_copy
        _sell_history[:] = sell_copy
        _save_to_file(buy_data=buy_copy, sell_data=sell_copy)
    except Exception as e:
        logger.error("[체결이력] 저장 실패: %s", e, exc_info=True)


def _perform_clear() -> None:
    """전체 초기화 (Consumer Task에서 실행)."""
    global _buy_history, _sell_history
    try:
        _buy_history.clear()
        _sell_history.clear()
        _save_to_file()
        logger.info("[체결이력] 전체 이력 초기화 완료")
    except Exception as e:
        logger.error("[체결이력] 초기화 실패: %s", e, exc_info=True)


def _perform_clear_test() -> None:
    """테스트모드 초기화 (Consumer Task에서 실행)."""
    global _buy_history, _sell_history
    try:
        _ensure_loaded()
        before_buy = len(_buy_history)
        before_sell = len(_sell_history)
        _buy_history = [r for r in _buy_history if r.get("trade_mode") != "test"]
        _sell_history = [r for r in _sell_history if r.get("trade_mode") != "test"]
        removed_buy = before_buy - len(_buy_history)
        removed_sell = before_sell - len(_sell_history)
        _save_to_file()
        logger.info(
            "[체결이력] 테스트 이력 초기화 -- 매수 %d건, 매도 %d건 삭제",
            removed_buy, removed_sell,
        )
    except Exception as e:
        logger.error("[체결이력] 테스트 초기화 실패: %s", e, exc_info=True)


# ── Lifecycle Management ───────────────────────────────────────────────────────

def _reset_global_state() -> None:
    """전역 변수 초기화 (비정상 종료 후 재시작 시 잔존 상태 방지)."""
    global _io_queue, _consumer_task, _shutdown_event, _buy_history, _sell_history, _loaded
    _io_queue = None
    _consumer_task = None
    _shutdown_event = None
    _buy_history = []
    _sell_history = []
    _loaded = False


def start_consumer_task() -> None:
    """Consumer Task 시작 (앱 시작 시 호출)."""
    global _io_queue, _consumer_task, _shutdown_event
    if _consumer_task is not None:
        logger.warning("[체결이력] Consumer Task 이미 실행 중")
        return
    
    _io_queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _consumer_task = loop.create_task(_consumer_task_impl())


async def stop_consumer_task() -> None:
    """Consumer Task 정지 (앱 종료 시 호출). Graceful Shutdown 보장."""
    global _consumer_task, _shutdown_event, _io_queue
    if _consumer_task is None:
        return
    
    logger.info("[체결이력] Consumer Task 종료 요청")
    _shutdown_event.set()
    
    try:
        await asyncio.wait_for(_consumer_task, timeout=5.0)
        logger.info("[체결이력] Consumer Task 정상 종료")
    except asyncio.TimeoutError:
        logger.warning("[체결이력] Consumer Task 종료 타임아웃 - 강제 취소")
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            logger.info("[체결이력] Consumer Task 강제 종료 완료")
    finally:
        _consumer_task = None
        _shutdown_event = None
        _io_queue = None


# ── 기록 API ─────────────────────────────────────────────────────────────────

def record_buy(
    *,
    stk_cd: str,
    stk_nm: str,
    price: int,
    qty: int,
    reason: str = "",
    trade_mode: str = "test",
) -> dict:
    """매수 체결 기록. 반환: 저장된 레코드.
    
    메인 엔진에서 호출 - Lock 없이 인메모리 업데이트 후 비블로킹 큐 전송.
    """
    _ensure_loaded()
    now = datetime.now()
    total_amt = price * qty
    # 테스트모드: 수수료 0.015% 계산
    fee = round(total_amt * 0.00015) if trade_mode == "test" else 0
    rec = {
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "side": "BUY",
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "price": price,
        "qty": qty,
        "total_amt": total_amt + fee,
        "fee": fee,
        "reason": reason,
        "trade_mode": trade_mode,
    }
    logger.info(
        "[체결이력] 매수 기록 -- %s(%s) %d주 @%s 수수료=%s %s",
        stk_nm, stk_cd, qty, f"{price:,}", f"{fee:,}", reason,
    )
    # 실전모드: 증권사 서버가 원본이므로 로컬 저장 불필요
    if trade_mode != "real":
        _buy_history.append(rec)
        _enqueue_save_request()  # 비블로킹 큐 전송
    _broadcast_buy_append(rec)
    return rec


def _calc_avg_buy_price(stk_cd: str) -> int:
    """매수 이력에서 해당 종목의 가중평균 매입가를 역산. 매수 기록 없으면 0."""
    total_amt = 0
    total_qty = 0
    for r in _buy_history:
        if r.get("stk_cd") == stk_cd:
            total_amt += int(r.get("price", 0)) * int(r.get("qty", 0))
            total_qty += int(r.get("qty", 0))
    if total_qty == 0:
        return 0
    return round(total_amt / total_qty)


def record_sell(
    *,
    stk_cd: str,
    stk_nm: str,
    price: int,
    qty: int,
    avg_buy_price: int = 0,
    reason: str = "",
    pnl_rate: float = 0.0,
    trade_mode: str = "test",
) -> dict:
    """매도 체결 기록. 실현손익 자동 계산.
    
    메인 엔진에서 호출 - Lock 없이 인메모리 업데이트 후 비블로킹 큐 전송.
    """
    _ensure_loaded()
    now = datetime.now()
    # 안전장치: avg_buy_price가 0이면 매수 이력에서 역산
    if avg_buy_price <= 0:
        avg_buy_price = _calc_avg_buy_price(stk_cd)
        if avg_buy_price > 0:
            logger.info(
                "[체결이력] avg_buy_price 역산 -- %s → %s",
                stk_cd, f"{avg_buy_price:,}",
            )
    total_amt = price * qty
    # 테스트모드: 수수료 0.015%, 세금 0.20%
    fee = round(total_amt * 0.00015) if trade_mode == "test" else 0
    tax = round(total_amt * 0.002) if trade_mode == "test" else 0
    # 매도금액(실수령) = 매도가×수량 - 수수료 - 세금
    sell_net = total_amt - fee - tax
    # 매수금액(실지출) = 매수가×수량 + 매수수수료
    buy_fee = round(avg_buy_price * qty * 0.00015) if trade_mode == "test" and avg_buy_price > 0 else 0
    buy_total = avg_buy_price * qty + buy_fee if avg_buy_price > 0 else 0
    # 실현손익 = 실수령 - 실지출
    realized_pnl = sell_net - buy_total if avg_buy_price > 0 else 0
    rec = {
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "side": "SELL",
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "price": price,
        "qty": qty,
        "total_amt": sell_net,
        "avg_buy_price": avg_buy_price,
        "buy_total_amt": buy_total,
        "realized_pnl": realized_pnl,
        "pnl_rate": round(realized_pnl / buy_total * 100, 2) if buy_total > 0 else 0.0,
        "fee": fee,
        "tax": tax,
        "reason": reason,
        "trade_mode": trade_mode,
    }
    logger.info(
        "[체결이력] 매도 기록 -- %s(%s) %d주 @%s 실현손익=%s 수수료=%s 세금=%s %s",
        stk_nm, stk_cd, qty, f"{price:,}",
        f"{realized_pnl:+,}", f"{fee:,}", f"{tax:,}", reason,
    )
    # 실전모드: 증권사 서버가 원본이므로 로컬 저장 불필요
    if trade_mode != "real":
        _sell_history.append(rec)
        _enqueue_save_request()  # 비블로킹 큐 전송
    _broadcast_sell_append(rec)
    return rec


# ── 조회 API ─────────────────────────────────────────────────────────────────

def _in_date_range(d: str, date_from: str, date_to: str) -> bool:
    """날짜 문자열이 범위 안에 있는지 판단. 빈 문자열이면 해당 방향 무제한."""
    if not d:
        return False
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True

def get_buy_history(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> list[dict]:
    """매수 체결 이력 반환 (최신순).
    date_from/date_to: 'YYYY-MM-DD' 형식 날짜 범위 필터. 둘 다 비어있으면 전체.
    today_only=True이면 date_from/date_to 무시하고 오늘만.
    trade_mode: 'real' 또는 'test' 지정 시 해당 모드만 필터링. None이면 전체.
    
    Consumer Task만 인메모리 데이터 수정하므로 Lock 불필요.
    """
    _ensure_loaded()
    rows = _buy_history
    if today_only:
        td = date.today().isoformat()
        rows = [r for r in rows if r.get("date") == td]
    elif date_from or date_to:
        rows = [r for r in rows if _in_date_range(r.get("date", ""), date_from, date_to)]
    if trade_mode is not None:
        rows = [r for r in rows if r.get("trade_mode") == trade_mode]
    return list(reversed(rows))


def get_sell_history(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> list[dict]:
    """매도 체결 이력 반환 (최신순).
    date_from/date_to: 'YYYY-MM-DD' 형식 날짜 범위 필터. 둘 다 비어있으면 전체.
    today_only=True이면 date_from/date_to 무시하고 오늘만.
    trade_mode: 'real' 또는 'test' 지정 시 해당 모드만 필터링. None이면 전체.
    
    Consumer Task만 인메모리 데이터 수정하므로 Lock 불필요.
    """
    _ensure_loaded()
    rows = _sell_history
    if today_only:
        td = date.today().isoformat()
        rows = [r for r in rows if r.get("date") == td]
    elif date_from or date_to:
        rows = [r for r in rows if _in_date_range(r.get("date", ""), date_from, date_to)]
    if trade_mode is not None:
        rows = [r for r in rows if r.get("trade_mode") == trade_mode]
    return list(reversed(rows))


# ── 집계 API ─────────────────────────────────────────────────────────────────

def get_total_realized_pnl(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> int:
    """실현손익 합계.
    trade_mode: 'real' 또는 'test' 지정 시 해당 모드만 필터링. None이면 전체.
    
    Consumer Task만 인메모리 데이터 수정하므로 Lock 불필요.
    """
    _ensure_loaded()
    rows = _sell_history
    if today_only:
        td = date.today().isoformat()
        rows = [r for r in rows if r.get("date") == td]
    elif date_from or date_to:
        rows = [r for r in rows if _in_date_range(r.get("date", ""), date_from, date_to)]
    if trade_mode is not None:
        rows = [r for r in rows if r.get("trade_mode") == trade_mode]
    return sum(int(r.get("realized_pnl", 0)) for r in rows)


def get_daily_summary(
    *,
    days: int = 5,
    date_from: str = "",
    date_to: str = "",
    trade_mode: Optional[str] = None,
) -> list[dict]:
    """
    일별 요약 -- [{date, buy_count, sell_count, realized_pnl, pnl_rate}].

    date_from/date_to가 주어지면 days 무시, 해당 범위 내 데이터만 집계.
    둘 다 빈 문자열이면 기존 days 기반 로직 (하위 호환).

    days: 거래일(월~금) 기준 조회 기간. 기본 5일(1주).
    date_from/date_to: 'YYYY-MM-DD' 형식 날짜 범위 (inclusive).
    trade_mode: 'real' 또는 'test' 지정 시 해당 모드만 필터링. None이면 전체.
    
    Consumer Task만 인메모리 데이터 수정하므로 Lock 불필요.
    """
    _ensure_loaded()

    use_date_range = bool(date_from or date_to)

    if use_date_range:
        # date_from/date_to 범위 기반 집계
        daily: dict[str, dict] = defaultdict(
            lambda: {"buy_count": 0, "sell_count": 0, "realized_pnl": 0, "buy_total": 0}
        )
        for r in _buy_history:
            d = r.get("date", "")
            if not _in_date_range(d, date_from, date_to):
                continue
            if trade_mode is not None and r.get("trade_mode") != trade_mode:
                continue
            daily[d]["buy_count"] += 1
        for r in _sell_history:
            d = r.get("date", "")
            if not _in_date_range(d, date_from, date_to):
                continue
            if trade_mode is not None and r.get("trade_mode") != trade_mode:
                continue
            daily[d]["sell_count"] += 1
            daily[d]["realized_pnl"] += int(r.get("realized_pnl", 0))
            daily[d]["buy_total"] += int(r.get("buy_total_amt", 0))

        # 데이터가 있는 날짜만 오래된 순으로 반환
        result = []
        for d in sorted(daily.keys()):
            info = daily[d]
            bt = info["buy_total"]
            pr = round(info["realized_pnl"] / bt * 100, 2) if bt > 0 else 0.0
            result.append({
                "date": d,
                "buy_count": info["buy_count"],
                "sell_count": info["sell_count"],
                "realized_pnl": info["realized_pnl"],
                "pnl_rate": pr,
            })
        return result

    # 기존 days 기반 로직 (하위 호환)
    # 최근 N거래일 날짜 목록 (오래된 순)
    trading_dates = _recent_trading_days(days)
    cutoff = trading_dates[0]

    # 실제 데이터 집계
    daily_days: dict[str, dict] = defaultdict(
        lambda: {"buy_count": 0, "sell_count": 0, "realized_pnl": 0, "buy_total": 0}
    )
    for r in _buy_history:
        d = r.get("date", "")
        if d and d >= cutoff:
            if trade_mode is not None and r.get("trade_mode") != trade_mode:
                continue
            daily_days[d]["buy_count"] += 1
    for r in _sell_history:
        d = r.get("date", "")
        if d and d >= cutoff:
            if trade_mode is not None and r.get("trade_mode") != trade_mode:
                continue
            daily_days[d]["sell_count"] += 1
            daily_days[d]["realized_pnl"] += int(r.get("realized_pnl", 0))
            daily_days[d]["buy_total"] += int(r.get("buy_total_amt", 0))

    # N거래일 전부 채워서 반환 (데이터 없는 날 = 0)
    result = []
    for d in trading_dates:
        info = daily_days.get(d)
        if info:
            bt = info["buy_total"]
            pr = round(info["realized_pnl"] / bt * 100, 2) if bt > 0 else 0.0
            result.append({
                "date": d,
                "buy_count": info["buy_count"],
                "sell_count": info["sell_count"],
                "realized_pnl": info["realized_pnl"],
                "pnl_rate": pr,
            })
        else:
            result.append({
                "date": d,
                "buy_count": 0,
                "sell_count": 0,
                "realized_pnl": 0,
                "pnl_rate": 0.0,
            })
    return result


def clear_history() -> None:
    """전체 이력 초기화. 비블로킹 큐 전송."""
    global _buy_history, _sell_history
    _buy_history.clear()
    _sell_history.clear()
    _enqueue_clear_request()  # 비블로킹 큐 전송
    logger.info("[체결이력] 전체 이력 초기화 요청 전송")


def clear_test_history() -> None:
    """테스트모드(trade_mode=='test') 이력만 삭제. 실전 이력은 보존.
    
    비블로킹 큐 전송 - Consumer Task에서 실제 삭제 수행.
    """
    _enqueue_clear_test_request()  # 비블로킹 큐 전송
    logger.info("[체결이력] 테스트 이력 초기화 요청 전송")

def broadcast_history(trade_mode: str) -> None:
    """해당 trade_mode의 매수/매도 이력 및 일별 요약을 브로드캐스트 (초기 스냅샷용)."""
    _broadcast_full_buy_history(trade_mode)
    _broadcast_full_sell_history(trade_mode)
