# -*- coding: utf-8 -*-
"""
Loguru 기반 트레이딩 로거 — 안전한 파일 로깅 포함.

- 콘솔: LOG_LEVEL 이상 출력 (Windows cp949 환경 UTF-8 강제)
- trading.log: INFO 이상 (일별 분할, 10MB 로테이션, 2일 보관)
  LOG_LEVEL=DEBUG 시 DEBUG 로그도 trading.log에 기록됨

파일 로깅 안전 전략:
  loguru enqueue=True → multiprocessing.SimpleQueue → asyncio IOCP 충돌 (크래시)
  loguru enqueue=False → 멀티스레드 동시 _file_sink.write → access violation
  → 해결: asyncio.Queue + 단일 이벤트 루프 내 전용 태스크로 파일 쓰기.
     call_soon_threadsafe로 스레드 안전 큐 적재, 단일 루프 원칙 준수.
"""
from __future__ import annotations
import asyncio
import io
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles
from loguru import logger as _loguru_logger
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "trading.log"

_configured = False


# ── 안전한 파일 쓰기 큐 + asyncio 태스크 ──────────────────────────────────────

_file_queue: asyncio.Queue[str | None] | None = None
_writer_task: asyncio.Task | None = None
_loop_ref: asyncio.AbstractEventLoop | None = None


def _get_file_queue() -> asyncio.Queue[str | None]:
    """asyncio.Queue 지연 초기화 — 단일 이벤트 루프 내에서 생성."""
    global _file_queue
    if _file_queue is None:
        _file_queue = asyncio.Queue(maxsize=50_000)
    return _file_queue


_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB — 파일 크기 제한
_BACKUP_COUNT = 5  # 최대 5개 파일 보관


async def _rotate_old_logs(pattern: str, keep_days: int) -> None:
    """오래된 로그 파일 자동 삭제 — 파일명의 날짜 기준으로 keep_days일 이전 파일 제거.

    파일명 형식: trading_2026-04-28.log, trading_debug_2026-04-28.1.log
    mtime 기반은 23:59 생성 파일이 다음날 삭제 안 되는 문제가 있어 파일명 날짜로 판단.
    """
    import re
    try:
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        date_re = re.compile(r"(\d{4}-\d{2}-\d{2})")
        files = await asyncio.to_thread(lambda: list(LOG_DIR.glob(pattern)))
        for f in files:
            if not await asyncio.to_thread(f.is_file):
                continue
            m = date_re.search(f.name)
            if m and m.group(1) < cutoff:
                await asyncio.to_thread(f.unlink, missing_ok=True)
    except Exception as e:
        sys.stderr.write(f"[logger] _rotate_old_logs 실패: {e}\n")


def _get_daily_log_path(base_name: str) -> Path:
    """일별 로그 파일 경로 반환 — trading_2026-04-08.log 형식."""
    today = datetime.now().strftime("%Y-%m-%d")
    stem = base_name.replace(".log", "")
    return LOG_DIR / f"{stem}_{today}.log"


