# -*- coding: utf-8 -*-
"""
Loguru 기반 트레이딩 로거 — 안전한 파일 로깅 포함.

- 콘솔: INFO 이상만 출력 (Windows cp949 환경 UTF-8 강제)
- trading.log: INFO 이상 (중요 로그만, 일별 분할, 50MB 로테이션, 2일 보관)
- trading_debug.log: DEBUG 포함 전체 (문제 추적용, 일별 분할, 50MB 로테이션, 1일 보관)

파일 로깅 안전 전략:
  loguru enqueue=True → multiprocessing.SimpleQueue → asyncio IOCP 충돌 (크래시)
  loguru enqueue=False → 멀티스레드 동시 _file_sink.write → access violation
  → 해결: 표준 queue.Queue + 전용 데몬 스레드로 파일 쓰기 분리.
     asyncio 이벤트 루프와 완전 독립, OS 파이프 미사용, IOCP 충돌 없음.
"""
from __future__ import annotations

import io
import logging
import queue
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger as _loguru_logger

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "trading.log"

_configured = False


# ── 안전한 파일 쓰기 큐 + 데몬 스레드 ─────────────────────────────────────────

_file_queue: queue.Queue[str | None] = queue.Queue(maxsize=50_000)
_debug_file_queue: queue.Queue[str | None] = queue.Queue(maxsize=50_000)
_writer_started = False


_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB — 파일 크기 제한


def _rotate_old_logs(pattern: str, keep_days: int) -> None:
    """오래된 로그 파일 자동 삭제 — 파일명의 날짜 기준으로 keep_days일 이전 파일 제거.

    파일명 형식: trading_2026-04-28.log, trading_debug_2026-04-28.1.log
    mtime 기반은 23:59 생성 파일이 다음날 삭제 안 되는 문제가 있어 파일명 날짜로 판단.
    """
    import re
    try:
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        date_re = re.compile(r"(\d{4}-\d{2}-\d{2})")
        for f in LOG_DIR.glob(pattern):
            if not f.is_file():
                continue
            m = date_re.search(f.name)
            if m and m.group(1) < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def _get_daily_log_path(base_name: str) -> Path:
    """일별 로그 파일 경로 반환 — trading_2026-04-08.log 형식."""
    today = datetime.now().strftime("%Y-%m-%d")
    stem = base_name.replace(".log", "")
    return LOG_DIR / f"{stem}_{today}.log"


def _file_writer_loop(q: queue.Queue, base_name: str, keep_days: int) -> None:
    """전용 데몬 스레드 — 큐에서 로그 메시지를 꺼내 파일에 쓴다.

    50MB 초과 시 .1, .2 … 로 로테이션하고 오래된 파일은 자동 삭제.
    """
    current_date = ""
    fh = None
    log_path: Path | None = None
    part = 0  # 현재 파트 번호 (0 = 기본)

    def _open_part() -> io.TextIOWrapper | None:
        """현재 part 번호에 맞는 파일 핸들을 연다."""
        nonlocal log_path
        stem = base_name.replace(".log", "")
        today = datetime.now().strftime("%Y-%m-%d")
        suffix = f".{part}" if part > 0 else ""
        log_path = LOG_DIR / f"{stem}_{today}{suffix}.log"
        try:
            return open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            return None

    try:
        while True:
            try:
                msg = q.get(timeout=2.0)
            except queue.Empty:
                continue
            if msg is None:  # 종료 신호
                break
            today = datetime.now().strftime("%Y-%m-%d")
            if today != current_date or fh is None:
                # 날짜 변경 → 파일 교체 + 오래된 파일 정리
                if fh is not None:
                    try:
                        fh.close()
                    except Exception:
                        pass
                current_date = today
                part = 0
                fh = _open_part()
                if fh is None:
                    continue
                _rotate_old_logs(f"{base_name.replace('.log', '')}_*.log", keep_days)

            # 크기 초과 → 다음 파트로 로테이션
            if log_path is not None and log_path.exists():
                try:
                    if log_path.stat().st_size >= _MAX_FILE_SIZE:
                        if fh is not None:
                            fh.close()
                        part += 1
                        fh = _open_part()
                        if fh is None:
                            continue
                except Exception:
                    pass

            if fh is not None:
                try:
                    fh.write(msg)
                    fh.flush()
                except Exception:
                    pass
    finally:
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass


