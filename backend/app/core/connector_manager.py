# -*- coding: utf-8 -*-
"""
ConnectorManager — 다중 증권사 WebSocket 연결 관리자.

broker_config.websocket 설정을 읽어 필요한 Connector를 모두 생성·연결한다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from app.core.broker_connector import BrokerConnector

logger = logging.getLogger(__name__)


class ConnectorManager:
    """
    다중 증권사 WS Connector 관리자.

    - broker_config.websocket 값에 따라 Connector를 생성한다.
      예) "kiwoom" → 키움 1개
    - 모든 Connector의 메시지를 단일 콜백으로 통합 전달한다.
    - get_connector(broker_id) 로 개별 Connector에 접근 가능하다.
    """

    def __init__(self, settings: dict) -> None:
        self._settings = settings
        self._connectors: dict[str, BrokerConnector] = {}
        self._callback: Callable | None = None
        self._build(settings)

    # ── 생성 ──────────────────────────────────────────────────────────

    def _build(self, settings: dict) -> None:
        """broker_config.websocket 값을 파싱해 Connector 인스턴스를 생성한다."""
        broker_config = settings.get("broker_config") or {}
        ws_val = str(
            broker_config.get("websocket") or settings.get("broker", "kiwoom") or "kiwoom"
        ).lower().strip()

        broker_names = [b.strip() for b in ws_val.split(",") if b.strip()]

        for broker_name in broker_names:
            try:
                connector = self._create_single(broker_name, settings)
                self._connectors[broker_name] = connector
                logger.info("[ConnectorManager] %s Connector 생성 완료", broker_name.upper())
            except ValueError as e:
                logger.warning("[ConnectorManager] %s Connector 생성 실패 (설정 확인 필요): %s", broker_name.upper(), e)

        if not self._connectors:
            logger.warning("[ConnectorManager] 생성된 Connector 없음 — broker_config.websocket=%r", ws_val)

    @staticmethod
    def _create_single(broker_name: str, settings: dict) -> BrokerConnector:
        """단일 증권사 Connector 생성."""
        if broker_name == "kiwoom":
            from app.core.kiwoom_connector import create_kiwoom_connector
            return create_kiwoom_connector(settings)
        raise ValueError(f"지원하지 않는 증권사: {broker_name}")

    # ── 콜백 ──────────────────────────────────────────────────────────

    def set_message_callback(self, callback: Callable) -> None:
        """모든 Connector의 메시지를 받을 단일 콜백 설정."""
        self._callback = callback
        for connector in self._connectors.values():
            connector.set_message_callback(callback)

    def set_reconnect_callback(self, callback: Callable) -> None:
        """재연결 성공 시 구독 복원 콜백 설정. Connector가 지원하면 등록한다."""
        for connector in self._connectors.values():
            if hasattr(connector, "set_reconnect_success_callback"):
                connector.set_reconnect_success_callback(callback)

    # ── 연결/해제 ──────────────────────────────────────────────────────

    async def connect_all(self) -> None:
        """모든 Connector를 병렬로 연결한다."""
        if not self._connectors:
            logger.warning("[ConnectorManager] 연결할 Connector 없음")
            return

        # 재연결 성공 시 구독 복원 콜백 등록
        self.set_reconnect_callback(self._on_reconnect_success)

        async def _connect_one(broker_name: str, connector: BrokerConnector) -> None:
            try:
                await connector.connect()
                logger.info("[ConnectorManager] %s 연결 완료", broker_name.upper())
            except Exception as e:
                logger.error("[ConnectorManager] %s 연결 실패: %s", broker_name.upper(), e)

        await asyncio.gather(
            *[_connect_one(name, conn) for name, conn in self._connectors.items()],
            return_exceptions=True,
        )

    async def _on_reconnect_success(self, broker_id: str) -> None:
        """재연결 성공 후 구독 복원 — engine_service._subscribed_stocks 기준으로 REG 재전송."""
        logger.info("[ConnectorManager] %s 재연결 성공 — 구독 복원 시작", broker_id.upper())
        try:
            from app.services import engine_service as _es
            from app.services import engine_ws_reg as _reg
            await _reg.restore_subscriptions_after_reconnect(_es, broker_id)
        except Exception as e:
            logger.error("[ConnectorManager] %s 구독 복원 실패: %s", broker_id.upper(), e)

    async def disconnect_all(self) -> None:
        """모든 Connector를 병렬로 해제한다."""
        if not self._connectors:
            return

        async def _disconnect_one(broker_name: str, connector: BrokerConnector) -> None:
            try:
                await connector.disconnect()
                logger.info("[ConnectorManager] %s 연결 해제 완료", broker_name.upper())
            except Exception as e:
                logger.warning("[ConnectorManager] %s 연결 해제 실패: %s", broker_name.upper(), e)

        await asyncio.gather(
            *[_disconnect_one(name, conn) for name, conn in self._connectors.items()],
            return_exceptions=True,
        )

    # ── 상태 조회 ──────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """활성 Connector 중 하나라도 연결되면 True."""
        return any(c.is_connected() for c in self._connectors.values())

    def get_connector(self, broker_id: str) -> BrokerConnector | None:
        """broker_id에 해당하는 Connector 반환. 없으면 None."""
        return self._connectors.get(broker_id)

    def active_broker_ids(self) -> list[str]:
        """현재 연결된 Connector의 broker_id 목록."""
        return [bid for bid, c in self._connectors.items() if c.is_connected()]

    # ── 송신 (REG/UNREG 라우팅) ───────────────────────────────────────

    async def send_message(self, payload: dict) -> bool:
        """
        REG/UNREG 페이로드를 키움 Connector로 라우팅해 송신한다.
        키움이 없으면 첫 번째 연결된 Connector로 폴백.
        """
        # 키움 우선
        kiwoom = self._connectors.get("kiwoom")
        if kiwoom and kiwoom.is_connected():
            return await kiwoom.send_message(payload)

        # 폴백: 첫 번째 연결된 Connector
        for connector in self._connectors.values():
            if connector.is_connected():
                return await connector.send_message(payload)

        logger.warning("[ConnectorManager] send_message 실패 — 연결된 Connector 없음")
        return False
