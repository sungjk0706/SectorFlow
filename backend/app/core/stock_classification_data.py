# -*- coding: utf-8 -*-
"""
업종분류 커스텀 데이터 관리 모듈.

기존 JSON 파일 저장을 중단하고, 모든 업종 분류 데이터를 SQLite 데이터베이스(stocks.db)의 
stocks 및 sectors 테이블에서 직접 조회 및 업데이트하도록 개선.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


# ── 데이터 모델 ──
@dataclass
class StockClassificationData:
    """사용자 커스텀 업종 분류 데이터 (하위 호환성용 dummy 구조체)."""
    sectors: dict[str, str] = field(default_factory=dict)
    stock_moves: dict[str, str] = field(default_factory=dict)
    deleted_sectors: list[str] = field(default_factory=list)


# ── 캐시 조회 (하위 호환 및 REST API용 더미 인터페이스) ──

def load_custom_data() -> StockClassificationData:
    """하위 호환성을 위한 빈 데이터 로드 함수."""
    return StockClassificationData()


def load_custom_data_readonly() -> StockClassificationData:
    """하위 호환성을 위한 빈 데이터 로드 함수."""
    return StockClassificationData()


# ── 비즈니스 로직 (SQLite DB 직접 제어) ──

def rename_sector(old_name: str, new_name: str) -> None:
    """업종명을 변경한다. DB와 인메모리 캐시를 동시에 업데이트."""
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise ValueError("기존 업종명과 새 업종명은 필수입니다")
    if old_name == new_name:
        raise ValueError("기존 업종명과 새 업종명이 동일합니다")

    # 1) SQLite DB 업데이트
    from backend.app.db.database import get_db_connection
    conn = get_db_connection()
    try:
        conn.execute("UPDATE sectors SET name = ? WHERE name = ?", (new_name, old_name))
        conn.execute("UPDATE stocks SET sector = ? WHERE sector = ?", (new_name, old_name))
        conn.commit()
    except Exception as e:
        conn.rollback()
        _log.error("[DB업데이트] 업종명 변경 실패: %s", e)
        raise e
    finally:
        conn.close()

    # 2) 인메모리 캐시 업데이트
    try:
        import backend.app.services.engine_service as es
        for cd, entry in es._pending_stock_details.items():
            if entry.get("sector") == old_name:
                entry["sector"] = new_name
        es._invalidate_sector_stocks_cache()
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종명 변경 실패: %s", e)


def create_sector(name: str) -> None:
    """신규 업종 등록."""
    name = name.strip()
    if not name:
        raise ValueError("업종명은 필수입니다")

    # 1) SQLite DB 업데이트
    from backend.app.db.database import get_db_connection
    conn = get_db_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO sectors (name) VALUES (?)", (name,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        _log.error("[DB업데이트] 업종 생성 실패: %s", e)
        raise e
    finally:
        conn.close()


def delete_sector(name: str) -> None:
    """업종을 삭제한다. 해당 업종의 종목들을 '기타'로 이동."""
    name = name.strip()
    if not name:
        raise ValueError("업종명은 필수입니다")

    # 1) SQLite DB 업데이트
    from backend.app.db.database import get_db_connection
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM sectors WHERE name = ?", (name,))
        conn.execute("UPDATE stocks SET sector = '기타' WHERE sector = ?", (name,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        _log.error("[DB업데이트] 업종 삭제 실패: %s", e)
        raise e
    finally:
        conn.close()

    # 2) 인메모리 캐시 업데이트
    try:
        import backend.app.services.engine_service as es
        for cd, entry in es._pending_stock_details.items():
            if entry.get("sector") == name:
                entry["sector"] = "기타"
        es._invalidate_sector_stocks_cache()
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종 삭제 반영 실패: %s", e)


def move_stock(stock_code: str, target_sector: str) -> None:
    """종목을 다른 업종으로 이동. DB와 인메모리 캐시를 동시에 업데이트."""
    stock_code = stock_code.strip()
    target_sector = target_sector.strip()
    if not stock_code or not target_sector:
        raise ValueError("종목코드와 대상 업종명은 필수입니다")

    # 1) SQLite DB 업데이트
    from backend.app.db.database import get_db_connection
    conn = get_db_connection()
    try:
        conn.execute("UPDATE stocks SET sector = ? WHERE code = ?", (target_sector, stock_code))
        conn.commit()
    except Exception as e:
        conn.rollback()
        _log.error("[DB업데이트] 종목 이동 실패: %s", e)
        raise e
    finally:
        conn.close()

    # 2) 인메모리 캐시 업데이트
    try:
        import backend.app.services.engine_service as es
        entry = es._pending_stock_details.get(stock_code)
        if entry:
            entry["sector"] = target_sector
            es._invalidate_sector_stocks_cache()
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 종목 업종 갱신 실패: %s", e)
