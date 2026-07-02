from __future__ import annotations
# -*- coding: utf-8 -*-
"""
Persistence Journaling - 메모리 기반 저널링

책임:
  1. 설정 변경 기록 (SETTINGS_CHANGE)
  2. 주문 요청 기록 (ORDER_REQUEST)
  3. 체결 결과 기록 (FILL_EVENT)
  4. 장애 복구 시 재생 로직

특징:
  - 메모리 기반 저널링 (실시간 파이프라인 DB 접근 금지)
  - 순서 보장 (리스트 순서)
  - 장마감 후 배치 파이프라인에서 DB 저장
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ── 메모리 저장소 ─────────────────────────────────────────────────────────────
_journal_entries: list[dict] = []
_journal_lock: asyncio.Lock = asyncio.Lock()


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

async def _get_conn() -> None:
    """No-op - 메모리 전용으로 변경"""
    pass


async def _ensure_loaded() -> None:
    """No-op - 메모리 전용으로 변경"""
    pass


async def _migrate_from_json() -> None:
    """No-op - 메모리 전용으로 변경"""
    pass


# ── File I/O ─────────────────────────────────────────────────────────────────

async def _append_entry(event_type: Any, timestamp: float | None = None, data: dict | None = None) -> int:
    """저널 엔트리를 메모리에 추가하고 seq 반환"""
    await _ensure_loaded()

    # 1. dataclass 및 인자 하위 호환 파싱
    if hasattr(event_type, "event_type"):  # JournalEntry dataclass
        entry = event_type
        evt_type = entry.event_type.value if hasattr(entry.event_type, "value") else str(entry.event_type)
        evt_ts = entry.timestamp
        evt_data = entry.data
    else:
        evt_type = event_type
        evt_ts = timestamp
        evt_data = data

    seq = 0
    try:
        async with _journal_lock:
            seq = len(_journal_entries) + 1
            _journal_entries.append({
                "id": seq,
                "event_type": evt_type,
                "timestamp": evt_ts,
                "data": evt_data
            })
    except Exception as e:
        logger.error("[Journal] 메모리 쓰기 실패: %s", e, exc_info=True)

    return seq


async def _read_all_entries() -> list[JournalEntry]:
    """메모리에서 모든 엔트리 읽기"""
    await _ensure_loaded()
    entries = []
    try:
        async with _journal_lock:
            for row in _journal_entries:
                try:
                    event_type = JournalEventType(row["event_type"])
                    entries.append(JournalEntry(
                        event_type=event_type,
                        timestamp=row["timestamp"],
                        seq=row["id"],
                        data=row["data"],
                    ))
                except Exception as e:
                    logger.warning("[Journal] 엔트리 파싱 실패 (id=%s): %s", row["id"], e)
    except Exception as e:
        logger.error("[Journal] 메모리 읽기 실패: %s", e, exc_info=True)
    return entries


async def _perform_compaction() -> None:
    """Compaction - 오래된 엔트리 정리 (최근 1000개 유지)"""
    await _ensure_loaded()
    try:
        async with _journal_lock:
            if len(_journal_entries) > 1000:
                cutoff_index = len(_journal_entries) - 1000
                removed = _journal_entries[:cutoff_index]
                _journal_entries[:] = _journal_entries[cutoff_index:]
                logger.info("[Journal] Compaction 완료 - %d개 이전 엔트리 삭제됨", len(removed))
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

async def record_settings_change(changed_keys: set[str], before: dict, after: dict) -> None:
    """설정 변경 기록"""
    await _append_entry(
        JournalEventType.SETTINGS_CHANGE.value,
        time.time(),
        {
            "changed_keys": list(changed_keys),
            "before": before,
            "after": after,
        }
    )


async def record_order_request(
    order_id: str,
    stock_code: str,
    side: str,
    quantity: int,
    price: float,
    trade_mode: str,
) -> None:
    """주문 요청 기록"""
    await _append_entry(
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


async def record_fill_event(
    order_id: str,
    stock_code: str,
    side: str,
    fill_quantity: int,
    fill_price: float,
    trade_mode: str,
) -> None:
    """체결 이벤트 기록"""
    await _append_entry(
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


# ── OMS 전용 메서드 ─────────────────────────────────────────────────────────

async def oms_get_pending_orders() -> list[dict]:
    """OMS용 로컬 장부에서 Pending 상태인 주문 조회"""
    await _ensure_loaded()
    pending = []
    try:
        async with _journal_lock:
            for row in _journal_entries:
                if row["event_type"] == JournalEventType.ORDER_REQUEST.value:
                    data = row["data"]
                    if data.get("status") == "pending":
                        pending.append(data)
    except Exception as e:
        logger.error("[Journal] Pending 주문 조회 실패: %s", e, exc_info=True)
    return pending


async def oms_update_order_status(order_id: str, status: str) -> None:
    """OMS용 주문 상태 업데이트"""
    await _ensure_loaded()
    try:
        async with _journal_lock:
            for row in _journal_entries:
                if row["event_type"] == JournalEventType.ORDER_REQUEST.value:
                    data = row["data"]
                    if data.get("order_id") == order_id:
                        data["status"] = status
                        return
    except Exception as e:
        logger.error("[Journal] 주문 상태 업데이트 실패: %s", e, exc_info=True)


async def oms_get_next_seq() -> int:
    """OMS용 다음 시퀀스 번호 발급"""
    await _ensure_loaded()
    try:
        async with _journal_lock:
            return len(_journal_entries) + 1
    except Exception:
        return 1

_next_seq = oms_get_next_seq


# ── Public API - 재생 ─────────────────────────────────────────────────────────

async def replay_journal(
    settings_change_handler: callable | None = None,
    order_request_handler: callable | None = None,
    fill_event_handler: callable | None = None,
) -> int:
    """저널 재생"""
    entries = await _read_all_entries()
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


async def clear_journal() -> None:
    """저널 초기화"""
    await _ensure_loaded()
    try:
        async with _journal_lock:
            _journal_entries.clear()
        logger.info("[Journal] 저널 초기화 완료")
    except Exception as e:
        logger.error("[Journal] 저널 초기화 실패: %s", e, exc_info=True)


async def get_journal_stats() -> dict[str, Any]:
    """저널 통계 조회"""
    entries = await _read_all_entries()

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


async def close_db_connection() -> None:
    """No-op - 메모리 전용으로 변경"""
    pass
