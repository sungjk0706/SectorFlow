"""journal.py 단위 테스트 — 메모리 기반 저널링 전체 API 검증.

_append_entry: 엔트리 추가 + seq 반환 + JournalEntry dataclass 호환
_read_all_entries: 전체 읽기 + 파싱
_perform_compaction: 1000개 초과 시 최근 1000개 유지
record_settings_change / record_order_request / record_fill_event: 공개 API
oms_get_pending_orders / oms_update_order_status / oms_get_next_seq: OMS API
replay_journal: 재생 + 핸들러 호출
clear_journal: 초기화
get_journal_stats: 통계 조회

LazyLock은 실제 asyncio.Lock을 생성하므로 mock으로 대체 (hang 방지).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from backend.app.core.journal import (
    JournalEventType,
    JournalEntry,
    _append_entry,
    _read_all_entries,
    _perform_compaction,
    record_settings_change,
    record_order_request,
    record_fill_event,
    oms_get_pending_orders,
    oms_update_order_status,
    oms_get_next_seq,
    replay_journal,
    clear_journal,
    get_journal_stats,
    start_consumer_task,
    stop_consumer_task,
    close_db_connection,
    _get_conn,
    _ensure_loaded,
    _migrate_from_json,
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
    @pytest.mark.asyncio
    async def test_get_conn_noop(self):
        assert await _get_conn() is None

    @pytest.mark.asyncio
    async def test_ensure_loaded_noop(self):
        assert await _ensure_loaded() is None

    @pytest.mark.asyncio
    async def test_migrate_from_json_noop(self):
        assert await _migrate_from_json() is None

    @pytest.mark.asyncio
    async def test_close_db_connection_noop(self):
        assert await close_db_connection() is None

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


# ── _read_all_entries ─────────────────────────────────────────────────────────────

class TestReadAllEntries:
    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            entries = await _read_all_entries()
        assert entries == []

    @pytest.mark.asyncio
    async def test_reads_all_entries_as_dataclass(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {"a": 1}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0, "data": {"b": 2}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            entries = await _read_all_entries()
        assert len(entries) == 2
        assert entries[0].event_type == JournalEventType.SETTINGS_CHANGE
        assert entries[0].seq == 1
        assert entries[1].event_type == JournalEventType.ORDER_REQUEST
        assert entries[1].seq == 2

    @pytest.mark.asyncio
    async def test_invalid_event_type_skipped(self):
        from backend.app.core import journal
        journal._journal_entries.append({
            "id": 1, "event_type": "invalid_type", "timestamp": 1000.0, "data": {},
        })
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            entries = await _read_all_entries()
        assert entries == []


# ── _perform_compaction ───────────────────────────────────────────────────────────

class TestPerformCompaction:
    @pytest.mark.asyncio
    async def test_under_1000_no_compaction(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": i, "event_type": "test", "timestamp": float(i), "data": {}}
            for i in range(500)
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await _perform_compaction()
        assert len(journal._journal_entries) == 500

    @pytest.mark.asyncio
    async def test_over_1000_keeps_last_1000(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": i, "event_type": "test", "timestamp": float(i), "data": {}}
            for i in range(1200)
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await _perform_compaction()
        assert len(journal._journal_entries) == 1000
        # 가장 오래된 200개가 삭제됨
        assert journal._journal_entries[0]["id"] == 200


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


# ── record_fill_event ─────────────────────────────────────────────────────────────

class TestRecordFillEvent:
    @pytest.mark.asyncio
    async def test_records_correctly(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await record_fill_event("ord001", "005930", "BUY", 10, 70050.0, "test")
        from backend.app.core import journal
        row = journal._journal_entries[0]
        assert row["event_type"] == "fill_event"
        assert row["data"]["order_id"] == "ord001"
        assert row["data"]["fill_quantity"] == 10
        assert row["data"]["fill_price"] == 70050.0


# ── oms_get_pending_orders ─────────────────────────────────────────────────────────

class TestOmsGetPendingOrders:
    @pytest.mark.asyncio
    async def test_empty_returns_empty(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            result = await oms_get_pending_orders()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_only_pending_orders(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "order_request", "timestamp": 1000.0,
             "data": {"order_id": "ord1", "status": "pending"}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0,
             "data": {"order_id": "ord2", "status": "filled"}},
            {"id": 3, "event_type": "order_request", "timestamp": 3000.0,
             "data": {"order_id": "ord3", "status": "pending"}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            result = await oms_get_pending_orders()
        assert len(result) == 2
        assert result[0]["order_id"] == "ord1"
        assert result[1]["order_id"] == "ord3"

    @pytest.mark.asyncio
    async def test_non_order_entries_ignored(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {}},
            {"id": 2, "event_type": "fill_event", "timestamp": 2000.0, "data": {}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            result = await oms_get_pending_orders()
        assert result == []


# ── oms_update_order_status ───────────────────────────────────────────────────────

class TestOmsUpdateOrderStatus:
    @pytest.mark.asyncio
    async def test_updates_matching_order(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "order_request", "timestamp": 1000.0,
             "data": {"order_id": "ord1", "status": "pending"}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await oms_update_order_status("ord1", "filled")
        assert journal._journal_entries[0]["data"]["status"] == "filled"

    @pytest.mark.asyncio
    async def test_no_match_does_nothing(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "order_request", "timestamp": 1000.0,
             "data": {"order_id": "ord1", "status": "pending"}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await oms_update_order_status("nonexistent", "filled")
        assert journal._journal_entries[0]["data"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_updates_only_matching_order_id(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "order_request", "timestamp": 1000.0,
             "data": {"order_id": "ord1", "status": "pending"}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0,
             "data": {"order_id": "ord2", "status": "pending"}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await oms_update_order_status("ord2", "cancelled")
        assert journal._journal_entries[0]["data"]["status"] == "pending"
        assert journal._journal_entries[1]["data"]["status"] == "cancelled"


# ── oms_get_next_seq ──────────────────────────────────────────────────────────────

class TestOmsGetNextSeq:
    @pytest.mark.asyncio
    async def test_empty_returns_1(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            seq = await oms_get_next_seq()
        assert seq == 1

    @pytest.mark.asyncio
    async def test_with_entries_returns_next(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "test", "timestamp": 1000.0, "data": {}},
            {"id": 2, "event_type": "test", "timestamp": 2000.0, "data": {}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            seq = await oms_get_next_seq()
        assert seq == 3


# ── replay_journal ────────────────────────────────────────────────────────────────

class TestReplayJournal:
    @pytest.mark.asyncio
    async def test_empty_returns_zero(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            count = await replay_journal()
        assert count == 0

    @pytest.mark.asyncio
    async def test_replays_all_entries(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {"a": 1}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0, "data": {"b": 2}},
            {"id": 3, "event_type": "fill_event", "timestamp": 3000.0, "data": {"c": 3}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            count = await replay_journal()
        assert count == 3

    @pytest.mark.asyncio
    async def test_calls_handlers_by_type(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {"a": 1}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0, "data": {"b": 2}},
            {"id": 3, "event_type": "fill_event", "timestamp": 3000.0, "data": {"c": 3}},
        ])
        settings_handler = MagicMock()
        order_handler = MagicMock()
        fill_handler = MagicMock()
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            count = await replay_journal(
                settings_change_handler=settings_handler,
                order_request_handler=order_handler,
                fill_event_handler=fill_handler,
            )
        assert count == 3
        settings_handler.assert_called_once()
        order_handler.assert_called_once()
        fill_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_stop_replay(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {}},
            {"id": 2, "event_type": "settings_change", "timestamp": 2000.0, "data": {}},
        ])
        bad_handler = MagicMock(side_effect=Exception("handler error"))
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            count = await replay_journal(settings_change_handler=bad_handler)
        # 핸들러 예외 시 replayed_count 증가 안 함 — 0 반환
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_handler_skips_entry(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0, "data": {}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            count = await replay_journal(settings_change_handler=MagicMock())
        # settings_change는 핸들러 있음, order_request는 핸들러 없음 → 둘 다 카운트됨
        assert count == 2


# ── clear_journal ──────────────────────────────────────────────────────────────────

class TestClearJournal:
    @pytest.mark.asyncio
    async def test_clears_all_entries(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "test", "timestamp": 1000.0, "data": {}},
            {"id": 2, "event_type": "test", "timestamp": 2000.0, "data": {}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await clear_journal()
        assert len(journal._journal_entries) == 0

    @pytest.mark.asyncio
    async def test_clear_empty_no_error(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            await clear_journal()


# ── get_journal_stats ──────────────────────────────────────────────────────────────

class TestGetJournalStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self):
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            stats = await get_journal_stats()
        assert stats["total_entries"] == 0
        assert stats["settings_changes"] == 0
        assert stats["order_requests"] == 0
        assert stats["fill_events"] == 0
        assert stats["oldest_timestamp"] is None
        assert stats["newest_timestamp"] is None

    @pytest.mark.asyncio
    async def test_stats_with_entries(self):
        from backend.app.core import journal
        journal._journal_entries.extend([
            {"id": 1, "event_type": "settings_change", "timestamp": 1000.0, "data": {}},
            {"id": 2, "event_type": "order_request", "timestamp": 2000.0, "data": {}},
            {"id": 3, "event_type": "order_request", "timestamp": 3000.0, "data": {}},
            {"id": 4, "event_type": "fill_event", "timestamp": 4000.0, "data": {}},
        ])
        with patch("backend.app.core.journal._journal_lock", _fake_lock_ctx()):
            stats = await get_journal_stats()
        assert stats["total_entries"] == 4
        assert stats["settings_changes"] == 1
        assert stats["order_requests"] == 2
        assert stats["fill_events"] == 1
        assert stats["oldest_timestamp"] == 1000.0
        assert stats["newest_timestamp"] == 4000.0


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────────

def _fake_lock_ctx():
    """asynccontextmanager를 반환 — _journal_lock 대체용."""
    @asynccontextmanager
    async def _ctx():
        yield
    return _ctx()
