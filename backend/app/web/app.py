from __future__ import annotations
# -*- coding: utf-8 -*-
"""FastAPI 웹 서버 — 엔진과 동일한 asyncio 이벤트 루프에서 실행."""

import asyncio
import logging
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from backend.app.di.container import get_container

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan 이벤트 핸들러."""
    # --- startup ---
    from backend.app.core.logging_config import configure_app_logging
    configure_app_logging()
    
    container = get_container()

    # DB 캐시 테이블 초기화 (가장 먼저 실행)
    from backend.app.db.db_writer import start_db_writer
    await start_db_writer()
    
    # 전역 큐 초기화 (엔진 시작 전 보장)
    from backend.app.services.core_queues import initialize_queues
    initialize_queues()
    
    from backend.app.db.stock_tables import init_cache_tables, create_stock_5d_array_table
    await init_cache_tables()
    await create_stock_5d_array_table()
    
    # SQLite 3차 마이그레이션 자동 실행 (통합 단일 마스터 테이블 구축)
    from backend.app.db.migration_v3 import run_migration_v3
    await run_migration_v3()

    # 거래일 캐시 초기화
    from backend.app.core.trading_calendar import initialize_trading_calendar_cache
    await initialize_trading_calendar_cache()

    # 새 설정 테이블 초기화 (표준 아키텍처)
    from backend.app.db.models import (
        create_system_settings_table,
        create_user_settings_table,
        create_broker_credentials_table,
        create_system_config_table,
        create_broker_specs_table,
        create_integrated_system_settings_table,
    )
    await create_system_settings_table()
    await create_user_settings_table()
    await create_broker_credentials_table()
    await create_system_config_table()
    await create_broker_specs_table()

    # 기존 system_settings 테이블이 있을 경우 개별 테이블로 마이그레이션 실행
    from backend.app.db.migration import migrate_settings_from_system_settings, drop_system_settings_table
    await migrate_settings_from_system_settings()

    # broker_specs JSON → SQLite 마이그레이션
    from backend.app.db.models import migrate_broker_specs_from_json
    await migrate_broker_specs_from_json()

    # 최종 통합설정 마스터 물리 테이블 및 트리거(integrated_system_settings) 생성
    await create_integrated_system_settings_table()

    # 기존 system_settings 테이블 안전 제거
    await drop_system_settings_table()

    # 단일 통합설정 마스터 테이블(integrated_system_settings)로부터 1회 로드 완료
    from backend.app.core.settings_file import load_settings
    settings = await load_settings()
    
    # settings를 container에 등록
    container.register_singleton("settings", settings)

    logger.info("[웹서버] ThreadPoolExecutor 설정 직전")
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=8))
    logger.info("[웹서버] ThreadPoolExecutor 설정 완료")

    logger.info("[웹서버] daily_time_scheduler import 직전")
    from backend.app.services.daily_time_scheduler import start_daily_time_scheduler
    logger.info("[웹서버] daily_time_scheduler import 완료")
    
    logger.info("[웹서버] engine_service import 직전")
    from backend.app.services.engine_service import start_engine
    logger.info("[웹서버] engine_service import 완료")
    
    from backend.app.services.telegram_bot import telegram_bot
    from backend.app.services import trade_history
    from backend.app.services.backend_coalescing import BackendCoalescing
    import backend.app.services.engine_service as _es

    # 체결 이력 Consumer Task 시작 (비동기 I/O 백그라운드 처리)
    # 모듈 전역 변수 초기화 (비정상 종료 후 재시작 시 잔존 상태 방지)
    trade_history._reset_global_state()
    trade_history.start_consumer_task()

    # Journal Consumer Task 시작 (Phase 4.2 Persistence Journaling)
    from backend.app.core import journal
    logger.info("[웹서버] journal.start_consumer_task() 호출 직전")
    journal.start_consumer_task()
    logger.info("[웹서버] journal.start_consumer_task() 호출 완료")
    logger.info("[웹서버] Journal Consumer Task 시작 완료")

    # 엔진 초기화 (설정 → 데이터 로드 → 증권사 연결)
    logger.info("[웹서버] 엔진 초기화 시작")
    logger.info("[웹서버] start_engine() 호출 직전")
    success = await start_engine(user_id="admin")
    logger.info("[웹서버] start_engine() 반환 완료, success=%s", success)
    if not success:
        logger.error("[웹서버] 엔진 초기화 실패")
        raise RuntimeError("엔진 초기화 실패")
    
    logger.info("[웹서버] 엔진 초기화 성공, backend_coalescing 등록 진입")
    # Backend Coalescing 싱글톤 등록
    backend_coalescing = BackendCoalescing.get_instance()
    await backend_coalescing.start()
    container.register_singleton("backend_coalescing", backend_coalescing)
    logger.info("[DI Container] backend_coalescing 싱글톤 등록 완료")
    
    # WS Manager 싱글톤 등록
    from backend.app.web.ws_manager import ws_manager
    container.register_singleton("ws_manager", ws_manager)
    logger.info("[DI Container] ws_manager 싱글톤 등록 완료")
    
    # 서버 준비 완료 상태 설정 (클라이언트 요청 수신 가능)
    # 웹 서버가 즉시 기동되어 Health Check 등에 응답할 수 있도록 함
    _es._server_ready_event.set()
    logger.info("[웹서버] 서버 준비 완료 이벤트 설정 (Fast Boot)")

    # 엔진 준비 완료 플래그 즉시 설정 (백그라운드 다운로드와 무관하게 웹서버 기동 완료)
    _es._engine_ready_event.set()
    logger.info("[웹서버] 엔진 준비 완료 이벤트 설정 (비차단)")

    # 스케줄러 시작
    await start_daily_time_scheduler()

    # 텔레그램은 후순위 — 여유 시간 후 시작 (편의 기능, 타이머 제거)
    async def _start_telegram_lazy():
        await asyncio.sleep(3.0)  # 브로커·WS 안정화 후 시작
        telegram_bot.start()
        logger.info("[웹서버] 텔레그램 폴링 시작 (후순위)")

    asyncio.create_task(_start_telegram_lazy())

    yield

    # --- shutdown ---
    from backend.app.services.daily_time_scheduler import stop_daily_time_scheduler
    from backend.app.services.engine_service import stop_engine
    from backend.app.services import trade_history

    # 체결 이력 Consumer Task 종료 (Graceful Shutdown - 큐에 남은 데이터 모두 저장)
    await trade_history.stop_consumer_task()
    logger.info("[웹서버] 체결 이력 Consumer Task 종료 완료")

    # Journal Consumer Task 종료 (Phase 4.2 Persistence Journaling)
    from backend.app.core import journal
    await journal.stop_consumer_task()
    logger.info("[웹서버] Journal Consumer Task 종료 완료")

    await telegram_bot.stop_async()
    await stop_engine()
    await stop_daily_time_scheduler()
    
    # DB Writer 종료 및 DB 커넥션 정리
    from backend.app.db.db_writer import stop_db_writer
    from backend.app.db.database import close_db_connection
    await stop_db_writer()
    await close_db_connection()
    logger.info("[웹서버] DB Writer 및 DB 커넥션 정리 완료")
    
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
from backend.app.web.routes.auth import router as auth_router
from backend.app.web.routes.account import router as account_router
from backend.app.web.routes.market import router as market_router
from backend.app.web.routes.status import router as status_router
from backend.app.web.routes.settings import router as settings_router
from backend.app.web.routes.ws import router as ws_router
from backend.app.web.routes.ws_settings import router as ws_settings_router
from backend.app.web.routes.ws_orders import router as ws_orders_router
from backend.app.web.routes.trade import router as trade_router
from backend.app.web.routes.ws_subscribe import router as ws_subscribe_router

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(market_router)
app.include_router(status_router)
app.include_router(ws_settings_router)
app.include_router(ws_orders_router)
app.include_router(settings_router)
app.include_router(ws_router)
app.include_router(trade_router)
app.include_router(ws_subscribe_router)

from backend.app.web.routes.stock_classification import router as stock_classification_router
app.include_router(stock_classification_router)

from backend.app.web.routes.settlement import router as settlement_router
app.include_router(settlement_router)



# --- 전역 예외 핸들러 ---
from fastapi import Request
from fastapi.responses import JSONResponse
import time

# P1-3: 중복 알림 차단 (5분 제한)
_last_alert_time: dict[str, float] = {}
ALERT_COOLDOWN_SECONDS = 300  # 5분


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("[웹서버] 처리되지 않은 예외: %s", exc)

    # P1-3: 텔레그램 알림 (5분 동안 동일 에러 1회 제한)
    error_type = type(exc).__name__
    current_time = time.time()
    last_alert = _last_alert_time.get(error_type, 0)

    if current_time - last_alert >= ALERT_COOLDOWN_SECONDS:
        # 5분 이상 지났으면 알림 전송
        from backend.app.services.telegram import send_msg_async
        from backend.app.core.settings_store import get_settings_async

        try:
            settings = await get_settings_async()
            error_msg = f"[SectorFlow 에러 알림]\n에러 타입: {error_type}\n메시지: {str(exc)}\n경로: {request.url.path}"
            await send_msg_async(error_msg, settings, msg_type="error_alert")
            _last_alert_time[error_type] = current_time
            logger.info("[웹서버] 텔레그램 에러 알림 전송 완료 - error_type=%s", error_type)
        except Exception as e:
            logger.warning("[웹서버] 텔레그램 알림 전송 실패: %s", e)
    else:
        logger.debug("[웹서버] 텔레그램 알림 스킵 (쿨다운 중) - error_type=%s", error_type)

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
