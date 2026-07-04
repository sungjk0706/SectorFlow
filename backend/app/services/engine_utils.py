# -*- coding: utf-8 -*-
"""
엔진 유틸리티 클래스 모듈.

LazyEvent 등 엔진 전역에서 사용하는 유틸리티 클래스.
"""
from __future__ import annotations
import asyncio
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


class LazyLock:
    """지연 초기화 Lock.

    처음 사용 시 asyncio.Lock()을 생성.
    async with 문에서 drop-in replacement로 사용 가능.
    """
    def __init__(self):
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def __aenter__(self):
        lock = self._get_lock()
        await lock.acquire()
        return lock

    async def __aexit__(self, *args):
        if self._lock is not None:
            self._lock.release()

    async def acquire(self) -> bool:
        return await self._get_lock().acquire()

    def release(self) -> None:
        if self._lock is not None:
            self._lock.release()

    def locked(self) -> bool:
        if self._lock is None:
            return False
        return self._lock.locked()
