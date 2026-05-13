# -*- coding: utf-8 -*-
"""
Kiwoom Connector — 키움증권 WebSocket 커넥터

ws_client.py 완전 대체: _KiwoomSocket 내부 클래스에 수신루프/큐/송신 통합.
크로스 플랫폼: Windows, macOS, Linux
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from typing import Callable

from app.core.broker_connector import BrokerConnector

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.exceptions import ConnectionClosed as _WsConnectionClosed
except ImportError:
    websockets = None  # type: ignore
    _WsConnectionClosed = None  # type: ignore




# ── 내부 소켓 클래스 ─────────────────────────────────────────────────────────

class _KiwoomSocket:
    """키움 WebSocket 전용 내부 소켓.

    연결 + LOGIN + 수신루프 + REAL 큐/워커 + 송신을 단일 클래스로 관리.
    connect() 호출 시 수신루프 태스크를 자동 기동 (버그 수정 포함).
    on_message 콜백은 async 함수여야 한다.
    """

    def __init__(self, uri: str, token: str, on_message: Callable, on_disconnect: Callable | None = None, queue_callback: Callable | None = None):
        self._uri = uri
        self._token = token
        self._on_message = on_message          # async callable (폴백)
        self._on_disconnect = on_disconnect    # 연결 끊김 시 호출 (재연결 트리거)
        self._queue_callback = queue_callback  # Producer 콜백 (asyncio.Queue.put_nowait)
        self._ws = None                        # websockets connection
        self.connected = False
        self._stop_event = asyncio.Event()
        self._recv_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """서버 연결 + LOGIN 전송 + 수신루프/워커 기동."""
        if not websockets:
            raise RuntimeError("websockets 패키지가 없습니다.")
        logger.info("[서버소켓] 연결 시도: %s", self._uri)
        self._ws = await websockets.connect(self._uri, open_timeout=10)
        self.connected = True
        logger.info("[서버소켓] 연결 완료 — 로그인 전송")
        await self._raw_send({"trnm": "LOGIN", "token": self._token})
        self._stop_event.clear()
        self._recv_task = asyncio.get_running_loop().create_task(self._recv_loop())

    async def disconnect(self) -> None:
        """수신루프/워커 취소 + 소켓 종료 (최대 30초)."""
        self._stop_event.set()
        self.connected = False
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        self._recv_task = None
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=5.0)
            except Exception:
                logger.warning("[서버소켓] 소켓 종료 실패", exc_info=True)
            self._ws = None
        logger.info("[서버소켓] 연결 종료")

    async def send(self, payload: dict) -> bool:
        """REG/UNREG 등 페이로드 송신. 연결 없으면 False."""
        if not self.connected or not self._ws:
            trnm = payload.get("trnm", "?")
            logger.warning("[서버소켓] 전송 생략 — 연결 없음 (trnm=%s)", trnm)
            return False
        msg = json.dumps(payload, ensure_ascii=False)
        await self._ws.send(msg)
        trnm = payload.get("trnm", "")
        if trnm in ("REG", "UNREG", "REMOVE"):
            logger.debug("[서버소켓] ▶ %s 전송", trnm)
        else:
            logger.debug("[서버소켓] ▶ 전송: %s", msg[:300])
        return True

    async def _raw_send(self, payload: dict) -> None:
        """내부 전용 송신 (연결 체크 없음)."""
        try:
            obj = copy.copy(payload)
            if isinstance(obj.get("token"), str):
                t = obj["token"]
                obj["token"] = f"{t[:4]}…<마스킹됨>" if len(t) > 8 else "***"
            logger.debug("[서버소켓] ▶ 전송: %s", json.dumps(obj, ensure_ascii=False)[:300])
        except Exception:
            logger.warning("[서버소켓] 토큰 마스킹 실패", exc_info=True)
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def _recv_loop(self) -> None:
        """WebSocket 수신루프 — PING 처리, LOGIN 응답, REAL 큐 투입, 연결 끊김 감지."""
        logger.info("[서버소켓] 수신 시작")
        while not self._stop_event.is_set():
            try:
                raw = await self._ws.recv()

                # 1. 문자열 PING
                if isinstance(raw, str) and raw.strip().upper() == "PING":
                    await self._ws.send(raw)
                    logger.debug("[서버소켓] PING 응답(문자)")
                    continue

                # 2. JSON 파싱
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("[서버소켓] 메시지 해석 실패(무시): %s", raw[:80])
                    continue

                if isinstance(msg, list):
                    continue

                trnm = msg.get("trnm", "")

                # 3. JSON PING
                if trnm.upper() == "PING":
                    await self._ws.send(raw)
                    logger.debug("[서버소켓] PING 응답(JSON)")
                    continue

                # 4. LOGIN 응답
                if trnm == "LOGIN":
                    rc = msg.get("return_code", -1)
                    if str(rc) != "0":
                        err = msg.get("return_msg", "원인 불명")
                        logger.error("[서버소켓] 로그인 실패: %s (code=%s)", err, rc)
                        self.connected = False
                        return
                    logger.info("[서버소켓] 로그인 성공")
                    await self._on_message(msg)
                    continue

                # 5. REAL → 큐에 투입 (Producer)
                if trnm == "REAL":
                    if self._queue_callback:
                        try:
                            self._queue_callback(msg)  # put_nowait 호출
                        except asyncio.QueueFull:
                            logger.warning("[서버소켓] 큐 가득 참 — REAL 데이터 드롭: %s", msg.get("trnm"))
                    else:
                        # 폴백: 기존 방식 유지
                        await self._on_message(msg)
                    continue

                # 6. REG/UNREG/REMOVE/SYSTEM 등
                if trnm in ("REG", "UNREG", "REMOVE"):
                    rc = msg.get("return_code", "?")
                    d = msg.get("data", [])
                    cnt = len(d) if isinstance(d, list) else (1 if d else 0)
                    logger.info("[서버소켓] ◄ %s — 결과코드=%s 항목=%d건", trnm, rc, cnt)
                elif trnm == "SYSTEM":
                    logger.warning("[서버소켓] ◄ 서버 강제종료 신호: %s", raw[:300])
                else:
                    logger.debug("[서버소켓] ◄ trnm=%s", trnm)

                # 7. 비-REAL 콜백 (REG ACK 등)
                await self._on_message(msg)

            except Exception as e:
                err_name = type(e).__name__
                is_closed = (
                    (_WsConnectionClosed is not None and isinstance(e, _WsConnectionClosed))
                    or "ConnectionClosed" in err_name
                    or "connection" in str(e).lower()
                )
                if is_closed:
                    self.connected = False
                    if not self._stop_event.is_set():
                        logger.warning("[서버소켓] 연결 끊김 (%s) — 수신 종료", err_name)
                        if self._on_disconnect:
                            asyncio.get_running_loop().create_task(self._on_disconnect())
                    break
                else:
                    if not self._stop_event.is_set():
                        logger.warning("[서버소켓] 수신 오류(계속): %s", e, exc_info=True)
                    await asyncio.sleep(1)

        logger.info("[서버소켓] 수신 종료")




# ── KiwoomConnector ──────────────────────────────────────────────────────────

class KiwoomConnector(BrokerConnector):
    """키움증권 WebSocket 커넥터."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        ws_uri: str = "wss://api.kiwoom.com:10000/api/dostk/websocket",
    ):
        self._app_key = app_key
        self._app_secret = app_secret
        self._ws_uri = ws_uri
        self._socket: _KiwoomSocket | None = None
        self._token: str | None = None
        self._connected = False
        self._receive_callback: Callable | None = None
        self._on_reconnect_success: Callable | None = None
        self._lock = asyncio.Lock()
        self._received_count = 0
        self._realtime_enabled: bool = True  # 실시간 연결 ON/OFF 플래그 (ws_subscribe_on)
        self._auto_trade_enabled: bool = True  # 자동매매 ON/OFF 플래그 (time_scheduler_on)
        self._holiday_block_enabled: bool = True  # 공휴일 자동 차단 ON/OFF (holiday_guard_on)
        self._reconnect_task: asyncio.Task | None = None
        self._stop_reconnect: bool = False
        self._ws_queue: asyncio.Queue | None = None  # Producer-Consumer Queue

    @property
    def broker_id(self) -> str:
        return "kiwoom"

    def is_connected(self) -> bool:
        return self._connected and (self._socket is not None and self._socket.connected)

    def is_realtime_enabled(self) -> bool:
        """실시간 연결 ON/OFF 상태 반환 (ws_subscribe_on 설정값)"""
        return self._realtime_enabled

    def set_realtime_enabled(self, enabled: bool) -> None:
        """실시간 연결 ON/OFF 설정. OFF시 연결되어 있으면 데이터 수신은 계속되지만 로직에서 차단 가능."""
        self._realtime_enabled = enabled
        logger.info("[증권사연결] 실시간 연결 설정 변경: %s", enabled)

    def is_auto_trade_enabled(self) -> bool:
        """자동매매 ON/OFF 상태 반환 (time_scheduler_on 설정값)"""
        return self._auto_trade_enabled

    def set_auto_trade_enabled(self, enabled: bool) -> None:
        """자동매매 ON/OFF 설정."""
        self._auto_trade_enabled = enabled
        logger.info("[증권사연결] 자동매매 설정 변경: %s", enabled)

    def is_holiday_block_enabled(self) -> bool:
        """공휴일 자동 차단 ON/OFF 상태 반환 (holiday_guard_on 설정값)"""
        return self._holiday_block_enabled

    def set_holiday_block_enabled(self, enabled: bool) -> None:
        """공휴일 자동 차단 ON/OFF 설정."""
        self._holiday_block_enabled = enabled
        logger.info("[증권사연결] 공휴일 자동 차단 설정 변경: %s", enabled)

    async def connect(self) -> None:
        """토큰 발급 + WebSocket 연결 + 수신루프 기동."""
        self._stop_reconnect = False
        async with self._lock:
            if self._connected:
                return
            token = await self._get_token_async()
            if not token:
                raise ConnectionError("키움 토큰 발급 실패")
            self._token = token
            # Queue 콜백 래퍼 (put_nowait 호출)
            queue_callback = None
            if self._ws_queue is not None:
                def _queue_put_nowait(msg: dict) -> None:
                    try:
                        self._ws_queue.put_nowait(msg)
                    except asyncio.QueueFull:
                        logger.warning("[증권사연결] 큐 가득 참 — 데이터 드롭")
                queue_callback = _queue_put_nowait

            self._socket = _KiwoomSocket(
                uri=self._ws_uri,
                token=self._token,
                on_message=self._on_ws_message,
                on_disconnect=self._on_socket_disconnect,
                queue_callback=queue_callback,
            )
            await self._socket.connect()
            self._connected = True
            logger.info("[증권사연결] 연결 완료")
            # 연결 상태 브로드캐스트
            try:
                from app.services.ws_subscribe_control import broadcast_ws_connection_status
                broadcast_ws_connection_status(True)
            except Exception:
                logger.warning("[증권사연결] 연결 상태 브로드캐스트 실패", exc_info=True)

    async def disconnect(self) -> None:
        """수신루프 중단 + WebSocket 종료. 재연결 루프도 중단."""
        self._stop_reconnect = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        async with self._lock:
            self._connected = False
            if self._socket:
                await self._socket.disconnect()
                self._socket = None
            logger.info("[증권사연결] 연결 종료")
            # 연결 해제 상태 브로드캐스트
            try:
                from app.services.ws_subscribe_control import broadcast_ws_connection_status
                broadcast_ws_connection_status(False)
            except Exception:
                logger.warning("[증권사연결] 연결 해제 상태 브로드캐스트 실패", exc_info=True)

    async def send_message(self, payload: dict) -> bool:
        """engine_service._ws_send_reg_unreg_and_wait_ack용 송신 API."""
        if not self._socket:
            return False
        return await self._socket.send(payload)

    async def subscribe(self, code: str, data_types: list[str]) -> bool:
        """종목 구독 등록."""
        if not self.is_connected() or not self._socket:
            logger.warning("[증권사연결] 구독 실패 — 연결 없음")
            return False
        formatted_code = self._format_code(code)
        type_mapping = {"0B": "0B", "0D": "0D", "quote": "0B", "fill": "0D"}
        mapped_types = [type_mapping.get(dt, dt) for dt in data_types]
        payload = {
            "trnm": "REG",
            "grp_no": "4",
            "refresh": "1",
            "data": [{"item": [formatted_code], "type": mapped_types}],
        }
        success = await self._socket.send(payload)
        if success:
            logger.debug("[증권사연결] 구독 등록: %s (%s)", code, mapped_types)
        return success

    async def unsubscribe(self, code: str, data_types: list[str]) -> bool:
        """종목 구독 해지."""
        if not self.is_connected() or not self._socket:
            return False
        formatted_code = self._format_code(code)
        type_mapping = {"0B": "0B", "0D": "0D", "quote": "0B", "fill": "0D"}
        mapped_types = [type_mapping.get(dt, dt) for dt in data_types]
        payload = {
            "trnm": "REMOVE",
            "grp_no": "4",
            "refresh": "1",
            "data": [{"item": [formatted_code], "type": mapped_types}],
        }
        success = await self._socket.send(payload)
        if success:
            logger.debug("[증권사연결] 구독 해지: %s", code)
        return success

    async def _on_ws_message(self, payload: dict) -> None:
        """_KiwoomSocket 콜백 → 핸들러 직접 호출."""
        self._received_count += 1
        if self._receive_callback:
            if asyncio.iscoroutinefunction(self._receive_callback):
                await self._receive_callback(payload)
            else:
                self._receive_callback(payload)

    async def _on_socket_disconnect(self) -> None:
        """_KiwoomSocket 연결 끊김 시 호출 — 재연결 루프 기동."""
        if self._stop_reconnect:
            return
        self._connected = False
        try:
            import app.services.engine_service as _es
            _es._login_ok = False
        except Exception:
            logger.warning("[증권사연결] _login_ok 초기화 실패", exc_info=True)
        try:
            from app.services.ws_subscribe_control import broadcast_ws_connection_status
            broadcast_ws_connection_status(False)
        except Exception:
            logger.warning("[증권사연결] 연결 끊김 상태 브로드캐스트 실패", exc_info=True)
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.get_running_loop().create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """지수 백오프 재연결 루프 (1→2→4→8→16→32초, 최대 10회)."""
        delays = [1, 2, 4, 8, 16, 32, 32, 32, 32, 32]
        for attempt, delay in enumerate(delays, start=1):
            if self._stop_reconnect:
                logger.info("[증권사연결] 재연결 중단 (stop 신호)")
                return
            logger.info("[증권사연결] 재연결 시도 %d/10 — %d초 후", attempt, delay)
            await asyncio.sleep(delay)
            if self._stop_reconnect:
                return
            try:
                token = await self._get_token_async()
                if not token:
                    logger.warning("[증권사연결] 재연결 %d회: 토큰 발급 실패", attempt)
                    continue
                self._token = token
                async with self._lock:
                    # Queue 콜백 래퍼 (재연결 시도)
                    queue_callback = None
                    if self._ws_queue is not None:
                        def _queue_put_nowait(msg: dict) -> None:
                            try:
                                self._ws_queue.put_nowait(msg)
                            except asyncio.QueueFull:
                                logger.warning("[증권사연결] 큐 가득 참 — 데이터 드롭 (재연결)")
                        queue_callback = _queue_put_nowait

                    self._socket = _KiwoomSocket(
                        uri=self._ws_uri,
                        token=self._token,
                        on_message=self._on_ws_message,
                        on_disconnect=self._on_socket_disconnect,
                        queue_callback=queue_callback,
                    )
                    await self._socket.connect()
                    self._connected = True
                logger.info("[증권사연결] 재연결 성공 (시도 %d회)", attempt)
                # 재연결 성공 후 큐 클리어 (과거 데이터 제거)
                if self._ws_queue is not None:
                    while not self._ws_queue.empty():
                        try:
                            self._ws_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    logger.info("[증권사연결] 재연결 후 큐 클리어 완료")
                try:
                    from app.services.ws_subscribe_control import broadcast_ws_connection_status
                    broadcast_ws_connection_status(True)
                except Exception:
                    logger.warning("[증권사연결] 재연결 상태 브로드캐스트 실패", exc_info=True)
                # 재연결 후 구독 복원은 ConnectorManager가 담당
                if self._on_reconnect_success:
                    asyncio.get_running_loop().create_task(self._on_reconnect_success(self.broker_id))
                return
            except Exception as e:
                logger.warning("[증권사연결] 재연결 %d회 실패: %s", attempt, e, exc_info=True)
        logger.error("[증권사연결] 최대 재연결 횟수(10회) 초과 — 포기")

    def set_reconnect_success_callback(self, callback: Callable) -> None:
        """재연결 성공 시 호출될 콜백 설정 (ConnectorManager가 구독 복원에 사용)."""
        self._on_reconnect_success = callback

    def set_message_callback(self, callback: Callable) -> None:
        """메시지 수신 콜백 설정."""
        self._receive_callback = callback

    def set_queue_callback(self, queue: asyncio.Queue) -> None:
        """Producer-Consumer Queue 설정."""
        self._ws_queue = queue

    def _format_code(self, code: str) -> str:
        """종목코드 포맷팅 — 키움 형식."""
        code = code.strip().upper().lstrip("A")
        if not code.endswith("_AL") and len(code) == 6:
            return f"{code}_AL"
        return code

    async def _get_token_async(self) -> str | None:
        """토큰 발급 (비동기 래핑)."""
        def _sync_get_token():
            from app.core.kiwoom_rest import KiwoomRestAPI
            api = KiwoomRestAPI(self._app_key, self._app_secret)
            return api.get_access_token()
        return await asyncio.to_thread(_sync_get_token)


# ── 팩토리 ───────────────────────────────────────────────────────────────────

def create_kiwoom_connector(settings: dict) -> KiwoomConnector:
    """설정 dict에서 KiwoomConnector 생성."""
    app_key = (settings.get("kiwoom_app_key") or "").strip()
    app_secret = (settings.get("kiwoom_app_secret") or "").strip()
    if not app_key or not app_secret:
        raise ValueError("키움 app_key, app_secret이 설정되지 않았습니다")
    return KiwoomConnector(app_key=app_key, app_secret=app_secret)
