# -*- coding: utf-8 -*-
"""WebSocket 통합 엔드포인트 — 모든 이벤트를 단일 채널로 전송.

fire-and-forget broadcast는 WSManager가 담당하며,
이 엔드포인트는 연결 관리 + initial snapshot + ping-pong만 처리한다."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.web.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["websocket"])


async def _send_stocks_delayed(websocket: WebSocket) -> None:
    """앱준비 완료 대기 → sector-stocks-refresh, sector-scores, buy-targets-update 순차 유니캐스트."""
    try:
        # 앱준비 완료 대기
        from app.services.engine_service import _bootstrap_event

        if not _bootstrap_event.is_set():
            logger.info("[연결] 앱준비 대기 중 -- 업종목록 전송 지연")
            try:
                await asyncio.wait_for(_bootstrap_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning("[연결] 앱준비 60초 대기 초과 -- 현재 데이터로 전송")

        # sector-stocks-refresh: 앱준비 완료 즉시 전송
        from app.services.engine_service import build_sector_stocks_payload

        stocks_payload = await build_sector_stocks_payload()
        stock_count = len(stocks_payload.get("stocks", []))
        logger.info("[연결] 업종목록 화면전송 -- %d종목", stock_count)
        await ws_manager.send_to(websocket, "sector-stocks-refresh", stocks_payload)

        # 업종순위 계산 완료 대기
        from app.services.engine_service import _sector_summary_ready_event

        if not _sector_summary_ready_event.is_set():
            logger.info("[연결] 업종순위 계산 대기 중")
            try:
                await asyncio.wait_for(_sector_summary_ready_event.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.warning("[연결] 업종순위 계산 120초 대기 초과 -- 생략")
                return

        # sector-scores 전송
        from app.services.engine_service import (
            _settings_cache,
            get_sector_scores_snapshot,
        )

        scores_result = get_sector_scores_snapshot()
        scores, ranked_count = scores_result if isinstance(scores_result, tuple) else (scores_result, 0)
        if scores:
            scores_payload = {
                "_v": 1,
                "scores": scores,
                "status": {
                    "total_stocks": len(scores),
                    "max_targets": int(
                        _settings_cache.get("sector_max_targets", 3) or 3
                    ),
                    "ranked_sectors_count": ranked_count,
                },
            }
            await ws_manager.send_to(websocket, "sector-scores", scores_payload)
            logger.info("[연결] 업종점수 화면전송 -- %d개 섹터", len(scores))
        else:
            from app.services import engine_service as _es_check

            if _es_check._sector_summary_cache is None:
                logger.warning(
                    "[연결] 업종점수 미전송 -- 업종 요약정보 없음"
                )
            else:
                logger.info("[연결] 업종점수 미전송 -- 종목 없음 (정상)")

        # buy-targets 전송
        from app.services.engine_service import get_buy_targets_snapshot

        targets = get_buy_targets_snapshot()
        if targets:
            await ws_manager.send_to(
                websocket, "buy-targets-update", {"_v": 1, "buy_targets": targets}
            )
            logger.info("[연결] 매수후보 화면전송 -- %d건", len(targets))
    except Exception as e:
        logger.error("[연결] 업종목록 화면전송 실패: %s", e, exc_info=True)


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
    ws_manager.register(websocket)
    logger.info(
        "[연결] 접속화면 연결 (user=%s, 총 %d)", username, ws_manager.client_count
    )

    delayed_task: asyncio.Task | None = None
    try:
        # initial-snapshot 유니캐스트
        from app.services.engine_service import build_initial_snapshot

        logger.info("[연결] 시작화면 데이터 생성 시작")
        snapshot = await build_initial_snapshot()
        logger.info("[연결] 시작화면 데이터 생성 완료")
        await ws_manager.send_to(websocket, "initial-snapshot", snapshot)

        # 앱준비 대기 → sector 데이터 순차 유니캐스트
        delayed_task = asyncio.create_task(_send_stocks_delayed(websocket))

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
        logger.warning("[연결] 접속화면 오류: %s", e)
    finally:
        if delayed_task is not None:
            delayed_task.cancel()
        ws_manager.unregister(websocket)
        logger.info("[연결] 접속화면 해제 (총 %d)", ws_manager.client_count)
