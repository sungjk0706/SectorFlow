"""공통 pytest fixture — 전역 캐시 초기화만 수행.

주의: async fixture 사용 금지 — pytest-asyncio 이벤트 루프 정리 중 hang 유발 가능.
asyncio.sleep 전역 패치 금지 — pytest-asyncio 내부 동작 간섭 가능.
각 테스트 파일에서 필요한 asyncio 객체는 반드시 mock으로 대체할 것.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_global_caches():
    """각 테스트 종료 후 전역 캐시 초기화 — 테스트 간 state 누수 방지."""
    yield
    try:
        from backend.app.services.engine_account_notify import notify_cache
        notify_cache.clear_all()
    except Exception:
        pass
    try:
        from backend.app.core import settings_file
        settings_file._migrations_completed = False
    except Exception:
        pass
    try:
        from backend.app.services import trade_history
        trade_history._loaded = False
    except Exception:
        pass
    try:
        import asyncio
        from backend.app.db.database import _db_connection, close_db_connection
        if _db_connection is not None:
            asyncio.run(close_db_connection())
    except Exception:
        pass
