# -*- coding: utf-8 -*-
"""
Persistence Journaling - SQLite 기반 저널링

책임:
  1. 설정 변경 기록 (SETTINGS_CHANGE)
  2. 주문 요청 기록 (ORDER_REQUEST)
  3. 체결 결과 기록 (FILL_EVENT)
  4. 장애 복구 시 재생 로직

특징:
  - SQLite를 활용한 동기식 즉시 기록 (Race Condition 방지)
  - WAL 모드 적용으로 I/O 병목 완화
  - 순서 보장 (AUTOINCREMENT id)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_FILE = _DATA_DIR / "journal.db"
_OLD_JSON_FILE = _DATA_DIR / "journal.jsonl"

_db_lock = threading.Lock()
_loaded = False


# ── Journal Event Types ──────────────────────────────────────────────────────

class JournalEventType(str, Enum):
    """저널 이벤트 타입"""
    SETTINGS_CHANGE = "settings_change"
    ORDER_REQUEST = "order_request"
    FILL_EVENT = "fill_event"
    ORDER_STATUS_UPDATE = "order_status_update"  # OMS용 상태 업데이트 추가


@dataclass
class JournalEntry:
    """저널 엔트리"""
    event_type: JournalEventType
    timestamp: float
    data: dict[str, Any]
    seq: int  # SQLite id와 매핑


# ── DB Connection ─────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_FILE), timeout=10.0)
    # WAL 모드 활성화로 동시 읽기/쓰기 성능 향상
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_loaded() -> None:
    """DB 초기화 및 마이그레이션"""
    global _loaded
    if _loaded:
        return

    with _db_lock:
        if _loaded:
            return

        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT,
                    timestamp REAL,
                    data TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_type ON journal(event_type)")
            
        _migrate_from_json()
        _loaded = True


def _migrate_from_json() -> None:
    """기존 journal.jsonl 파일 마이그레이션"""
    if not _OLD_JSON_FILE.exists():
        return
        
    try:
        with _get_conn() as conn:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM journal")
            if cursor.fetchone()["cnt"] > 0:
                _OLD_JSON_FILE.rename(_OLD_JSON_FILE.with_suffix(".jsonl.bak"))
                return
                
        entries_to_insert = []
        with open(_OLD_JSON_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    entries_to_insert.append((
                        raw["event_type"],
                        raw["timestamp"],
                        json.dumps(raw["data"], ensure_ascii=False)
                    ))
                except Exception:
                    pass
                    
        if entries_to_insert:
            with _get_conn() as conn:
                with conn:
                    conn.executemany(
                        "INSERT INTO journal (event_type, timestamp, data) VALUES (?, ?, ?)",
                        entries_to_insert
                    )
                    
        _OLD_JSON_FILE.rename(_OLD_JSON_FILE.with_suffix(".jsonl.bak"))
        logger.info("[Journal] JSONL 데이터 SQLite 마이그레이션 완료 (%d건)", len(entries_to_insert))
    except Exception as e:
        logger.error("[Journal] 마이그레이션 실패: %s", e, exc_info=True)


# ── File I/O ─────────────────────────────────────────────────────────────────

def _append_entry(event_type: str, timestamp: float, data: dict) -> int:
    """저널 엔트리를 DB에 추가하고 seq 반환"""
    _ensure_loaded()
    try:
        with _db_lock:
            with _get_conn() as conn:
                with conn:
                    cursor = conn.execute(
                        "INSERT INTO journal (event_type, timestamp, data) VALUES (?, ?, ?)",
                        (event_type, timestamp, json.dumps(data, ensure_ascii=False))
                    )
                    return cursor.lastrowid or 0
    except Exception as e:
        logger.error("[Journal] DB 쓰기 실패: %s", e, exc_info=True)
        return 0


def _read_all_entries() -> list[JournalEntry]:
    """DB에서 모든 엔트리 읽기"""
    _ensure_loaded()
    entries = []
    try:
        with _get_conn() as conn:
            cursor = conn.execute("SELECT id, event_type, timestamp, data FROM journal ORDER BY id ASC")
            for row in cursor.fetchall():
                try:
                    event_type = JournalEventType(row["event_type"])
                    entries.append(JournalEntry(
                        event_type=event_type,
                        timestamp=row["timestamp"],
                        seq=row["id"],
                        data=json.loads(row["data"]),
                    ))
                except Exception as e:
                    logger.warning("[Journal] 엔트리 파싱 실패 (id=%s): %s", row["id"], e)
    except Exception as e:
        logger.error("[Journal] DB 읽기 실패: %s", e, exc_info=True)
    return entries


def _perform_compaction() -> None:
    """Compaction - 오래된 엔트리 정리 (최근 1000개 유지)"""
    _ensure_loaded()
    try:
        with _db_lock:
            with _get_conn() as conn:
                with conn:
                    # 보존할 시작 ID 찾기
                    cursor = conn.execute("SELECT id FROM journal ORDER BY id DESC LIMIT 1 OFFSET 1000")
                    row = cursor.fetchone()
                    if row:
                        cutoff_id = row["id"]
                        cursor = conn.execute("DELETE FROM journal WHERE id <= ?", (cutoff_id,))
                        logger.info("[Journal] Compaction 완료 - %d개 이전 엔트리 삭제됨", cursor.rowcount)
    except Exception as e:
        logger.error("[Journal] Compaction 실패: %s", e, exc_info=True)


# ── Lifecycle Management (No-op in SQLite) ───────────────────────────────────

def start_consumer_task() -> None:
    """Consumer Task 시작 (SQLite 구조에서는 사용안함)"""
    pass


async def stop_consumer_task() -> None:
    """Consumer Task 정지 (SQLite 구조에서는 사용안함)"""
    pass


# ── Public API - 기록 ────────────────────────────────────────────────────────

def record_settings_change(changed_keys: set[str], before: dict, after: dict) -> None:
    """설정 변경 기록"""
    _append_entry(
        JournalEventType.SETTINGS_CHANGE.value,
        time.time(),
        {
            "changed_keys": list(changed_keys),
            "before": before,
            "after": after,
        }
    )
    logger.debug("[Journal] 설정 변경 기록 - 키: %s", changed_keys)


def record_order_request(
    order_id: str,
    stock_code: str,
    side: str,
    quantity: int,
    price: float,
    trade_mode: str,
) -> None:
    """주문 요청 기록"""
    _append_entry(
        JournalEventType.ORDER_REQUEST.value,
        time.time(),
        {
            "order_id": order_id,
            "stock_code": stock_code,
            "side": side,
            "quantity": quantity,
            "price": price,
            "trade_mode": trade_mode,
            "status": "pending",
        }
    )
    logger.debug("[Journal] 주문 요청 기록 - %s %s %d주", order_id, side, quantity)


def record_fill_event(
    order_id: str,
    stock_code: str,
    side: str,
    fill_quantity: int,
    fill_price: float,
    trade_mode: str,
) -> None:
    """체결 이벤트 기록"""
    _append_entry(
        JournalEventType.FILL_EVENT.value,
        time.time(),
        {
            "order_id": order_id,
            "stock_code": stock_code,
            "side": side,
            "fill_quantity": fill_quantity,
            "fill_price": fill_price,
            "trade_mode": trade_mode,
        }
    )
    logger.debug("[Journal] 체결 이벤트 기록 - %s %d주 @%s", order_id, fill_quantity, fill_price)


# ── OMS 전용 메서드 ─────────────────────────────────────────────────────────

def oms_get_pending_orders() -> list[dict]:
    """OMS용 로컬 장부에서 Pending 상태인 주문 조회"""
    _ensure_loaded()
    pending = []
    try:
        # JSON 데이터 내부를 검색하는 대신 가장 단순하게 전체 ORDER_REQUEST를 읽어서 필터링
        with _get_conn() as conn:
            cursor = conn.execute("SELECT id, data FROM journal WHERE event_type = ?", (JournalEventType.ORDER_REQUEST.value,))
            for row in cursor.fetchall():
                try:
                    data = json.loads(row["data"])
                    if data.get("status") == "pending":
                        pending.append(data)
                except Exception:
                    pass
    except Exception as e:
        logger.error("[Journal] Pending 주문 조회 실패: %s", e, exc_info=True)
    return pending


def oms_update_order_status(order_id: str, status: str) -> None:
    """OMS용 주문 상태 업데이트"""
    _ensure_loaded()
    try:
        with _db_lock:
            with _get_conn() as conn:
                # 해당 order_id를 가진 엔트리를 찾아 갱신
                cursor = conn.execute("SELECT id, data FROM journal WHERE event_type = ?", (JournalEventType.ORDER_REQUEST.value,))
                for row in cursor.fetchall():
                    data = json.loads(row["data"])
                    if data.get("order_id") == order_id:
                        data["status"] = status
                        with conn:
                            conn.execute(
                                "UPDATE journal SET data = ? WHERE id = ?",
                                (json.dumps(data, ensure_ascii=False), row["id"])
                            )
                        logger.debug("[Journal] 주문 상태 업데이트 - order_id=%s, status=%s", order_id, status)
                        return
    except Exception as e:
        logger.error("[Journal] 주문 상태 업데이트 실패: %s", e, exc_info=True)


def oms_get_next_seq() -> int:
    """OMS용 다음 시퀀스 번호 발급 (SQLite의 AUTOINCREMENT를 모방)"""
    _ensure_loaded()
    try:
        with _get_conn() as conn:
            cursor = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='journal'")
            row = cursor.fetchone()
            if row:
                return row["seq"] + 1
            return 1
    except Exception:
        return 1


# ── Public API - 재생 ─────────────────────────────────────────────────────────

def replay_journal(
    settings_change_handler: callable | None = None,
    order_request_handler: callable | None = None,
    fill_event_handler: callable | None = None,
) -> int:
    """저널 재생"""
    entries = _read_all_entries()
    replayed_count = 0
    
    for entry in entries:
        try:
            if entry.event_type == JournalEventType.SETTINGS_CHANGE and settings_change_handler:
                settings_change_handler(entry)
            elif entry.event_type == JournalEventType.ORDER_REQUEST and order_request_handler:
                order_request_handler(entry)
            elif entry.event_type == JournalEventType.FILL_EVENT and fill_event_handler:
                fill_event_handler(entry)
            replayed_count += 1
        except Exception as e:
            logger.error("[Journal] 엔트리 재생 실패 (seq=%d): %s", entry.seq, e, exc_info=True)
            continue
    
    logger.info("[Journal] 저널 재생 완료 - %d/%d 엔트리 재생됨", replayed_count, len(entries))
    return replayed_count


def clear_journal() -> None:
    """저널 초기화"""
    try:
        with _db_lock:
            with _get_conn() as conn:
                with conn:
                    conn.execute("DELETE FROM journal")
                    # SQLite 시퀀스 초기화
                    conn.execute("DELETE FROM sqlite_sequence WHERE name='journal'")
        logger.info("[Journal] 저널 파일 초기화 완료")
    except Exception as e:
        logger.error("[Journal] 저널 파일 초기화 실패: %s", e, exc_info=True)


def get_journal_stats() -> dict[str, Any]:
    """저널 통계 조회"""
    entries = _read_all_entries()
    
    stats = {
        "total_entries": len(entries),
        "settings_changes": 0,
        "order_requests": 0,
        "fill_events": 0,
        "oldest_timestamp": None,
        "newest_timestamp": None,
    }
    
    if entries:
        stats["oldest_timestamp"] = entries[0].timestamp
        stats["newest_timestamp"] = entries[-1].timestamp
        
        for entry in entries:
            if entry.event_type == JournalEventType.SETTINGS_CHANGE:
                stats["settings_changes"] += 1
            elif entry.event_type == JournalEventType.ORDER_REQUEST:
                stats["order_requests"] += 1
            elif entry.event_type == JournalEventType.FILL_EVENT:
                stats["fill_events"] += 1
    
    return stats
