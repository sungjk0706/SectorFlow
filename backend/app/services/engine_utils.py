from __future__ import annotations
# -*- coding: utf-8 -*-
"""
엔진 유틸리티 클래스 모듈.

LazyLock, LazyEvent 등 엔진 전역에서 사용하는 유틸리티 클래스.
"""

import asyncio


class LazyLock:
    """지연 초기화 Lock.

    처음 사용 시 asyncio.Lock()을 생성.
    """
    def __init__(self):
        self._lock = None

    def _get_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self) -> bool:
        return await self._get_lock().acquire()

    def release(self) -> None:
        self._get_lock().release()

    def locked(self) -> bool:
        return self._get_lock().locked()

    async def __aenter__(self):
        return await self._get_lock().__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._get_lock().__aexit__(exc_type, exc_val, exc_tb)


class LazyEvent:
    """지연 초기화 Event.

    처음 사용 시 asyncio.Event()를 생성.
    """
    def __init__(self):
        self._event = None

    def _get_event(self):
        if self._event is None:
            self._event = asyncio.Event()
        return self._event

    def is_set(self) -> bool:
        return self._get_event().is_set()

    def set(self) -> None:
        self._get_event().set()

    def clear(self) -> None:
        self._get_event().clear()

    async def wait(self) -> bool:
        return await self._get_event().wait()
