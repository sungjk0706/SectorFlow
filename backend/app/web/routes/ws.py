# -*- coding: utf-8 -*-
"""WebSocket 통합 엔드포인트 — 모든 이벤트를 단일 채널로 전송.

fire-and-forget broadcast는 WSManager가 담당하며,
이 엔드포인트는 연결 관리 + initial snapshot + ping-pong만 처리한다."""
from __future__ import annotations
import asyncio
import json
import logging
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from backend.app.web.ws_manager import ws_manager
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["websocket"])


async def _send_initial_snapshot_delayed(websocket: WebSocket, ws_manager) -> None:
    """데이터 준비 대기 → engine-ready → stock-classification-changed → initial-snapshot → sector-stocks-refresh → sector-scores → buy-targets-update → index-data 순차 유니캐스트.

    아키텍처 원칙: 외부 HTTP I/O(토큰 발급)가 UI 렌더링을 블로킹하지 않음.
    initial-snapshot은 캐시 기반 데이터만 포함하므로 토큰 없이 즉시 전송.
    index-data(broker_statuses 포함)는 token_ready와 무관하게 즉시 전송."""
    try:
        from backend.app.services.engine_state import state
        from backend.app.services.engine_config import get_settings_snapshot

        settings = get_settings_snapshot()
        _trade_mode = settings.get("trade_mode", "")

        # 이벤트 구동 방식: 데이터 준비 완료 시 즉시 전송 (타임아웃/폴링 제거)
        # 테스트모드와 실전모드 동일하게 데이터 준비 대기 (앱 기동 준비는 돈과 무관)
        if not state.data_ready_event.is_set():
            logger.info("[연결] 데이터 준비 대기 중 — 초기 스냅샷 전송 지연")
            await state.data_ready_event.wait()
            logger.info("[연결] 데이터 준비 완료 — 초기 스냅샷 전송 시작")

        # 앱 준비 완료 대기 (이벤트 구동)
        # 테스트모드와 실전모드 동일하게 앱 준비 대기 (앱 기동 준비는 돈과 무관)
        if not state.bootstrap_event.is_set():
            logger.info("[연결] 앱 준비 대기 중 — 초기 스냅샷 전송 지연")
            await state.bootstrap_event.wait()
            logger.info("[연결] 앱 준비 완료 — 초기 스냅샷 전송 시작")

        # 엔진 준비 완료 유니캐스트 전송 (engine-ready)
        if state.bootstrap_event.is_set():
            await ws_manager.send_to(websocket, "engine-ready", {"_v": 1, "ready": True})

        # stock-classification 초기 데이터 전송 (업종순위 계산과 무관하게 독립 전송)
        from backend.app.core.stock_classification_data import load_custom_data
        from backend.app.core.sector_mapping import get_merged_all_sectors

        custom = load_custom_data()
        merged = await get_merged_all_sectors()
        no_sector_count = 0
        filter_summary = ""
        try:
            from backend.app.services.sector_data_provider import get_all_sector_stocks
            import backend.app.services.engine_state as _es
            from backend.app.core.sector_stock_cache import assemble_filter_summary
            stocks = await get_all_sector_stocks()
            if "미분류" in merged:
                no_sector_count = sum(1 for s in stocks if s["sector"] == "미분류")
            filter_summary = assemble_filter_summary(
                getattr(_es.state, "latest_filter_summary_meta", ""), len(stocks)
            )
        except Exception as e:
            logger.warning("[연결] 초기 스냅샷 데이터 준비 실패: %s", e, exc_info=True)

        stock_classification_payload = {
            "_v": 1,
            "custom_data": {
                "sectors": dict(custom.sectors),
                "stock_moves": dict(custom.stock_moves),
                "deleted_sectors": list(custom.deleted_sectors),
            },
            "merged_sectors": merged,
            "no_sector_count": no_sector_count,
            "filter_summary": filter_summary,
            "all_stocks": stocks,
        }
        await ws_manager.send_to(websocket, "stock-classification-changed", stock_classification_payload)

        # 업종순위 계산 대기 로직 삭제 (앱 기동과 업종순위 계산 독립성 보장)
        # 업종순위 계산은 백그라운드 태스크로 실행되며, 완료 시 WS로 전송됨

        # initial-snapshot 전송 (업종순위 계산 완료와 무관하게 즉시 전송)
        from backend.app.services.engine_snapshot import build_initial_snapshot

        snapshot = await build_initial_snapshot()
        await ws_manager.send_to(websocket, "initial-snapshot", snapshot)

        # sector-stocks-refresh 전송
        from backend.app.services.engine_snapshot import build_sector_stocks_payload

        stocks_payload = await build_sector_stocks_payload()
        await ws_manager.send_to(websocket, "sector-stocks-refresh", stocks_payload)

        # sector-scores 전송
        from backend.app.services.sector_data_provider import get_sector_scores_snapshot
        from backend.app.services.engine_state import state

        # 업종 요약정보 생성 완료 대기 (테스트모드 포함)
        if not state.sector_summary_ready_event.is_set():
            logger.info("[연결] 업종 요약정보 생성 대기 중")
            await state.sector_summary_ready_event.wait()
            logger.info("[연결] 업종 요약정보 생성 완료")

        # ── 수신율 임계값 게이트 — WS 구독 구간 내 임계값 미달 시 sector-scores 전송 차단 ──
        from backend.app.pipelines.pipeline_compute import is_sector_threshold_passed
        if not is_sector_threshold_passed():
            logger.info("[연결] 업종점수 미전송 — 수신율 임계값 미달")
        else:
            scores_result = get_sector_scores_snapshot()
            scores, ranked_count = scores_result if isinstance(scores_result, tuple) else (scores_result, 0)
            if scores:
                from backend.app.pipelines.pipeline_compute import get_current_receive_rate
                scores_payload = {
                    "_v": 1,
                    "scores": scores,
                    "status": {
                        "total_stocks": len(scores),
                        "max_targets": int(
                            state.integrated_system_settings_cache["sector_max_targets"]
                        ),
                        "ranked_sectors_count": ranked_count,
                        "receive_rate": get_current_receive_rate(),
                    },
                }
                await ws_manager.send_to(websocket, "sector-scores", scores_payload)
            else:
                if state.sector_summary_cache is None:
                    logger.info(
                        "[연결] 업종점수 미전송 — 업종 요약정보 없음"
                    )
                else:
                    logger.info("[연결] 업종점수 미전송 — 종목 없음 (정상)")

        # buy-targets 전송 (initial-snapshot에 이미 포함되어 있으나, WS delta 메커니즘을 위해 별도 전송)
        from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks

        targets = await get_buy_targets_sector_stocks()
        if targets:
            await ws_manager.send_to(
                websocket, "buy-targets-update", {"_v": 1, "buy_targets": targets}
            )

        # 엔진 상태 전송 (index-data) — broker_statuses 포함, token_ready와 무관하게 즉시 전송
        from backend.app.services.engine_lifecycle import get_engine_status
        engine_status = get_engine_status()
        engine_status["_v"] = 1
        await ws_manager.send_to(websocket, "index-data", engine_status)
    except Exception as e:
        logger.error("[연결] 초기 스냅샷 전송 실패: %s", e, exc_info=True)


