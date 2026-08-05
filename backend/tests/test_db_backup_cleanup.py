"""database.py cleanup_old_backups 단위 테스트 — 오래된 DB 백업 파일 자동 정리 검증.

검증 항목:
  - 최근 keep세트만 남고 나머지 세트는 삭제된다.
  - 같은 타임스탬스의 db/shm/wal 3종이 함께 정리된다.
  - stocks.db 본체·stocks.db-shm·stocks.db-wal·sectorflow.db는 절대 삭제되지 않는다 (P22).
  - keep=0이면 모든 백업 세트가 삭제된다.
  - 백업이 없으면 0을 반환하고 본체는 건드리지 않는다.
  - 정렬 기준은 파일명 문자열이 아닌 파일시스템 mtime (P10/P22).
  - 비표준 타임스탬스(접두사 포함)도 mtime 기준으로 동일 처리 (P22).
  - mtime 조회 실패 시 해당 세트만 스킵 + warning, 나머지 정상 처리 (P25).
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.app.db.database import cleanup_old_backups


def _make_backup_set(data_dir: Path, ts: str, *, with_shm: bool = True, with_wal: bool = True) -> None:
    """한 타임스탬스 세트(db/shm/wal) 생성 헬퍼."""
    (data_dir / f"stocks.db.{ts}.backup").write_bytes(b"backup")
    if with_shm:
        (data_dir / f"stocks.db-shm.{ts}.backup").write_bytes(b"shm")
    if with_wal:
        (data_dir / f"stocks.db-wal.{ts}.backup").write_bytes(b"wal")


def _set_mtime(data_dir: Path, ts: str, mtime: float) -> None:
    """한 세트의 db/shm/wal 백업 파일 mtime 일괄 설정."""
    for prefix in ("stocks.db.", "stocks.db-shm.", "stocks.db-wal."):
        p = data_dir / f"{prefix}{ts}.backup"
        if p.exists():
            os.utime(p, (mtime, mtime))


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


def test_sorts_by_mtime_not_filename(tmp_path: Path) -> None:
    """파일명 문자열이 아닌 mtime 기준 정렬 — step2_ 접두사 구 백업이 신규 백업보다
    파일명 순으로 앞서도, mtime이 더 최신인 7/28 백업이 보존되어야 한다 (P10/P22)."""
    _make_live_db(tmp_path)
    # 구 백업: 접두사 step2_ — 파일명 문자열상 더 큼 ('s' > '2')
    _make_backup_set(tmp_path, "step2_20260725_155057")
    # 신규 백업: 순수 타임스탬프 — 파일명 문자열상 더 작지만 mtime이 더 최신
    _make_backup_set(tmp_path, "20260728_162400")

    # mtime 명시 설정: 7/25 백업은 과거, 7/28 백업은 최신
    _set_mtime(tmp_path, "step2_20260725_155057", 1_753_449_057)  # 2025-07-25 15:50:57 UTC
    _set_mtime(tmp_path, "20260728_162400", 1_753_707_840)        # 2025-07-28 16:24:00 UTC

    deleted = cleanup_old_backups(keep=1, data_dir=tmp_path)

    # mtime 기준 최신(7/28) 보존, 구 백업(7/25) 3개 삭제
    assert deleted == 3
    assert (tmp_path / "stocks.db.20260728_162400.backup").exists()
    assert (tmp_path / "stocks.db-shm.20260728_162400.backup").exists()
    assert (tmp_path / "stocks.db-wal.20260728_162400.backup").exists()
    assert not (tmp_path / "stocks.db.step2_20260725_155057.backup").exists()
    assert not (tmp_path / "stocks.db-shm.step2_20260725_155057.backup").exists()
    assert not (tmp_path / "stocks.db-wal.step2_20260725_155057.backup").exists()


def test_nonstandard_timestamp_handled_normally(tmp_path: Path, caplog) -> None:
    """비표준 타임스탬스(접두사 포함)도 mtime 기준으로 표준 파일과 동일 처리.
    warning이 아닌 info 레벨 로그만 출력되어야 한다 (P22 — 형식 무관 동일 처리)."""
    import logging

    _make_live_db(tmp_path)
    _make_backup_set(tmp_path, "pre_migration_20260720_000000")
    _make_backup_set(tmp_path, "20260722_000000")

    # mtime 명시 설정: pre_migration이 과거, 표준이 최신
    _set_mtime(tmp_path, "pre_migration_20260720_000000", 1_753_017_600)
    _set_mtime(tmp_path, "20260722_000000", 1_753_190_400)

    with caplog.at_level(logging.INFO, logger="backend.app.db.database"):
        deleted = cleanup_old_backups(keep=1, data_dir=tmp_path)

    # mtime 기준 최신(표준 7/22) 보존, 비표준 7/20 3개 삭제
    assert deleted == 3
    assert (tmp_path / "stocks.db.20260722_000000.backup").exists()
    assert not (tmp_path / "stocks.db.pre_migration_20260720_000000.backup").exists()

    # warning 로그 미출력, info 로그만 출력
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"warning 이상 로그가 출력됨: {[r.getMessage() for r in warnings]}"
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("백업 파일" in r.getMessage() for r in infos)


def test_skips_set_on_stat_error(tmp_path: Path, monkeypatch, caplog) -> None:
    """mtime 조회 실패(OSError) 시 해당 세트만 스킵 + warning, 나머지 정상 처리 (P25)."""
    import logging

    _make_live_db(tmp_path)
    _make_backup_set(tmp_path, "20260720_000000")
    _make_backup_set(tmp_path, "20260722_000000")

    # mtime 명시 설정
    _set_mtime(tmp_path, "20260720_000000", 1_753_017_600)
    _set_mtime(tmp_path, "20260722_000000", 1_753_190_400)

    # 7/20 세트의 stocks.db 백업 파일 stat()이 OSError 발생하도록 패치
    target_path = tmp_path / "stocks.db.20260720_000000.backup"
    real_stat = Path.stat

    def _patched_stat(self: Path, *args, **kwargs):
        if self == target_path:
            raise OSError("mock stat failure")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _patched_stat)

    with caplog.at_level(logging.WARNING, logger="backend.app.db.database"):
        deleted = cleanup_old_backups(keep=1, data_dir=tmp_path)

    # assertion 전 패치 해제 — Path.stat 복원 후 exists() 정상 동작
    monkeypatch.undo()

    # 7/20 세트는 mtime 조회 실패로 스킵 → 삭제 대상에서 제외, 7/22 보존
    # keep=1이지만 7/20이 스킵되어 timed 리스트에 7/22만 남음 → 삭제 0건
    assert deleted == 0
    assert (tmp_path / "stocks.db.20260722_000000.backup").exists()
    assert (tmp_path / "stocks.db.20260720_000000.backup").exists()  # 스킵되어 남음

    # warning 로그 출력 (mtime 조회 실패)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("mtime 조회 실패" in r.getMessage() for r in warnings)
