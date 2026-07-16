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
    "buy_time_end": "15:20",
    "auto_sell_on": False,
    "sell_time_start": "09:00",
    "sell_time_end": "15:20",
    # 웹소켓
    "confirmed_download_time": "20:40",
    
    # 텔레그램
    "tele_on": False,
    "telegram_chat_id": "",
    "telegram_bot_token_test": "",
    "telegram_bot_token_real": "",
    
    # 투자모드
    "trade_mode": "test",
    "test_virtual_deposit": 10000000,
    "test_virtual_balance": 10000000,
    
    # 증권사 선택
    "broker": "kiwoom",
    
    # 매수 설정
    "max_daily_total_buy_on": False,
    "max_daily_total_buy_amt": 0,
    "max_stock_cnt_on": True,
    "max_stock_cnt": 5,
    "buy_amt_on": True,
    "buy_amt": 1000000,
    "rebuy_block_on": True,
    "rebuy_block_period": "today",
    "boost_high_breakout_on": False,
    "boost_high_breakout_score": 1.0,
    "boost_order_ratio_on": False,
    "boost_order_ratio_pct": 20,
    "boost_order_ratio_score": 1.0,
    "boost_program_net_buy_on": False,
    "boost_program_net_buy_score": 1.0,
    "boost_trade_amount_rank_on": False,
    "boost_trade_amount_rank_score": 1.0,

    # 리스크 관리
    "max_daily_loss_limit": -500000,
    "max_single_stock_exposure": 20000000,
    "max_position_size": 0,

     # 매도 설정
     "tp_apply": False,
     "tp_val": 0,
     "loss_apply": False,
     "loss_val": 0,
     "ts_apply": False,
     "ts_start_val": 0,
     "ts_drop_val": 0,
     
     # 매도 주문 설정
     "sell_price_type": "mkt",
     "sell_offset": 0,
     "sell_custom_qty": 0,
     "sell_qty_type": "%",

     # 업종순위 설정
     "sector_min_rise_ratio_pct": 60.0,
     "buy_block_rise_on": True,
     "buy_block_rise_pct": 7.0,
     "buy_block_fall_on": True,
     "buy_block_fall_pct": 7.0,
     "buy_block_strength_on": False,
     "buy_min_strength": 0.0,
     "sector_min_trade_amt": 0.0,
     "sector_max_targets": 3,
     "sector_sort_keys": ["score"],
     "sector_stock_layout": [],
     # 업종 점수 3단계 가산점 슬라이더 (-100~+100, 기본값 0) — 조정 만점 = 업종 수 × (1 + slider/100)
     "sector_bonus_rise_ratio_slider": 0,
     "sector_bonus_relative_strength_slider": 0,
     "sector_bonus_trade_amount_slider": 0,

     # 매수 주문 간격 (1순위 종목만 매수 후 사용자 설정 간격 대기)
     "buy_interval_on": False,
     "buy_interval_min": 0,

     # 수신율 임계값
     "sector_start_threshold_pct": 70.0,

     # 종목별 매도 설정
     "sell_per_symbol": {},

     # 브로커 기능별 매핑
     "broker_config": {},

     # 장마감 후 스케줄러 토글 (기본값 True = 활성화)
     # ws_subscribe_end 도달 시 확정 데이터 다운로드 실행 여부
     "scheduler_market_close_on": True,
     # 5일 거래대금/최고가 롤링 다운로드 실행 여부
     "scheduler_5d_download_on": True,

     # UI 설정 — 실시간 현재가 플래시 효과 (기본값 True = 활성화)
     "ui_price_flash_on": True,
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
