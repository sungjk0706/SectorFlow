# -*- coding: utf-8 -*-
"""
실시간 잔고(REAL 04/80) -- 로직은 `engine_account_rest.real04_official_*` 에 둔다.

키움증권 공식 안내 기준 FID만 사용한다(930 예수금·931 출금가능 추정, 932~934 합계, 302·10 종목명·현재가).
"""
from __future__ import annotations

# 하위 호환: 과거 import 경로 -- 실제 구현은 engine_account_rest
from app.services.engine_account_rest import (  # noqa: F401
    real04_official_account_delta,
    real04_official_apply_position_line,
)
