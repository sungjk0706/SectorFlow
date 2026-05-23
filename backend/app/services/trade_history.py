# -*- coding: utf-8 -*-
"""
체결 이력 저장 모듈 -- 매수/매도 체결 기록을 SQLite 로 관리.

책임:
  1. record_buy()  -- 매수 체결 기록 (SQLite INSERT)
  2. record_sell() -- 매도 체결 기록 (실현손익 자동 계산 후 SQLite INSERT)
  3. get_buy_history() / get_sell_history() -- UI 조회용 (SQLite SELECT)
  4. 일별 요약 (daily_summary) -- 수익현황 탭 좌측 그래프/요약용 (SQLite GROUP BY)
  5. 승률 / MDD / 실현손익 집계
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_FILE = _DATA_DIR / "trade_history.db"
_OLD_JSON_FILE = _DATA_DIR / "trade_history.json"

# ── 보관 기한 상수 ─────────────────────────────────────────────────────────────
RETENTION_TRADING_DAYS_TEST: int = 60
RETENTION_TRADING_DAYS_REAL: int = 5

_db_lock = threading.Lock()
_loaded: bool = False


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_FILE), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


# ── 파일/DB 초기화 및 마이그레이션 ──────────────────────────────────────────────

def _ensure_loaded() -> None:
    """최초 호출 시 DB 초기화 + 기존 JSON 데이터 마이그레이션 + 만료 레코드 트림."""
    global _loaded
    if _loaded:
        return

    with _db_lock:
        if _loaded:
            return

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        with _get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    date TEXT,
                    time TEXT,
                    side TEXT,
                    stk_cd TEXT,
                    stk_nm TEXT,
                    price INTEGER,
                    qty INTEGER,
                    total_amt INTEGER,
                    fee INTEGER,
                    tax INTEGER,
                    avg_buy_price INTEGER,
                    buy_total_amt INTEGER,
                    realized_pnl INTEGER,
                    pnl_rate REAL,
                    reason TEXT,
                    trade_mode TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(trade_mode)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_side ON trades(side)")
            
        _migrate_from_json()
        _trim_expired()
        _patch_sell_history()
        
        _loaded = True


def _migrate_from_json() -> None:
    """기존 trade_history.json이 존재하면 SQLite로 마이그레이션."""
    if not _OLD_JSON_FILE.exists():
        return
        
    try:
        with _get_conn() as conn:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM trades")
            if cursor.fetchone()["cnt"] > 0:
                # 이미 데이터가 있으면 마이그레이션 생략하고 백업 파일로 변경
                _OLD_JSON_FILE.rename(_OLD_JSON_FILE.with_suffix(".json.bak"))
                return
                
        with open(_OLD_JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        buy_history = data.get("buy", [])
        sell_history = data.get("sell", [])
        
        with _get_conn() as conn:
            with conn: # 트랜잭션
                for b in buy_history:
                    _insert_trade(conn, {**b, "side": "BUY"})
                for s in sell_history:
                    _insert_trade(conn, {**s, "side": "SELL"})
                    
        _OLD_JSON_FILE.rename(_OLD_JSON_FILE.with_suffix(".json.bak"))
        logger.info("[체결이력] JSON 데이터 SQLite 마이그레이션 완료 (매수 %d건, 매도 %d건)", len(buy_history), len(sell_history))
    except Exception as e:
        logger.error("[체결이력] 마이그레이션 실패: %s", e, exc_info=True)


def _insert_trade(conn: sqlite3.Connection, rec: dict) -> None:
    conn.execute("""
        INSERT INTO trades (
            ts, date, time, side, stk_cd, stk_nm, price, qty, 
            total_amt, fee, tax, avg_buy_price, buy_total_amt, 
            realized_pnl, pnl_rate, reason, trade_mode
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, 
            ?, ?, ?, ?, ?, 
            ?, ?, ?, ?
        )
    """, (
        rec.get("ts"), rec.get("date"), rec.get("time"), rec.get("side"),
        rec.get("stk_cd"), rec.get("stk_nm"), rec.get("price", 0), rec.get("qty", 0),
        rec.get("total_amt", 0), rec.get("fee", 0), rec.get("tax", 0),
        rec.get("avg_buy_price", 0), rec.get("buy_total_amt", 0),
        rec.get("realized_pnl", 0), rec.get("pnl_rate", 0.0),
        rec.get("reason", ""), rec.get("trade_mode", "test")
    ))


def _trim_expired() -> None:
    """보관 기한 초과 레코드 제거. 모드별 독립 적용."""
    try:
        from backend.app.core.trading_calendar import recent_business_days
        test_cutoff = recent_business_days(RETENTION_TRADING_DAYS_TEST)[0].isoformat()
        real_cutoff = recent_business_days(RETENTION_TRADING_DAYS_REAL)[0].isoformat()
        
        with _get_conn() as conn:
            with conn: # 트랜잭션
                c1 = conn.execute("DELETE FROM trades WHERE trade_mode = 'test' AND date < ?", (test_cutoff,))
                c2 = conn.execute("DELETE FROM trades WHERE trade_mode = 'real' AND date < ?", (real_cutoff,))
                
                trimmed = c1.rowcount + c2.rowcount
                if trimmed > 0:
                    logger.info("[체결이력] 로드 시 만료 레코드 %d건 정리 (test<%s, real<%s)", trimmed, test_cutoff, real_cutoff)
    except Exception as e:
        logger.error("[체결이력] 만료 레코드 정리 실패: %s", e)


def _patch_sell_history() -> None:
    """avg_buy_price=0인 매도 건의 실현손익을 보정."""
    patched = 0
    try:
        with _get_conn() as conn:
            with conn:
                cursor = conn.execute("SELECT id, stk_cd, price, qty FROM trades WHERE side = 'SELL' AND avg_buy_price = 0")
                rows = cursor.fetchall()
                for row in rows:
                    stk_cd = row["stk_cd"]
                    # Calculate avg_buy_price based on buy history up to this point? 
                    # Simple approach: overall average
                    avg = _calc_avg_buy_price_internal(conn, stk_cd)
                    if avg <= 0:
                        continue
                    
                    qty = int(row["qty"] or 0)
                    sell_price = int(row["price"] or 0)
                    realized_pnl = (sell_price - avg) * qty
                    
                    conn.execute("""
                        UPDATE trades 
                        SET avg_buy_price = ?, realized_pnl = ? 
                        WHERE id = ?
                    """, (avg, realized_pnl, row["id"]))
                    patched += 1
                    
        if patched > 0:
            logger.info("[체결이력] 매도 %d건 실현손익 보정 완료", patched)
    except Exception as e:
        logger.error("[체결이력] 기존 매도건 보정 중 오류: %s", e)


# ── 날짜 유틸 ──────────────────────────────────────────────────────────────

def _broadcast_sell_append(rec: dict) -> None:
    """매도 체결 후 단건 + 해당 일자 요약을 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        trade_mode = rec.get("trade_mode", "test")
        summary = get_daily_summary(days=20, trade_mode=trade_mode)
        ws_manager.broadcast("sell-history-append", {"trade": rec, "daily_summary": summary})
    except Exception as e:
        logger.warning("[체결이력] 매도 단건 실시간 화면전송 실패: %s", e)


