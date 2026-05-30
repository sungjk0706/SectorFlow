from __future__ import annotations
# -*- coding: utf-8 -*-
"""
엔진 유틸리티 클래스 모듈.

LRUCache, LazyLock, LazyEvent 등 엔진 전역에서 사용하는 유틸리티 클래스.
"""

import asyncio
from collections import OrderedDict


class LRUCache:
    """최대 크기를 가진 LRU(Least Recently Used) 캐시.

    OrderedDict 단일 구조로 단일 소스 진리 원칙 준수.
    maxsize 초과 시 가장 오래된 항목 자동 삭제.
    """
    def __init__(self, maxsize: int = 1000, *args, **kwargs):
        self._maxsize = maxsize
        self._data: OrderedDict = OrderedDict()
        # 초기 데이터가 있으면 추가
        for key, value in kwargs.items():
            self._data[key] = value
        for item in args:
            if isinstance(item, dict):
                for key, value in item.items():
                    self._data[key] = value
        # 초기화 후 invariant 검증
        assert len(self._data) <= self._maxsize, f"LRUCache 초기화 실패: 크기 {len(self._data)} > maxsize {self._maxsize}"

    def __getitem__(self, key):
        value = self._data[key]
        # 접근 시 순서 갱신
        self._data.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
        else:
            self._data[key] = value
            # 크기 초과 시 가장 오래된 항목 삭제
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)
        # mutation 후 invariant 검증
        assert len(self._data) <= self._maxsize, f"LRUCache __setitem__ 실패: 크기 {len(self._data)} > maxsize {self._maxsize}"
        # OrderedDict 내부 키 수 vs 실제 조회 가능한 키 수 검증
        internal_len = len(self._data)
        actual_len = len(list(self._data.keys()))
        assert internal_len == actual_len, f"LRUCache __setitem__ invariant 위반: internal_len={internal_len}, actual_len={actual_len}"

    def __delitem__(self, key):
        del self._data[key]
        # mutation 후 invariant 검증
        internal_len = len(self._data)
        actual_len = len(list(self._data.keys()))
        assert internal_len == actual_len, f"LRUCache __delitem__ invariant 위반: internal_len={internal_len}, actual_len={actual_len}"

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def clear(self):
        self._data.clear()
        # mutation 후 invariant 검증
        assert len(self._data) == 0, f"LRUCache clear 실패: 크기 {len(self._data)} != 0"
        # OrderedDict 내부 키 수 vs 실제 조회 가능한 키 수 검증
        internal_len = len(self._data)
        actual_len = len(list(self._data.keys()))
        assert internal_len == actual_len, f"LRUCache clear invariant 위반: internal_len={internal_len}, actual_len={actual_len}"

    def get(self, key, default=None):
        if key in self._data:
            try:
                self._data.move_to_end(key)
            except KeyError as e:
                raise
            return self._data[key]
        return default

    def pop(self, key, *args):
        return self._data.pop(key, *args)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()


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
