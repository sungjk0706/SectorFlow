"""logger.py 단위 테스트 — 로거 설정 + 파일 라이터 + InterceptHandler 검증.

_get_file_queue: asyncio.Queue 지연 초기화
_get_daily_log_path: 일별 로그 파일 경로
_rotate_old_logs: 오래된 로그 파일 삭제
_info_file_sink: 큐 적재 싱크
InterceptHandler: 표준 logging → loguru 리다이렉트
setup_loguru: 메인 설정 (이벤트 루프 + 파일 I/O mock)
stop_file_writers: 태스크 정지
get_logger: deprecated 경고

주의: 실제 asyncio.Queue / create_task / 파일 I/O 사용 금지 (hang 방지).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core import logger as logger_mod
from backend.app.core.logger import (
    LOG_DIR,
    LOG_FILE,
    _MAX_FILE_SIZE,
    _BACKUP_COUNT,
    _get_file_queue,
    _get_daily_log_path,
    _info_file_sink,
    InterceptHandler,
    get_logger,
    log_progress,
    log_progress_end,
)


# ── 상수 ──────────────────────────────────────────────────────────────────────────

class TestConstants:
    def test_log_dir_path(self):
        assert LOG_DIR.name == "logs"

    def test_log_file_path(self):
        assert LOG_FILE.name == "trading.log"
        assert LOG_FILE.parent == LOG_DIR

    def test_max_file_size_10mb(self):
        assert _MAX_FILE_SIZE == 10 * 1024 * 1024

    def test_backup_count_5(self):
        assert _BACKUP_COUNT == 5


# ── _get_file_queue ───────────────────────────────────────────────────────────────

class TestGetFileQueue:
    def test_returns_queue(self):
        # 이미 초기화되어 있을 수 있으므로 현재 상태 확인
        q = _get_file_queue()
        assert q is not None
        assert hasattr(q, "put_nowait")
        assert hasattr(q, "get")

    def test_returns_same_instance(self):
        q1 = _get_file_queue()
        q2 = _get_file_queue()
        assert q1 is q2


# ── _get_daily_log_path ───────────────────────────────────────────────────────────

class TestGetDailyLogPath:
    def test_returns_correct_format(self):
        path = _get_daily_log_path("trading.log")
        today = datetime.now().strftime("%Y-%m-%d")
        assert path.name == f"trading_{today}.log"
        assert path.parent == LOG_DIR

    def test_strips_log_extension(self):
        path = _get_daily_log_path("debug.log")
        today = datetime.now().strftime("%Y-%m-%d")
        assert path.name == f"debug_{today}.log"

    def test_returns_path_object(self):
        path = _get_daily_log_path("trading.log")
        assert isinstance(path, Path)


# ── _info_file_sink ────────────────────────────────────────────────────────────────

class TestInfoFileSink:
    def test_no_loop_does_nothing(self):
        with patch.object(logger_mod, "_loop_ref", None):
            # 예외 발생하지 않아야 함
            _info_file_sink(MagicMock())

    def test_closed_loop_does_nothing(self):
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = True
        with patch.object(logger_mod, "_loop_ref", mock_loop):
            _info_file_sink(MagicMock())
        mock_loop.call_soon_threadsafe.assert_not_called()

    def test_open_loop_schedules_put(self):
        mock_queue = MagicMock()
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        with (
            patch.object(logger_mod, "_loop_ref", mock_loop),
            patch.object(logger_mod, "_get_file_queue", return_value=mock_queue),
        ):
            _info_file_sink(MagicMock())
        mock_loop.call_soon_threadsafe.assert_called_once()

    def test_runtime_error_suppressed(self):
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        mock_loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
        with (
            patch.object(logger_mod, "_loop_ref", mock_loop),
            patch.object(logger_mod, "_get_file_queue", return_value=MagicMock()),
        ):
            # 예외 발생하지 않아야 함
            _info_file_sink(MagicMock())


# ── InterceptHandler ───────────────────────────────────────────────────────────────

class TestInterceptHandler:
    def test_ws_msg_map_contains_connection_messages(self):
        assert "connection open" in InterceptHandler._WS_MSG_MAP
        assert "connection closed" in InterceptHandler._WS_MSG_MAP
        assert "연결 닫힘" in InterceptHandler._WS_MSG_MAP

    def test_ws_msg_map_values_are_korean(self):
        assert InterceptHandler._WS_MSG_MAP["connection open"] == "[연결] 성공"
        assert InterceptHandler._WS_MSG_MAP["connection closed"] == "[연결] 종료"

    def test_emit_does_not_raise(self):
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="test message", args=(), exc_info=None,
        )
        # loguru로 리다이렉트되므로 예외 없이 완료되어야 함
        handler.emit(record)

    # ── uvicorn 메시지 맵 ──────────────────────────────────────────────────────────

    def test_uvicorn_msg_map_contains_startup_messages(self):
        assert "Waiting for application startup." in InterceptHandler._UVICORN_MSG_MAP
        assert "Application startup complete." in InterceptHandler._UVICORN_MSG_MAP
        assert "Application startup failed. Exiting." in InterceptHandler._UVICORN_MSG_MAP

    def test_uvicorn_msg_map_contains_shutdown_messages(self):
        assert "Waiting for application shutdown." in InterceptHandler._UVICORN_MSG_MAP
        assert "Application shutdown complete." in InterceptHandler._UVICORN_MSG_MAP
        assert "Application shutdown failed. Exiting." in InterceptHandler._UVICORN_MSG_MAP
        assert "Shutting down" in InterceptHandler._UVICORN_MSG_MAP

    def test_uvicorn_msg_map_values_are_korean(self):
        assert InterceptHandler._UVICORN_MSG_MAP["Application startup complete."] == "앱 시작 완료"
        assert InterceptHandler._UVICORN_MSG_MAP["Shutting down"] == "종료 중"

    def test_uvicorn_prefix_map_contains_process_messages(self):
        assert "Started server process" in InterceptHandler._UVICORN_PREFIX_MAP
        assert "Finished server process" in InterceptHandler._UVICORN_PREFIX_MAP
        assert "Uvicorn running on" in InterceptHandler._UVICORN_PREFIX_MAP

    def test_uvicorn_prefix_map_values_are_korean(self):
        assert InterceptHandler._UVICORN_PREFIX_MAP["Started server process"] == "서버 프로세스 시작"
        assert InterceptHandler._UVICORN_PREFIX_MAP["Finished server process"] == "서버 프로세스 종료"

    def test_emit_translates_uvicorn_startup_message(self):
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="uvicorn.error", level=logging.INFO, pathname=__file__, lineno=1,
            msg="Application startup complete.", args=(), exc_info=None,
        )
        with patch("backend.app.core.logger._loguru_logger") as mock_logger:
            mock_logger.level.return_value = MagicMock(name="INFO")
            mock_logger.opt.return_value.log = MagicMock()
            handler.emit(record)
        args = mock_logger.opt.return_value.log.call_args
        assert "앱 시작 완료" in args[0][1]

    def test_emit_translates_uvicorn_prefix_message(self):
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="uvicorn.error", level=logging.INFO, pathname=__file__, lineno=1,
            msg="Started server process [12345]", args=(), exc_info=None,
        )
        with patch("backend.app.core.logger._loguru_logger") as mock_logger:
            mock_logger.level.return_value = MagicMock(name="INFO")
            mock_logger.opt.return_value.log = MagicMock()
            handler.emit(record)
        args = mock_logger.opt.return_value.log.call_args
        assert "서버 프로세스 시작" in args[0][1]
        assert "12345" in args[0][1]

    def test_emit_does_not_translate_uvicorn_access(self):
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
            msg="Application startup complete.", args=(), exc_info=None,
        )
        with patch("backend.app.core.logger._loguru_logger") as mock_logger:
            mock_logger.level.return_value = MagicMock(name="INFO")
            mock_logger.opt.return_value.log = MagicMock()
            handler.emit(record)
        args = mock_logger.opt.return_value.log.call_args
        # access log는 영문 유지 — 치환되지 않아야 함
        assert "Application startup complete." in args[0][1]


# ── _rotate_old_logs ───────────────────────────────────────────────────────────────

class TestRotateOldLogs:
    @pytest.mark.asyncio
    async def test_no_files_no_error(self):
        with patch.object(logger_mod, "LOG_DIR", MagicMock()):
            mock_dir = MagicMock()
            mock_dir.glob.return_value = []
            with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *a, **kw: f())):
                # LOG_DIR.glob을 호출하는 람다가 반환되므로 빈 리스트 처리
                with patch.object(logger_mod, "LOG_DIR", mock_dir):
                    await logger_mod._rotate_old_logs("trading_*.log", 2)

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("io error"))):
            await logger_mod._rotate_old_logs("trading_*.log", 2)


# ── stop_file_writers ──────────────────────────────────────────────────────────────

class TestStopFileWriters:
    @pytest.mark.asyncio
    async def test_no_task_does_nothing(self):
        mock_queue = AsyncMock()
        with (
            patch.object(logger_mod, "_writer_task", None),
            patch.object(logger_mod, "_get_file_queue", return_value=mock_queue),
        ):
            await logger_mod.stop_file_writers()
        mock_queue.put.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_sends_stop_signal(self):
        mock_queue = AsyncMock()
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        with (
            patch.object(logger_mod, "_writer_task", mock_task),
            patch.object(logger_mod, "_get_file_queue", return_value=mock_queue),
            patch("asyncio.wait_for", AsyncMock()),
        ):
            await logger_mod.stop_file_writers()
        mock_queue.put.assert_called_once_with(None)


# ── get_logger ─────────────────────────────────────────────────────────────────────

class TestGetLogger:
    def test_returns_logger(self):
        with pytest.warns(DeprecationWarning):
            log = get_logger("test_logger")
        assert isinstance(log, logging.Logger)
        assert log.name == "test_logger"

    def test_default_name(self):
        with pytest.warns(DeprecationWarning):
            log = get_logger()
        assert log.name == "sectorflow"


# ── setup_loguru ───────────────────────────────────────────────────────────────────

class TestSetupLoguru:
    @pytest.mark.asyncio
    async def test_already_configured_returns_early(self):
        with patch.object(logger_mod, "_configured", True):
            await logger_mod.setup_loguru()
        # _configured가 True이면 아무 작업 없이 return

    @pytest.mark.asyncio
    async def test_sets_configured_flag(self):
        original = logger_mod._configured
        logger_mod._configured = False
        try:
            mock_stdout_wrapper = MagicMock()
            with (
                patch("asyncio.to_thread", AsyncMock()),
                patch("backend.app.core.logger._start_file_writers", AsyncMock()),
                patch("loguru.logger.remove"),
                patch("loguru.logger.add"),
                patch("logging.basicConfig"),
                patch("backend.app.core.logger.io.TextIOWrapper", return_value=mock_stdout_wrapper),
            ):
                await logger_mod.setup_loguru("DEBUG")
            assert logger_mod._configured is True
        finally:
            logger_mod._configured = original


# ── setup_console_intercept ───────────────────────────────────────────────────────

class TestSetupConsoleIntercept:
    def test_installs_intercept_handler_on_uvicorn_loggers(self):
        mock_stdout_wrapper = MagicMock()
        with (
            patch("loguru.logger.remove"),
            patch("loguru.logger.add"),
            patch("logging.basicConfig"),
            patch("backend.app.core.logger.io.TextIOWrapper", return_value=mock_stdout_wrapper),
        ):
            logger_mod.setup_console_intercept("INFO")
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            log = logging.getLogger(name)
            assert len(log.handlers) == 1
            assert isinstance(log.handlers[0], InterceptHandler)

    def test_sets_uvicorn_access_to_warning(self):
        # access log는 InterceptHandler 설치되지만 메시지 치환은 emit()에서 제외
        mock_stdout_wrapper = MagicMock()
        with (
            patch("loguru.logger.remove"),
            patch("loguru.logger.add"),
            patch("logging.basicConfig"),
            patch("backend.app.core.logger.io.TextIOWrapper", return_value=mock_stdout_wrapper),
        ):
            logger_mod.setup_console_intercept("INFO")
        # httpx, httpcore 노이즈 차단 확인
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING


# ── log_progress / log_progress_end ───────────────────────────────────────────────

class TestLogProgress:
    """다운로드 진행률 1줄 갱신 헬퍼 — TTY/\r 갱신 + 파일 DEBUG + 인터리브 안전."""

    def test_tty_writes_carriage_return_and_sets_progress_active(self):
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        logger_mod._progress_active = False
        with (
            patch("backend.app.core.logger._get_stdout_utf8", return_value=mock_stdout),
            patch("backend.app.core.logger.sys.stdout", mock_stdout),
            patch("backend.app.core.logger._loguru_logger.opt") as mock_opt,
        ):
            log_progress("[다운로드]", 5, 100, code="005930")
        # \r 로 같은 줄 갱신
        written = mock_stdout.write.call_args_list[0].args[0]
        assert written.startswith("\r")
        assert "005930" in written
        assert "5/100" in written
        assert "5.0%" in written
        assert logger_mod._progress_active is True
        # 파일은 DEBUG로 기록
        mock_opt.return_value.debug.assert_called_once()

    def test_non_tty_writes_newline_no_carriage_return(self):
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = False
        logger_mod._progress_active = False
        with (
            patch("backend.app.core.logger._get_stdout_utf8", return_value=mock_stdout),
            patch("backend.app.core.logger.sys.stdout", mock_stdout),
            patch("backend.app.core.logger._loguru_logger.opt"),
        ):
            log_progress("[다운로드]", 1, 10)
        written = mock_stdout.write.call_args_list[0].args[0]
        assert not written.startswith("\r")
        assert written.endswith("\n")
        assert "1/10" in written
        # non-TTY는 _progress_active 유지 안 함
        assert logger_mod._progress_active is False

    def test_zero_total_does_not_raise(self):
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        with (
            patch("backend.app.core.logger._get_stdout_utf8", return_value=mock_stdout),
            patch("backend.app.core.logger.sys.stdout", mock_stdout),
            patch("backend.app.core.logger._loguru_logger.opt"),
        ):
            log_progress("[다운로드]", 0, 0)
        assert "0/0" in mock_stdout.write.call_args_list[0].args[0]

    def test_log_progress_end_writes_newline_when_active(self):
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        logger_mod._progress_active = True
        with (
            patch("backend.app.core.logger._get_stdout_utf8", return_value=mock_stdout),
            patch("backend.app.core.logger.sys.stdout", mock_stdout),
        ):
            log_progress_end()
        mock_stdout.write.assert_called_once_with("\n")
        assert logger_mod._progress_active is False

    def test_log_progress_end_noop_when_not_active(self):
        mock_stdout = MagicMock()
        logger_mod._progress_active = False
        with (
            patch("backend.app.core.logger._get_stdout_utf8", return_value=mock_stdout),
            patch("backend.app.core.logger.sys.stdout", mock_stdout),
        ):
            log_progress_end()
        mock_stdout.write.assert_not_called()

    def test_stdout_sink_inserts_newline_when_progress_active(self):
        """진행률 \r 갱신 중 다른 로그가 끼어들면 줄 바꿈 후 출력하여 커서 꼬임 방지."""
        mock_stdout = MagicMock()
        logger_mod._progress_active = True
        with patch("backend.app.core.logger._get_stdout_utf8", return_value=mock_stdout):
            logger_mod._stdout_sink("2026-07-18 20:00:00 [정보] 다른 로그\n")
        # 첫 write: \n (진행 줄 종료), 두 번째 write: 메시지 본문
        assert mock_stdout.write.call_args_list[0].args[0] == "\n"
        assert mock_stdout.write.call_args_list[1].args[0] == "2026-07-18 20:00:00 [정보] 다른 로그\n"
        assert logger_mod._progress_active is False
