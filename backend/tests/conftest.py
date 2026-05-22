# -*- coding: utf-8 -*-
"""테스트 공통 fixture -- 프로덕션 데이터 파일 오염 방지."""
from __future__ import annotations

import sys
import pytest

import importlib
from importlib.machinery import ModuleSpec

class RedirectLoader:
    def __init__(self, target_module):
        self.target_module = target_module

    def create_module(self, spec):
        return self.target_module

    def exec_module(self, module):
        pass

class RedirectFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("backend.app"):
            alias_name = fullname[len("backend."):]
            try:
                target_module = importlib.import_module(alias_name)
                return ModuleSpec(fullname, RedirectLoader(target_module))
            except Exception:
                return None
        return None

if not any(isinstance(finder, RedirectFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, RedirectFinder())


@pytest.fixture(autouse=True)
def isolate_settlement_state(tmp_path, monkeypatch):
    """settlement_engine._STATE_PATH를 임시 경로로 교체하여 실제 파일 보호."""
    monkeypatch.setattr(
        "app.services.settlement_engine._STATE_PATH",
        tmp_path / "settlement_state.json",
    )
    monkeypatch.setattr(
        "backend.app.services.settlement_engine._STATE_PATH",
        tmp_path / "settlement_state.json",
    )