async def _async_file_writer_loop(base_name: str, keep_days: int) -> None:
    """단일 asyncio 이벤트 루프 내 파일 쓰기 태스크 — 큐에서 로그 메시지를 꺼내 파일에 쓴다.

    10MB 초과 시 .1, .2 … 로 로테이션하고 오래된 파일은 자동 삭제.
    """
    current_date = ""
    fh = None
    log_path: Path | None = None
    part = 0  # 현재 파트 번호 (0 = 기본)
    stem = base_name.replace(".log", "")

    async def _open_part():
        """현재 part 번호에 맞는 파일 핸들을 연다."""
        nonlocal log_path
        today = datetime.now().strftime("%Y-%m-%d")
        suffix = f".{part}" if part > 0 else ""
        log_path = LOG_DIR / f"{stem}_{today}{suffix}.log"
        try:
            return await aiofiles.open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            return None

    try:
        while True:
            try:
                msg = await asyncio.wait_for(_get_file_queue().get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if msg is None:  # 종료 신호
                break
            today = datetime.now().strftime("%Y-%m-%d")
            if today != current_date or fh is None:
                # 날짜 변경 → 파일 교체 + 오래된 파일 정리
                if fh is not None:
                    try:
                        await fh.close()
                    except Exception as e:
                        sys.stderr.write(f"[logger] 파일 핸들 close 실패 (날짜 변경): {e}\n")
                current_date = today
                part = 0
                fh = await _open_part()
                if fh is None:
                    continue
                await _rotate_old_logs(f"{base_name.replace('.log', '')}_*.log", keep_days)

            # 크기 초과 → 다음 파트로 로테이션
            if log_path is not None and await asyncio.to_thread(log_path.exists):
                try:
                    stat_size = await asyncio.to_thread(lambda: log_path.stat().st_size)
                    if stat_size >= _MAX_FILE_SIZE:
                        if fh is not None:
                            await fh.close()
                        part += 1
                        # _BACKUP_COUNT 초과 시 가장 오래된 파일 삭제
                        if part > _BACKUP_COUNT:
                            oldest_part = part - _BACKUP_COUNT - 1
                            oldest_suffix = f".{oldest_part}" if oldest_part > 0 else ""
                            oldest_path = LOG_DIR / f"{stem}_{today}{oldest_suffix}.log"
                            await asyncio.to_thread(oldest_path.unlink, missing_ok=True)
                        fh = await _open_part()
                        if fh is None:
                            continue
                except Exception as e:
                    sys.stderr.write(f"[logger] 파일 크기 체크/로테이션 실패: {e}\n")

            if fh is not None:
                try:
                    await fh.write(msg)
                    await fh.flush()
                except Exception as e:
                    sys.stderr.write(f"[logger] 파일 쓰기 실패: {e}\n")
    except asyncio.CancelledError:
        pass
    finally:
        if fh is not None:
            try:
                await fh.close()
            except Exception as e:
                sys.stderr.write(f"[logger] 파일 핸들 close 실패 (finally): {e}\n")


async def _start_file_writers() -> None:
    """파일 쓰기 asyncio 태스크 시작 — setup_loguru()에서 호출 (이벤트 루프 실행 중)."""
    global _writer_task, _loop_ref
    if _writer_task is not None and not _writer_task.done():
        return
    _loop_ref = asyncio.get_running_loop()
    await asyncio.to_thread(LOG_DIR.mkdir, parents=True, exist_ok=True)
    _writer_task = asyncio.create_task(_async_file_writer_loop("trading.log", 2))


async def stop_file_writers() -> None:
    """파일 쓰기 태스크 정지 — 앱 종료 시 호출."""
    global _writer_task
    q = _get_file_queue()
    await q.put(None)  # 종료 신호
    if _writer_task is not None:
        try:
            await asyncio.wait_for(_writer_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _writer_task.cancel()
        _writer_task = None


# ── loguru 커스텀 싱크 (큐에 넣기만 함, 파일 I/O 없음) ──────────────────────

_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} [{level: <8}] {name}: {message}\n"


def _info_file_sink(message) -> None:
    """INFO 이상 로그를 asyncio.Queue에 적재 — 실제 파일 쓰기는 asyncio 태스크가 담당.

    loguru sink는 어떤 스레드에서도 호출될 수 있으므로 call_soon_threadsafe로
    메인 이벤트 루프에 큐 적재를 예약한다.
    """
    try:
        if _loop_ref is not None and not _loop_ref.is_closed():
            q = _get_file_queue()
            def _safe_put(msg=str(message)):
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass
            _loop_ref.call_soon_threadsafe(_safe_put)
    except RuntimeError:
        pass  # 루프가 닫혀 있음 — 로그 버림


# ── InterceptHandler: 표준 logging → loguru 리다이렉트 ────────────────────────

class InterceptHandler(logging.Handler):
    """표준 logging -> loguru 로 리다이렉트."""

    _WS_MSG_MAP = {
        "connection open": "[연결] 성공",
        "connection closed": "[연결] 종료",
        "연결 닫힘": "[연결] 종료",
    }

    # uvicorn 기동/종료 메시지 한국어화 (access log 제외)
    _UVICORN_MSG_MAP = {
        "Waiting for application startup.": "앱 시작 대기 중",
        "Application startup complete.": "앱 시작 완료",
        "Application startup failed. Exiting.": "앱 시작 실패. 종료.",
        "Waiting for application shutdown.": "앱 종료 대기 중",
        "Application shutdown complete.": "앱 종료 완료",
        "Application shutdown failed. Exiting.": "앱 종료 실패. 종료.",
        "Shutting down": "종료 중",
    }

    # 파라미터 포함 메시지 — 접두사 일치 후 나머지 보존
    _UVICORN_PREFIX_MAP = {
        "Started server process": "서버 프로세스 시작",
        "Finished server process": "서버 프로세스 종료",
        "Uvicorn running on": "Uvicorn 실행 중",
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
        elif record.name.startswith("uvicorn") and not record.name.startswith("uvicorn.access"):
            if msg in self._UVICORN_MSG_MAP:
                msg = self._UVICORN_MSG_MAP[msg]
            else:
                for prefix, replacement in self._UVICORN_PREFIX_MAP.items():
                    if msg.startswith(prefix):
                        msg = replacement + msg[len(prefix):]
                        break

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, msg
        )


# ── 메인 설정 함수 ────────────────────────────────────────────────────────────

_stdout_utf8: io.TextIOWrapper | None = None
# 진행률 \r 갱신 중인지 추적 — 다른 로그가 끼어들면 줄 바꿈 후 출력하여 커서 꼬임 방지 (P23/P24)
_progress_active: bool = False


def _get_stdout_utf8() -> io.TextIOWrapper:
    """stdout UTF-8 래퍼 싱글톤 — loguru remove()로 닫히지 않도록 함수 싱크에서 사용."""
    global _stdout_utf8
    if _stdout_utf8 is None or _stdout_utf8.closed:
        _stdout_utf8 = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
        )
    return _stdout_utf8


