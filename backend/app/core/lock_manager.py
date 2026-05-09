# -*- coding: utf-8 -*-
"""
잠금 파일(Lock File) 기반 중복 실행 방지 모듈.
서버 시작 시 잠금 파일을 확인하여 이미 실행 중인 인스턴스가 있으면 차단한다.

변경: 가이드라인에 따라 PID 체크 등 복잡한 로직을 제거하고 OS 레벨의 파일 락에만 의존하는 "단순 파일 락"으로 전환.
크로스 플랫폼 지원: Windows, macOS, Linux
"""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 잠금 파일 경로 — backend/data/server.lock
LOCK_FILE_PATH: Path = Path(__file__).resolve().parent.parent.parent / "data" / "server.lock"

# 모듈 수준에서 잠금 파일 핸들을 유지 (프로세스 종료 전까지 잠금 유지)
_lock_fh = None


def acquire_lock(lock_path: Path) -> bool:
    """잠금 파일 획득 시도. 성공 시 True, 중복 실행 감지 시 False.

    OS별 배타적 잠금을 사용하여 두 프로세스가
    동시에 실행되더라도 하나만 통과하도록 보장한다.
    """
    global _lock_fh  # noqa: PLW0603

    # 디렉토리 없으면 자동 생성
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Windows: 배타적 잠금 (msvcrt.locking)
        # macOS/Linux: 파일 락 (fcntl.flock)
        if sys.platform == "win32":
            import msvcrt
            fh = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115
            try:
                # LK_NBLCK: Non-blocking lock
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except (OSError, IOError):
                fh.close()
                logger.warning("중복 실행 감지: 다른 프로세스가 잠금 파일을 점유 중입니다.")
                return False
        else:
            # macOS/Linux
            import fcntl
            fh = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, IOError):
                fh.close()
                logger.warning("중복 실행 감지: 다른 프로세스가 잠금 파일을 점유 중입니다.")
                return False

        # 현재 PID 기록 (단순 정보용)
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        
        _lock_fh = fh  # 핸들을 유지해야 잠금이 풀리지 않음
        logger.info("잠금 파일 획득 완료: %s (PID: %d)", lock_path, os.getpid())
        return True
    except OSError as exc:
        logger.error("잠금 파일 획득 실패: %s — %s", lock_path, exc)
        return False


def release_lock(lock_path: Path) -> None:
    """잠금 파일 삭제 + 파일 핸들 닫기."""
    global _lock_fh  # noqa: PLW0603
    try:
        if _lock_fh is not None:
            try:
                _lock_fh.close()
            except OSError:
                pass
            _lock_fh = None
        
        # 파일 삭제 (OS 락이 풀린 후)
        if lock_path.exists():
            lock_path.unlink(missing_ok=True)
            logger.info("잠금 파일 삭제 완료: %s", lock_path)
    except OSError as exc:
        logger.warning("잠금 파일 삭제 실패: %s — %s", lock_path, exc)


def register_cleanup(lock_path: Path) -> None:
    """atexit + signal 핸들러 등록하여 종료 시 잠금 파일 자동 삭제."""

    def _cleanup() -> None:
        release_lock(lock_path)

    # atexit 핸들러 — 정상 종료 시 호출
    atexit.register(_cleanup)

    def _signal_handler(signum: int, frame: object) -> None:
        release_lock(lock_path)
        sys.exit(0)

    # SIGTERM, SIGINT 핸들러 등록
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Windows 전용: SIGBREAK
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)  # type: ignore[attr-defined]

    logger.info("잠금 파일 정리 핸들러 등록 완료")


def read_lock_pid(lock_path: Path) -> int | None:
    """잠금 파일에서 PID를 읽어온다. 실패 시 None."""
    try:
        if lock_path.exists():
            content = lock_path.read_text(encoding="utf-8").strip()
            if content.isdigit():
                return int(content)
    except Exception:  # noqa: BLE001
        pass
    return None


def format_duplicate_message(existing_pid: int) -> str:
    """중복 실행 에러 메시지 포맷팅."""
    return (
        f"\n{'='*60}\n"
        f"⚠️ 중복 실행 감지 (SectorFlow)\n"
        f"이미 다른 프로세스(PID: {existing_pid})가 실행 중이거나,\n"
        f"이전 프로세스가 비정상 종료되어 잠금 파일이 남아 있습니다.\n\n"
        f"해결 방법:\n"
        f"1. 해당 프로세스 종료: `kill -9 {existing_pid}`\n"
        f"2. 잠금 파일 삭제: `rm {LOCK_FILE_PATH}`\n"
        f"{'='*60}\n"
    )
