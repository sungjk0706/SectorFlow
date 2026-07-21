"""journal.py 단위 테스트 — 메모리 기반 저널링 API 검증.

_append_entry: 엔트리 추가 + seq 반환 + JournalEntry dataclass 호환
record_settings_change / record_order_request: 공개 API
start_consumer_task / stop_consumer_task: 생명주기 (no-op)

LazyLock은 실제 asyncio.Lock을 생성하므로 mock으로 대체 (hang 방지).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from contextlib import asynccontextmanager

from backend.app.core.journal import (
    JournalEventType,
    JournalEntry,
    _append_entry,
    record_settings_change,
    record_order_request,
    start_consumer_task,
    stop_consumer_task,
)


# ── 헬퍼: LazyLock mock ────────────────────────────────────────────────────────

@asynccontextmanager
async def _fake_lock():
    yield


@pytest.fixture(autouse=True)
def _reset_journal():
    """각 테스트 전후로 저널 엔트리 초기화 + LazyLock mock."""
    from backend.app.core import journal
    journal._journal_entries.clear()
    with patch.object(journal._journal_lock, "_get_lock", return_value=MagicMock()):
        yield
    journal._journal_entries.clear()


# ── JournalEventType ────────────────────────────────────────────────────────────

class TestJournalEventType:
    def test_values(self):
        assert JournalEventType.SETTINGS_CHANGE.value == "settings_change"
        assert JournalEventType.ORDER_REQUEST.value == "order_request"
        assert JournalEventType.FILL_EVENT.value == "fill_event"
        assert JournalEventType.ORDER_STATUS_UPDATE.value == "order_status_update"

    def test_is_str_enum(self):
        assert isinstance(JournalEventType.SETTINGS_CHANGE, str)


# ── JournalEntry ────────────────────────────────────────────────────────────────

class TestJournalEntry:
    def test_dataclass_fields(self):
        entry = JournalEntry(
            event_type=JournalEventType.SETTINGS_CHANGE,
            timestamp=1234567890.0,
            data={"key": "value"},
            seq=1,
        )
        assert entry.event_type == JournalEventType.SETTINGS_CHANGE
        assert entry.timestamp == 1234567890.0
        assert entry.data == {"key": "value"}
        assert entry.seq == 1


# ── No-op 함수 ──────────────────────────────────────────────────────────────────

class TestNoopFunctions:
    def test_start_consumer_task_noop(self):
        assert start_consumer_task() is None

    @pytest.mark.asyncio
    async def test_stop_consumer_task_noop(self):
        assert await stop_consumer_task() is None


# ── _append_entry ────────────────────────────────────────────────────────────────

class TestAppendEntry:
    @pytest.mark.asyncio
    async def test_append_first_entry_returns_seq_1(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            seq = await _append_entry("settings_change", 1000.0, {"key": "val"})
        assert seq == 1

    @pytest.mark.asyncio
    async def test_append_second_entry_returns_seq_2(self):
        from backend.app.core import journal
        journal._journal_entries.append({"id": 1, "event_type": "test", "timestamp": 1000.0, "data": {}})
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            seq = await _append_entry("order_request", 2000.0, {"order": "buy"})
        assert seq == 2

    @pytest.mark.asyncio
    async def test_append_journal_entry_dataclass(self):
        entry = JournalEntry(
            event_type=JournalEventType.FILL_EVENT,
            timestamp=3000.0,
            data={"fill": "data"},
            seq=0,
        )
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            seq = await _append_entry(entry)
        assert seq == 1
        from backend.app.core import journal
        assert journal._journal_entries[0]["event_type"] == "fill_event"
        assert journal._journal_entries[0]["data"] == {"fill": "data"}

    @pytest.mark.asyncio
    async def test_append_stores_correct_fields(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await _append_entry("fill_event", 5000.0, {"price": 70000})
        from backend.app.core import journal
        row = journal._journal_entries[0]
        assert row["id"] == 1
        assert row["event_type"] == "fill_event"
        assert row["timestamp"] == 5000.0
        assert row["data"] == {"price": 70000}


# ── record_settings_change ────────────────────────────────────────────────────────

class TestRecordSettingsChange:
    @pytest.mark.asyncio
    async def test_records_correctly(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await record_settings_change({"tele_on"}, {"tele_on": False}, {"tele_on": True})
        from backend.app.core import journal
        row = journal._journal_entries[0]
        assert row["event_type"] == "settings_change"
        assert row["data"]["changed_keys"] == ["tele_on"]
        assert row["data"]["before"] == {"tele_on": False}
        assert row["data"]["after"] == {"tele_on": True}
        assert row["timestamp"] is not None


# ── record_order_request ──────────────────────────────────────────────────────────

class TestRecordOrderRequest:
    @pytest.mark.asyncio
    async def test_records_correctly(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await record_order_request("ord001", "005930", "BUY", 10, 70000.0, "test")
        from backend.app.core import journal
        row = journal._journal_entries[0]
        assert row["event_type"] == "order_request"
        assert row["data"]["order_id"] == "ord001"
        assert row["data"]["stock_code"] == "005930"
        assert row["data"]["side"] == "BUY"
        assert row["data"]["quantity"] == 10
        assert row["data"]["price"] == 70000.0
        assert row["data"]["trade_mode"] == "test"
        assert row["data"]["status"] == "pending"


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────────

def _fake_lock_ctx():
    """asynccontextmanager를 반환 — _journal_lock 대체용."""
    @asynccontextmanager
    async def _ctx():
        yield
    return _ctx()