def _broadcast_buy_append(rec: dict) -> None:
    """매수 체결 후 단건 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        ws_manager.broadcast("buy-history-append", {"trade": rec})
    except Exception as e:
        logger.warning("[체결이력] 매수 단건 실시간 화면전송 실패: %s", e)


def _broadcast_full_sell_history(trade_mode: str) -> None:
    """초기 스냅샷용: 해당 trade_mode의 전체 매도 내역 + 일별 요약을 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        rows = get_sell_history(trade_mode=trade_mode)
        ws_manager.broadcast("sell-history-update", {"sell_history": rows})
        summary = get_daily_summary(days=20, trade_mode=trade_mode)
        ws_manager.broadcast("daily-summary-update", {"daily_summary": summary})
    except Exception as e:
        logger.warning("[체결이력] 매도 내역 실시간 화면전송 실패: %s", e)


def _broadcast_full_buy_history(trade_mode: str) -> None:
    """초기 스냅샷용: 해당 trade_mode의 전체 매수 내역을 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        rows = get_buy_history(trade_mode=trade_mode)
        ws_manager.broadcast("buy-history-update", {"buy_history": rows})
    except Exception as e:
        logger.warning("[체결이력] 매수 내역 실시간 화면전송 실패: %s", e)


def _broadcast_order_filled(fill_data: dict) -> None:
    """체결 이벤트 발행 -- 거래내역 테이블 즉시 갱신용."""
    try:
        from backend.app.web.ws_manager import ws_manager
        ws_manager.broadcast("order-filled", fill_data)
    except Exception as e:
        logger.warning("[체결이력] 체결 이벤트 실시간 화면전송 실패: %s", e)


# ── Lifecycle Management (No-op in SQLite architecture) ────────────────────────

def _reset_global_state() -> None:
    """전역 변수 초기화 (테스트용)."""
    global _loaded
    _loaded = False


def start_consumer_task() -> None:
    """Consumer Task 시작 (SQLite 구조에서는 사용안함)."""
    pass


async def stop_consumer_task() -> None:
    """Consumer Task 정지 (SQLite 구조에서는 사용안함)."""
    pass


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
    
    메인 엔진에서 호출 - 즉시 SQLite DB 저장 후 브로드캐스트.
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
        "tax": 0,
        "avg_buy_price": 0,
        "buy_total_amt": 0,
        "realized_pnl": 0,
        "pnl_rate": 0.0,
        "reason": reason,
        "trade_mode": trade_mode,
    }
    logger.info(
        "[체결이력] 매수 기록 -- %s(%s) %d주 @%s 수수료=%s %s",
        stk_nm, stk_cd, qty, f"{price:,}", f"{fee:,}", reason,
    )
    # 실전모드: 증권사 서버가 원본이므로 로컬 저장 불필요
    if trade_mode != "real":
        with _db_lock:
            with _get_conn() as conn:
                with conn:
                    _insert_trade(conn, rec)
    _broadcast_buy_append(rec)
    return rec


def _calc_avg_buy_price_internal(conn: sqlite3.Connection, stk_cd: str) -> int:
    cursor = conn.execute(
        "SELECT SUM(price * qty) as tot_amt, SUM(qty) as tot_qty FROM trades WHERE side = 'BUY' AND stk_cd = ?",
        (stk_cd,)
    )
    row = cursor.fetchone()
    tot_amt = row["tot_amt"] or 0
    tot_qty = row["tot_qty"] or 0
    if tot_qty == 0:
        return 0
    return round(tot_amt / tot_qty)


def _calc_avg_buy_price(stk_cd: str) -> int:
    """매수 이력에서 해당 종목의 가중평균 매입가를 역산. 매수 기록 없으면 0."""
    with _db_lock:
        with _get_conn() as conn:
            return _calc_avg_buy_price_internal(conn, stk_cd)


def record_sell(
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
    
    메인 엔진에서 호출 - 즉시 SQLite DB 저장 후 브로드캐스트.
    """
    _ensure_loaded()
    now = datetime.now()
    # 안전장치: avg_buy_price가 0이면 유령 데이터 혼입 방지를 위해 실현손익 계산 건너뜀
    if avg_buy_price <= 0:
        logger.warning("[체결이력] 외부에서 전달된 평균매입가(avg_buy_price)가 0 이하입니다. 유령 데이터 혼입 방지를 위해 실현손익 계산을 건너뜁니다.")
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
    }
    logger.info(
        "[체결이력] 매도 기록 -- %s(%s) %d주 @%s 실현손익=%s 수수료=%s 세금=%s %s",
        stk_nm, stk_cd, qty, f"{price:,}",
        f"{realized_pnl:+,}", f"{fee:,}", f"{tax:,}", reason,
    )
    # 실전모드: 증권사 서버가 원본이므로 로컬 저장 불필요
    if trade_mode != "real":
        with _db_lock:
            with _get_conn() as conn:
                with conn:
                    _insert_trade(conn, rec)
    _broadcast_sell_append(rec)
    return rec


