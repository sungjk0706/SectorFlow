"""database.py cleanup_old_backups 단위 테스트 — 오래된 DB 백업 파일 자동 정리 검증.

검증 항목:
  - 최근 keep세트만 남고 나머지 세트는 삭제된다.
  - 같은 타임스탬스의 db/shm/wal 3종이 함께 정리된다.
  - stocks.db 본체·stocks.db-shm·stocks.db-wal·sectorflow.db는 절대 삭제되지 않는다 (P22).
  - keep=0이면 모든 백업 세트가 삭제된다.
  - 백업이 없으면 0을 반환하고 본체는 건드리지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from backend.app.db.database import cleanup_old_backups


def _make_backup_set(data_dir: Path, ts: str, *, with_shm: bool = True, with_wal: bool = True) -> None:
    """한 타임스탬스 세트(db/shm/wal) 생성 헬퍼."""
    (data_dir / f"stocks.db.{ts}.backup").write_bytes(b"backup")
    if with_shm:
        (data_dir / f"stocks.db-shm.{ts}.backup").write_bytes(b"shm")
    if with_wal:
        (data_dir / f"stocks.db-wal.{ts}.backup").write_bytes(b"wal")


def _make_live_db(data_dir: Path) -> None:
    """본체 DB 파일 생성 — 정리 대상이 아니어야 함."""
    (data_dir / "stocks.db").write_bytes(b"live-db")
    (data_dir / "stocks.db-shm").write_bytes(b"live-shm")
    (data_dir / "stocks.db-wal").write_bytes(b"live-wal")
    (data_dir / "sectorflow.db").write_bytes(b"sectorflow")


def test_keeps_only_latest_set(tmp_path: Path) -> None:
    """최근 1세트만 남고 나머지는 삭제."""
    _make_live_db(tmp_path)
    for ts in ("20260710_171552", "20260715_002605", "20260723_234321"):
        _make_backup_set(tmp_path, ts)

    deleted = cleanup_old_backups(keep=1, data_dir=tmp_path)

    # 3세트(9파일) 중 최근 1세트(3파일) 보존 → 6개 삭제
    assert deleted == 6
    assert (tmp_path / "stocks.db.20260723_234321.backup").exists()
    assert (tmp_path / "stocks.db-shm.20260723_234321.backup").exists()
    assert (tmp_path / "stocks.db-wal.20260723_234321.backup").exists()
    # 오래된 세트는 모두 삭제
    assert not (tmp_path / "stocks.db.20260715_002605.backup").exists()
    assert not (tmp_path / "stocks.db.20260710_171552.backup").exists()


def test_preserves_live_db_files(tmp_path: Path) -> None:
    """본체 DB 파일은 백업이 많아도 절대 삭제되지 않는다 (P22)."""
    _make_live_db(tmp_path)
    _make_backup_set(tmp_path, "20260720_000000")
    _make_backup_set(tmp_path, "20260722_000000")

    cleanup_old_backups(keep=0, data_dir=tmp_path)

    # 본체는 보존
    assert (tmp_path / "stocks.db").exists()
    assert (tmp_path / "stocks.db-shm").exists()
    assert (tmp_path / "stocks.db-wal").exists()
    assert (tmp_path / "sectorflow.db").exists()


def test_keep_zero_deletes_all_sets(tmp_path: Path) -> None:
    """keep=0이면 모든 백업 세트 삭제 (본체는 보존)."""
    _make_live_db(tmp_path)
    _make_backup_set(tmp_path, "20260720_000000")
    _make_backup_set(tmp_path, "20260722_000000")

    deleted = cleanup_old_backups(keep=0, data_dir=tmp_path)

    assert deleted == 6
    assert not any(tmp_path.glob("stocks.db*.backup"))


def test_no_backups_returns_zero(tmp_path: Path) -> None:
    """백업이 없으면 0 반환, 본체는 건드리지 않음."""
    _make_live_db(tmp_path)
    assert cleanup_old_backups(keep=1, data_dir=tmp_path) == 0
    assert (tmp_path / "stocks.db").exists()


def test_partial_set_only_deletes_existing(tmp_path: Path) -> None:
    """shm/wal이 없는 불완전 세트도 db 백업만 정리 대상."""
    _make_live_db(tmp_path)
    _make_backup_set(tmp_path, "20260720_000000", with_shm=False, with_wal=False)
    _make_backup_set(tmp_path, "20260722_000000")

    deleted = cleanup_old_backups(keep=1, data_dir=tmp_path)

    # 최근 세트(20260722) 3개 보존, 오래된 세트(20260720)는 db만 1개 → 1개 삭제
    assert deleted == 1
    assert (tmp_path / "stocks.db.20260722_000000.backup").exists()
    assert not (tmp_path / "stocks.db.20260720_000000.backup").exists()


def test_keep_two_preserves_two_sets(tmp_path: Path) -> None:
    """keep=2면 최근 2세트 보존."""
    _make_live_db(tmp_path)
    for ts in ("20260710_000000", "20260715_000000", "20260720_000000", "20260722_000000"):
        _make_backup_set(tmp_path, ts)

    deleted = cleanup_old_backups(keep=2, data_dir=tmp_path)

    # 4세트(12파일) 중 2세트(6파일) 보존 → 6개 삭제
    assert deleted == 6
    assert (tmp_path / "stocks.db.20260722_000000.backup").exists()
    assert (tmp_path / "stocks.db.20260720_000000.backup").exists()
    assert not (tmp_path / "stocks.db.20260715_000000.backup").exists()
    assert not (tmp_path / "stocks.db.20260710_000000.backup").exists()