def _stdout_sink(message) -> None:
    """loguru 콘솔 싱크 — 함수 기반 (loguru가 close하지 않음).

    진행률 \r 갱신 중에 다른 로그가 끼어들면 먼저 줄 바꿈하여 커서 꼬임 방지.
    """
    global _progress_active
    try:
        s = _get_stdout_utf8()
        if _progress_active:
            s.write("\n")
            s.flush()
            _progress_active = False
        s.write(str(message))
        s.flush()
    except (ValueError, OSError):
        pass  # stdout이 닫힌 경우 — 무시


# ── 다운로드 진행률 1줄 갱신 헬퍼 ──────────────────────────────────────────────
# 콘솔: \r 로 같은 줄 갱신 (TTY 아니면 \n), 파일: DEBUG 레벨 (INFO 운영 시 파일에 안 씀)
# 완료/실패 요약은 logger.info/warning 으로 별도 출력 — P21(사용자 투명성) + P24(단순성)

def log_progress(label: str, cur: int, total: int, *, code: str = "") -> None:
    """다운로드 진행률을 콘솔 1줄에 \r 갱신 + 파일은 DEBUG 기록.

    label: "[다운로드]" 같은 접두 태그
    cur/total: 현재/전체 (1-based cur 권장)
    code: 종목코드 (선택 — 있으면 "삼성전자(005930) 다운로드 완료 — N/M (X%)" 형태)
    """
    global _progress_active
    pct = (cur / total * 100) if total > 0 else 0.0
    code_part = f"{code} " if code else ""
    msg = f"{label} {code_part}다운로드 완료 — {cur:,}/{total:,} ({pct:.1f}%)"
    try:
        s = _get_stdout_utf8()
        if sys.stdout.isatty():
            s.write("\r" + msg)
            s.flush()
            _progress_active = True
        else:
            # 파이프/리다이렉트 시 \r 깨짐 방지 — 일반 줄 출력
            s.write(msg + "\n")
            s.flush()
    except (ValueError, OSError):
        pass
    # 파일에는 DEBUG로 기록 (INFO 운영 시 파일에 진행률 누적 안 됨 → 용량 절감)
    _loguru_logger.opt(depth=1).debug(msg)


