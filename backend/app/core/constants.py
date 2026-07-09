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
