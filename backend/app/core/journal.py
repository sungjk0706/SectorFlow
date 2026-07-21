# -*- coding: utf-8 -*-
"""
영속성 저널링 - 메모리 기반 저널링

책임:
  1. 설정 변경 기록 (SETTINGS_CHANGE)
  2. 주문 요청 기록 (ORDER_REQUEST)

특징:
  - 메모리 기반 저널링 (실시간 파이프라인 DB 접근 금지)
  - 순서 보장 (리스트 순서)
  - 장마감 후 배치 파이프라인에서 DB 저장
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any
from backend.app.services.engine_utils import LazyLock
logger = logging.getLogger(__name__)

# ── 메모리 저장소 ─────────────────────────────────────────────────────────────
_journal_entries: list[dict] = []
_journal_lock: LazyLock = LazyLock()


# ── 저널 이벤트 타입 ──────────────────────────────────────────────────────────

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


# ── 파일 입출력 ────────────────────────────────────────────────────────────────

async def _append_entry(event_type: Any, timestamp: float | None = None, data: dict | None = None) -> int:
    """저널 엔트리를 메모리에 추가하고 seq 반환"""
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
        logger.error("[연산] 메모리 쓰기 실패: %s", e, exc_info=True)

    return seq


# ── 생명주기 관리 (SQLite에서 작업 없음) ────────────────────────────────────────

def start_consumer_task() -> None:
    """컨슈머 작업 시작 (SQLite 구조에서는 사용안함)"""
    pass


async def stop_consumer_task() -> None:
    """컨슈머 작업 정지 (SQLite 구조에서는 사용안함)"""
    pass


# ── 공개 API - 기록 ────────────────────────────────────────────────────────────

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
