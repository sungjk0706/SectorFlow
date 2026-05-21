# -*- coding: utf-8 -*-
"""
Persistence Journaling 테스트
"""
import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.core.journal import (
    JournalEventType,
    JournalEntry,
    _next_seq,
    record_settings_change,
    record_order_request,
    record_fill_event,
    replay_journal,
    clear_journal,
    get_journal_stats,
    start_consumer_task,
    stop_consumer_task,
)


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_journal_file():
    """임시 저널 파일 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = Path(tmpdir) / "journal.jsonl"
        with patch("backend.app.core.journal._JOURNAL_FILE", journal_path):
            with patch("backend.app.core.journal._DATA_DIR", Path(tmpdir)):
                yield journal_path


@pytest.fixture
async def consumer_task():
    """Consumer Task fixture"""
    start_consumer_task()
    yield
    await stop_consumer_task()


# ── Sequence Generator 테스트 ───────────────────────────────────────────────


def test_sequence_generator():
    """시퀀스 번호 생성 테스트"""
    from backend.app.core.journal import _seq_counter
    
    # 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    seq1 = _next_seq()
    seq2 = _next_seq()
    seq3 = _next_seq()
    
    assert seq1 == 1
    assert seq2 == 2
    assert seq3 == 3


# ── 저널링 기록 테스트 ─────────────────────────────────────────────────────


def test_record_settings_change_direct(temp_journal_file):
    """설정 변경 기록 테스트 (직접 파일 I/O)"""
    from backend.app.core.journal import JournalEntry, _append_entry, _next_seq
    
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    changed_keys = {"auto_buy_on", "buy_amt"}
    before = {"auto_buy_on": False, "buy_amt": 100000}
    after = {"auto_buy_on": True, "buy_amt": 200000}
    
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
    
    # 직접 파일 쓰기
    _append_entry(entry)
    
    # 파일 확인
    assert temp_journal_file.exists()
    with open(temp_journal_file, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        assert line
        data = json.loads(line)
        assert data["event_type"] == "settings_change"
        assert set(data["data"]["changed_keys"]) == changed_keys
        assert data["seq"] == 1


def test_record_order_request_direct(temp_journal_file):
    """주문 요청 기록 테스트 (직접 파일 I/O)"""
    from backend.app.core.journal import JournalEntry, _append_entry, _next_seq
    
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    entry = JournalEntry(
        event_type=JournalEventType.ORDER_REQUEST,
        timestamp=time.time(),
        data={
            "order_id": "ord123",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 10,
            "price": 50000.0,
            "trade_mode": "test",
        },
        seq=_next_seq(),
    )
    
    # 직접 파일 쓰기
    _append_entry(entry)
    
    # 파일 확인
    assert temp_journal_file.exists()
    with open(temp_journal_file, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        assert line
        data = json.loads(line)
        assert data["event_type"] == "order_request"
        assert data["data"]["order_id"] == "ord123"
        assert data["data"]["stock_code"] == "005930"
        assert data["data"]["side"] == "buy"
        assert data["seq"] == 1


def test_record_fill_event_direct(temp_journal_file):
    """체결 이벤트 기록 테스트 (직접 파일 I/O)"""
    from backend.app.core.journal import JournalEntry, _append_entry, _next_seq
    
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    entry = JournalEntry(
        event_type=JournalEventType.FILL_EVENT,
        timestamp=time.time(),
        data={
            "order_id": "ord123",
            "stock_code": "005930",
            "side": "buy",
            "fill_quantity": 10,
            "fill_price": 50000.0,
            "trade_mode": "test",
        },
        seq=_next_seq(),
    )
    
    # 직접 파일 쓰기
    _append_entry(entry)
    
    # 파일 확인
    assert temp_journal_file.exists()
    with open(temp_journal_file, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        assert line
        data = json.loads(line)
        assert data["event_type"] == "fill_event"
        assert data["data"]["order_id"] == "ord123"
        assert data["data"]["fill_quantity"] == 10
        assert data["seq"] == 1


# ── 저널 재생 테스트 ─────────────────────────────────────────────────────────


def test_replay_journal(temp_journal_file):
    """저널 재생 테스트"""
    # 저널 파일 직접 작성
    entries = [
        {
            "event_type": "settings_change",
            "timestamp": time.time(),
            "seq": 1,
            "data": {"changed_keys": ["auto_buy_on"], "before": {}, "after": {}},
        },
        {
            "event_type": "order_request",
            "timestamp": time.time(),
            "seq": 2,
            "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "quantity": 10, "price": 50000.0, "trade_mode": "test"},
        },
        {
            "event_type": "fill_event",
            "timestamp": time.time(),
            "seq": 3,
            "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "fill_quantity": 10, "fill_price": 50000.0, "trade_mode": "test"},
        },
    ]
    
    with open(temp_journal_file, "w", encoding="utf-8") as f:
        for entry in entries:
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    
    # 핸들러 모의
    settings_handler_called = []
    order_handler_called = []
    fill_handler_called = []
    
    def settings_handler(entry):
        settings_handler_called.append(entry)
    
    def order_handler(entry):
        order_handler_called.append(entry)
    
    def fill_handler(entry):
        fill_handler_called.append(entry)
    
    # 재생 실행
    replayed_count = replay_journal(
        settings_change_handler=settings_handler,
        order_request_handler=order_handler,
        fill_event_handler=fill_handler,
    )
    
    assert replayed_count == 3
    assert len(settings_handler_called) == 1
    assert len(order_handler_called) == 1
    assert len(fill_handler_called) == 1


# ── 저널 통계 테스트 ───────────────────────────────────────────────────────


def test_get_journal_stats(temp_journal_file):
    """저널 통계 조회 테스트"""
    # 저널 파일 직접 작성
    entries = [
        {
            "event_type": "settings_change",
            "timestamp": time.time() - 100,
            "seq": 1,
            "data": {"changed_keys": ["auto_buy_on"], "before": {}, "after": {}},
        },
        {
            "event_type": "order_request",
            "timestamp": time.time() - 50,
            "seq": 2,
            "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "quantity": 10, "price": 50000.0, "trade_mode": "test"},
        },
        {
            "event_type": "fill_event",
            "timestamp": time.time(),
            "seq": 3,
            "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "fill_quantity": 10, "fill_price": 50000.0, "trade_mode": "test"},
        },
    ]
    
    with open(temp_journal_file, "w", encoding="utf-8") as f:
        for entry in entries:
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    
    stats = get_journal_stats()
    
    assert stats["total_entries"] == 3
    assert stats["settings_changes"] == 1
    assert stats["order_requests"] == 1
    assert stats["fill_events"] == 1
    assert stats["oldest_timestamp"] is not None
    assert stats["newest_timestamp"] is not None


# ── 저널 초기화 테스트 ─────────────────────────────────────────────────────


def test_clear_journal(temp_journal_file):
    """저널 초기화 테스트"""
    # 저널 파일 작성
    with open(temp_journal_file, "w", encoding="utf-8") as f:
        json.dump({"event_type": "test", "timestamp": time.time(), "seq": 1, "data": {}}, f)
    
    assert temp_journal_file.exists()
    
    # 초기화
    clear_journal()
    
    assert not temp_journal_file.exists()


# ── 복합 테스트 ────────────────────────────────────────────────────────────


def test_journal_lifecycle_direct(temp_journal_file):
    """저널 라이프사이클 테스트 (기록 -> 재생 -> 통계)"""
    from backend.app.core.journal import JournalEntry, _append_entry, _next_seq
    
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    # 기록
    entry1 = JournalEntry(
        event_type=JournalEventType.SETTINGS_CHANGE,
        timestamp=time.time(),
        data={"changed_keys": ["auto_buy_on"], "before": {}, "after": {}},
        seq=_next_seq(),
    )
    _append_entry(entry1)
    
    entry2 = JournalEntry(
        event_type=JournalEventType.ORDER_REQUEST,
        timestamp=time.time(),
        data={"order_id": "ord123", "stock_code": "005930", "side": "buy", "quantity": 10, "price": 50000.0, "trade_mode": "test"},
        seq=_next_seq(),
    )
    _append_entry(entry2)
    
    entry3 = JournalEntry(
        event_type=JournalEventType.FILL_EVENT,
        timestamp=time.time(),
        data={"order_id": "ord123", "stock_code": "005930", "side": "buy", "fill_quantity": 10, "fill_price": 50000.0, "trade_mode": "test"},
        seq=_next_seq(),
    )
    _append_entry(entry3)
    
    # 통계 확인
    stats = get_journal_stats()
    assert stats["total_entries"] == 3
    assert stats["settings_changes"] == 1
    assert stats["order_requests"] == 1
    assert stats["fill_events"] == 1
    
    # 재생
    replayed_count = replay_journal()
    assert replayed_count == 3
