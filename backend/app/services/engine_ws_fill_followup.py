# -*- coding: utf-8 -*-
"""
주문체결(00) 직후 후속 처리 -- 지연·스냅샷·브로드캐스트·매도조건 검사.

엔진 전역·AutoTradeManager 는 콜백으로만 연결한다 (로직 불변·순서 유지).
테스트모드(dry-run)에서는 REST 잔고 조회를 건너뛰고 인메모리 잔고만 사용.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def run_after_order_fill_ws(
    delay_sec: float,
    refresh_account_snapshot_meta: Callable[[], None],
    run_sell_conditions_if_applicable: Callable[[], None],
    *,
    is_dry_run: bool = False,
) -> None:
    """REST 없이 메모리·매도조건만 갱신하는 기존 _on_fill_after_ws 와 동일 순서.

    is_dry_run=True 이면 REST 잔고 새로고침을 건너뛰고
    인메모리(dry_run) 잔고 기반 메타 갱신 + 매도조건 검사만 수행.
    """
    if is_dry_run:
        logger.debug("[DRY-RUN] fill_00 후속 -- REST 생략, 인메모리 잔고 기준 처리")
    refresh_account_snapshot_meta()
    run_sell_conditions_if_applicable()
