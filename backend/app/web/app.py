# -*- coding: utf-8 -*-
"""FastAPI 웹 서버 — 엔진과 동일한 asyncio 이벤트 루프에서 실행."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan 이벤트 핸들러."""
    # --- startup ---
    from app.core.logging_config import configure_app_logging
    configure_app_logging()

    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=8))

    from app.services.daily_time_scheduler import start_daily_time_scheduler
    from app.services.engine_service import start_engine
    from app.services.telegram_bot import telegram_bot
    from app.services import trade_history
    import app.services.engine_service as _es

    # 체결 이력 Consumer Task 시작 (비동기 I/O 백그라운드 처리)
    # 모듈 전역 변수 초기화 (비정상 종료 후 재시작 시 잔존 상태 방지)
    trade_history._reset_global_state()
    trade_history.start_consumer_task()

    # 엔진 초기화 (설정 → 데이터 로드 → 증권사 연결)
    logger.info("[웹서버] 엔진 초기화 시작")
    success = await start_engine(user_id="admin")
    if not success:
        logger.error("[웹서버] 엔진 초기화 실패")
        raise RuntimeError("엔진 초기화 실패")
    
    # 엔진 부트스트랩 완료 대기 (최대 120초)
    try:
        await asyncio.wait_for(_es._bootstrap_event.wait(), timeout=120.0)
        logger.info("[웹서버] 엔진 초기화 완료")
        
        # 엔진 준비 완료 상태 설정
        _es._engine_ready_event.set()
        logger.info("[웹서버] 엔진 준비 완료 이벤트 설정")
        
    except asyncio.TimeoutError:
        logger.error("[웹서버] 엔진 부트스트랩 120초 초과")
        # 타임아웃이어도 서버는 시작되어야 함
        logger.warning("[웹서버] 타임아웃 발생했지만 서버 시작 계속 진행")
        # 엔진 준비 상태는 설정하지 않음 (클라이언트가 health check로 확인)

    # 서버 준비 완료 상태 설정 (클라이언트 요청 수신 가능)
    _es._server_ready_event.set()
    logger.info("[웹서버] 서버 준비 완료 이벤트 설정")

    # 스케줄러 시작
    start_daily_time_scheduler()

    # 텔레그램은 후순위 — 앱준비 완료 + 여유 시간 후 시작 (편의 기능)
    async def _start_telegram_lazy():
        try:
            await asyncio.wait_for(_es._bootstrap_event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            logger.warning("[웹서버] 엔진 앱준비 120초 대기 초과")
        await asyncio.sleep(3.0)  # 브로커·WS 안정화 후 시작
        telegram_bot.start()
        logger.info("[웹서버] 텔레그램 폴링 시작 (후순위)")

    asyncio.create_task(_start_telegram_lazy())

    yield

    # --- shutdown ---
    from app.services.daily_time_scheduler import stop_daily_time_scheduler
    from app.services.engine_service import stop_engine
    from app.services import trade_history

    # 체결 이력 Consumer Task 종료 (Graceful Shutdown - 큐에 남은 데이터 모두 저장)
    await trade_history.stop_consumer_task()
    logger.info("[웹서버] 체결 이력 Consumer Task 종료 완료")

    await telegram_bot.stop_async()
    await stop_engine()
    await stop_daily_time_scheduler()
    
    # 상태 이벤트 정리
    _es._engine_ready_event.clear()
    _es._server_ready_event.clear()
    logger.info("[웹서버] 엔진 종료 완료")


app = FastAPI(
    title="SectorFlow",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 미들웨어 (개발 시 localhost 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 페이지 컨텍스트는 미들웨어 대신 각 라우트에서 request.headers로 직접 읽음
# (미들웨어는 WebSocket/WS/CORS와 충돌 위험이 있으므로 사용하지 않음)

# --- 라우터 등록 ---
from app.web.routes.auth import router as auth_router
from app.web.routes.account import router as account_router
from app.web.routes.market import router as market_router
from app.web.routes.status import router as status_router
from app.web.routes.settings import router as settings_router
from app.web.routes.ws import router as ws_router
from app.web.routes.trade import router as trade_router
from app.web.routes.ws_subscribe import router as ws_subscribe_router

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(market_router)
app.include_router(status_router)
app.include_router(settings_router)
app.include_router(ws_router)
app.include_router(trade_router)
app.include_router(ws_subscribe_router)

from app.web.routes.sector_custom import router as sector_custom_router
app.include_router(sector_custom_router)

from app.web.routes.settlement import router as settlement_router
app.include_router(settlement_router)


# --- 전역 예외 핸들러 ---
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("[웹서버] 처리되지 않은 예외: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류"},
    )


# --- 캐시 제어 미들웨어 ---
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse


class CacheControlMiddleware(BaseHTTPMiddleware):
    """모든 정적 파일 응답에 적절한 Cache-Control 헤더를 일괄 적용.

    - /assets/* (Vite 해시 번들): 1년 장기 캐시 (immutable)
    - index.html 및 기타 HTML: no-cache (항상 최신)
    - API 응답: 건드리지 않음
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        response: StarletteResponse = await call_next(request)
        path = request.url.path

        # API 경로는 건드리지 않음
        if path.startswith("/api/") or path.startswith("/ws") or path.startswith("/stream"):
            return response

        # /assets/* — Vite 해시 번들 → 장기 캐시
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

        # 그 외 (index.html, favicon 등) → no-cache
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type or path == "/" or not path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response


app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(CacheControlMiddleware)


# --- 정적 파일 서빙 (React 빌드 결과물) ---
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """API 경로가 아닌 모든 요청 → React index.html 반환 (SPA 라우팅)."""
        file_path = _FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
