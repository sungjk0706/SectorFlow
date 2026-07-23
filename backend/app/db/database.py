import logging
import os
from pathlib import Path

import aiosqlite

from backend.app.services.engine_utils import LazyLock

_db_connection: aiosqlite.Connection | None = None
_db_lock: LazyLock = LazyLock()

_logger = logging.getLogger(__name__)

# 백업 파일 보관 세트 수 — 한 세트 = 같은 타임스탬프의 db/shm/wal 백업 3종.
_BACKUP_KEEP_SETS = 1


async def get_db_connection() -> aiosqlite.Connection:
    """SQLite 데이터베이스 연결 객체 반환 (단일 커넥션 공유)"""
    global _db_connection

    if _db_connection is None:
        db_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(db_dir, "data", "stocks.db")

        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        _db_connection = await aiosqlite.connect(db_path)
        _db_connection.row_factory = aiosqlite.Row

        # WAL 모드 활성화
        await _db_connection.execute("PRAGMA journal_mode = WAL;")
        await _db_connection.execute("PRAGMA synchronous = NORMAL;")
        await _db_connection.execute("PRAGMA cache_size = -64000;")
        await _db_connection.execute("PRAGMA temp_store = MEMORY;")
        await _db_connection.execute("PRAGMA mmap_size = 268435456;")

    return _db_connection


async def close_db_connection() -> None:
    """SQLite 데이터베이스 연결 종료"""
    global _db_connection

    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None


def get_db_lock() -> LazyLock:
    """DB 쓰기 Lock 반환"""
    return _db_lock


def _db_dir() -> Path:
    """stocks.db 가 위치한 디렉토리 경로 (P10 SSOT — get_db_connection 경로 계산과 동일)."""
    return Path(__file__).resolve().parent.parent.parent / "data"


def cleanup_old_backups(keep: int = _BACKUP_KEEP_SETS, data_dir: Path | None = None) -> int:
    """오래된 DB 백업 파일 정리 — 최근 ``keep`` 세트만 남기고 삭제.

    한 "세트" = 같은 타임스탬프의 ``stocks.db`` / ``stocks.db-shm`` / ``stocks.db-wal`` 백업 3종.
    ``stocks.db`` 본체·``-shm``·``-wal``·``sectorflow.db``는 절대 삭제하지 않으며
    ``.backup`` 확장자만 대상으로 한다 (P22 데이터 정합성).

    Returns:
        삭제된 파일 수.
    """
    base = data_dir if data_dir is not None else _db_dir()

    # 타임스탬스 추출 — stocks.db.{TS}.backup / stocks.db-shm.{TS}.backup / stocks.db-wal.{TS}.backup
    prefixes = ("stocks.db.", "stocks.db-shm.", "stocks.db-wal.")
    suffix = ".backup"
    timestamps: set[str] = set()
    for p in base.glob("stocks.db*.backup"):
        name = p.name
        for prefix in prefixes:
            if name.startswith(prefix) and name.endswith(suffix):
                timestamps.add(name[len(prefix):-len(suffix)])
                break

    if not timestamps:
        return 0

    # 최신 타임스탬스 순 정렬, 최근 keep세트 외 삭제
    to_delete = sorted(timestamps, reverse=True)[keep:]
    deleted = 0
    for ts in to_delete:
        for prefix in prefixes:
            target = base / f"{prefix}{ts}{suffix}"
            if not target.exists():
                continue
            try:
                target.unlink()
                deleted += 1
            except OSError as e:
                _logger.warning("[DB] 백업 파일 삭제 실패 — %s: %s", target, e)

    if deleted:
        _logger.info("[DB] 오래된 백업 파일 %d개 정리 완료 (최근 %d세트 보존)", deleted, keep)
    return deleted
