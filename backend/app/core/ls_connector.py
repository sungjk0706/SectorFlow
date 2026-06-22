from __future__ import annotations
# -*- coding: utf-8 -*-
"""
LS증권 Connector — LS증권 WebSocket 커넥터

키움 Connector와 동일한 아키텍처로 구현:
- _LsSocket: 내부 WebSocket 소켓 클래스 (연결, 수신루프, 메시지 파싱)
- LsConnector: BrokerConnector 인터페이스 구현
- Producer-Consumer Queue 연동 (tick_queue)
- 재연결 루프 (지수 백오프)
- LS WebSocket 메시지 → 내부 형식 변환
"""

import asyncio
import copy
import json
import logging
from collections.abc import Callable

from backend.app.core.broker_connector import BrokerConnector

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.exceptions import ConnectionClosed as _WsConnectionClosed
except ImportError:
    websockets = None  # type: ignore
    _WsConnectionClosed = None  # type: ignore


# ── 내부 소켓 클래스 ─────────────────────────────────────────────────────────

class _LsSocket:
    """LS증권 WebSocket 전용 내부 소켓.

    연결 + 수신루프 + 송신을 단일 클래스로 관리.
    connect() 호출 시 수신루프 태스크를 자동 기동.
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
        """서버 연결 + 수신루프 기동."""
        if not websockets:
            raise RuntimeError("websockets 패키지가 없습니다.")
        logger.info("[LS서버소켓] 연결 시도: %s", self._uri)
        self._ws = await websockets.connect(self._uri, open_timeout=10)
        self.connected = True
        logger.info("[LS서버소켓] 연결 완료")
        self._stop_event.clear()
        self._recv_task = asyncio.get_running_loop().create_task(self._recv_loop())

    async def disconnect(self) -> None:
        """수신루프 취소 + 소켓 종료 (최대 30초)."""
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
                logger.warning("[LS서버소켓] 소켓 종료 실패", exc_info=True)
            self._ws = None
        logger.info("[LS서버소켓] 연결 종료")

    async def send(self, payload: dict) -> bool:
        """페이로드 송신. 연결 없으면 False."""
        if not self.connected or not self._ws:
            tr_cd = payload.get("body", {}).get("tr_cd", "?")
            logger.warning("[LS서버소켓] 전송 생략 — 연결 없음 (tr_cd=%s)", tr_cd)
            return False
        msg = json.dumps(payload, ensure_ascii=False)
        await self._ws.send(msg)
        tr_cd = payload.get("body", {}).get("tr_cd", "")
        tr_type = payload.get("header", {}).get("tr_type", "")
        if tr_type in ("3", "4"):
            logger.debug("[LS서버소켓] ▶ %s 전송 (tr_type=%s)", tr_cd, tr_type)
        else:
            logger.debug("[LS서버소켓] ▶ 전송: %s", msg[:300])
        return True

    async def _recv_loop(self) -> None:
        """WebSocket 수신루프 — 메시지 파싱, LS → 내부 형식 변환, 연결 끊김 감지."""
        logger.info("[LS서버소켓] 수신 시작")
        while not self._stop_event.is_set():
            try:
                raw = await self._ws.recv()

                # JSON 파싱
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("[LS서버소켓] 메시지 해석 실패(무시): %s", raw[:80])
                    continue

                if isinstance(msg, list):
                    continue

                # LS 메시지 구조: {header: {tr_cd, tr_key}, body: {...}}
                header = msg.get("header", {})
                body = msg.get("body", {})
                tr_cd = header.get("tr_cd", "")

                # LS → 내부 형식 변환
                internal_msg = self._convert_ls_to_internal(tr_cd, header, body)

                if internal_msg:
                    # Producer-Consumer Queue에 투입
                    if self._queue_callback:
                        try:
                            self._queue_callback(internal_msg)  # put_nowait 호출
                        except asyncio.QueueFull:
                            logger.warning("[LS서버소켓] 큐 가득 참 — REAL 데이터 드롭: %s", tr_cd)
                    else:
                        # 폴백: 기존 방식 유지
                        await self._on_message(internal_msg)
                else:
                    # 변환 실패 또는 처리 불필요한 메시지
                    logger.debug("[LS서버소켓] 변환 실패 또는 처리 불필요: %s", tr_cd)

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
                        logger.warning("[LS서버소켓] 연결 끊김 (%s) — 수신 종료", err_name)
                        if self._on_disconnect:
                            asyncio.get_running_loop().create_task(self._on_disconnect())
                    break
                else:
                    if not self._stop_event.is_set():
                        logger.warning("[LS서버소켓] 수신 오류(계속): %s", e, exc_info=True)
                    await asyncio.sleep(1)

        logger.info("[LS서버소켓] 수신 종료")

    def _convert_ls_to_internal(self, tr_cd: str, header: dict, body: dict | None) -> dict | None:
        """LS WebSocket 메시지 → 내부 tick_queue 형식 변환.

        LS US3 (체결) → 키움 REAL 형식과 호환
        """
        if not body:
            return None

        if tr_cd == "US3":
            # 체결 데이터
            shcode = body.get("shcode", "")
            if not shcode:
                return None

            # LS에서 받은 데이터는 문자열이므로 숫자로 변환 (엔진 호환성을 위해 값 추출 시 정규화)
            price = int(body.get("price", 0) or 0)
            volume = int(body.get("volume", 0) or 0)
            value = int(body.get("value", 0) or 0)
            chetime = str(body.get("chetime", "")).strip()
            sign = str(body.get("sign", "3")).strip()
            change = int(body.get("change", 0) or 0)
            drate = float(body.get("drate", 0) or 0)
            
            # KRX 실시간 체결 틱에서 drate 누락 대비 보정 로직
            if drate == 0.0 and change > 0 and price > 0:
                if sign in ("4", "5"):
                    prev_close = price + change
                elif sign in ("1", "2"):
                    prev_close = price - change
                else:
                    prev_close = price
                
                if prev_close > 0:
                    drate = round((change / prev_close) * 100, 2)
            open_price = int(body.get("open", 0) or 0)
            high = int(body.get("high", 0) or 0)
            low = int(body.get("low", 0) or 0)
            cvolume = int(body.get("cvolume", 0) or 0)
            cgubun = str(body.get("cgubun", "")).strip()
            offerho = int(body.get("offerho", 0) or 0)
            bidho = int(body.get("bidho", 0) or 0)
            cpower = float(body.get("cpower", 0) or 0.0)

            # 부호 적용 (키움 포맷)
            sign_char = ""
            if sign in ("4", "5"):
                sign_char = "-"
            elif sign in ("1", "2"):
                sign_char = "+"

            price_str = f"{sign_char}{price}" if sign_char else str(price)
            change_str = f"{sign_char}{change}" if sign_char else str(change)
            drate_str = f"{sign_char}{drate}" if sign_char else str(drate)

            # 내부 형식 (키움 REAL과 완벽 호환되도록 type, values 래핑 및 FID 매핑)
            return {
                "trnm": "REAL",
                "data": [{
                    "type": "0B", # 주식 체결
                    "code": shcode,
                    "values": {
                        "10": price_str,       # 현재가
                        "11": change_str,      # 전일대비
                        "12": drate_str,       # 등락률
                        "13": str(cvolume),    # 거래량(당일체결량)
                        "14": str(value),      # 누적거래대금(백만원)
                        "15": str(volume),     # 누적거래량
                        "16": str(open_price), # 시가
                        "17": str(high),       # 고가
                        "18": str(low),        # 저가
                        "20": chetime,         # 체결시간
                        "27": str(offerho),    # 최우선매도호가
                        "28": str(bidho),      # 최우선매수호가
                        "228": str(cpower),    # 체결강도
                    }
                }]
            }
        elif tr_cd == "UH1":
            # 호가잔량 데이터 (통합)
            raw_shcode = body.get("shcode") or body.get("ex_shcode", "")
            if not raw_shcode:
                return None
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            shcode = _base_stk_cd(raw_shcode)
            unt_totofferrem = int(body.get("unt_totofferrem", 0) or 0)
            unt_totbidrem = int(body.get("unt_totbidrem", 0) or 0)
            return {
                "trnm": "REAL",
                "data": [{
                    "type": "0D", # 주식호가잔량
                    "code": shcode,
                    "values": {
                        "121": str(unt_totofferrem),  # 총 매도호가잔량
                        "125": str(unt_totbidrem),    # 총 매수호가잔량
                    }
                }]
            }
        elif tr_cd == "UPH":
            # 프로그램순매수 데이터 (금액 tval 기준)
            raw_shcode = body.get("shcode") or body.get("ex_shcode", "")
            if not raw_shcode:
                return None
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            shcode = _base_stk_cd(raw_shcode)
            tval = int(body.get("tval", 0) or 0)
            return {
                "trnm": "REAL",
                "data": [{
                    "type": "PGM", # 프로그램매매 커스텀 타입
                    "code": shcode,
                    "values": {
                        "tval": str(tval), # 전체순매수금액
                    }
                }]
            }
        elif tr_cd == "IJ_":
            # 지수 데이터 (향후 확장용)
            # 현재는 업종 점수 계산에 US3만 사용하므로 로그만 남김
            logger.debug("[LS서버소켓] 지수 데이터 수신 (현재 미사용): %s", tr_cd)
            return None
        elif tr_cd == "BM_":
            # 업종 데이터 (향후 확장용)
            logger.debug("[LS서버소켓] 업종 데이터 수신 (현재 미사용): %s", tr_cd)
            return None
        else:
            # logger.debug("[LS서버소켓] 알 수 없는 TR 코드: %s", tr_cd)  # 로깅 억제
            return None


# ── LsConnector ──────────────────────────────────────────────────────────

class LsConnector(BrokerConnector):
    """LS증권 WebSocket 커넥터."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        ws_uri: str = "wss://openapi.ls-sec.co.kr:9443/websocket",
    ):
        self._app_key = app_key
        self._app_secret = app_secret
        self._ws_uri = ws_uri
        self._socket: _LsSocket | None = None
        self._token: str | None = None
        self._connected = False
        self._receive_callback: Callable | None = None
        self._on_reconnect_success: Callable | None = None
        self._lock: asyncio.Lock | None = None
        self._received_count = 0
        self._realtime_enabled: bool = True  # 실시간 연결 ON/OFF 플래그
        self._auto_trade_enabled: bool = True  # 자동매매 ON/OFF 플래그
        self._holiday_block_enabled: bool = True  # 공휴일 자동 차단 ON/OFF
        self._reconnect_task: asyncio.Task | None = None
        self._stop_reconnect: bool = False
        self._ws_queue: asyncio.Queue | None = None  # Producer-Consumer Queue

    @property
    def broker_id(self) -> str:
        return "ls"

    def is_connected(self) -> bool:
        return self._connected and (self._socket is not None and self._socket.connected)

    def supports_ack(self) -> bool:
        return False

    def is_realtime_enabled(self) -> bool:
        """실시간 연결 ON/OFF 상태 반환"""
        return self._realtime_enabled

    def set_realtime_enabled(self, enabled: bool) -> None:
        """실시간 연결 ON/OFF 설정."""
        self._realtime_enabled = enabled
        logger.info("[LS증권연결] 실시간 연결 설정 변경: %s", enabled)

    def is_auto_trade_enabled(self) -> bool:
        """자동매매 ON/OFF 상태 반환"""
        return self._auto_trade_enabled

    def set_auto_trade_enabled(self, enabled: bool) -> None:
        """자동매매 ON/OFF 설정."""
        self._auto_trade_enabled = enabled
        logger.info("[LS증권연결] 자동매매 설정 변경: %s", enabled)

    def is_holiday_block_enabled(self) -> bool:
        """공휴일 자동 차단 ON/OFF 상태 반환"""
        return self._holiday_block_enabled

    def set_holiday_block_enabled(self, enabled: bool) -> None:
        """공휴일 자동 차단 ON/OFF 설정."""
        self._holiday_block_enabled = enabled
        logger.info("[LS증권연결] 공휴일 자동 차단 설정 변경: %s", enabled)

    async def connect(self) -> None:
        """토큰 발급 + WebSocket 연결 + 수신루프 기동."""
        self._stop_reconnect = False
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._connected:
                return
            token = await self._get_token_async()
            if not token:
                raise ConnectionError("LS증권 토큰 발급 실패")
            self._token = token
            # Queue 콜백 래퍼 (드롭 정책 적용)
            queue_callback = None
            if self._ws_queue is not None:
                def _queue_put_with_drop(msg: dict) -> None:
                    """드롭 정책 적용 - 큐 가득 찼을 때 가장 오래된 데이터 버리고 최신 데이터 삽입."""
                    try:
                        self._ws_queue.put_nowait(msg)
                    except asyncio.QueueFull:
                        try:
                            self._ws_queue.get_nowait()
                            self._ws_queue.put_nowait(msg)
                            logger.debug("[LS증권연결] tick_queue 드롭 발생 - 최신 데이터 유지")
                        except asyncio.QueueEmpty:
                            self._ws_queue.put_nowait(msg)
                queue_callback = _queue_put_with_drop

            self._socket = _LsSocket(
                uri=self._ws_uri,
                token=self._token,
                on_message=self._on_ws_message,
                on_disconnect=self._on_socket_disconnect,
                queue_callback=queue_callback,
            )
            await self._socket.connect()
            self._connected = True
            logger.info("[LS증권연결] 연결 완료")
            try:
                from backend.app.services.engine_state import state
                state.login_ok = True
                from backend.app.services.engine_state import _notify_reg_ack
                _notify_reg_ack()
                # LS증권은 소켓 연결 완료가 로그인 완료이므로 직접 REG 파이프라인 트리거
                from backend.app.services.daily_time_scheduler import _trigger_reg_pipeline
                _trigger_reg_pipeline()
            except Exception:
                logger.warning("[LS증권연결] _login_ok 설정 및 파이프라인 트리거 실패", exc_info=True)
            # 연결 상태 브로드캐스트
            try:
                from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                broadcast_ws_connection_status(True)
            except Exception:
                logger.warning("[LS증권연결] 연결 상태 브로드캐스트 실패", exc_info=True)

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
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self._connected = False
            if self._socket:
                await self._socket.disconnect()
                self._socket = None
            logger.info("[LS증권연결] 연결 종료")
            # 연결 해제 상태 브로드캐스트
            try:
                from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                broadcast_ws_connection_status(False)
            except Exception:
                logger.warning("[LS증권연결] 연결 해제 상태 브로드캐스트 실패", exc_info=True)

    async def send_message(self, payload: dict) -> bool:
        """engine_service._ws_send_reg_unreg_and_wait_ack용 송신 API."""
        if not self._socket:
            return False
        return await self._socket.send(payload)

    async def subscribe(self, code: str, data_types: list[str]) -> bool:
        """단건 종목 구독 등록 (하위 호환성용)."""
        return await self.subscribe_stocks([code])

    async def unsubscribe(self, code: str, data_types: list[str]) -> bool:
        """단건 종목 구독 해지 (하위 호환성용)."""
        return await self.unsubscribe_stocks([code])

    async def subscribe_stocks(self, codes: list[str]) -> bool:
        """종목 리스트 실시간 구독 등록 (LS WebSocket: tr_type=3, tr_cd=US3)."""
        if not self.is_connected() or not self._socket:
            logger.warning("[LS증권연결] 구독 실패 — 연결 없음")
            return False

        success_all = True
        for code in codes:
            # LS 종목코드 포맷: U + 6자리 + 공백 3자리
            formatted_code = self._format_code(code)

            # LS는 US3 (체결) 하나만 지원
            payload = {
                "header": {
                    "token": self._token,
                    "tr_type": "3"  # 3: 실시간 시세 등록
                },
                "body": {
                    "tr_cd": "US3",
                    "tr_key": formatted_code
                }
            }
            success = await self._socket.send(payload)
            if not success:
                success_all = False
            else:
                logger.debug("[LS증권연결] 구독 등록: %s", code)
            # 웹소켓 부하 조절을 위해 지연 추가 (0.1초 간격)
            await asyncio.sleep(0.1)
        return success_all

    async def unsubscribe_stocks(self, codes: list[str]) -> bool:
        """종목 리스트 실시간 구독 해지 (LS WebSocket: tr_type=4, tr_cd=US3)."""
        if not self.is_connected() or not self._socket:
            return False

        success_all = True
        for code in codes:
            # LS 종목코드 포맷: U + 6자리 + 공백 3자리
            formatted_code = self._format_code(code)

            payload = {
                "header": {
                    "token": self._token,
                    "tr_type": "4"  # 4: 실시간 시세 해제
                },
                "body": {
                    "tr_cd": "US3",
                    "tr_key": formatted_code
                }
            }
            success = await self._socket.send(payload)
            if not success:
                success_all = False
            else:
                logger.debug("[LS증권연결] 구독 해지: %s", code)
            await asyncio.sleep(0.01)
        return success_all

    async def subscribe_stocks_tr(self, codes: list[str], tr_cd: str) -> bool:
        """지정된 TR 코드로 종목 리스트 실시간 구독 등록 (예: UH1, UPH)."""
        if not self.is_connected() or not self._socket:
            logger.warning(f"[LS증권연결] {tr_cd} 구독 실패 — 연결 없음")
            return False

        success_all = True
        for code in codes:
            formatted_code = self._format_code(code)
            payload = {
                "header": {
                    "token": self._token,
                    "tr_type": "3"  # 3: 실시간 시세 등록
                },
                "body": {
                    "tr_cd": tr_cd,
                    "tr_key": formatted_code
                }
            }
            success = await self._socket.send(payload)
            if not success:
                success_all = False
            else:
                logger.info(f"[LS증권연결] {tr_cd} 구독 등록: {code}")
            await asyncio.sleep(0.01)
        return success_all

    async def unsubscribe_stocks_tr(self, codes: list[str], tr_cd: str) -> bool:
        """지정된 TR 코드로 종목 리스트 실시간 구독 해지."""
        if not self.is_connected() or not self._socket:
            return False

        success_all = True
        for code in codes:
            formatted_code = self._format_code(code)
            payload = {
                "header": {
                    "token": self._token,
                    "tr_type": "4"  # 4: 실시간 시세 해제
                },
                "body": {
                    "tr_cd": tr_cd,
                    "tr_key": formatted_code
                }
            }
            success = await self._socket.send(payload)
            if not success:
                success_all = False
            else:
                logger.debug(f"[LS증권연결] {tr_cd} 구독 해지: {code}")
            await asyncio.sleep(0.01)
        return success_all

    async def subscribe_dynamic(self, codes: list[str]) -> None:
        """동적 데이터(호가, 프로그램 매매) 구독 등록"""
        logger.info("[LS증권연결] subscribe_dynamic 호출 - codes: %s", codes)
        if not codes:
            logger.warning("[LS증권연결] subscribe_dynamic - codes 비어있음")
            return
        await self.subscribe_stocks_tr(codes, "UH1")
        await self.subscribe_stocks_tr(codes, "UPH")

    async def unsubscribe_dynamic(self, codes: list[str]) -> None:
        """동적 데이터 구독 해지"""
        if not codes:
            return
        await self.unsubscribe_stocks_tr(codes, "UH1")
        await self.unsubscribe_stocks_tr(codes, "UPH")

    async def _on_ws_message(self, payload: dict) -> None:
        """_LsSocket 콜백 → 핸들러 직접 호출."""
        self._received_count += 1
        if self._receive_callback:
            if asyncio.iscoroutinefunction(self._receive_callback):
                await self._receive_callback(payload)
            else:
                self._receive_callback(payload)

    async def _on_socket_disconnect(self) -> None:
        """_LsSocket 연결 끊김 시 호출 — 재연결 루프 기동."""
        if self._stop_reconnect:
            return
        self._connected = False
        try:
            from backend.app.services.engine_state import state
            state.login_ok = False
        except Exception:
            logger.warning("[LS증권연결] _login_ok 초기화 실패", exc_info=True)
        try:
            from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
            broadcast_ws_connection_status(False)
        except Exception:
            logger.warning("[LS증권연결] 연결 끊김 상태 브로드캐스트 실패", exc_info=True)
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.get_running_loop().create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """지수 백오프 재연결 루프 (1→2→4→8→16→32초, 최대 10회)."""
        delays = [1, 2, 4, 8, 16, 32, 32, 32, 32, 32]
        for attempt, delay in enumerate(delays, start=1):
            if self._stop_reconnect:
                logger.info("[LS증권연결] 재연결 중단 (stop 신호)")
                return
            logger.info("[LS증권연결] 재연결 시도 %d/10 — %d초 후", attempt, delay)
            await asyncio.sleep(delay)
            if self._stop_reconnect:
                return
            try:
                token = await self._get_token_async()
                if not token:
                    logger.warning("[LS증권연결] 재연결 %d회: 토큰 발급 실패", attempt)
                    continue
                self._token = token
                if self._lock is None:
                    self._lock = asyncio.Lock()
                async with self._lock:
                    # Queue 콜백 래퍼 (재연결 시도 - 드롭 정책 적용)
                    queue_callback = None
                    if self._ws_queue is not None:
                        def _queue_put_with_drop(msg: dict) -> None:
                            """드롭 정책 적용 - 재연결 시도."""
                            try:
                                self._ws_queue.put_nowait(msg)
                            except asyncio.QueueFull:
                                try:
                                    self._ws_queue.get_nowait()
                                    self._ws_queue.put_nowait(msg)
                                    logger.debug("[LS증권연결] tick_queue 드롭 발생 (재연결) - 최신 데이터 유지")
                                except asyncio.QueueEmpty:
                                    self._ws_queue.put_nowait(msg)
                        queue_callback = _queue_put_with_drop

                    self._socket = _LsSocket(
                        uri=self._ws_uri,
                        token=self._token,
                        on_message=self._on_ws_message,
                        on_disconnect=self._on_socket_disconnect,
                        queue_callback=queue_callback,
                    )
                    await self._socket.connect()
                    self._connected = True
                    try:
                        from backend.app.services.engine_state import state
                        state.login_ok = True
                    except Exception:
                        pass
                logger.info("[LS증권연결] 재연결 성공 (시도 %d회)", attempt)
                # 재연결 성공 후 큐 클리어 (과거 데이터 제거)
                if self._ws_queue is not None:
                    while not self._ws_queue.empty():
                        try:
                            self._ws_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    logger.info("[LS증권연결] 재연결 후 큐 클리어 완료")
                try:
                    from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                    broadcast_ws_connection_status(True)
                except Exception:
                    logger.warning("[LS증권연결] 재연결 상태 브로드캐스트 실패", exc_info=True)
                # 재연결 후 구독 복원은 ConnectorManager가 담당
                if self._on_reconnect_success:
                    asyncio.get_running_loop().create_task(self._on_reconnect_success(self.broker_id))
                return
            except Exception as e:
                logger.warning("[LS증권연결] 재연결 %d회 실패: %s", attempt, e, exc_info=True)
        logger.error("[LS증권연결] 최대 재연결 횟수(10회) 초과 — 포기")

    def set_reconnect_success_callback(self, callback: Callable) -> None:
        """재연결 성공 시 호출될 콜백 설정 (ConnectorManager가 구독 복원에 사용)."""
        self._on_reconnect_success = callback

    def set_message_callback(self, callback: Callable) -> None:
        """메시지 수신 콜백 설정."""
        self._receive_callback = callback

    def set_queue_callback(self, queue: asyncio.Queue) -> None:
        """Producer-Consumer Queue 설정 (드롭 정책 적용)."""
        self._ws_queue = queue

    def _format_code(self, code: str) -> str:
        """종목코드 포맷팅 — LS 형식 (U + 6자리 + 공백 3자리).
        
        KRX 표준: 숫자 6자리(005930) 및 알파벳 포함 6자리(0017J0) 모두 지원
        """
        from backend.app.services.engine_symbol_utils import _base_stk_cd
        base = _base_stk_cd(code)
        
        # 6자리 코드는 모두 LS 형식으로 변환 (숫자든 알파벳이든)
        if len(base) == 6:
            return f"U{base}   "
        
        return code

    async def _get_token_async(self) -> str | None:
        """토큰 발급 (비동기) - LsRestAPI 직접 호출 (키움과 동일 패턴)."""
        from backend.app.core.ls_rest import LsRestAPI
        api = LsRestAPI(self._app_key, self._app_secret)
        ok = await api.ensure_token()
        if ok:
            return api.get_token()
        return None


# ── 팩토리 ───────────────────────────────────────────────────────────────────

def create_ls_connector() -> LsConnector:
    """단일 소스 진리: state.integrated_system_settings_cache 직접 사용."""
    from backend.app.services.engine_state import state
    app_key = state.integrated_system_settings_cache.get("ls_app_key", "").strip()
    app_secret = state.integrated_system_settings_cache.get("ls_app_secret", "").strip()
    if not app_key or not app_secret:
        raise ValueError("LS app_key, app_secret이 설정되지 않았습니다")
    return LsConnector(app_key=app_key, app_secret=app_secret)
