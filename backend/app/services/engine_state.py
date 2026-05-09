# -*- coding: utf-8 -*-
"""
엔진 전역 상태 프록시 모듈.

engine_service.py의 전역 상태에 대한 접근 레이어.
순환 import 방지: 이 모듈은 engine_service를 lazy import한다.
외부 모듈이 `import app.services.engine_state as _st` 후
`_st.X` 읽기/쓰기 모두 engine_service.X에 프록시된다.

구현: types.ModuleType 서브클래스로 sys.modules 교체 (PEP 562는 __setattr__ 미지원).
"""
from __future__ import annotations

import sys
import types


class _EngineStateProxy(types.ModuleType):
    """engine_service 모듈의 읽기/쓰기를 모두 프록시하는 모듈 래퍼."""

    def __getattr__(self, name: str):
        from app.services import engine_service as _es
        try:
            return getattr(_es, name)
        except AttributeError:
            raise AttributeError(
                f"module {self.__name__!r} has no attribute {name!r}"
            )

    def __setattr__(self, name: str, value):
        # 모듈 메타 속성(__name__, __loader__ 등)은 자기 자신에 저장
        if name.startswith("__") and name.endswith("__"):
            super().__setattr__(name, value)
            return
        from app.services import engine_service as _es
        setattr(_es, name, value)

    def __delattr__(self, name: str):
        # unittest.mock.patch 복원 시 delattr 호출 — engine_service에 위임
        from app.services import engine_service as _es
        try:
            delattr(_es, name)
        except AttributeError:
            pass


# sys.modules 교체 — import 시 _EngineStateProxy 인스턴스가 반환됨
_proxy = _EngineStateProxy(__name__)
_proxy.__package__ = __package__
_proxy.__loader__ = __loader__  # type: ignore[name-defined]
_proxy.__file__ = __file__
_proxy.__path__ = []  # type: ignore[attr-defined]
_proxy.__spec__ = __spec__  # type: ignore[name-defined]
sys.modules[__name__] = _proxy
