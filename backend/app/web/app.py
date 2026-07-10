# -*- coding: utf-8 -*-
"""FastAPI 웹 서버 — 엔진과 동일한 asyncio 이벤트 루프에서 실행."""
from __future__ import annotations
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
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
from backend.app.web.routes.stock_classification import router as stock_classification_router
from backend.app.web.routes.settlement import router as settlement_router
from backend.app.web.routes.stock_detail import router as stock_detail_router
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan 이벤트 핸들러."""
    # --- startup ---
    _t_lifespan_start = time.perf_counter()
    from backend.app.core.logging_config import configure_app_logging
    await configure_app_logging()

    

    # DB Writer 시작
    from backend.app.db.db_writer import start_db_writer
    await start_db_writer()

    # DB 테이블 초기화 (CREATE TABLE IF NOT EXISTS — 기존 테이블 영향 없음)
    # 다른 DB read가 해당 테이블에 의존할 수 있으므로 가장 먼저 실행
    from backend.app.db.stock_tables import init_cache_tables, migrate_add_hidden_to_custom_sectors, create_master_stocks_table, migrate_master_stocks_table_pk
    await init_cache_tables()
    await create_master_stocks_table()
    await migrate_master_stocks_table_pk()
    await migrate_add_hidden_to_custom_sectors()

    # 전역 큐 초기화 (엔진 시작 전 보장)
    from backend.app.services.core_queues import initialize_queues
    initialize_queues()

    # Gateway 루프 시작 (엔진과 독립적으로 실행 - 파이프라인 독립성 보장)
    from backend.app.pipelines.pipeline_gateway import start_gateway_loop
    _gateway_task = asyncio.create_task(start_gateway_loop())
    _gateway_task.add_done_callback(lambda t: logger.warning("[웹서버] Gateway 루프 태스크 실패: %s", t.exception()) if t.exception() else None)
    logger.info("[웹서버] Gateway 루프 시작 완료")

    # ── 3개 독립 DB read 작업 병렬 실행 (순차 대기 시간 제거) ──
    from backend.app.core.trading_calendar import initialize_trading_calendar_cache
    from backend.app.core.sector_stock_cache import load_filter_summary_meta_cache
    from backend.app.core.settings_file import load_integrated_system_settings
    from backend.app.services.engine_state import state

    async def _load_filter_summary_meta():
        try:
            state.latest_filter_summary_meta = await load_filter_summary_meta_cache()
            logger.info("[웹서버] filter_summary_meta 캐시 로드 완료")
        except Exception as e:
            logger.warning("[웹서버] filter_summary_meta 캐시 초기 로드 실패: %s", e)

    _trading_cal_task, _filter_meta_task, _settings_task = await asyncio.gather(
        initialize_trading_calendar_cache(),
        _load_filter_summary_meta(),
        load_integrated_system_settings(),
    )
    logger.info("[웹서버] 거래일 캐시 초기화 완료")
    settings = _settings_task


    # state.integrated_system_settings_cache 초기화 (단일 소스 진리 보장)
    state.integrated_system_settings_cache.clear()
    state.integrated_system_settings_cache.update(settings)


    from backend.app.services.daily_time_scheduler import start_daily_time_scheduler
    
    from backend.app.services.engine_lifecycle import start_engine
    
    from backend.app.services.telegram_bot import telegram_bot
    from backend.app.services import trade_history

    # 체결 이력 Consumer Task 시작 (비동기 I/O 백그라운드 처리)
    # 모듈 전역 변수 초기화 (비정상 종료 후 재시작 시 잔존 상태 방지)
    trade_history._reset_global_state()
    trade_history.start_consumer_task()

    # Journal Consumer Task 시작 (Phase 4.2 Persistence Journaling)
    from backend.app.core import journal
    journal.start_consumer_task()
    logger.info("[웹서버] Journal Consumer Task 시작 완료")

    # 서버 준비 완료 — Health endpoint 즉시 응답 (프론트엔드 접속 허용)
    from backend.app.services.engine_state import state
    state.server_ready_event.set()

    # 엔진 초기화 백그라운드 실행 (프론트엔드 접속과 병렬)
    # WS 핸들러가 data_ready_event / bootstrap_event 대기 후 스냅샷 전송하므로
    # 엔진 초기화 완료 전에 프론트엔드 접속해도 데이터는 자동 대기됨
    logger.info("[웹서버] 엔진 백그라운드 초기화 시작")
    async def _engine_init_background():
        try:
            success = await start_engine(user_id="admin")
            if not success:
                logger.error("[웹서버] 엔진 초기화 실패")
                return

            state.engine_ready_event.set()
            logger.info("[웹서버] [앱시작] lifespan 총 기동시간 — %.0fms", (time.perf_counter() - _t_lifespan_start) * 1000)

            await start_daily_time_scheduler()

            async def _start_telegram_lazy():
                await asyncio.sleep(3.0)
                _s = state.integrated_system_settings_cache
                if bool(_s.get("tele_on", False)):
                    telegram_bot.start()
                    logger.info("[웹서버] 텔레그램 폴링 시작 (후순위)")
                else:
                    logger.info("[웹서버] 텔레그램 OFF — 폴링 시작 안 함")
            _tg_task = asyncio.create_task(_start_telegram_lazy())
            _tg_task.add_done_callback(lambda t: logger.warning("[웹서버] 텔레그램 지연시작 태스크 실패: %s", t.exception()) if t.exception() else None)
        except Exception as e:
            logger.error("[웹서버] 엔진 백그라운드 초기화 실패: %s", e, exc_info=True)

    _engine_init_task = asyncio.create_task(_engine_init_background())
    _engine_init_task.add_done_callback(lambda t: logger.warning("[웹서버] 엔진 초기화 태스크 실패: %s", t.exception()) if t.exception() else None)

    yield

    # --- shutdown ---
    # 1. WS 클라이언트 정상 종료 (EPIPE 방지 — close_all이 flush_task 취소 + 모든 ws.close())
    from backend.app.web.ws_manager import ws_manager
    await ws_manager.close_all()
    logger.info("[웹서버] WebSocket 클라이언트 정상 종료 완료")

    from backend.app.services.daily_time_scheduler import stop_daily_time_scheduler
    from backend.app.services.engine_lifecycle import stop_engine
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

    # 파일 로거 태스크 정지
    from backend.app.core.logger import stop_file_writers
    await stop_file_writers()
    logger.info("[웹서버] 파일 로거 태스크 정지 완료")
    
    # 상태 이벤트 정리
    state.engine_ready_event.clear()
    state.server_ready_event.clear()
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
app.include_router(stock_classification_router)
app.include_router(settlement_router)
app.include_router(stock_detail_router)



# --- 전역 예외 핸들러 ---

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
        from backend.app.services.engine_config import get_settings_snapshot

        try:
            settings = get_settings_snapshot()
            error_msg = f"[SectorFlow 에러 알림]\n에러 타입: {error_type}\n메시지: {str(exc)}\n경로: {request.url.path}"
            await send_msg_async(error_msg, settings, msg_type="error_alert")
            _last_alert_time[error_type] = current_time
            logger.info("[웹서버] 텔레그램 에러 알림 전송 완료 - error_type=%s", error_type)
        except Exception as e:
            logger.warning("[웹서버] 텔레그램 알림 전송 실패: %s", e)

    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류"},
    )


# --- 캐시 제어 미들웨어 ---


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

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """API 경로가 아닌 모든 요청 → React index.html 반환 (SPA 라우팅)."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        file_path = _FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
