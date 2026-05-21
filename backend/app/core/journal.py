# -*- coding: utf-8 -*-
"""
Persistence Journaling - Append-only JSON 파일 저널링

책임:
  1. 설정 변경 기록 (SETTINGS_CHANGE)
  2. 주문 요청 기록 (ORDER_REQUEST)
  3. 체결 결과 기록 (FILL_EVENT)
  4. 장애 복구 시 재생 로직

특징:
  - Append-only JSON 파일 (쓰기 전용, 수정 없음)
  - 비동기 Consumer Task (trade_history.py 패턴 따름)
  - Lock 불필요 (Consumer Task 단일 스레드)
  - 순서 보장 (FIFO 큐)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_JOURNAL_FILE = _DATA_DIR / "journal.jsonl"

# ── Producer-Consumer Queue ─────────────────────────────────────────────────
_QUEUE_MAXSIZE = 1000
_io_queue: asyncio.Queue[dict] | None = None
_consumer_task: asyncio.Task[None] | None = None
_shutdown_event: asyncio.Event | None = None

# ── Journal Event Types ──────────────────────────────────────────────────────


class JournalEventType(str, Enum):
    """저널 이벤트 타입"""
    SETTINGS_CHANGE = "settings_change"
    ORDER_REQUEST = "order_request"
    FILL_EVENT = "fill_event"


@dataclass
class JournalEntry:
    """저널 엔트리"""
    event_type: JournalEventType
    timestamp: float
    data: dict[str, Any]
    seq: int  # 시퀀스 번호 (순서 보장)


# ── Sequence Generator ───────────────────────────────────────────────────────
_seq_counter: int = 0


def _next_seq() -> int:
    """다음 시퀀스 번호 생성"""
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ── File I/O ─────────────────────────────────────────────────────────────────


def _append_entry(entry: JournalEntry) -> None:
    """저널 엔트리를 파일에 추가 (Append-only)"""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_JOURNAL_FILE, "a", encoding="utf-8") as f:
            # 한 줄씩 JSON 기록 (JSONL 형식)
            json.dump({
                "event_type": entry.event_type.value,
                "timestamp": entry.timestamp,
                "seq": entry.seq,
                "data": entry.data,
            }, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        logger.error("[Journal] 파일 쓰기 실패: %s", e, exc_info=True)


def _read_all_entries() -> list[JournalEntry]:
    """파일에서 모든 엔트리 읽기 (재생용)"""
    if not _JOURNAL_FILE.exists():
        return []
    
    entries = []
    try:
        with open(_JOURNAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    entry = JournalEntry(
                        event_type=JournalEventType(raw["event_type"]),
                        timestamp=raw["timestamp"],
                        seq=raw["seq"],
                        data=raw["data"],
                    )
                    entries.append(entry)
                except Exception as e:
                    logger.warning("[Journal] 엔트리 파싱 실패 (무시): %s", e)
                    continue
    except Exception as e:
        logger.error("[Journal] 파일 읽기 실패: %s", e, exc_info=True)
    
    # 시퀀스 순서대로 정렬
    entries.sort(key=lambda x: x.seq)
    return entries


# ── Producer-Consumer Queue API ─────────────────────────────────────────────


def _enqueue_write_request(entry: JournalEntry) -> None:
    """쓰기 요청을 큐에 전달 (비블로킹)"""
    global _io_queue
    if _io_queue is None:
        logger.warning("[Journal] Consumer Task 미시작 상태 - 쓰기 요청 무시")
        return
    try:
        _io_queue.put_nowait({"type": "write", "entry": entry})
    except asyncio.QueueFull:
        logger.warning("[Journal] I/O 큐 폭주 - 디스크 쓰기 지연됨 (메모리에는 안전함)")


def _enqueue_compaction_request() -> None:
    """Compaction 요청을 큐에 전달"""
    global _io_queue
    if _io_queue is None:
        logger.warning("[Journal] Consumer Task 미시작 상태 - Compaction 요청 무시")
        return
    try:
        _io_queue.put_nowait({"type": "compact"})
    except asyncio.QueueFull:
        logger.warning("[Journal] I/O 큐 폭주 - Compaction 요청 드롭")


async def _consumer_task_impl() -> None:
    """백그라운드 Consumer Task - 큐에서 요청을 받아 디스크 I/O 처리"""
    global _io_queue, _shutdown_event
    
    while True:
        try:
            if _shutdown_event and _shutdown_event.is_set():
                # 큐에 남은 요청 모두 처리
                while not _io_queue.empty():
                    req = await asyncio.wait_for(_io_queue.get(), timeout=1.0)
                    _process_io_request(req)
                logger.info("[Journal] Consumer Task Graceful Shutdown 완료")
                break
            
            req = await asyncio.wait_for(_io_queue.get(), timeout=1.0)
            _process_io_request(req)
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error("[Journal] Consumer Task 오류: %s", e, exc_info=True)
            await asyncio.sleep(0.1)


def _process_io_request(req: dict) -> None:
    """I/O 요청 처리 (Consumer Task에서 실행)"""
    req_type = req.get("type")
    
    if req_type == "write":
        entry = req.get("entry")
        if entry:
            _append_entry(entry)
    elif req_type == "compact":
        _perform_compaction()
    else:
        logger.warning("[Journal] 알 수 없는 요청 타입: %s", req_type)


def _perform_compaction() -> None:
    """Compaction - 오래된 엔트리 정리"""
    try:
        entries = _read_all_entries()
        # 최근 1000개만 유지 (나머지 삭제)
        if len(entries) > 1000:
            entries = entries[-1000:]
            # 파일 덮어쓰기
            with open(_JOURNAL_FILE, "w", encoding="utf-8") as f:
                for entry in entries:
                    json.dump({
                        "event_type": entry.event_type.value,
                        "timestamp": entry.timestamp,
                        "seq": entry.seq,
                        "data": entry.data,
                    }, f, ensure_ascii=False)
                    f.write("\n")
            logger.info("[Journal] Compaction 완료 - %d개 엔트리 유지", len(entries))
    except Exception as e:
        logger.error("[Journal] Compaction 실패: %s", e, exc_info=True)


# ── Lifecycle Management ─────────────────────────────────────────────────────


def start_consumer_task() -> None:
    """Consumer Task 시작 (앱 시작 시 호출)"""
    global _io_queue, _consumer_task, _shutdown_event
    if _consumer_task is not None:
        logger.warning("[Journal] Consumer Task 이미 실행 중")
        return
    
    _io_queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _consumer_task = loop.create_task(_consumer_task_impl())
    logger.info("[Journal] Consumer Task 시작")


async def stop_consumer_task() -> None:
    """Consumer Task 정지 (앱 종료 시 호출)"""
    global _consumer_task, _shutdown_event, _io_queue
    if _consumer_task is None:
        return
    
    logger.info("[Journal] Consumer Task 종료 요청")
    _shutdown_event.set()
    
    try:
        await asyncio.wait_for(_consumer_task, timeout=5.0)
        logger.info("[Journal] Consumer Task 정상 종료")
    except asyncio.TimeoutError:
        logger.warning("[Journal] Consumer Task 종료 타임아웃 - 강제 취소")
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            logger.info("[Journal] Consumer Task 강제 종료 완료")
    finally:
        _consumer_task = None
        _shutdown_event = None
        _io_queue = None


# ── Public API - 기록 ────────────────────────────────────────────────────────


def record_settings_change(changed_keys: set[str], before: dict, after: dict) -> None:
    """설정 변경 기록"""
    entry = JournalEntry(
        event_type=JournalEventType.SETTINGS_CHANGE,
        timestamp=time.time(),
        data={
            "changed_keys": list(changed_keys),
            "before": before,
            "after": after,
        },
        seq=_next_seq(),
    )
    _enqueue_write_request(entry)
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
    entry = JournalEntry(
        event_type=JournalEventType.ORDER_REQUEST,
        timestamp=time.time(),
        data={
            "order_id": order_id,
            "stock_code": stock_code,
            "side": side,
            "quantity": quantity,
            "price": price,
            "trade_mode": trade_mode,
        },
        seq=_next_seq(),
    )
    _enqueue_write_request(entry)
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
    entry = JournalEntry(
        event_type=JournalEventType.FILL_EVENT,
        timestamp=time.time(),
        data={
            "order_id": order_id,
            "stock_code": stock_code,
            "side": side,
            "fill_quantity": fill_quantity,
            "fill_price": fill_price,
            "trade_mode": trade_mode,
        },
        seq=_next_seq(),
    )
    _enqueue_write_request(entry)
    logger.debug("[Journal] 체결 이벤트 기록 - %s %d주 @%s", order_id, fill_quantity, fill_price)


# ── Public API - 재생 ─────────────────────────────────────────────────────────


def replay_journal(
    settings_change_handler: callable | None = None,
    order_request_handler: callable | None = None,
    fill_event_handler: callable | None = None,
) -> int:
    """저널 재생 - 장애 복구 시 호출
    
    Args:
        settings_change_handler: 설정 변경 핸들러 (entry -> None)
        order_request_handler: 주문 요청 핸들러 (entry -> None)
        fill_event_handler: 체결 이벤트 핸들러 (entry -> None)
    
    Returns:
        재생된 엔트리 수
    """
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
    """저널 파일 초기화"""
    try:
        if _JOURNAL_FILE.exists():
            _JOURNAL_FILE.unlink()
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
