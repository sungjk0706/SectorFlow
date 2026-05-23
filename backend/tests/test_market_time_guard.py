# -*- coding: utf-8 -*-
"""시간 가드 시뮬레이션 테스트 - 20:30 이전 차단 검증"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed


class TestMarketTimeGuard:
    """시간 가드 테스트"""

    @pytest.fixture
    def kst(self):
        return ZoneInfo("Asia/Seoul")

    def test_guard_blocks_before_2030(self, kst):
        """20:30 이전에는 차단되어야 함"""
        # 가상 장중 시간 (14:00)
        mock_time = datetime(2026, 5, 22, 14, 0, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert not is_heavy_operation_allowed(), "14:00에 차단되어야 함"

        # 가상 시간외 시간 (16:00)
        mock_time = datetime(2026, 5, 22, 16, 0, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert not is_heavy_operation_allowed(), "16:00에 차단되어야 함"

        # 가상 마켓 정리 시간 (19:30)
        mock_time = datetime(2026, 5, 22, 19, 30, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert not is_heavy_operation_allowed(), "19:30에 차단되어야 함"

    def test_guard_allows_after_2030(self, kst):
        """20:30 이후에는 허용되어야 함"""
        # 가상 안전 시간 (21:00)
        mock_time = datetime(2026, 5, 22, 21, 0, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert is_heavy_operation_allowed(), "21:00에 허용되어야 함"

        # 가상 심야 시간 (23:00)
        mock_time = datetime(2026, 5, 22, 23, 0, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert is_heavy_operation_allowed(), "23:00에 허용되어야 함"

    def test_guard_allows_before_market_open(self, kst):
        """자정 이후 새벽 시간에는 허용되어야 함"""
        # 가상 새벽 시간 (04:00)
        mock_time = datetime(2026, 5, 23, 4, 0, tzinfo=kst)  # 다음날 04:00
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert is_heavy_operation_allowed(), "04:00에 허용되어야 함"

    def test_guard_blocks_after_market_open(self, kst):
        """연결 시작 시간 이후에는 차단되어야 함"""
        # 가상 연결 시작 시간 이후 (08:30) - 평일
        mock_time = datetime(2026, 5, 22, 8, 30, tzinfo=kst)  # 금요일 08:30
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert not is_heavy_operation_allowed(), "08:30에 차단되어야 함"

    def test_guard_allows_holiday(self, kst):
        """휴장일에는 허용되어야 함"""
        # 가상 휴장일 (토요일 14:00)
        mock_time = datetime(2026, 5, 24, 14, 0, tzinfo=kst)  # 토요일
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert is_heavy_operation_allowed(), "휴장일에 허용되어야 함"

    def test_guard_blocks_at_2000_boundary(self, kst):
        """20:00 경계 시점 테스트"""
        # 20:00 (차단)
        mock_time = datetime(2026, 5, 22, 20, 0, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert not is_heavy_operation_allowed(), "20:00에 차단되어야 함"

        # 20:01 (허용)
        mock_time = datetime(2026, 5, 22, 20, 1, tzinfo=kst)
        with patch('backend.app.services.daily_time_scheduler._kst_now', return_value=mock_time):
            assert is_heavy_operation_allowed(), "20:01에 허용되어야 함"