@router.websocket("/prices")
async def ws_prices(websocket: WebSocket, token: str = Query(...)):
    """통합 WebSocket 엔드포인트 — 연결 관리 + initial snapshot + ping-pong."""
    # TODO: 개발 완료 후 토큰 검증 재활성화
    # username = verify_token(token)
    # if username is None:
    #     await websocket.close(code=1008)
    #     return
    username = "dev"

    await websocket.accept()
    await ws_manager.register(websocket)
    logger.info(
        "[연결] 접속 화면 연결 (사용자=%s, 총 %d)", username, ws_manager.client_count
    )

    delayed_task: asyncio.Task | None = None
    try:
        # 앱 준비 대기 → 업종순위 계산 대기 → initial-snapshot 및 sector 데이터 순차 유니캐스트
        delayed_task = asyncio.create_task(_send_initial_snapshot_delayed(websocket, ws_manager))

        # 수신 루프: ping → pong, page-active/page-inactive → 페이지 추적, 그 외 무시
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "page-active":
                page = msg.get("page", "")
                if page:
                    ws_manager.set_active_page(websocket, page)
            elif msg_type == "page-inactive":
                ws_manager.clear_active_page(websocket)
            elif msg_type == "subscribe-fids":
                fids = msg.get("fids", [])
                if isinstance(fids, list):
                    ws_manager.set_subscribed_fids(websocket, fids)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("[연결] 접속 화면 오류: %s", e)
    finally:
        if delayed_task is not None:
            delayed_task.cancel()
        ws_manager.unregister(websocket)
        logger.info("[연결] 접속 화면 해제 (총 %d)", ws_manager.client_count)
