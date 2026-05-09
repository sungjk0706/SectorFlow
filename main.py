# -*- coding: utf-8 -*-
"""
SectorFlow — FastAPI 서버 진입점
실행: 프로젝트 루트에서  python main.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if __name__ == "__main__":
    import logging
    import asyncio
    import uvicorn
    from backend.app.core.lock_manager import (
        LOCK_FILE_PATH,
        acquire_lock,
        format_duplicate_message,
        read_lock_pid,
        register_cleanup,
    )

    logger = logging.getLogger(__name__)

    # 1. 잠금 파일 기반 중복 실행 검사
    if not acquire_lock(LOCK_FILE_PATH):
        existing_pid = read_lock_pid(LOCK_FILE_PATH)
        msg = format_duplicate_message(existing_pid or 0)
        print(msg)
        logger.warning("중복 실행 시도 차단: %s", msg)
        sys.exit(1)

    # 2. 종료 시 잠금 파일 자동 삭제 핸들러 등록
    register_cleanup(LOCK_FILE_PATH)

    from fastapi.staticfiles import StaticFiles
    from backend.app.web.app import app
    
    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    else:
        print(f"⚠️ 프론트엔드 빌드 폴더 없음: {frontend_dist}")

    # 3. 포트 사용 여부 사전 검사
    import socket
    _port = 8000
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        if _s.connect_ex(("127.0.0.1", _port)) == 0:
            print(f"\n❌ 포트 {_port}가 이미 사용 중입니다.")
            print(f"   기존 프로세스를 종료하거나 잠금 파일을 삭제하세요:")
            print(f"   lsof -ti:{_port} | xargs kill -9")
            print(f"   rm -f {LOCK_FILE_PATH}\n")
            sys.exit(1)

    # 4. uvicorn 서버 시작 (엔진 초기화는 lifespan에서 처리)
    uvicorn.run(
        "app.web.app:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        ws_ping_interval=30,
        ws_ping_timeout=10,
    )