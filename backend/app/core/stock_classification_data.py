from __future__ import annotations
# -*- coding: utf-8 -*-
"""
업종분류 커스텀 데이터 관리 모듈.

기존 JSON 파일 저장을 중단하고, 모든 업종 분류 데이터를 SQLite 데이터베이스(stocks.db)의 
stocks 및 sectors 테이블에서 직접 조회 및 업데이트하도록 개선.
"""

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

async def rename_sector(old_name: str, new_name: str) -> None:
    """업종명을 변경한다. DB와 인메모리 캐시를 동시에 업데이트."""
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise ValueError("기존 업종명과 새 업종명은 필수입니다")
    if old_name == new_name:
        raise ValueError("기존 업종명과 새 업종명이 동일합니다")

    # 1) SQLite DB 업데이트
    from backend.app.db.database import get_db_connection
    conn = await get_db_connection()
    try:
        await conn.execute("UPDATE custom_sectors SET name = ? WHERE name = ?", (new_name, old_name))
        await conn.execute("UPDATE master_stocks_table SET sector = ? WHERE sector = ?", (new_name, old_name))
        await conn.commit()
    except Exception as e:
        await conn.rollback()
        _log.error("[DB업데이트] 업종명 변경 실패: %s", e)
        raise e

    # 2) 인메모리 캐시 증분 업데이트
    try:
        import backend.app.services.engine_service as es
        for cd, entry in es._master_stocks_cache.items():
            if entry.get("sector") == old_name:
                entry["sector"] = new_name
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종명 변경 실패: %s", e)


async def create_sector(name: str) -> None:
    """신규 업종 등록.
    
    custom_sectors 테이블은 stock_code를 기본 키로 사용하므로,
    업종 정의만 저장하는 방식이 아닌 종목 매핑 시 업종이 자동 생성됨.
    이 함수는 더 이상 사용되지 않음 (하위 호환성용).
    """
    raise NotImplementedError("업종 생성은 종목 매핑(move_stock)을 통해 자동 생성됩니다")


async def delete_sector(name: str) -> None:
    """업종을 삭제한다. 해당 업종의 종목들을 '기타'로 이동."""
    name = name.strip()
    if not name:
        raise ValueError("업종명은 필수입니다")

    # 1) SQLite DB 업데이트
    from backend.app.db.database import get_db_connection
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM custom_sectors WHERE name = ?", (name,))
        await conn.execute("UPDATE master_stocks_table SET sector = '기타' WHERE sector = ?", (name,))
        await conn.commit()
    except Exception as e:
        await conn.rollback()
        _log.error("[DB업데이트] 업종 삭제 실패: %s", e)
        raise e

    # 2) 인메모리 캐시 증분 업데이트
    try:
        import backend.app.services.engine_service as es
        for cd, entry in es._master_stocks_cache.items():
            if entry.get("sector") == name:
                entry["sector"] = "기타"
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종 삭제 반영 실패: %s", e)


async def move_stock(stock_code: str, target_sector: str) -> None:
    """종목을 다른 업종으로 이동. DB와 인메모리 캐시를 동시에 업데이트.
    
    custom_sectors 테이블 기본 키: stock_code (단일)
    한 종목은 하나의 업종만 소속.
    """
    stock_code = stock_code.strip()
    target_sector = target_sector.strip()
    if not stock_code or not target_sector:
        raise ValueError("종목코드와 대상 업종명은 필수입니다")

    # 1) SQLite DB 업데이트 (custom_sectors 원본 + master_stocks_table 파생)
    from backend.app.db.database import get_db_connection
    conn = await get_db_connection()
    try:
        await conn.execute("UPDATE master_stocks_table SET sector = ? WHERE code = ?", (target_sector, stock_code))
        # stock_code 단일 기본 키이므로 INSERT OR REPLACE로 기존 매핑 교체
        await conn.execute("INSERT OR REPLACE INTO custom_sectors (stock_code, name) VALUES (?, ?)", (stock_code, target_sector))
        await conn.commit()
    except Exception as e:
        await conn.rollback()
        _log.error("[DB업데이트] 종목 이동 실패: %s", e)
        raise e

    # 2) 인메모리 캐시 증분 업데이트
    try:
        import backend.app.services.engine_service as es
        entry = es._master_stocks_cache.get(stock_code)
        if entry:
            entry["sector"] = target_sector
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 종목 업종 갱신 실패: %s", e)


async def sync_sector_from_custom_sectors() -> None:
    """custom_sectors 테이블을 기준으로 master_stocks_table.sector 동기화.
    
    확정시세 다운로드 후 사용자 커스텀 업종 매핑 복구용.
    custom_sectors 테이블 기본 키: stock_code (단일)
    """
    from backend.app.db.database import get_db_connection
    import backend.app.services.engine_state as _st
    
    conn = await get_db_connection()
    
    try:
        # custom_sectors에서 매핑 로드 (stock_code, name 순서)
        cursor = await conn.execute("SELECT stock_code, name FROM custom_sectors")
        rows = await cursor.fetchall()
        
        updated = 0
        for row in rows:
            await conn.execute(
                "UPDATE master_stocks_table SET sector = ? WHERE code = ?",
                (row["name"], row["stock_code"])
            )
            updated += 1
        
        await conn.commit()
        _log.info("[동기화] custom_sectors 기반 master_stocks_table.sector 동기화 완료 -- %d종목", updated)
        
        # 메모리 캐시 sector 필드 갱신
        import backend.app.services.engine_service as es
        for row in rows:
            code = row["stock_code"]
            sector = row["name"]
            if code in _st._master_stocks_cache:
                _st._master_stocks_cache[code]["sector"] = sector
        
        _log.info("[동기화] 메모리 캐시 sector 필드 갱신 완료 -- %d종목", updated)
    except Exception as e:
        await conn.rollback()
        _log.error("[동기화] custom_sectors 기반 동기화 실패: %s", e)
        raise e