# ── 조회 API ─────────────────────────────────────────────────────────────────

def _query_history(side: str, today_only: bool, date_from: str, date_to: str, trade_mode: Optional[str]) -> list[dict]:
    _ensure_loaded()
    query = "SELECT * FROM trades WHERE side = ?"
    params = [side]
    
    if today_only:
        td = date.today().isoformat()
        query += " AND date = ?"
        params.append(td)
    else:
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
            
    if trade_mode is not None:
        query += " AND trade_mode = ?"
        params.append(trade_mode)
        
    query += " ORDER BY id DESC"
    
    with _get_conn() as conn:
        cursor = conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def get_buy_history(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> list[dict]:
    """매수 체결 이력 반환 (최신순)."""
    return _query_history("BUY", today_only, date_from, date_to, trade_mode)


def get_sell_history(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> list[dict]:
    """매도 체결 이력 반환 (최신순)."""
    return _query_history("SELL", today_only, date_from, date_to, trade_mode)


# ── 집계 API ─────────────────────────────────────────────────────────────────

def get_total_realized_pnl(*, today_only: bool = False, date_from: str = "", date_to: str = "", trade_mode: Optional[str] = None) -> int:
    """실현손익 합계."""
    _ensure_loaded()
    query = "SELECT SUM(realized_pnl) as pnl FROM trades WHERE side = 'SELL'"
    params = []
    
    if today_only:
        td = date.today().isoformat()
        query += " AND date = ?"
        params.append(td)
    else:
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
            
    if trade_mode is not None:
        query += " AND trade_mode = ?"
        params.append(trade_mode)
        
    with _get_conn() as conn:
        cursor = conn.execute(query, tuple(params))
        row = cursor.fetchone()
        return row["pnl"] if row and row["pnl"] is not None else 0


def get_daily_summary(
    *,
    days: int = 5,
    date_from: str = "",
    date_to: str = "",
    trade_mode: Optional[str] = None,
) -> list[dict]:
    """
    일별 요약 -- [{date, buy_count, sell_count, realized_pnl, pnl_rate}].
    """
    _ensure_loaded()
    use_date_range = bool(date_from or date_to)
    
    query = """
        SELECT 
            date, 
            SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) as buy_count,
            SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) as sell_count,
            SUM(CASE WHEN side = 'SELL' THEN realized_pnl ELSE 0 END) as realized_pnl,
            SUM(CASE WHEN side = 'SELL' THEN buy_total_amt ELSE 0 END) as buy_total
        FROM trades
        WHERE 1=1
    """
    params = []
    
    trading_dates = []
    if use_date_range:
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
    else:
        from backend.app.core.trading_calendar import recent_business_days
        trading_dates = [d.isoformat() for d in recent_business_days(days)]
        if trading_dates:
            cutoff = sorted(trading_dates)[0]
            query += " AND date >= ?"
            params.append(cutoff)

    if trade_mode is not None:
        query += " AND trade_mode = ?"
        params.append(trade_mode)
        
    query += " GROUP BY date ORDER BY date ASC"
    
    with _get_conn() as conn:
        cursor = conn.execute(query, tuple(params))
        db_rows = cursor.fetchall()
        
    daily_map = {}
    for row in db_rows:
        bt = row["buy_total"] or 0
        realized_pnl = row["realized_pnl"] or 0
        daily_map[row["date"]] = {
            "date": row["date"],
            "buy_count": row["buy_count"] or 0,
            "sell_count": row["sell_count"] or 0,
            "realized_pnl": realized_pnl,
            "pnl_rate": round(realized_pnl / bt * 100, 2) if bt > 0 else 0.0
        }
        
    result = []
    if use_date_range:
        for d in sorted(daily_map.keys()):
            result.append(daily_map[d])
    else:
        for d in sorted(trading_dates):
            if d in daily_map:
                result.append(daily_map[d])
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
    """전체 이력 즉시 초기화 (동기적 수행)."""
    with _db_lock:
        with _get_conn() as conn:
            with conn:
                conn.execute("DELETE FROM trades")
    logger.info("[체결이력] 전체 이력 즉시 초기화 완료")


def clear_test_history() -> None:
    """테스트모드(trade_mode=='test') 이력만 즉시 삭제 (동기적 수행). 실전 이력은 보존."""
    with _db_lock:
        with _get_conn() as conn:
            with conn:
                conn.execute("DELETE FROM trades WHERE trade_mode = 'test'")
    logger.info("[체결이력] 테스트 이력 즉시 초기화 완료")


def broadcast_history(trade_mode: str) -> None:
    """해당 trade_mode의 매수/매도 이력 및 일별 요약을 브로드캐스트 (초기 스냅샷용)."""
    _broadcast_full_buy_history(trade_mode)
    _broadcast_full_sell_history(trade_mode)
