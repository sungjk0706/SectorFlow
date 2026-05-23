# -*- coding: utf-8 -*-
"""
엔진 유틸리티 클래스 모듈.

LRUCache, LazyLock, LazyEvent 등 엔진 전역에서 사용하는 유틸리티 클래스.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict


class LRUCache(dict):
    """최대 크기를 가진 LRU(Least Recently Used) 캐시.

    dict를 상속받아 기존 코드와 호환성 유지.
    maxsize 초과 시 가장 오래된 항목 자동 삭제.
    """
    def __init__(self, maxsize: int = 1000, *args, **kwargs):
        self._maxsize = maxsize
        self._order: OrderedDict = OrderedDict()
        super().__init__(*args, **kwargs)
        # 초기 데이터가 있으면 순서에 추가
        for key in self:
            self._order[key] = None

    def __getitem__(self, key):
        value = super().__getitem__(key)
        # 접근 시 순서 갱신
        self._order.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self._order.move_to_end(key)
        else:
            self._order[key] = None
            # 크기 초과 시 가장 오래된 항목 삭제
            if len(self._order) > self._maxsize:
                oldest = next(iter(self._order))
                del self._order[oldest]
                super().__delitem__(oldest)
        super().__setitem__(key, value)

    def __delitem__(self, key):
        if key in self._order:
            del self._order[key]
        super().__delitem__(key)

    def clear(self):
        self._order.clear()
        super().clear()

    def get(self, key, default=None):
        if key in self:
            self._order.move_to_end(key)
            return super().__getitem__(key)
        return default

    def pop(self, key, *args):
        if key in self._order:
            del self._order[key]
        return super().pop(key, *args)


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
