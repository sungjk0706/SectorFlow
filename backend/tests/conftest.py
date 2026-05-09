# -*- coding: utf-8 -*-
"""테스트 공통 fixture -- 프로덕션 데이터 파일 오염 방지."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_settlement_state(tmp_path, monkeypatch):
    """settlement_engine._STATE_PATH를 임시 경로로 교체하여 실제 파일 보호."""
    monkeypatch.setattr(
        "app.services.settlement_engine._STATE_PATH",
        tmp_path / "settlement_state.json",
    )