def _start_file_writers() -> None:
    """파일 쓰기 데몬 스레드 2개 시작 — INFO용, DEBUG용."""
    global _writer_started
    if _writer_started:
        return
    _writer_started = True
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    t1 = threading.Thread(
        target=_file_writer_loop,
        args=(_file_queue, "trading.log", 1),
        name="log-writer-info",
        daemon=True,
    )
    t2 = threading.Thread(
        target=_file_writer_loop,
        args=(_debug_file_queue, "trading_debug.log", 0),
        name="log-writer-debug",
        daemon=True,
    )
    t1.start()
    t2.start()


# ── loguru 커스텀 싱크 (큐에 넣기만 함, 파일 I/O 없음) ──────────────────────

_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} [{level: <8}] {name}: {message}\n"


def _info_file_sink(message) -> None:
    """INFO 이상 로그를 큐에 넣는다 — 실제 파일 쓰기는 데몬 스레드가 담당."""
    try:
        text = message  # loguru Message 객체는 str()로 변환됨
        _file_queue.put_nowait(str(text))
    except queue.Full:
        pass  # 큐 가득 차면 버림 (크래시보다 나음)


def _debug_file_sink(message) -> None:
    """DEBUG 포함 전체 로그를 큐에 넣는다."""
    try:
        _debug_file_queue.put_nowait(str(message))
    except queue.Full:
        pass


# ── InterceptHandler: 표준 logging → loguru 리다이렉트 ────────────────────────

class InterceptHandler(logging.Handler):
    """표준 logging -> loguru 로 리다이렉트."""

    _WS_MSG_MAP = {
        "connection open": "[연결] 성공",
        "connection closed": "[연결] 종료",
        "연결 닫힘": "[연결] 종료",
    }

    def emit(self, record: logging.LogRecord) -> None:
        """표준 logging 레코드를 loguru로 전달."""
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno  # type: ignore[assignment]

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        msg = record.getMessage()
        msg_lower = msg.strip().lower()
        if msg_lower in self._WS_MSG_MAP:
            msg = self._WS_MSG_MAP[msg_lower]
        elif record.name.startswith("websockets"):
            msg = self._WS_MSG_MAP.get(msg_lower, msg)

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, msg
        )


# ── 메인 설정 함수 ────────────────────────────────────────────────────────────

def setup_loguru(log_level: str = "DEBUG") -> None:
    """앱 기동 시 1회 호출 — 콘솔 + 파일(INFO) + 파일(DEBUG) 3채널 설정."""
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    _loguru_logger.remove()  # 기본 핸들러 제거

    # ── 1. 콘솔 — INFO 이상 (Windows cp949 환경 UTF-8 강제) ──────────────
    _stdout_utf8 = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
    )
    _KR_LEVEL = {
        "DEBUG":    "디버그",
        "INFO":     "정보",
        "WARNING":  "주의",
        "ERROR":    "오류",
        "CRITICAL": "심각",
    }

    def _inject_kr_level(record):
        record["extra"]["level_kr"] = _KR_LEVEL.get(record["level"].name, record["level"].name)
        return True

    _loguru_logger.add(
        _stdout_utf8,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> [<level>{extra[level_kr]}</level>] {message}",
        colorize=True,
        filter=_inject_kr_level,
    )

    # ── 2. 파일 — INFO 이상 (trading.log, 일별 분할, 50MB 로테이션, 2일 보관) ────────────
    _loguru_logger.add(
        _info_file_sink,
        level="INFO",
        format=_FILE_FORMAT,
        colorize=False,
    )

    # ── 3. 파일 — DEBUG 전체 (trading_debug.log, 일별 분할, 50MB 로테이션, 1일 보관) ─────
    _loguru_logger.add(
        _debug_file_sink,
        level="DEBUG",
        format=_FILE_FORMAT,
        colorize=False,
    )

    # 파일 쓰기 데몬 스레드 시작
    _start_file_writers()

    # ── 표준 logging → loguru 인터셉트 ────────────────────────────────────
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app", "engine"):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False

    # websockets — InterceptHandler로 인터셉트 (connection open/closed 한국어 치환)
    for ws_name in ("websockets", "websockets.client", "websockets.server"):
        logging.getLogger(ws_name).handlers = [InterceptHandler()]
        logging.getLogger(ws_name).propagate = False

    # 외부 라이브러리 노이즈 차단
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "sectorflow") -> logging.Logger:
    """기존 코드 호환용 — 표준 logging.Logger 반환 (loguru로 인터셉트됨)."""
    return logging.getLogger(name)
