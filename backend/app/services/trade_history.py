# -*- coding: utf-8 -*-
"""
체결 이력 저장 모듈 -- 매수/매도 체결 기록을 메모리+SQLite로 관리.

책임:
  1. record_buy()  -- 매수 체결 기록 (메모리 저장 + DB 비동기 저장)
  2. record_sell() -- 매도 체결 기록 (실현손익 자동 계산 후 메모리+DB 저장)
  3. get_buy_history() / get_sell_history() -- UI 조회용 (메모리 조회)
  4. 일별 요약 (daily_summary) -- 수익현황 탭 좌측 그래프/요약용 (메모리 집계)
  5. 승률 / MDD / 실현손익 집계

영속성: 체결 시 db_writer queue 경유 SQLite 비동기 INSERT.
        앱 기동 시 _ensure_loaded()에서 SQLite → 메모리 로드.
"""
from __future__ import annotations
import logging
from datetime import datetime, date
from typing import Optional
from backend.app.services.engine_utils import LazyLock
logger = logging.getLogger(__name__)

# ── 메모리 저장소 ─────────────────────────────────────────────────────────────
_buy_history: list[dict] = []
_sell_history: list[dict] = []
_history_lock: LazyLock = LazyLock()
_loaded: bool = False

RETENTION_TRADING_DAYS_TEST: int = 30
RETENTION_TRADING_DAYS_REAL: int = 90


# ── 메모리 초기화 ─────────────────────────────────────────────────────────────

async def _ensure_loaded() -> None:
    """앱 기동 시 SQLite → 메모리 로드. 최초 1회만 실행."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        async with conn.execute(
            "SELECT t.ts, t.date, t.time, t.side, t.stk_cd, t.stk_nm, t.price, t.qty,"
            " t.total_amt, t.fee, t.tax, t.avg_buy_price, t.buy_total_amt,"
            " t.realized_pnl, t.pnl_rate, t.reason, t.trade_mode,"
            " cs.name AS sector"
            " FROM trades t"
            " LEFT JOIN custom_sectors cs ON t.stk_cd = cs.stock_code"
            " ORDER BY t.ts DESC"
        ) as cur:
            rows = await cur.fetchall()
        async with _history_lock:
            for row in rows:
                rec = dict(row)
                if rec.get("side") == "BUY":
                    _buy_history.append(rec)
                else:
                    _sell_history.append(rec)
        logger.info(
            "[정산] 체결 이력 로드 완료 — 매수 %d건, 매도 %d건",
            len(_buy_history), len(_sell_history),
        )
    except Exception as e:
        logger.warning("[정산] 체결 이력 로드 실패 (신규 설치 시 정상): %s", e)


async def _migrate_from_json() -> None:
    """No-op - 메모리 전용으로 변경"""
    pass


_TRADE_INSERT_SQL = (
    "INSERT OR IGNORE INTO trades"
    " (ts, date, time, side, stk_cd, stk_nm, price, qty,"
    "  total_amt, fee, tax, avg_buy_price, buy_total_amt,"
    "  realized_pnl, pnl_rate, reason, trade_mode)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _trade_params(rec: dict) -> tuple:
    return (
        rec["ts"], rec["date"], rec["time"], rec["side"],
        rec["stk_cd"], rec["stk_nm"], rec["price"], rec["qty"],
        rec["total_amt"], rec["fee"], rec["tax"],
        rec["avg_buy_price"], rec["buy_total_amt"],
        rec["realized_pnl"], rec["pnl_rate"],
        rec["reason"], rec["trade_mode"],
    )


async def _insert_trade(rec: dict) -> None:
    """메모리에 체결 기록 추가 + DB에 비동기 저장 (db_writer queue 경유).

    메모리 추가 후 dry_run._positions_dirty=True로 설정하여
    _test_positions 캐시가 다음 조회 시 build_positions_from_trades로 재구축되도록 한다.
    (SSOT: trade_history가 유일한 진실 원천, _test_positions는 파생 캐시)
    """
    async with _history_lock:
        if rec["side"] == "BUY":
            _buy_history.insert(0, rec)
        else:
            _sell_history.insert(0, rec)
    # dry_run 포지션 캐시 무효화 (순환 참조 방지: 지연 import)
    try:
        from backend.app.services import dry_run
        dry_run._positions_dirty = True
    except Exception as e:
        logger.warning("[정산] dry_run 포지션 캐시 무효화 실패 (stale 가능): %s", e, exc_info=True)
    try:
        from backend.app.db.db_writer import execute_db_write, DBWriteOperation
        await execute_db_write(DBWriteOperation(
            table="trades", operation="INSERT", data=rec,
            query=_TRADE_INSERT_SQL, params=_trade_params(rec),
        ))
    except Exception as e:
        logger.warning("[정산] DB 저장 큐 실패 (메모리 저장은 완료): %s", e)


async def _trim_expired() -> None:
    """보관 기한 초과 레코드 제거. 모드별 독립 적용."""
    try:
        from backend.app.core.trading_calendar import get_recent_trading_days
        test_cutoff = get_recent_trading_days(RETENTION_TRADING_DAYS_TEST)[0].isoformat()
        real_cutoff = get_recent_trading_days(RETENTION_TRADING_DAYS_REAL)[0].isoformat()

        async with _history_lock:
            _buy_history[:] = [r for r in _buy_history if not (r["trade_mode"] == "test" and r["date"] < test_cutoff)]
            _buy_history[:] = [r for r in _buy_history if not (r["trade_mode"] == "real" and r["date"] < real_cutoff)]
            _sell_history[:] = [r for r in _sell_history if not (r["trade_mode"] == "test" and r["date"] < test_cutoff)]
            _sell_history[:] = [r for r in _sell_history if not (r["trade_mode"] == "real" and r["date"] < real_cutoff)]

        logger.info("[정산] 만료 레코드 정리 완료")
    except Exception as e:
        logger.error("[정산] 만료 레코드 정리 실패: %s", e)


async def _patch_sell_history() -> None:
    """avg_buy_price=0인 매도 건의 실현손익을 보정."""
    patched = 0
    try:
        async with _history_lock:
            for rec in _sell_history:
                if rec["avg_buy_price"] == 0:
                    avg = await _calc_avg_buy_price(rec["stk_cd"])
                    if avg <= 0:
                        continue
                    qty = int(rec["qty"] or 0)
                    sell_price = int(rec["price"] or 0)
                    realized_pnl = (sell_price - avg) * qty
                    rec["avg_buy_price"] = avg
                    rec["realized_pnl"] = realized_pnl
                    rec["pnl_rate"] = round(realized_pnl / (avg * qty) * 100, 2) if qty > 0 else 0.0
                    patched += 1

        if patched > 0:
            logger.info("[정산] 매도 %d건 실현손익 보정 완료", patched)
    except Exception as e:
        logger.error("[정산] 기존 매도건 보정 중 오류: %s", e)


# ── 날짜 유틸 ──────────────────────────────────────────────────────────────

async def _broadcast_sell_append(rec: dict) -> None:
    """매도 체결 후 단건 + 해당 일자 요약을 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        trade_mode = rec.get("trade_mode", "test")
        summary = await get_daily_summary(days=20, trade_mode=trade_mode)
        await ws_manager.broadcast("sell-history-append", {"trade": rec, "daily_summary": summary})
    except Exception as e:
        logger.warning("[정산] 매도 단건 실시간 화면전송 실패: %s", e)


