"""lock_manager.py 단위 테스트 — 잠금 파일 기반 중복 실행 방지 검증.

acquire_lock / release_lock / read_lock_pid / format_duplicate_message 동작 검증.
hang 방지: 실제 파일 I/O 및 signal 핸들러 등록은 mock으로 대체.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from backend.app.core import lock_manager
from backend.app.core.lock_manager import (
    acquire_lock,
    format_duplicate_message,
    read_lock_pid,
    release_lock,
)


@pytest.fixture(autouse=True)
def _reset_lock_fh():
    """각 테스트 전후로 _lock_fh 초기화."""
    lock_manager._lock_fh = None
    yield
    lock_manager._lock_fh = None


# ── acquire_lock ───────────────────────────────────────────────────────────────

class TestAcquireLock:
    def test_success_unix(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        mock_open_obj = mock_open()

        with patch("builtins.open", mock_open_obj):
            with patch("fcntl.flock"):
                with patch("sys.platform", "darwin"):
                    with patch.object(lock_manager, "_lock_fh", None):
                        result = acquire_lock(lock_path)

        assert result is True

    def test_duplicate_detected_unix(self, tmp_path):
        lock_path = tmp_path / "test.lock"

        with patch("builtins.open", mock_open()):
            with patch("fcntl.flock", side_effect=OSError("locked")):
                with patch("sys.platform", "darwin"):
                    result = acquire_lock(lock_path)

        assert result is False

    def test_os_error_returns_false(self, tmp_path):
        lock_path = tmp_path / "test.lock"

        with patch("builtins.open", side_effect=OSError("permission denied")):
            with patch("sys.platform", "darwin"):
                result = acquire_lock(lock_path)

        assert result is False

    def test_creates_parent_directory(self, tmp_path):
        lock_path = tmp_path / "subdir" / "test.lock"

        with patch("builtins.open", mock_open()):
            with patch("fcntl.flock"):
                with patch("sys.platform", "darwin"):
                    result = acquire_lock(lock_path)

        assert result is True
        assert lock_path.parent.exists()


# ── release_lock ───────────────────────────────────────────────────────────────

class TestReleaseLock:
    def test_releases_existing_fh(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        mock_fh = MagicMock()
        lock_manager._lock_fh = mock_fh

        release_lock(lock_path)

        mock_fh.close.assert_called_once()
        assert lock_manager._lock_fh is None

    def test_no_fh_no_error(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_manager._lock_fh = None

        release_lock(lock_path)
        # no exception

    def test_deletes_lock_file(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("12345")
        lock_manager._lock_fh = None

        release_lock(lock_path)

        assert not lock_path.exists()

    def test_missing_file_no_error(self, tmp_path):
        lock_path = tmp_path / "nonexistent.lock"
        lock_manager._lock_fh = None

        release_lock(lock_path)
        # no exception

    def test_close_error_handled(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        mock_fh = MagicMock()
        mock_fh.close.side_effect = OSError("already closed")
        lock_manager._lock_fh = mock_fh

        release_lock(lock_path)
        # no exception — close error is suppressed
        assert lock_manager._lock_fh is None


# ── read_lock_pid ──────────────────────────────────────────────────────────────

class TestReadLockPid:
    def test_reads_valid_pid(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("12345")

        result = read_lock_pid(lock_path)

        assert result == 12345

    def test_returns_none_for_missing_file(self, tmp_path):
        lock_path = tmp_path / "nonexistent.lock"

        result = read_lock_pid(lock_path)

        assert result is None

    def test_returns_none_for_non_digit(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("not_a_pid")

        result = read_lock_pid(lock_path)

        assert result is None

    def test_strips_whitespace(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("  12345  \n")

        result = read_lock_pid(lock_path)

        assert result == 12345

    def test_empty_file_returns_none(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("")

        result = read_lock_pid(lock_path)

        assert result is None

    def test_negative_pid_returns_none(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("-1")

        result = read_lock_pid(lock_path)

        assert result is None

    def test_zero_pid_returns_zero(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("0")

        result = read_lock_pid(lock_path)

        assert result == 0

    def test_read_error_returns_none(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("12345")

        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            result = read_lock_pid(lock_path)

        assert result is None


# ── format_duplicate_message ───────────────────────────────────────────────────

class TestFormatDuplicateMessage:
    def test_contains_pid(self):
        msg = format_duplicate_message(12345)
        assert "12345" in msg

    def test_contains_warning_emoji(self):
        msg = format_duplicate_message(12345)
        assert "⚠️" in msg

    def test_contains_kill_command(self):
        msg = format_duplicate_message(12345)
        assert "kill -9 12345" in msg

    def test_contains_separator(self):
        msg = format_duplicate_message(12345)
        assert "=" * 60 in msg

    def test_contains_lock_file_path(self):
        msg = format_duplicate_message(12345)
        assert str(lock_manager.LOCK_FILE_PATH) in msg

    def test_different_pids(self):
        msg1 = format_duplicate_message(111)
        msg2 = format_duplicate_message(222)
        assert "111" in msg1
        assert "222" in msg2
        assert "111" not in msg2