def log_progress_end() -> None:
    """진행률 1줄 갱신 종료 — 다음 로그가 새 줄에서 시작하도록 줄 바꿈."""
    global _progress_active
    if not _progress_active:
        return
    try:
        s = _get_stdout_utf8()
        if sys.stdout.isatty():
            s.write("\n")
            s.flush()
    except (ValueError, OSError):
        pass
    _progress_active = False


def log_receive_rate_progress(
    krx_received: int, krx_total: int,
    nxt_received: int, nxt_total: int,
    threshold_pct: float, *, waiting: bool,
) -> None:
    """수신율 갱신을 콘솔 1줄에 \r 갱신 + 파일은 DEBUG 기록.

    log_progress와 동일 패턴 (P23 일관성). _progress_active 플래그 공유.
    waiting=True: 임계값 대기 중 메시지, False: Phase 2 통과 후 메시지.
    파일에는 DEBUG로 기록 (INFO 운영 시 파일에 수신 과정 누적 안 됨 → 용량 절감).
    임계값 통과 시점은 호출측에서 별도 logger.info로 영구 기록 (P21 투명성).
    """
    global _progress_active
    krx_pct = (krx_received / krx_total * 100) if krx_total > 0 else 0.0
    nxt_pct = (nxt_received / nxt_total * 100) if nxt_total > 0 else 0.0
    if waiting:
        msg = (
            f"[연산] 수신율 갱신 — KRX: {krx_received}/{krx_total} ({krx_pct:.1f}%)"
            f" | NXT: {nxt_received}/{nxt_total} ({nxt_pct:.1f}%)"
            f" — 임계값 대기 ({threshold_pct:.1f}%)"
        )
    else:
        msg = (
            f"[연산] 수신율 갱신 — KRX: {krx_received}/{krx_total} ({krx_pct:.1f}%)"
            f" | NXT: {nxt_received}/{nxt_total} ({nxt_pct:.1f}%)"
        )
    try:
        s = _get_stdout_utf8()
        if sys.stdout.isatty():
            s.write("\r" + msg)
            s.flush()
            _progress_active = True
        else:
            # 파이프/리다이렉트 시 \r 깨짐 방지 — 일반 줄 출력
            s.write(msg + "\n")
            s.flush()
    except (ValueError, OSError):
        pass
    # 파일에는 DEBUG로 기록 (INFO 운영 시 파일에 수신 과정 누적 안 됨 → 용량 절감)
    _loguru_logger.opt(depth=1).debug(msg)


def setup_console_intercept(log_level: str = "INFO") -> None:
    """콘솔 싱크 + InterceptHandler 설치 — uvicorn.run() 이전에 호출 가능 (동기).

    uvicorn 기동 초기 메시지(Started server process, Waiting for application startup 등)를
    한국어로 변환. 파일 싱크는 setup_loguru()에서 별도 추가됨.
    """
    _loguru_logger.remove()  # 기본 핸들러 제거 (함수 싱크는 close되지 않음)

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
        _stdout_sink,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> [<level>{extra[level_kr]}</level>] {message}",
        colorize=True,
        filter=_inject_kr_level,
    )

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


async def setup_loguru(log_level: str = "INFO") -> None:
    """앱 기동 시 1회 호출 — 콘솔 + 파일(trading.log) 2채널 설정."""
    global _configured
    if _configured:
        return
    _configured = True

    await asyncio.to_thread(LOG_DIR.mkdir, parents=True, exist_ok=True)

    # 콘솔 싱크 + InterceptHandler (uvicorn.run() 이전에 setup_console_intercept()가
    # 호출되었어도 재설정 — 파일 싱크만 이 시점에 추가)
    setup_console_intercept(log_level)

    # ── 파일 — LOG_LEVEL 이상 (trading.log, 일별 분할, 10MB 로테이션, 2일 보관) ───────
    #    LOG_LEVEL=DEBUG 시 DEBUG 로그도 trading.log에 기록됨
    _loguru_logger.add(
        _info_file_sink,
        level=log_level,
        format=_FILE_FORMAT,
        colorize=False,
    )

    # 파일 쓰기 asyncio 태스크 시작
    await _start_file_writers()
