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
from __future__ import annotations
import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from backend.app.core.broker_connector import BrokerConnector
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
logger = logging.getLogger(__name__)

_BROKER_DISPLAY = BROKER_DISPLAY_NAMES["ls"]

_TR_KOR = {"UH1": "호가", "UPH": "프로그램매매", "US3": "체결", "JIF": "장운영정보", "IJ_": "업종지수"}

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
        self._on_message = on_message          # async callable (대체)
        self._on_disconnect = on_disconnect    # 연결 끊김 시 호출 (재연결 트리거)
        self._queue_callback = queue_callback  # Producer 콜백 (asyncio.Queue.put_nowait)
        self._ws: Any = None                        # websockets connection
        self.connected = False
        self._stop_event = asyncio.Event()
        self._recv_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """서버 연결 + 수신루프 기동."""
        if not websockets:
            raise RuntimeError("websockets 패키지가 없습니다.")
        logger.info("[연결] %s 서버 연결 시도: %s", _BROKER_DISPLAY, self._uri)
        self._ws = await websockets.connect(self._uri, open_timeout=20, ping_interval=20, ping_timeout=20)
        self.connected = True
        logger.info("[연결] %s 서버 연결 완료", _BROKER_DISPLAY)
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
                logger.warning("[연결] %s 소켓 종료 실패", _BROKER_DISPLAY, exc_info=True)
            self._ws = None
        logger.info("[연결] %s 서버 연결 종료", _BROKER_DISPLAY)

    async def send(self, payload: dict) -> bool:
        """페이로드 송신. 연결 없으면 False."""
        if not self.connected or not self._ws:
            tr_cd = payload.get("body", {}).get("tr_cd", "?")
            logger.warning("[연결] %s 전송 생략 — 연결 없음 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
            return False
        msg = json.dumps(payload, ensure_ascii=False)
        await self._ws.send(msg)
        return True

    async def _recv_loop(self) -> None:
        """WebSocket 수신루프 — PING 처리, 메시지 파싱, LS → 내부 형식 변환, 연결 끊김 감지."""
        logger.info("[연결] %s 데이터 수신 시작", _BROKER_DISPLAY)
        while not self._stop_event.is_set():
            try:
                raw = await self._ws.recv()

                # 1. 문자열 PING
                if isinstance(raw, str) and raw.strip().upper() == "PING":
                    await self._ws.send(raw)
                    continue

                # 2. JSON 파싱
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("[연결] %s 메시지 해석 실패 (무시): %s", _BROKER_DISPLAY, raw[:80])
                    continue

                if isinstance(msg, list):
                    continue

                # 3. JSON PING
                trnm = msg.get("trnm", "")
                if trnm.upper() == "PING":
                    await self._ws.send(raw)
                    continue

                # LS 메시지 구조: {header: {tr_cd, tr_key}, body: {...}}
                header = msg.get("header", {})
                body = msg.get("body", {})
                tr_cd = header.get("tr_cd", "")

                # LS → 내부 형식 변환
                internal_msg = self._convert_ls_to_internal(tr_cd, header, body)

                if internal_msg:
                    # JIF (장운영정보)는 tick_queue를 우회하고 직접 처리
                    # Kiwoom 커넥터와 동일한 패턴: JIF는 큐 대기 없이 즉시 핸들러로 전달
                    if internal_msg.get("trnm") == "JIF":
                        await self._on_message(internal_msg)
                    elif self._queue_callback:
                        try:
                            self._queue_callback(internal_msg)  # put_nowait 호출
                        except asyncio.QueueFull:
                            logger.warning("[연결] %s 데이터 큐 가득 참 — 실시간 데이터 일부 누락: %s", _BROKER_DISPLAY, tr_cd)
                    else:
                        # 대체: 기존 방식 유지
                        await self._on_message(internal_msg)
                else:
                    # 변환 실패 또는 처리 불필요한 메시지
                    logger.debug("[연결] %s 변환 실패 또는 처리 불필요: %s", _BROKER_DISPLAY, tr_cd)

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
                        logger.warning("[연결] %s 연결 끊김 (%s) — 데이터 수신 종료", _BROKER_DISPLAY, err_name)
                        if self._on_disconnect:
                            await self._on_disconnect()
                    break
                else:
                    if not self._stop_event.is_set():
                        logger.warning("[연결] %s 데이터 수신 오류 (계속): %s", _BROKER_DISPLAY, e, exc_info=True)
                    await asyncio.sleep(0.1)

        logger.info("[연결] %s 데이터 수신 종료", _BROKER_DISPLAY)

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

            price = int(body.get("price", 0) or 0)
            value = int(body.get("value", 0) or 0)
            sign = str(body.get("sign", "3")).strip()
            change = int(body.get("change", 0) or 0)
            drate = float(body.get("drate", 0) or 0)

            if drate == 0.0 and change > 0 and price > 0:
                logger.warning("[연결] %s 체결 데이터 등락률 누락 — 서버 데이터 품질 이슈 (종목=%s 부호=%s 변동=%d 가격=%d)", _BROKER_DISPLAY, shcode, sign, change, price)
                if sign in ("4", "5"):
                    prev_close = price + change
                elif sign in ("1", "2"):
                    prev_close = price - change
                else:
                    prev_close = price

                if prev_close > 0:
                    drate = round((change / prev_close) * 100, 2)

            high = int(body.get("high", 0) or 0)
            offerho = int(body.get("offerho", 0) or 0)
            bidho = int(body.get("bidho", 0) or 0)
            cpower = float(body.get("cpower", 0) or 0.0)

            sign_char = ""
            if sign in ("4", "5"):
                sign_char = "-"
            elif sign in ("1", "2"):
                sign_char = "+"

            price_str = f"{sign_char}{price}" if sign_char else str(price)
            change_str = f"{sign_char}{change}" if sign_char else str(change)
            drate_str = f"{sign_char}{drate}" if sign_char else str(drate)

            return {
                "trnm": "REAL",
                "data": [{
                    "type": "0B",
                    "code": shcode,
                    "values": {
                        "10": price_str,
                        "11": change_str,
                        "12": drate_str,
                        "14": str(value),
                        "17": str(high),
                        "27": str(offerho),
                        "28": str(bidho),
                        "228": str(cpower),
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
        elif tr_cd == "JIF":
            jangubun = str(body.get("jangubun", "")).strip()
            jstatus = str(body.get("jstatus", "")).strip()
            if not jangubun or not jstatus:
                return None
            return {
                "trnm": "JIF",
                "jangubun": jangubun,
                "jstatus": jstatus,
            }
        elif tr_cd == "IJ_":
            upcode = str(body.get("upcode", "")).strip()
            if not upcode:
                return None
            jisu = str(body.get("jisu", "")).strip()
            change_str = str(body.get("change", "")).strip()
            drate_str = str(body.get("drate", "")).strip()
            sign = str(body.get("sign", "")).strip()
            return {
                "trnm": "REAL",
                "data": [{
                    "type": "0J",
                    "item": upcode,
                    "values": {
                        "10": jisu,    # 지수
                        "11": change_str,  # 전일대비
                        "12": drate_str,   # 등락률
                        "25": sign,    # 전일대비구분
                    }
                }]
            }
        else:
            return None


# ── LsConnector ──────────────────────────────────────────────────────────

class LsConnector(BrokerConnector):
    """LS증권 WebSocket 커넥터."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        ws_uri: str = "",
    ):
        self._app_key = app_key
        self._app_secret = app_secret
        if not ws_uri:
            from backend.app.core.broker_urls import build_broker_urls
            ws_uri = build_broker_urls("ls")["ws_uri"]
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
        self._reconnecting: bool = False
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
        logger.info("[연결] %s 실시간 데이터 설정 변경: %s", _BROKER_DISPLAY, enabled)

    def is_auto_trade_enabled(self) -> bool:
        """자동매매 ON/OFF 상태 반환"""
        return self._auto_trade_enabled

    def set_auto_trade_enabled(self, enabled: bool) -> None:
        """자동매매 ON/OFF 설정."""
        self._auto_trade_enabled = enabled
        logger.info("[매매] %s 자동매매 설정 변경: %s", _BROKER_DISPLAY, enabled)

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
                raise ConnectionError(f"{_BROKER_DISPLAY} 토큰 발급 실패")
            self._token = token
            # Queue 콜백 래퍼 (누락 정책 적용)
            queue_callback = None
            if self._ws_queue is not None:
                _q = self._ws_queue
                def _queue_put_with_drop(msg: dict) -> None:
                    """누락 정책 적용 — 큐 가득 찼을 때 가장 오래된 데이터 버리고 최신 데이터 삽입."""
                    try:
                        _q.put_nowait(msg)
                    except asyncio.QueueFull:
                        try:
                            _q.get_nowait()
                            _q.put_nowait(msg)
                            logger.warning("[연결] %s 데이터 큐 누락 발생 — 최신 데이터 유지", _BROKER_DISPLAY)
                        except asyncio.QueueEmpty:
                            _q.put_nowait(msg)
                queue_callback = _queue_put_with_drop

            self._socket = _LsSocket(
                uri=self._ws_uri,
                token=self._token,
                on_message=self._on_ws_message,
                on_disconnect=self._on_socket_disconnect,
                queue_callback=queue_callback,
            )
            try:
                await self._socket.connect()
            except Exception:
                logger.warning("[연결] %s 초기 연결 실패 — 재연결 시작", _BROKER_DISPLAY)
                asyncio.get_running_loop().create_task(self._on_socket_disconnect())
                raise
            self._connected = True
            logger.info("[연결] %s 연결 완료", _BROKER_DISPLAY)
            try:
                from backend.app.services.engine_state import state
                state.login_ok = True
                from backend.app.services.engine_state import _notify_reg_ack
                _notify_reg_ack()
                # LS증권은 소켓 연결 완료가 로그인 완료이므로 직접 REG 파이프라인 트리거
                from backend.app.services.daily_time_scheduler import _trigger_reg_pipeline
                _trigger_reg_pipeline()
            except Exception:
                logger.warning("[연결] %s 로그인 상태 설정 및 파이프라인 시작 실패", _BROKER_DISPLAY, exc_info=True)
            # JIF 장운영정보 구독
            try:
                await self.subscribe_jif()
            except Exception:
                logger.warning("[구독] %s 장운영정보 구독 실패", _BROKER_DISPLAY, exc_info=True)
            # 업종지수(IJ_) 구독은 REG 파이프라인(ws_subscribe_control)에서 통합 관리
            # 연결 상태 전송
            try:
                from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                broadcast_ws_connection_status(True)
            except Exception:
                logger.warning("[연결] %s 연결 상태 알림 실패", _BROKER_DISPLAY, exc_info=True)

    async def disconnect(self) -> None:
        """수신루프 중단 + WebSocket 종료. 재연결 루프도 중단."""
        self._stop_reconnect = True
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self._connected = False
            if self._socket:
                await self._socket.disconnect()
                self._socket = None
            logger.info("[연결] %s 연결 종료", _BROKER_DISPLAY)
            # 연결 해제 상태 전송
            try:
                from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                broadcast_ws_connection_status(False)
            except Exception:
                logger.warning("[연결] %s 연결 해제 상태 알림 실패", _BROKER_DISPLAY, exc_info=True)

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
            logger.warning("[구독] %s 종목 구독 실패 — 연결 없음", _BROKER_DISPLAY)
            return False

        success_all = True
        for code in codes:
            if not self._socket:
                logger.warning("[구독] %s 종목 구독 중단 — 연결 해제됨", _BROKER_DISPLAY)
                success_all = False
                break
            formatted_code = self._format_code(code)
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
            await asyncio.sleep(0)
        return success_all

    async def unsubscribe_stocks(self, codes: list[str]) -> bool:
        """종목 리스트 실시간 구독 해지 (LS WebSocket: tr_type=4, tr_cd=US3)."""
        if not self.is_connected() or not self._socket:
            return False

        success_all = True
        for code in codes:
            if not self._socket:
                logger.warning("[구독] %s 종목 구독 해지 중단 — 연결 해제됨", _BROKER_DISPLAY)
                success_all = False
                break
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
            await asyncio.sleep(0)
        return success_all

    async def subscribe_stocks_tr(self, codes: list[str], tr_cd: str) -> tuple[int, int]:
        """지정된 TR 코드로 종목 리스트 실시간 구독 등록 (예: UH1, UPH).

        Returns:
            (success_count, fail_count) — per-code 로그 대신 호출자가 요약 로그 출력 (P23).
        """
        if not self.is_connected() or not self._socket:
            logger.warning(f"[구독] {_BROKER_DISPLAY} {_TR_KOR.get(tr_cd, tr_cd)} 구독 실패 — 연결 없음")
            return 0, len(codes)

        success_count = 0
        fail_count = 0
        for code in codes:
            if not self._socket:
                logger.warning(f"[구독] {_BROKER_DISPLAY} {_TR_KOR.get(tr_cd, tr_cd)} 구독 중단 — 연결 해제됨")
                fail_count += len(codes) - success_count - fail_count
                break
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
            if success:
                success_count += 1
            else:
                fail_count += 1
            await asyncio.sleep(0)
        return success_count, fail_count

    async def unsubscribe_stocks_tr(self, codes: list[str], tr_cd: str) -> tuple[int, int]:
        """지정된 TR 코드로 종목 리스트 실시간 구독 해지.

        Returns:
            (success_count, fail_count) — per-code 로그 대신 호출자가 요약 로그 출력 (P23).
        """
        if not self.is_connected() or not self._socket:
            return 0, len(codes)

        success_count = 0
        fail_count = 0
        for code in codes:
            if not self._socket:
                logger.warning(f"[구독] {_BROKER_DISPLAY} {_TR_KOR.get(tr_cd, tr_cd)} 구독 해지 중단 — 연결 해제됨")
                fail_count += len(codes) - success_count - fail_count
                break
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
            if success:
                success_count += 1
            else:
                fail_count += 1
            await asyncio.sleep(0)
        return success_count, fail_count

    async def subscribe_dynamic(self, codes: list[str]) -> None:
        """동적 데이터(호가, 프로그램 매매) 구독 등록.

        UH1(호가) + UPH(프로그램매매) 순차 등록 후 요약 1줄 로그 출력 (P23).
        per-code 로그는 subscribe_stocks_tr에서 제거됨.
        """
        if not codes:
            logger.warning("[구독] %s 호가·프로그램매매 구독 — 종목 목록 비어있음", _BROKER_DISPLAY)
            return
        logger.info("[구독] %s 호가·프로그램매매 구독 시작 — %d종목", _BROKER_DISPLAY, len(codes))
        uh1_ok, uh1_fail = await self.subscribe_stocks_tr(codes, "UH1")
        uph_ok, uph_fail = await self.subscribe_stocks_tr(codes, "UPH")
        total_ok = uh1_ok + uph_ok
        total_fail = uh1_fail + uph_fail
        logger.info(
            "[구독] %s 호가·프로그램매매 구독 완료 — %d종목 (성공 %d, 실패 %d)",
            _BROKER_DISPLAY, len(codes), total_ok, total_fail,
        )

    async def unsubscribe_dynamic(self, codes: list[str]) -> None:
        """동적 데이터 구독 해지. UH1 + UPH 순차 해지 후 요약 1줄 로그 출력 (P23)."""
        if not codes:
            return
        logger.info("[구독] %s 호가·프로그램매매 구독 해지 시작 — %d종목", _BROKER_DISPLAY, len(codes))
        uh1_ok, uh1_fail = await self.unsubscribe_stocks_tr(codes, "UH1")
        uph_ok, uph_fail = await self.unsubscribe_stocks_tr(codes, "UPH")
        total_ok = uh1_ok + uph_ok
        total_fail = uh1_fail + uph_fail
        logger.info(
            "[구독] %s 호가·프로그램매매 구독 해지 완료 — %d종목 (성공 %d, 실패 %d)",
            _BROKER_DISPLAY, len(codes), total_ok, total_fail,
        )

    async def register_account(self, tr_cd: str = "SC0") -> bool:
        """계좌 등록 (LS WebSocket: tr_type=1).

        명세서: header {token, tr_type="1"}, body {tr_cd, tr_key=""}
        tr_key는 계좌 등록/해제 시 필수값 아님 (명세서: Required=N).
        주문 관련 TR 코드: SC0(접수), SC1(체결), SC2(정정), SC3(취소), SC4(거부).
        """
        if not self.is_connected() or not self._socket:
            logger.warning("[계좌] %s 계좌 등록 실패 — 연결 없음 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
            return False
        payload = {
            "header": {
                "token": self._token,
                "tr_type": "1"  # 1: 계좌 등록
            },
            "body": {
                "tr_cd": tr_cd,
                "tr_key": ""
            }
        }
        success = await self._socket.send(payload)
        if success:
            logger.info("[계좌] %s 계좌 등록 완료 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
        else:
            logger.warning("[계좌] %s 계좌 등록 실패 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
        return success

    async def unregister_account(self, tr_cd: str = "SC0") -> bool:
        """계좌 해제 (LS WebSocket: tr_type=2).

        명세서: header {token, tr_type="2"}, body {tr_cd, tr_key=""}
        tr_key는 계좌 등록/해제 시 필수값 아님 (명세서: Required=N).
        """
        if not self.is_connected() or not self._socket:
            logger.warning("[계좌] %s 계좌 해제 실패 — 연결 없음 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
            return False
        payload = {
            "header": {
                "token": self._token,
                "tr_type": "2"  # 2: 계좌 해제
            },
            "body": {
                "tr_cd": tr_cd,
                "tr_key": ""
            }
        }
        success = await self._socket.send(payload)
        if success:
            logger.info("[계좌] %s 계좌 해제 완료 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
        else:
            logger.warning("[계좌] %s 계좌 해제 실패 (TR코드=%s)", _BROKER_DISPLAY, tr_cd)
        return success

    async def subscribe_jif(self) -> bool:
        """장운영정보(JIF) 실시간 구독 등록."""
        if not self.is_connected() or not self._socket:
            logger.warning("[구독] %s 장운영정보 구독 실패 — 연결 없음", _BROKER_DISPLAY)
            return False
        payload = {
            "header": {
                "token": self._token,
                "tr_type": "3"
            },
            "body": {
                "tr_cd": "JIF",
                "tr_key": "0"
            }
        }
        success = await self._socket.send(payload)
        if success:
            logger.info("[구독] %s 장운영정보 구독 완료", _BROKER_DISPLAY)
        else:
            logger.warning("[구독] %s 장운영정보 구독 실패", _BROKER_DISPLAY)
        return success

    async def subscribe_index(self) -> bool:
        """코스피·코스닥 업종지수(IJ_) 실시간 구독 등록."""
        if not self.is_connected() or not self._socket:
            logger.warning("[구독] %s 업종지수 구독 실패 — 연결 없음", _BROKER_DISPLAY)
            return False
        success_all = True
        for upcode in ("001", "301"):
            payload = {
                "header": {
                    "token": self._token,
                    "tr_type": "3"
                },
                "body": {
                    "tr_cd": "IJ_",
                    "tr_key": upcode
                }
            }
            success = await self._socket.send(payload)
            if success:
                logger.info("[구독] %s 업종지수 구독 완료: %s", _BROKER_DISPLAY, upcode)
            else:
                success_all = False
        return success_all

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
            logger.warning("[연결] %s 로그인 상태 초기화 실패", _BROKER_DISPLAY, exc_info=True)
        try:
            from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
            broadcast_ws_connection_status(False)
        except Exception:
            logger.warning("[연결] %s 연결 끊김 상태 알림 실패", _BROKER_DISPLAY, exc_info=True)
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            await self._reconnect_loop()
        finally:
            self._reconnecting = False

    async def _reconnect_loop(self) -> None:
        """지수 백오프 재연결 루프 (1→2→4→8→16→32초, 최대 20회)."""
        delays = [1, 2, 4, 8, 16, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32]
        for attempt, delay in enumerate(delays, start=1):
            if self._stop_reconnect:
                logger.info("[연결] %s 재연결 중단 (종료 신호)", _BROKER_DISPLAY)
                return
            logger.info("[연결] %s 재연결 시도 %d/20 — %d초 후", _BROKER_DISPLAY, attempt, delay)
            await asyncio.sleep(delay)
            if self._stop_reconnect:
                return
            try:
                token = await self._get_token_async()
                if not token:
                    logger.warning("[연결] %s 재연결 %d회: 토큰 발급 실패", _BROKER_DISPLAY, attempt)
                    continue
                self._token = token
                if self._lock is None:
                    self._lock = asyncio.Lock()
                async with self._lock:
                    # Queue 콜백 래퍼 (재연결 시도 - 누락 정책 적용)
                    queue_callback = None
                    if self._ws_queue is not None:
                        _q = self._ws_queue
                        def _queue_put_with_drop(msg: dict) -> None:
                            """누락 정책 적용 - 재연결 시도."""
                            try:
                                _q.put_nowait(msg)
                            except asyncio.QueueFull:
                                try:
                                    _q.get_nowait()
                                    _q.put_nowait(msg)
                                    logger.warning("[연결] %s 데이터 큐 누락 발생 (재연결) — 최신 데이터 유지", _BROKER_DISPLAY)
                                except asyncio.QueueEmpty:
                                    _q.put_nowait(msg)
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
                    except Exception as e:
                        logger.warning("[연결] %s 로그인 상태 설정 실패: %s", _BROKER_DISPLAY, e)
                logger.info("[연결] %s 재연결 성공 (시도 %d회)", _BROKER_DISPLAY, attempt)
                # 재연결 성공 후 큐 클리어 (과거 데이터 제거)
                if self._ws_queue is not None:
                    cleared = 0
                    while not self._ws_queue.empty():
                        try:
                            self._ws_queue.get_nowait()
                            cleared += 1
                        except asyncio.QueueEmpty:
                            break
                    if cleared > 0:
                        logger.warning("[연결] %s 재연결 후 데이터 정리 — %d건 과거 데이터 폐기", _BROKER_DISPLAY, cleared)
                try:
                    from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                    broadcast_ws_connection_status(True)
                except Exception:
                    logger.warning("[연결] %s 재연결 상태 알림 실패", _BROKER_DISPLAY, exc_info=True)
                # JIF 장운영정보 재구독
                try:
                    await self.subscribe_jif()
                except Exception:
                    logger.warning("[구독] %s 재연결 후 장운영정보 구독 실패", _BROKER_DISPLAY, exc_info=True)
                # 업종지수(IJ_) 재구독은 ConnectorManager(_on_reconnect_success)에서 통합 관리
                # 재연결 후 구독 복원은 ConnectorManager가 담당
                if self._on_reconnect_success:
                    await self._on_reconnect_success(self.broker_id)
                return
            except Exception as e:
                logger.warning("[연결] %s 재연결 %d회 실패: %s", _BROKER_DISPLAY, attempt, e)
        logger.error("[연결] %s 최대 재연결 횟수(20회) 초과 — 중단", _BROKER_DISPLAY, exc_info=True)

    def set_reconnect_success_callback(self, callback: Callable) -> None:
        """재연결 성공 시 호출될 콜백 설정 (ConnectorManager가 구독 복원에 사용)."""
        self._on_reconnect_success = callback

    def set_message_callback(self, callback: Callable) -> None:
        """메시지 수신 콜백 설정."""
        self._receive_callback = callback

    def set_queue_callback(self, queue: asyncio.Queue) -> None:
        """Producer-Consumer Queue 설정 (누락 정책 적용)."""
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
        """토큰 확보 (비동기) — 기존 LsRestAPI 인스턴스 재사용으로 중복 발급 방지."""
        from backend.app.services.engine_state import state

        # 1차: broker_rest_apis에서 기존 인스턴스 재사용
        rest_api = state.broker_rest_apis.get("ls")
        if rest_api is None:
            # 2차: router의 auth_cache에서 LsAuthProvider의 rest_api 재사용
            try:
                from backend.app.core.broker_factory import get_router
                auth_provider = get_router()._auth_cache.get("ls")
                if auth_provider and hasattr(auth_provider, "rest_api"):
                    rest_api = auth_provider.rest_api
            except Exception as e:
                logger.warning("[연결] %s 토큰 조회 실패: %s", _BROKER_DISPLAY, e)

        if rest_api and hasattr(rest_api, "ensure_token"):
            ok = await rest_api.ensure_token()
            if ok:
                return rest_api.get_token()
            return None

        # Fallback: 기존 인스턴스 없을 때만 새 발급
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
    from backend.app.core.broker_urls import build_broker_urls
    app_key = state.integrated_system_settings_cache.get("ls_app_key", "").strip()
    app_secret = state.integrated_system_settings_cache.get("ls_app_secret", "").strip()
    if not app_key or not app_secret:
        raise ValueError("LS app_key, app_secret이 설정되지 않았습니다")
    ws_uri = build_broker_urls("ls")["ws_uri"]
    return LsConnector(app_key=app_key, app_secret=app_secret, ws_uri=ws_uri)
