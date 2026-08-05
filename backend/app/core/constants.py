# -*- coding: utf-8 -*-
"""
공통 상수 모듈 -- settlement_engine 등에서 사용하는 상수를 한 곳에서 관리.
"""
from __future__ import annotations
from datetime import timedelta, timezone

# KST 타임존
_KST = timezone(timedelta(hours=9))

# 수수료/세금 상수
BUY_COMMISSION = 0.00015   # 매수 수수료 0.015%
SELL_COMMISSION = 0.00015  # 매도 수수료 0.015%
SECURITIES_TAX = 0.002     # 증권거래세 + 농특세 0.20%

# 토큰 발급 재시도 공통 상수 (키움·LS 공유 — P23 일관성)
TOKEN_ISSUE_MAX_RETRIES = 3            # 최대 재시도 횟수
TOKEN_BACKOFF_BASE_SEC = 1.0           # 지수 백오프 기준 간격 (1s→2s→4s)
TOKEN_BACKOFF_JITTER_RATIO = 1.0       # 풀 지터 — 0 ~ base*2^attempt 범위 랜덤
TOKEN_RECOVERY_INTERVAL_SEC = 30       # 회복 루프 간격 (초)
TOKEN_RECOVERY_MAX_ATTEMPTS = 10       # 회복 루프 최대 횟수 (약 5분)

# 토큰 발급 실패 분류 기준 (일시 vs 영구)
TOKEN_TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})  # 일시 실패 HTTP 코드
TOKEN_PERMANENT_HTTP_CODES = frozenset({401, 403})                 # 영구 실패 HTTP 코드 (발급 단계 기준)
TOKEN_PERMANENT_RESPONSE_KEYWORDS = frozenset({                    # 응답 내 인증 거부 코드/키워드
    "8030",
    "invalid_client",
    "invalid_grant",
    "unauthorized_client",
})
