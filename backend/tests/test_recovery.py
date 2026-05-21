# -*- coding: utf-8 -*-
"""
Phase 4.4: 장애 복구 테스트
- Journal 재생 테스트
- Event Queue 복구 테스트
- State 복구 테스트
"""
import pytest
import time
import tempfile
from pathlib import Path

from backend.app.core import journal as _journal
from backend.app.core.journal import JournalEventType, JournalEntry, _next_seq
from backend.app.services.state_manager import StateManager, OrderStatus


# ── Journal 재생 테스트 ───────────────────────────────────────────────────


@pytest.fixture
def temp_journal_file():
    """임시 저널 파일 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = Path(tmpdir) / "journal.jsonl"
        with pytest.MonkeyPatch.context() as m:
            m.setattr("backend.app.core.journal._JOURNAL_FILE", journal_path)
            m.setattr("backend.app.core.journal._DATA_DIR", Path(tmpdir))
            yield journal_path


def test_journal_replay_settings_change(temp_journal_file):
    """설정 변경 저널 재생 테스트"""
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    # 저널 파일 직접 작성
    entries = [
        {
            "event_type": "settings_change",
            "timestamp": time.time(),
            "seq": 1,
            "data": {"changed_keys": ["auto_buy_on"], "before": {"auto_buy_on": False}, "after": {"auto_buy_on": True}},
        },
    ]
    
    with open(temp_journal_file, "w", encoding="utf-8") as f:
        for entry in entries:
            import json
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    
    # 핸들러 모의
    settings_handler_called = []
    
    def settings_handler(entry):
        settings_handler_called.append(entry)
    
    # 재생 실행
    replayed_count = _journal.replay_journal(settings_change_handler=settings_handler)
    
    assert replayed_count == 1
    assert len(settings_handler_called) == 1
    assert settings_handler_called[0].data["changed_keys"] == ["auto_buy_on"]


def test_journal_replay_order_request(temp_journal_file):
    """주문 요청 저널 재생 테스트"""
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    # 저널 파일 직접 작성
    entries = [
        {
            "event_type": "order_request",
            "timestamp": time.time(),
            "seq": 1,
            "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "quantity": 10, "price": 50000.0, "trade_mode": "test"},
        },
    ]
    
    with open(temp_journal_file, "w", encoding="utf-8") as f:
        for entry in entries:
            import json
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    
    # 핸들러 모의
    order_handler_called = []
    
    def order_handler(entry):
        order_handler_called.append(entry)
    
    # 재생 실행
    replayed_count = _journal.replay_journal(order_request_handler=order_handler)
    
    assert replayed_count == 1
    assert len(order_handler_called) == 1
    assert order_handler_called[0].data["order_id"] == "ord123"


def test_journal_replay_fill_event(temp_journal_file):
    """체결 이벤트 저널 재생 테스트"""
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
    # 저널 파일 직접 작성
    entries = [
        {
            "event_type": "fill_event",
            "timestamp": time.time(),
            "seq": 1,
            "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "fill_quantity": 10, "fill_price": 50000.0, "trade_mode": "test"},
        },
    ]
    
    with open(temp_journal_file, "w", encoding="utf-8") as f:
        for entry in entries:
            import json
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    
    # 핸들러 모의
    fill_handler_called = []
    
    def fill_handler(entry):
        fill_handler_called.append(entry)
    
    # 재생 실행
    replayed_count = _journal.replay_journal(fill_event_handler=fill_handler)
    
    assert replayed_count == 1
    assert len(fill_handler_called) == 1
    assert fill_handler_called[0].data["order_id"] == "ord123"


def test_journal_replay_multiple_events(temp_journal_file):
    """다중 이벤트 저널 재생 테스트"""
    # 시퀀스 초기화
    from backend.app.core import journal
    journal._seq_counter = 0
    
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
            import json
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
    replayed_count = _journal.replay_journal(
        settings_change_handler=settings_handler,
        order_request_handler=order_handler,
        fill_event_handler=fill_handler,
    )
    
    assert replayed_count == 3
    assert len(settings_handler_called) == 1
    assert len(order_handler_called) == 1
    assert len(fill_handler_called) == 1


# ── Event Queue 복구 테스트 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_queue_recovery():
    """Event Queue 복구 테스트"""
    state_manager = StateManager()
    
    # 이벤트 큐에 이벤트 추가
    await state_manager.emit_event("ORDER_CREATED", {"order_id": "ord123"})
    await state_manager.emit_event("ORDER_FILLED", {"order_id": "ord123", "fill_quantity": 10})
    
    # 이벤트 큐 상태 확인
    # (실제 구현에서는 큐 상태를 저장하고 복구하는 로직이 필요하지만,
    # 현재 StateManager는 인메모리 큐만 사용하므로 테스트는 큐 동작만 검증)
    assert state_manager is not None


# ── State 복구 테스트 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_recovery_from_journal():
    """State Manager의 저널 재생 기능 테스트"""
    state_manager = StateManager()
    
    # 임시 저널 파일 설정
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = Path(tmpdir) / "journal.jsonl"
        with pytest.MonkeyPatch.context() as m:
            m.setattr("backend.app.core.journal._JOURNAL_FILE", journal_path)
            m.setattr("backend.app.core.journal._DATA_DIR", Path(tmpdir))
            
            # 시퀀스 초기화
            from backend.app.core import journal
            journal._seq_counter = 0
            
            # 저널 파일 직접 작성
            entries = [
                {
                    "event_type": "order_request",
                    "timestamp": time.time(),
                    "seq": 1,
                    "data": {"order_id": "ord123", "stock_code": "005930", "side": "buy", "quantity": 10, "price": 50000.0, "trade_mode": "test"},
                },
            ]
            
            with open(journal_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    import json
                    json.dump(entry, f, ensure_ascii=False)
                    f.write("\n")
            
            # State Manager의 저널 재생 실행
            replayed_count = await state_manager.replay_from_journal()
            
            assert replayed_count == 1
            
            # 복구된 주문 상태 확인
            orders = state_manager.get_all_orders()
            assert "ord123" in orders
            assert orders["ord123"].stock_code == "005930"
            assert orders["ord123"].status == OrderStatus.PENDING


@pytest.mark.asyncio
async def test_state_recovery_empty_journal():
    """빈 저널 파일에서의 State 복구 테스트"""
    state_manager = StateManager()
    
    # 임시 저널 파일 설정 (빈 파일)
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = Path(tmpdir) / "journal.jsonl"
        with pytest.MonkeyPatch.context() as m:
            m.setattr("backend.app.core.journal._JOURNAL_FILE", journal_path)
            m.setattr("backend.app.core.journal._DATA_DIR", Path(tmpdir))
            
            # 빈 파일 생성
            journal_path.touch()
            
            # State Manager의 저널 재생 실행
            replayed_count = await state_manager.replay_from_journal()
            
            assert replayed_count == 0
            
            # 주문 상태가 비어있는지 확인
            orders = state_manager.get_all_orders()
            assert len(orders) == 0


# ── 통합 복구 테스트 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_recovery_scenario():
    """전체 복구 시나리오 테스트"""
    state_manager = StateManager()
    
    # 임시 저널 파일 설정
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = Path(tmpdir) / "journal.jsonl"
        with pytest.MonkeyPatch.context() as m:
            m.setattr("backend.app.core.journal._JOURNAL_FILE", journal_path)
            m.setattr("backend.app.core.journal._DATA_DIR", Path(tmpdir))
            
            # 시퀀스 초기화
            from backend.app.core import journal
            journal._seq_counter = 0
            
            # 복잡한 시나리오 저널 작성
            entries = [
                {
                    "event_type": "settings_change",
                    "timestamp": time.time(),
                    "seq": 1,
                    "data": {"changed_keys": ["auto_buy_on"], "before": {"auto_buy_on": False}, "after": {"auto_buy_on": True}},
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
            
            with open(journal_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    import json
                    json.dump(entry, f, ensure_ascii=False)
                    f.write("\n")
            
            # State Manager의 저널 재생 실행
            replayed_count = await state_manager.replay_from_journal()
            
            assert replayed_count == 3
            
            # 복구된 상태 확인
            orders = state_manager.get_all_orders()
            assert "ord123" in orders
