# -*- coding: utf-8 -*-
"""
설정값 기본값 정의 (코드 레벨 단일 소스 진리)
DB 연결 실패 시 또는 DB에 값이 없을 때 사용
"""

from typing import Any

# 사용자 설정 기본값 (user_settings)
DEFAULT_USER_SETTINGS: dict[str, Any] = {
    # 자동매매
    "time_scheduler_on": False,
    "auto_buy_on": False,
    "buy_time_start": "09:00",
    "buy_time_end": "15:00",
    "auto_sell_on": False,
    "sell_time_start": "09:00",
    "sell_time_end": "15:00",
    "holiday_guard_on": True,
    
    # 웹소켓
    "ws_subscribe_on": False,
    "ws_subscribe_start": "09:00",
    "ws_subscribe_end": "15:00",
    
    # UI 설정
    "ui_price_flash_on": True,
    
    # 텔레그램
    "tele_on": False,
    "telegram_chat_id": "",
    "telegram_bot_token": "",
    
    # 거래모드
    "trade_mode": "test",
    "test_mode": True,
    "mock_mode": True,
    "mode_real": False,
    "test_virtual_deposit": 10000000,
    "test_virtual_balance": 10000000,
    
    # 증권사 선택
    "broker": "kiwoom",
    
    # 매수 설정
    "buy_block_rise_pct": 0,
    "buy_block_fall_pct": 0,
    "buy_min_strength": 0,
    "max_daily_total_buy_amt": 0,
    "max_stock_cnt": 0,
    "buy_amt": 0,
    "boost_high_breakout_on": False,
    "boost_high_breakout_score": 1.0,
    "boost_order_ratio_on": False,
    "boost_order_ratio_pct": 20,
    "boost_order_ratio_score": 1.0,
    
    # 매도 설정
    "tp_apply": False,
    "tp_val": 0,
    "loss_apply": False,
    "loss_val": 0,
    "ts_apply": False,
    "ts_start_val": 0,
    "ts_drop_val": 0,
}

# 시스템 설정 기본값 (system_config)
DEFAULT_SYSTEM_CONFIG: dict[str, Any] = {
    # 마켓 시간 (증권사 공식값)
    "krx_open_time": "09:00",
    "krx_close_time": "15:30",
    "krx_premarket_start": "08:00",
    "krx_premarket_end": "09:00",
    "krx_aftermarket_start": "15:40",
    "krx_aftermarket_end": "16:00",
    "krx_single_price_start": "16:00",
    "krx_single_price_end": "18:00",
    
    "nxt_premarket_start": "08:00",
    "nxt_premarket_end": "09:00",
    "nxt_mainmarket_start": "08:50",
    "nxt_mainmarket_end": "15:20",
    "nxt_aftermarket_start": "15:30",
    "nxt_aftermarket_end": "20:00",
    
    # 시스템 동작 설정
    "db_connection_timeout": 30,
    "db_retry_count": 3,
    "db_retry_delay": 1.0,
    "cache_size": 1000,
    "log_level": "INFO",
}

# broker_credentials는 기본값 없음 (사용자 입력 필수)
DEFAULT_BROKER_CREDENTIALS: dict[str, Any] = {}

# 통합 기본값
DEFAULT_SETTINGS: dict[str, Any] = {
    **DEFAULT_USER_SETTINGS,
    **DEFAULT_SYSTEM_CONFIG,
    **DEFAULT_BROKER_CREDENTIALS,
}
