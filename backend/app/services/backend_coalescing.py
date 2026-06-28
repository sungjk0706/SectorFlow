from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
Backend 1차 Coalescing 레이어
- 종목(code) 기준 Map 사용
- 동일 종목 이벤트 덮어쓰기
- 네트워크로 전송 전 압축
- flush 타이밍: 조건 1 (10ms 경과) OR 조건 2 (pendingMap size > 200)
- Protobuf 직렬화 (바이너리 스트림)
"""

import asyncio
import json
import logging
import time

from backend.protobuf import event_pb2
from backend.app.services.core_queues import get_tick_queue

logger = logging.getLogger(__name__)


class BackendCoalescing:
    """
    Backend 1차 Coalescing 레이어

    특징:
    - 종목(code) 기준 Map 사용
    - 동일 종목 이벤트 덮어쓰기
    - 네트워크로 전송 전 압축
    - flush 타이밍: 조건 1 (10ms 경과) OR 조건 2 (pendingMap size > 200)
    - 두 조건 중 하나 만족 시 즉시 flush
    - burst traffic 대응 가능
    """

    _instance: Optional["BackendCoalescing"] = None

    def __init__(self, flush_interval_ms: int = 10, flush_threshold: int = 200):
        self.pending_map: Dict[str, Dict[str, Any]] = {}
        self.flush_interval_ms = flush_interval_ms
        self.flush_threshold = flush_threshold
        self.is_running = False
        self.flush_task: Optional[asyncio.Task] = None
        self.websocket_connections: Set = set()
        self.last_flush_time: float = 0
        self._flush_event_obj: Optional[asyncio.Event] = None
        self.dropped_count: int = 0  # Drop된 패킷 수 (Coalescing으로 덮어쓰기)

    @property
    def flush_event(self) -> asyncio.Event:
        if self._flush_event_obj is None:
            self._flush_event_obj = asyncio.Event()
        return self._flush_event_obj

    @flush_event.setter
    def flush_event(self, val: asyncio.Event) -> None:
        self._flush_event_obj = val

    @classmethod
    def get_instance(cls) -> "BackendCoalescing":
        """싱글톤 인스턴스 반환"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_event(self, code: str, event: Dict[str, Any]) -> None:
        """이벤트 추가 (종목 기준 Coalescing)"""
        # 동일 종목 코드가 이미 존재하면 Drop 카운트 증가
        if code in self.pending_map:
            self.dropped_count += 1
        
        self.pending_map[code] = event

        # 조건 2: pendingMap size > threshold 즉시 flush (Event 기반)
        if len(self.pending_map) >= self.flush_threshold:
            self.flush_event.set()  # flush 이벤트 트리거

    def add_raw_data(self, data: Dict[str, Any]) -> None:
        """원본 JSON 데이터를 받아서 이벤트로 변환 후 추가"""
        try:
            code = self._extract_code(data)
            if code:
                event = {
                    "type": data.get("type", ""),
                    "data": data,
                    "timestamp": time.time(),
                }
                self.add_event(code, event)
            else:
                logger.debug("[BackendCoalescing] 종목코드 없음")
        except Exception as e:
            logger.error(f"[BackendCoalescing] 데이터 처리 오류: {e}", exc_info=True)

    def _extract_code(self, data: Dict[str, Any]) -> str:
        """종목코드 추출"""
        # 증권사 형식
        if "code" in data:
            return data["code"]
        # LS증권 형식
        if "header" in data:
            tr_key = data.get("header", {}).get("tr_key", "")
            return tr_key[1:7] if len(tr_key) >= 7 else ""
        return ""

    def add_websocket(self, websocket) -> None:
        """WebSocket 연결 추가"""
        self.websocket_connections.add(websocket)

    def remove_websocket(self, websocket) -> None:
        """WebSocket 연결 제거"""
        self.websocket_connections.discard(websocket)

    def get_dropped_count(self) -> int:
        """Drop된 패킷 수 조회"""
        return self.dropped_count

    def reset_dropped_count(self) -> None:
        """Drop 카운트 리셋"""
        self.dropped_count = 0

    async def start(self) -> None:
        """Coalescing 시작"""
        if self.is_running:
            logger.warning("[BackendCoalescing] 이미 실행 중, early return")
            return

        self.is_running = True
        self.last_flush_time = time.time()
        self.flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Coalescing 중지"""
        self.is_running = False
        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        logger.info("[BackendCoalescing] 중지")

    async def _flush_loop(self) -> None:
        """flush 루프 (Event 기반 최적화)"""
        try:
            while self.is_running:
                # flush_event가 set되거나 10ms 타이머 만료 시 flush
                try:
                    await asyncio.wait_for(
                        self.flush_event.wait(),
                        timeout=self.flush_interval_ms / 1000.0
                    )
                except asyncio.TimeoutError:
                    pass  # 10ms 타이머 만료 - 정상적인 타이머 flush

                # flush 실행
                await self._flush()
                self.last_flush_time = time.time()
                self.flush_event.clear()  # 이벤트 초기화
        except asyncio.CancelledError:
            pass
        finally:
            # 중지 시 남은 이벤트 flush
            if self.pending_map:
                await self._flush()

    async def _flush(self) -> None:
        """flush 실행 (네트워크로 전송 전 압축 + tick_queue 전송)"""
        if not self.pending_map:
            return

        # 복사 후 clear
        events = dict(self.pending_map)
        self.pending_map.clear()
        self.last_flush_time = time.time()

        # Protobuf 직렬화 (바이너리 스트림)
        serialized = self._serialize_events(events)

        # P2-5: tick_queue에 전송하던 로직 제거 (pipeline_compute 에러 방지)
        # active_connector가 직접 raw 데이터를 tick_queue에 넣으므로 여기서는 프론트엔드로 전송만 담당합니다.

        # 모든 WebSocket에 전송
        if self.websocket_connections:
            # 병렬 전송으로 개선 (느린 연결의 영향 최소화)
            tasks = []
            for websocket in self.websocket_connections:
                try:
                    tasks.append(websocket.send_bytes(serialized))
                except Exception as e:
                    logger.error(f"[BackendCoalescing] 전송 준비 실패: {e}")

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def _serialize_events(self, events: Dict[str, Dict[str, Any]]) -> bytes:
        """이벤트 직렬화 (Protobuf)"""
        if not events:
            return b""

        # 모든 이벤트를 직렬화하여 패킹
        serialized_events = []
        for code, event in events.items():
            event_proto = event_pb2.Event()
            event_proto.type = event.get("type", "")
            event_proto.timestamp = event.get("timestamp", time.time())

            # data 필드 추가
            for key, value in event.get("data", {}).items():
                event_proto.data[key] = str(value)

            # latency_trace 필드 추가
            latency_trace = event.get("latency_trace", {})
            for key, value in latency_trace.items():
                event_proto.latency_trace[key] = float(value)

            # 종목코드를 event.data에 추가
            event_proto.data["code"] = code

            # 직렬화
            serialized = event_proto.SerializeToString()
            # 길이 접두사 (4 bytes) + 직렬화된 이벤트
            length_prefix = len(serialized).to_bytes(4, byteorder='big')
            serialized_events.append(length_prefix + serialized)

        # 모든 직렬화된 이벤트를 하나의 바이너리 스트림으로 결합
        return b"".join(serialized_events)
