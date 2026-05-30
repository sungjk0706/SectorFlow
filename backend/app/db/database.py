import asyncio
import os
import aiosqlite

_db_connection: aiosqlite.Connection | None = None
_db_lock: asyncio.Lock = asyncio.Lock()


async def get_db_connection() -> aiosqlite.Connection:
    """SQLite 데이터베이스 연결 객체 반환 (단일 커넥션 공유)"""
    global _db_connection

    if _db_connection is None:
        db_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if "PYTEST_CURRENT_TEST" in os.environ:
            db_path = os.path.join(db_dir, "data", "stocks_test.db")
        else:
            db_path = os.path.join(db_dir, "data", "stocks.db")

        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        _db_connection = await aiosqlite.connect(db_path)
        _db_connection.row_factory = aiosqlite.Row

        # WAL 모드 활성화
        await _db_connection.execute("PRAGMA journal_mode = WAL;")
        await _db_connection.execute("PRAGMA synchronous = NORMAL;")
        await _db_connection.execute("PRAGMA cache_size = -64000;")
        await _db_connection.execute("PRAGMA temp_store = MEMORY;")

    return _db_connection


async def close_db_connection() -> None:
    """SQLite 데이터베이스 연결 종료"""
    global _db_connection

    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None


def get_db_lock() -> asyncio.Lock:
    """DB 쓰기 Lock 반환"""
    return _db_lock