async def _broadcast_buy_append(rec: dict) -> None:
    """매수 체결 후 단건 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        await ws_manager.broadcast("buy-history-append", {"trade": rec})
    except Exception as e:
        logger.warning("[정산] 매수 단건 실시간 화면전송 실패: %s", e)


async def _broadcast_full_sell_history(trade_mode: str) -> None:
    """초기 스냅샷용: 해당 trade_mode의 전체 매도 내역 + 일별 요약을 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        rows = await get_sell_history(trade_mode=trade_mode)
        await ws_manager.broadcast("sell-history-update", {"sell_history": rows})
        summary = await get_daily_summary(days=20, trade_mode=trade_mode)
        await ws_manager.broadcast("daily-summary-update", {"daily_summary": summary})
    except Exception as e:
        logger.warning("[정산] 매도 내역 실시간 화면전송 실패: %s", e)


async def _broadcast_full_buy_history(trade_mode: str) -> None:
    """초기 스냅샷용: 해당 trade_mode의 전체 매수 내역을 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        rows = await get_buy_history(trade_mode=trade_mode)
        await ws_manager.broadcast("buy-history-update", {"buy_history": rows})
    except Exception as e:
        logger.warning("[정산] 매수 내역 실시간 화면전송 실패: %s", e)


async def _broadcast_order_filled(fill_data: dict) -> None:
    """체결 이벤트 발행 -- 거래내역 테이블 즉시 갱신용."""
    try:
        from backend.app.web.ws_manager import ws_manager
        await ws_manager.broadcast("order-filled", fill_data)
    except Exception as e:
        logger.warning("[정산] 체결 이벤트 실시간 화면전송 실패: %s", e)


# ── Lifecycle Management (No-op in SQLite architecture) ────────────────────────

def _reset_global_state() -> None:
    """전역 변수 초기화 (비정상 종료 후 재시작 시 잔존 상태 방지)."""
    global _loaded
    _loaded = False
    _buy_history.clear()
    _sell_history.clear()
    # dry_run 포지션 캐시 무효화
    try:
        from backend.app.services import dry_run
        dry_run._positions_dirty = True
    except Exception as e:
        logger.warning("[정산] dry_run 포지션 캐시 무효화 실패 (stale 가능): %s", e, exc_info=True)


def start_consumer_task() -> None:
    """Consumer Task 시작 (SQLite 구조에서는 사용안함)."""
    pass


async def stop_consumer_task() -> None:
    """Consumer Task 정지 (SQLite 구조에서는 사용안함)."""
    pass


# ── 기록 API ─────────────────────────────────────────────────────────────────

async def record_buy(
    *,
    stk_cd: str,
    stk_nm: str,
    price: int,
    qty: int,
    reason: str = "",
    trade_mode: str = "test",
) -> dict:
    """매수 체결 기록. 반환: 저장된 레코드.

    메인 엔진에서 호출 - 메모리 저장 후 브로드캐스트.
    """
    await _ensure_loaded()
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
        "tax": 0,
        "avg_buy_price": 0,
        "buy_total_amt": 0,
        "realized_pnl": 0,
        "pnl_rate": 0.0,
        "reason": reason,
        "trade_mode": trade_mode,
    }
    logger.info(
        "[정산] 매수 기록 -- %s(%s) %d주 @%s 수수료=%s %s",
        stk_nm, stk_cd, qty, f"{price:,}", f"{fee:,}", reason,
    )
    # 메모리에 저장
    await _insert_trade(rec)
    await _broadcast_buy_append(rec)
    return rec


async def _calc_avg_buy_price(stk_cd: str) -> int:
    """매수 이력에서 해당 종목의 가중평균 매입가를 역산. 매수 기록 없으면 0."""
    async with _history_lock:
        tot_amt = 0
        tot_qty = 0
        for rec in _buy_history:
            if rec["stk_cd"] == stk_cd:
                tot_amt += rec["price"] * rec["qty"]
                tot_qty += rec["qty"]
        if tot_qty == 0:
            return 0
        return round(tot_amt / tot_qty)


async def record_sell(
    *,
    stk_cd: str,
    stk_nm: str,
    price: int,
    qty: int,
    avg_buy_price: int = 0,
    reason: str = "",
    pnl_rate: float = 0.0,  # Legacy field
    trade_mode: str = "test",
) -> dict:
    """매도 체결 기록. 실현손익 자동 계산.

    메인 엔진에서 호출 - 메모리 저장 후 브로드캐스트.
    """
    await _ensure_loaded()
    now = datetime.now()
    # sector 조회 (custom_sectors 테이블에서 단일 소스 진리)
    sector = await _lookup_sector(stk_cd)
    # 안전장치: avg_buy_price가 0이면 유령 데이터 혼입 방지를 위해 실현손익 계산 건너뜀
    if avg_buy_price <= 0:
        logger.warning("[정산] 외부에서 전달된 평균매입가(avg_buy_price)가 0 이하입니다. 유령 데이터 혼입 방지를 위해 실현손익 계산을 건너뜁니다.")
        # realized_pnl 및 pnl_rate를 0으로 처리 (이후 코드에서 avg_buy_price > 0 체크로 안전하게 처리됨)
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
        "sector": sector,
    }
    logger.info(
        "[정산] 매도 기록 -- %s(%s) %d주 @%s 실현손익=%s 수수료=%s 세금=%s %s",
        stk_nm, stk_cd, qty, f"{price:,}",
        f"{realized_pnl:+,}", f"{fee:,}", f"{tax:,}", reason,
    )
    # 메모리에 저장 + DB 비동기 저장
    await _insert_trade(rec)
    await _broadcast_sell_append(rec)
    return rec


async def _lookup_sector(stk_cd: str) -> str:
    """custom_sectors 테이블에서 종목코드로 업종명 조회. 매칭 안 되면 '미분류'."""
    try:
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        async with conn.execute(
            "SELECT name FROM custom_sectors WHERE stock_code = ?", (stk_cd,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return str(row["name"])
    except Exception as e:
        logger.warning("[정산] sector 조회 실패 (%s): %s", stk_cd, e)
    return "미분류"


# ── 조회 API ─────────────────────────────────────────────────────────────────

async def _query_history(side: str, today_only: bool, date_from: str, date_to: str, trade_mode: Optional[str]) -> list[dict]:
    await _ensure_loaded()
    async with _history_lock:
        source = _buy_history if side == "BUY" else _sell_history
        result = []
        for rec in source:
            if trade_mode is not None and rec["trade_mode"] != trade_mode:
                continue
            if today_only:
                td = date.today().isoformat()
                if rec["date"] != td:
                    continue
            else:
                if date_from and rec["date"] < date_from:
                    continue
                if date_to and rec["date"] > date_to:
                    continue
            result.append(rec)
        return result


async def get_buy_history(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> list[dict]:
    """매수 체결 이력 반환 (최신순)."""
    return await _query_history("BUY", today_only, date_from, date_to, trade_mode)


async def get_sell_history(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> list[dict]:
    """매도 체결 이력 반환 (최신순)."""
    return await _query_history("SELL", today_only, date_from, date_to, trade_mode)


# ── 집계 API ─────────────────────────────────────────────────────────────────

async def get_total_realized_pnl(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> int:
    """실현손익 합계."""
    await _ensure_loaded()
    async with _history_lock:
        total = 0
        for rec in _sell_history:
            if trade_mode is not None and rec["trade_mode"] != trade_mode:
                continue
            if today_only:
                td = date.today().isoformat()
                if rec["date"] != td:
                    continue
            else:
                if date_from and rec["date"] < date_from:
                    continue
                if date_to and rec["date"] > date_to:
                    continue
            total += rec["realized_pnl"] or 0
        return total


async def get_daily_summary(
    *,
    days: int = 5,
    date_from: str = "",
    date_to: str = "",
    trade_mode: Optional[str] = None,
) -> list[dict]:
    """
    일별 요약 -- [{date, buy_count, sell_count, realized_pnl, pnl_rate}].
    """
    await _ensure_loaded()
    use_date_range = bool(date_from or date_to)

    trading_dates = []
    if use_date_range:
        if date_from and date_to:
            from datetime import datetime
            start = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
            current = start
            while current <= end:
                trading_dates.append(current.isoformat())
                current = date.fromordinal(current.toordinal() + 1)
    elif days > 0:
        from backend.app.core.trading_calendar import get_recent_trading_days
        trading_dates = [d.isoformat() for d in get_recent_trading_days(days)]
    # days == 0 and not use_date_range: trading_dates를 락 내에서 데이터 기반으로 추출

    async with _history_lock:
        if not use_date_range and days == 0:
            dates_set: set[str] = set()
            for rec in _buy_history:
                if trade_mode is not None and rec["trade_mode"] != trade_mode:
                    continue
                dates_set.add(rec["date"])
            for rec in _sell_history:
                if trade_mode is not None and rec["trade_mode"] != trade_mode:
                    continue
                dates_set.add(rec["date"])
            trading_dates = sorted(dates_set)

        daily_map = {}
        for d in trading_dates:
            buy_count = 0
            sell_count = 0
            realized_pnl = 0
            buy_total = 0
            buy_fee = 0
            sell_fee = 0
            sell_tax = 0
            for rec in _buy_history:
                if trade_mode is not None and rec["trade_mode"] != trade_mode:
                    continue
                if rec["date"] == d:
                    buy_count += 1
                    buy_fee += rec.get("fee") or 0
            for rec in _sell_history:
                if trade_mode is not None and rec["trade_mode"] != trade_mode:
                    continue
                if rec["date"] == d:
                    sell_count += 1
                    realized_pnl += rec["realized_pnl"] or 0
                    buy_total += rec["buy_total_amt"] or 0
                    sell_fee += rec.get("fee") or 0
                    sell_tax += rec.get("tax") or 0
            daily_map[d] = {
                "date": d,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "realized_pnl": realized_pnl,
                "pnl_rate": round(realized_pnl / buy_total * 100, 2) if buy_total > 0 else 0.0,
                "buy_fee": buy_fee,
                "sell_fee": sell_fee,
                "tax": sell_tax,
            }

    result = []
    for d in sorted(trading_dates):
        result.append(daily_map.get(d, {
            "date": d,
            "buy_count": 0,
            "sell_count": 0,
            "realized_pnl": 0,
            "pnl_rate": 0.0,
            "buy_fee": 0,
            "sell_fee": 0,
            "tax": 0,
        }))
    return result


async def clear_test_history() -> None:
    """테스트모드(trade_mode=='test') 이력만 즉시 삭제 (비동기적 수행). 실전 이력은 보존."""
    async with _history_lock:
        _buy_history[:] = [r for r in _buy_history if r["trade_mode"] != "test"]
        _sell_history[:] = [r for r in _sell_history if r["trade_mode"] != "test"]
    # dry_run 포지션 캐시 무횜화
    try:
        from backend.app.services import dry_run
        dry_run._positions_dirty = True
    except Exception as e:
        logger.warning("[정산] dry_run 포지션 캐시 무효화 실패 (stale 가능): %s", e, exc_info=True)
    try:
        from backend.app.db.db_writer import execute_db_write, DBWriteOperation
        await execute_db_write(DBWriteOperation(
            table="trades", operation="DELETE", data={},
            query="DELETE FROM trades WHERE trade_mode = 'test'", params=(),
        ))
    except Exception as e:
        logger.warning("[정산] DB 테스트 이력 삭제 실패: %s", e)
    logger.info("[정산] 테스트 이력 즉시 초기화 완료")


async def broadcast_history(trade_mode: str) -> None:
    """해당 trade_mode의 매수/매도 이력 및 일별 요약을 브로드캐스트 (초기 스냅샷용)."""
    await _broadcast_full_buy_history(trade_mode)
    await _broadcast_full_sell_history(trade_mode)


async def build_positions_from_trades(trade_mode: str) -> dict[str, dict]:
    """trades 이력에서 보유 포지션을 파생. SSOT: trades가 유일한 포지션 진실 원천."""
    await _ensure_loaded()
    positions: dict[str, dict] = {}
    async with _history_lock:
        for rec in _buy_history:
            if rec.get("trade_mode") != trade_mode:
                continue
            cd = rec["stk_cd"]
            qty = int(rec["qty"])
            price = int(rec["price"])
            fee = int(rec.get("fee", 0))
            pos = positions.get(cd)
            if pos:
                old_qty = int(pos["qty"])
                old_avg = int(pos["avg_price"])
                old_fee = int(pos.get("total_fee", 0))
                new_qty = old_qty + qty
                pos["qty"] = new_qty
                pos["avg_price"] = ((old_avg * old_qty) + (price * qty)) // new_qty if new_qty > 0 else price
                pos["total_fee"] = old_fee + fee
                # buy_date를 최초 매수일로 추적 (_buy_history는 DESC 정렬이므로 더 오래된 date가 나중에 옴)
                rec_date = rec.get("date", "")
                if rec_date and (not pos.get("buy_date") or rec_date < pos["buy_date"]):
                    pos["buy_date"] = rec_date
            else:
                positions[cd] = {
                    "stk_cd": cd,
                    "stk_nm": rec.get("stk_nm", ""),
                    "qty": qty,
                    "avg_price": price,
                    "cur_price": price,
                    "total_fee": fee,
                    "buy_amt": price * qty + fee,
                    "eval_amt": price * qty,
                    "pnl_amount": -(fee),
                    "pnl_rate": 0.0,
                    "buy_date": rec.get("date", ""),
                }
        for rec in _sell_history:
            if rec.get("trade_mode") != trade_mode:
                continue
            cd = rec["stk_cd"]
            pos = positions.get(cd)
            if not pos:
                continue
            sell_qty = int(rec["qty"])
            old_qty = int(pos["qty"])
            new_qty = max(0, old_qty - sell_qty)
            if new_qty == 0:
                positions.pop(cd, None)
            else:
                pos["qty"] = new_qty
                pos["total_fee"] = int(pos.get("total_fee", 0) * new_qty / old_qty) if old_qty > 0 else 0
    return positions


async def get_earliest_buy_date(stk_cd: str, trade_mode: str) -> str:
    """해당 종목의 최초 매수일 조회. SSOT: _buy_history에서 파생.

    _buy_history는 DESC 정렬(최신순)이므로 전체 순회하며 최소 date를 추적한다.
    """
    await _ensure_loaded()
    async with _history_lock:
        earliest = ""
        for rec in _buy_history:
            if rec.get("trade_mode") != trade_mode:
                continue
            if rec["stk_cd"] == stk_cd:
                d = rec.get("date", "")
                if d and (not earliest or d < earliest):
                    earliest = d
        return earliest


async def close_db_connection() -> None:
    """No-op - 메모리 전용으로 변경"""
    pass
