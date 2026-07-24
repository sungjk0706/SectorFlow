"""테스트 mock 공통 헬퍼 — 코루틴 누수 방지.

asyncio.create_task / asyncio.gather / schedule_engine_task를 MagicMock/AsyncMock으로
대체할 때, 인자로 넘어온 코루틴이 한 번도 await 되지 않아 발생하는
RuntimeWarning("coroutine ... was never awaited")을 차단.

사용법:
    from tests._mock_helpers import swallow_coro_side_effect, swallow_gather_side_effect

    # create_task / schedule_engine_task (동기 mock)
    with patch("...asyncio.create_task", side_effect=swallow_coro_side_effect) as m:
        ...

    # gather (AsyncMock) — 인자 코루틴 전부 닫고 None 반환
    with patch("...asyncio.gather", new_callable=AsyncMock, side_effect=swallow_gather_side_effect):
        ...

    # gather에서 예외를 발생시켜야 하는 테스트 — 코루틴 닫은 뒤 예외 raise
    with patch("...asyncio.gather", new_callable=AsyncMock, side_effect=swallow_gather_then_raise(asyncio.CancelledError())):
        ...
"""
from __future__ import annotations

from unittest.mock import MagicMock
from typing import Any


class AwaitableMock(MagicMock):
    """await 가능한 MagicMock — create_task 반환값용.

    `await task`가 빈 이터레이터를 반환하여 즉시 완료되도록 __await__ 구현.
    add_done_callback도 no-op로 지원.
    """
    def __await__(self):
        return iter([])

    def add_done_callback(self, fn):
        pass


def _close_coros(args: tuple) -> None:
    """인자 중 코루틴(또는 close 가능한 객체)을 전부 close()."""
    for arg in args:
        if hasattr(arg, "close") and callable(getattr(arg, "close", None)):
            try:
                arg.close()
            except Exception:
                pass


def swallow_coro_side_effect(*args: Any, **kwargs: Any) -> Any:
    """create_task / schedule_engine_task mock side_effect — 코루틴 닫고 AwaitableMock 반환.

    첫 번째 위치 인자(코루틴)를 close() 하여 RuntimeWarning 차단.
    gather처럼 여러 코루틴을 인자로 받는 경우 전부 close().
    반환값은 await 가능 + add_done_callback 지원하는 AwaitableMock.
    """
    _close_coros(args)
    return AwaitableMock()


async def swallow_gather_side_effect(*args: Any, **kwargs: Any) -> Any:
    """gather mock(AsyncMock) side_effect — 인자 코루틴 전부 닫고 None 반환."""
    _close_coros(args)
    return None


def swallow_gather_then_raise(exc: BaseException):
    """gather mock side_effect 팩토리 — 코루틴 닫은 뒤 지정 예외 raise.

    기존 side_effect=CancelledError / side_effect=RuntimeError(...) 사용처 대체.
    """
    async def _side(*args: Any, **kwargs: Any) -> Any:
        _close_coros(args)
        raise exc
    return _side


def swallow_coro_returning(ret: Any):
    """create_task mock side_effect 팩토리 — 코루틴 닫고 지정 객체 반환.

    기존 `mock.return_value = mock_task` 패턴(코루틴 누수 방지 없음) 대체.
    side_effect가 우선하므로 return_value 설정 불필요.
    """
    def _side(*args: Any, **kwargs: Any) -> Any:
        _close_coros(args)
        return ret
    return _side


def swallow_coro_then_raise(exc: BaseException):
    """create_task mock side_effect 팩토리 — 코루틴 닫은 뒤 지정 예외 raise.

    기존 side_effect=RuntimeError(...) 사용처 대체 (동기 mock용).
    """
    def _side(*args: Any, **kwargs: Any) -> Any:
        _close_coros(args)
        raise exc
    return _side
