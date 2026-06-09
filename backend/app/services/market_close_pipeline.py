from __future__ import annotations
# -*- coding: utf-8 -*-
"""
장마감 후 데이터 캐시 파이프라인 — 핵심 로직.

KRX/NXT 장마감 후 WS 구독 해지 → REST 확정 데이터 조회 → 캐시 저장.
daily_time_scheduler.py 타이머 콜백에서 호출된다.
"""

import asyncio
import logging
from types import ModuleType

from backend.app.core.logger import get_logger
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    _format_kiwoom_reg_stk_cd,
    is_nxt_enabled,
    get_ws_subscribe_code,
)
from backend.app.services.engine_ws_reg import build_0b_remove_payloads
from backend.app.core.trading_calendar import get_current_trading_day_str

_log = get_logger("engine")


def _broadcast_confirmed_progress(
    current: int, total: int, *, message: str = "", eta_sec: float = 0, step: int = 0,
    _loop: "asyncio.AbstractEventLoop | None" = None,
) -> None:
    """확정 데이터 조회 진행률 → confirmed-progress WS 브로드캐스트 (헤더 칩 표시용).

    _loop が渡된 경우(스레드풀 내부 호출): broadcast_threadsafe()로 메인 루프에 예약.
    _loop가 없는 경우(async context 직접 호출): broadcast() 사용.
    """
    try:
        from backend.app.web.ws_manager import ws_manager
        payload = {
            "_v": 1,
            "current": current,
            "total": total,
            "done": current >= total and total > 0,
            "message": message,
            "eta_sec": eta_sec,
            "status": "confirmed",
            "step": step,
        }
        from backend.app.services.core_queues import get_broadcast_queue
        
        if current >= total:
            payload["status"] = "completed"

        q = get_broadcast_queue()
        data = {"type": "confirmed-progress", "data": payload}
        
        if _loop is not None:
            _loop.call_soon_threadsafe(lambda: q.put_nowait(data) if not q.full() else None)
        else:
            if not q.full():
                q.put_nowait(data)
    except Exception as exc:
        _log.warning("[데이터] 브로드캐스트 실패: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 종목 분류 헬퍼
# ---------------------------------------------------------------------------

def _get_krx_only_codes(es: ModuleType) -> list[str]:
    """_master_stocks_cache에서 KRX 단독 종목(nxt_enable=False)만 추출.

    Args:
        es: engine_service 모듈 참조

    Returns:
        6자리 정규화된 KRX 단독 종목코드 리스트 (중복 없음).
    """
    result: list[str] = []
    seen: set[str] = set()

    sources: list[set | dict | list] = []
    # _master_stocks_cache의 "_subscribed" 사용
    subscribed_codes = {cd for cd, entry in es._master_stocks_cache.items() if entry.get("_subscribed", False)}
    if subscribed_codes:
        sources.append(subscribed_codes)
    # _radar_cnsr_order 삭제

    for src in sources:
        for raw_cd in list(src):
            base = _base_stk_cd(raw_cd)
            if not base or base in seen:
                continue
            seen.add(base)
            if not is_nxt_enabled(base):
                result.append(base)

    # 레이아웃 캐시에서 seen에 없는 KRX 단독 종목 추가 (항상 순회)
    # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
    layout = es._integrated_system_settings_cache.get("sector_stock_layout", [])
    for kind, val in layout:
        if kind == "code":
            base = _base_stk_cd(val)
            if not base or base in seen:
                continue
            seen.add(base)
            if not is_nxt_enabled(base):
                result.append(base)

    return result


# ---------------------------------------------------------------------------
# KRX 단독 종목 REMOVE
# ---------------------------------------------------------------------------

async def remove_krx_only_stocks(es: ModuleType) -> dict:
    """KRX 단독 종목(nxt_enable=False)만 선택적 REMOVE.

    Args:
        es: engine_service 모듈 참조

    Returns:
        {"removed": int, "failed": int, "skipped": bool}
    """
    # WS 미연결 시 스킵
    ws = getattr(es, "_kiwoom_connector", None)
    if not ws or not getattr(ws, "is_connected", lambda: False)():
        _log.warning("[타이머] KRX 장마감 구독해지 생략 — 실시간 미연결")
        return {"removed": 0, "failed": 0, "skipped": True}

    krx_codes = _get_krx_only_codes(es)
    if not krx_codes:
        _log.info("[타이머] KRX 장마감 구독해지 대상 없음")
        return {"removed": 0, "failed": 0, "skipped": False}

    # 종목코드를 WS 구독 형식으로 변환하여 페이로드 생성
    ws_codes = [get_ws_subscribe_code(cd) for cd in krx_codes]
    payloads = build_0b_remove_payloads(ws_codes)

    if not payloads:
        return {"removed": 0, "failed": 0, "skipped": False}

    removed = 0
    failed = 0
    chunk_size = 100

    for ci, payload in enumerate(payloads):
        chunk = krx_codes[ci * chunk_size : (ci + 1) * chunk_size]
        try:
            ack_ok, rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
        except Exception as exc:
            _log.warning(
                "[타이머] KRX 장마감 구독해지 %d/%d 예외: %s",
                ci + 1, len(payloads), exc,
                exc_info=True,
            )
            failed += len(chunk)
            continue

        if ack_ok:
            # ACK 성공 — _master_stocks_cache에서 "_subscribed" 제거
            for cd in chunk:
                if cd in es._master_stocks_cache:
                    es._master_stocks_cache[cd].pop("_subscribed", None)
            removed += len(chunk)
            _log.info(
                "[타이머] KRX 장마감 구독해지 %d/%d 완료 — %d종목 (rc=%s)",
                ci + 1, len(payloads), len(chunk), rc,
            )
        else:
            # ACK 타임아웃 — _master_stocks_cache의 "_subscribed" 유지 + 경고
            failed += len(chunk)
            _log.warning(
                "[타이머] KRX 장마감 구독해지 %d/%d ACK 응답없음 — %d종목 유지",
                ci + 1, len(payloads), len(chunk),
            )

    _log.info(
        "[타이머] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목",
        removed, failed,
    )
    return {"removed": removed, "failed": failed, "skipped": False}


# ---------------------------------------------------------------------------
# 단일 벌크 트랜잭션 헬퍼 함수
# ---------------------------------------------------------------------------

async def execute_unified_rolling_and_save(
    es: ModuleType,
    confirmed: dict[str, dict],
    name_map: dict[str, str] | None = None,
) -> bool:
    """모든 정산 데이터를 메모리에서 연산 후 단일 트랜잭션으로 DB 및 메모리에 저장.

    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, trade_amount, high_price}}
        name_map: {6자리 종목코드: 종목명} — 종목명 보정용

    Returns:
        저장 성공 여부.
    """
    from backend.app.db.database import get_db_connection, get_db_lock
    import backend.app.services.engine_state as _st

    date_str = get_current_trading_day_str()
    _nm = name_map or {}

    async with get_db_lock():
        conn = await get_db_connection()

        try:
            # 1. 기존 5일 배열 일괄 로드 (1회 조회)
            cursor = await conn.execute("""
                SELECT code, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                       day1_high, day2_high, day3_high, day4_high, day5_high
                FROM stock_5d_array
                WHERE date = (SELECT MAX(date) FROM stock_5d_array WHERE date < ?)
            """, (date_str,))
            existing_rows = await cursor.fetchall()
            existing_map = {r["code"]: r for r in existing_rows}

            # 2. 메모리 연산 및 벌크 파라미터 빌드
            master_bulk_params = []
            array_5d_bulk_params = []

            for raw_cd, detail in confirmed.items():
                nk = _format_kiwoom_reg_stk_cd(raw_cd)
                if not nk:
                    continue

                # 당일 데이터 추출
                today_amt = int(detail.get("trade_amount") or 0)
                today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)
                cur_price = int(detail.get("cur_price") or 0)
                change = int(detail.get("change") or 0)
                change_rate = float(detail.get("change_rate") or 0.0)

                # 5일 롤링 계산
                if nk in existing_map:
                    row = existing_map[nk]
                    new_amts = [today_amt, row["day1_amount"], row["day2_amount"], row["day3_amount"], row["day4_amount"]]
                    new_highs = [today_high, row["day1_high"], row["day2_high"], row["day3_high"], row["day4_high"]]
                else:
                    new_amts = [today_amt, 0, 0, 0, 0]
                    new_highs = [today_high, 0, 0, 0, 0]

                # 메트릭 계산
                valid_amts = [a for a in new_amts if a > 0]
                avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0

                valid_highs = [h for h in new_highs if h > 0]
                high_5d = max(valid_highs) if valid_highs else 0

                # DB 벌크 파라미터 추가
                array_5d_bulk_params.append((
                    nk, date_str,
                    new_amts[0], new_amts[1], new_amts[2], new_amts[3], new_amts[4],
                    new_highs[0], new_highs[1], new_highs[2], new_highs[3], new_highs[4]
                ))

                # master_stocks_table market 정보 조회
                stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)
                sector = detail.get("sector", "기타")

                master_bulk_params.append((
                    nk, stk_nm, cur_price, change, change_rate,
                    today_amt, today_high, avg_5d, high_5d, date_str, sector
                ))

                # 메모리 캐시 동시 갱신
                if nk in _st._master_stocks_cache:
                    entry = _st._master_stocks_cache[nk]
                    entry.update({
                        "cur_price": cur_price,
                        "change": change,
                        "change_rate": change_rate,
                        "trade_amount": today_amt,
                        "high_price": today_high,
                        "avg_5d_trade_amount": avg_5d,
                        "high_5d_price": high_5d,
                        "date": date_str,
                        "status": "active"
                    })
                    if stk_nm and stk_nm != nk:
                        entry["name"] = stk_nm
                    if sector:
                        entry["sector"] = sector

            # 3. 단일 트랜잭션 내 벌크 실행
            # 5일 배열 적재
            if array_5d_bulk_params:
                await conn.executemany("""
                    INSERT OR REPLACE INTO stock_5d_array
                    (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                     day1_high, day2_high, day3_high, day4_high, day5_high)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, array_5d_bulk_params)

            # 마스터 테이블 적재 (UPSERT)
            if master_bulk_params:
                # 기존 market 정보 보존을 위해 먼저 조회
                cursor = await conn.execute("SELECT code, market FROM master_stocks_table")
                mkt_rows = await cursor.fetchall()
                mkt_map = {r["code"]: r["market"] for r in mkt_rows}

                updated_params = []
                for params in master_bulk_params:
                    code = params[0]
                    market = mkt_map.get(code, "")
                    updated_params.append(params + (market,))

                await conn.executemany("""
                    INSERT INTO master_stocks_table
                    (code, name, cur_price, change, change_rate, trade_amount, high_price, avg_5d_trade_amount, high_5d_price, date, sector, market)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        high_price = excluded.high_price,
                        avg_5d_trade_amount = excluded.avg_5d_trade_amount,
                        high_5d_price = excluded.high_5d_price,
                        date = excluded.date,
                        sector = CASE WHEN master_stocks_table.sector IS NOT NULL AND master_stocks_table.sector != '' AND master_stocks_table.sector != '기타' THEN master_stocks_table.sector ELSE excluded.sector END,
                        market = excluded.market
                """, updated_params)

            await conn.commit()
            _log.info("[단일 벌크 트랜잭션] 저장 완료 -- stock_5d_array: %d종목, master_stocks_table: %d종목", len(array_5d_bulk_params), len(master_bulk_params))
            return True

        except Exception as e:
            await conn.rollback()
            _log.warning("[단일 벌크 트랜잭션] 저장 실패: %s", e, exc_info=True)
            raise e


# ---------------------------------------------------------------------------
# 확정 데이터 메모리 반영
# ---------------------------------------------------------------------------

async def _apply_5d_to_memory(es: ModuleType, confirmed_5d: dict[str, dict]) -> int:
    """ka10081 5일봉 데이터를 master_stocks_table에 반영."""
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import get_current_trading_day_str

    updated = 0

    # DB 업데이트를 위한 연결
    conn = await get_db_connection()
    date_str = get_current_trading_day_str()

    for raw_cd, detail in confirmed_5d.items():
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue

        import backend.app.services.engine_state as _st

        if nk in _st._master_stocks_cache:
            _st._master_stocks_cache[nk]["status"] = "active"

            # avg_amt_5d - 단일 소스 진리: _master_stocks_cache 직접 업데이트
            avg5d = int(detail.get("avg_5d_trade_amount") or 0)
            if avg5d > 0:
                _st._master_stocks_cache[nk]["avg_5d_trade_amount"] = avg5d

            # high_price_5d
            high5d = int(detail.get("high_5d_price") or 0)
            if high5d > 0:
                _st._master_stocks_cache[nk]["high_5d_price"] = high5d

        # master_stocks_table에 5일 평균 거래대금 및 최고가 업데이트
        await conn.execute("""
            UPDATE master_stocks_table
            SET avg_5d_trade_amount = ?, high_5d_price = ?
            WHERE code = ?
        """, (avg5d, high5d, nk))

        updated += 1

    await conn.commit()

    _log.info("[타이머] 5일봉 데이터 메모리 및 DB 반영 -- %d종목", updated)
    return updated


async def _step1_apply_today_high_to_master_table(
    es: ModuleType,
    confirmed: dict[str, dict],
) -> int:
    """[Step 1] 다운로드한 오늘 최종 고가를 master_stocks_table.high_price에 적재.
    
    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, high_price}}
    
    Returns:
        반영된 종목 수.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import get_current_trading_day_str
    
    conn = await get_db_connection()
    date_str = get_current_trading_day_str()
    updated = 0
    
    for raw_cd, detail in confirmed.items():
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue
        
        today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)
        if today_high > 0:
            await conn.execute("""
                UPDATE master_stocks_table
                SET high_price = ?, date = ?
                WHERE code = ?
            """, (today_high, date_str, nk))
            updated += 1
    
    await conn.commit()
    _log.info("[Step 1] 당일 고가 master_stocks_table 적재 완료 -- %d종목", updated)
    return updated


async def _step2_roll_5d_arrays(
    es: ModuleType,
    confirmed: dict[str, dict],
) -> int:
    """[Step 2] stock_5d_array를 호출하여 5일 전 데이터를 탈락시키고, 
    오늘 적재된 high_price와 trade_amount를 배열에 밀어 넣는 롤링 업데이트.
    
    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, high_price}}
    
    Returns:
        반영된 종목 수.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import get_current_trading_day_str
    
    conn = await get_db_connection()
    date_str = get_current_trading_day_str()
    updated = 0
    
    # 기존 5일 배열 로드 (동일 거래일 재실행 시 오염 방지)
    cursor = await conn.execute("""
        SELECT code, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
               day1_high, day2_high, day3_high, day4_high, day5_high
        FROM stock_5d_array
        WHERE date = (SELECT MAX(date) FROM stock_5d_array WHERE date < ?)
    """, (date_str,))
    existing_rows = await cursor.fetchall()
    existing_map = {r["code"]: r for r in existing_rows}
    
    for raw_cd, detail in confirmed.items():
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue
        
        today_amt = int(detail.get("trade_amount") or 0)
        today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)
        
        # 기존 배열이 있으면 롤링, 없으면 새로 생성
        if nk in existing_map:
            row = existing_map[nk]
            new_amts = [today_amt, row["day1_amount"], row["day2_amount"], row["day3_amount"], row["day4_amount"]]
            new_highs = [today_high, row["day1_high"], row["day2_high"], row["day3_high"], row["day4_high"]]
        else:
            new_amts = [today_amt, 0, 0, 0, 0]
            new_highs = [today_high, 0, 0, 0, 0]
        
        # 롤링된 배열 저장
        await conn.execute("""
            INSERT OR REPLACE INTO stock_5d_array
            (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
             day1_high, day2_high, day3_high, day4_high, day5_high)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (nk, date_str,
              new_amts[0], new_amts[1], new_amts[2], new_amts[3], new_amts[4],
              new_highs[0], new_highs[1], new_highs[2], new_highs[3], new_highs[4]))
        updated += 1
    
    await conn.commit()
    _log.info("[Step 2] 5일 배열 롤링 업데이트 완료 -- %d종목", updated)
    return updated


async def _step3_recalculate_5d_metrics(
    es: ModuleType,
) -> int:
    """[Step 3] 롤링이 완료된 5일 배열을 기준으로 수학적 연산을 수행하여
    master_stocks_table의 high_5d_price와 avg_5d_trade_amount를 최종 갱신.
    
    Args:
        es: engine_service 모듈 참조
    
    Returns:
        반영된 종목 수.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import get_current_trading_day_str
    
    conn = await get_db_connection()
    date_str = get_current_trading_day_str()
    updated = 0
    
    # 오늘 날짜의 5일 배열 로드
    cursor = await conn.execute("""
        SELECT code, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
               day1_high, day2_high, day3_high, day4_high, day5_high
        FROM stock_5d_array
        WHERE date = ?
    """, (date_str,))
    rows = await cursor.fetchall()
    
    for row in rows:
        code = row["code"]
        
        # 5일 평균 거래대금 계산
        amts = [row["day1_amount"], row["day2_amount"], row["day3_amount"], row["day4_amount"], row["day5_amount"]]
        valid_amts = [a for a in amts if a > 0]
        if valid_amts:
            avg_5d = int(sum(valid_amts) / len(valid_amts))
        else:
            avg_5d = 0
        
        # 5일 최고가 계산
        highs = [row["day1_high"], row["day2_high"], row["day3_high"], row["day4_high"], row["day5_high"]]
        valid_highs = [h for h in highs if h > 0]
        high_5d = max(valid_highs) if valid_highs else 0
        
        # master_stocks_table 갱신
        await conn.execute("""
            UPDATE master_stocks_table
            SET avg_5d_trade_amount = ?, high_5d_price = ?
            WHERE code = ?
        """, (avg_5d, high_5d, code))
        updated += 1
    
    await conn.commit()
    _log.info("[Step 3] 5일 메트릭 재계산 완료 -- %d종목", updated)
    return updated


async def _apply_confirmed_to_memory(
    es: ModuleType,
    confirmed: dict[str, dict],
    strength: dict[str, float],
    name_map: dict[str, str] | None = None,
) -> int:
    """확정 데이터를 메모리 캐시에 반영. 0값은 기존 데이터를 덮지 않음.

    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, prev_close}}
        strength: {종목코드: 체결강도 float}
        name_map: {6자리 종목코드: 종목명} — ka10099에서 조회한 매핑. 있으면 모든 엔트리 종목명 갱신.

    Returns:
        반영된 종목 수.
    """
    _nm = name_map or {}
    # _pending_stock_details 제거: _master_stocks_cache 사용
    import backend.app.services.engine_state as _st
    pending: dict = _st._master_stocks_cache
    # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
    ltp: dict = {}
    lta: dict = {}
    lst: dict = {}

    updated = 0

    # SQLite DB에서 한 번에 모든 매핑 조회 (1회 쿼리 수행)
    from backend.app.db.database import get_db_connection
    db_mapping = {}
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()
        await cursor.execute("SELECT code, sector FROM master_stocks_table")
        rows = await cursor.fetchall()
        for r in rows:
            if r["code"] and r["sector"]:
                db_mapping[r["code"]] = r["sector"]
    except Exception as e:
        _log.warning("[메모리 반영] 전체 매핑 DB 조회 실패: %s", e)

    for raw_cd, detail in confirmed.items():
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue

        entry = pending.get(nk)
        if entry is None:
            # 엔트리 없으면 새로 생성
            from backend.app.services.engine_strategy_core import make_detail
            px = int(detail.get("cur_price") or 0)
            stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)
            sec = detail.get("sector")
            if not sec:
                sec = db_mapping.get(_base_stk_cd(raw_cd)) or "기타"
            entry = make_detail(
                nk, stk_nm, px,
                str(detail.get("sign") or "3"),
                int(detail.get("change") or 0),
                float(detail.get("change_rate") or 0.0),
                trade_amount=int(detail.get("trade_amount") or 0),
                sector=sec,
            )
            entry["status"] = "active"
            entry["base_price"] = px
            entry["target_price"] = px
            entry["captured_at"] = ""
            entry["reason"] = "확정 데이터 조회"
            async with es._shared_lock:
                pending[nk] = entry
                # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed" 사용
                if nk in es._master_stocks_cache:
                    es._master_stocks_cache[nk]["_subscribed"] = True
            ltp[nk] = px
            amt = int(detail.get("trade_amount") or 0)
            lta[nk] = amt
            updated += 1
            continue

        entry["status"] = "active"

        # cur_price
        px = int(detail.get("cur_price") or 0)
        entry["cur_price"] = px
        ltp[nk] = px

        # change
        change = int(detail.get("change") or 0)
        entry["change"] = change

        # change_rate
        rate = float(detail.get("change_rate") or 0.0)
        entry["change_rate"] = rate

        # sign
        sign = str(detail.get("sign") or "").strip()
        if sign:
            entry["sign"] = sign

        # trade_amount
        amt = int(detail.get("trade_amount") or 0)
        entry["trade_amount"] = amt
        lta[nk] = amt

        # high_price
        hp = int(detail.get("high_price") or 0)
        entry["high_price"] = hp

        # strength (from separate dict)
        str_val = strength.get(raw_cd) or strength.get(nk)
        if str_val is not None:
            try:
                strength_str = f"{float(str_val):.2f}"
                entry["strength"] = strength_str
                lst[nk] = strength_str
            except (ValueError, TypeError):
                pass

        # name (from name_map)
        mapped_nm = _nm.get(_base_stk_cd(raw_cd))
        if mapped_nm:
            entry["name"] = mapped_nm

        # ── 5일봉 롤링 갱신 제거: stock_5d_array 테이블에서 직접 읽도록 대체 ──

        updated += 1

    _log.info("[타이머] 확정 데이터 메모리 반영 -- %d종목", updated)
    return updated


# ---------------------------------------------------------------------------
# 확정 후 v2 캐시 롤링 파이프라인 (daily_time_scheduler.py에서 이동)
# ---------------------------------------------------------------------------

async def _run_post_confirmed_pipeline(es: ModuleType) -> None:
    """
    ka10081 도입으로 5일 거래대금 및 최고가를 즉시 추출하므로,
    기존의 복잡한 v2 캐시 롤링 갱신 로직은 제거되었습니다.
    단순히 최종 스냅샷 및 캐시를 저장합니다.
    """
    try:
        await _save_confirmed_cache(es)
        _log.info("[타이머] post-confirmed 파이프라인 완료 (롤링 로직 생략)")
    except Exception as exc:
        _log.warning("[타이머] post-confirmed 파이프라인 오류: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 확정 데이터 디스크 캐시 저장
# ---------------------------------------------------------------------------

async def _save_confirmed_cache(
    es: ModuleType,
    skip_codes: set[str] | None = None,
    name_map: dict[str, str] | None = None,
    eligible_codes: set[str] | None = None,
) -> bool:
    """현재 메모리 데이터를 master_stocks_table로 디스크 저장.

    저장 직전에 종목명 캐시를 참조하여 name 필드를 보정한다.
    execute_unified_rolling_and_save가 이미 처리한 종목은 skip_codes로 제외하여 중복 저장 방지.
    eligible_codes가 주어지면 해당 종목만 저장 (confirmed_codes 기반 단일 소스 진리).

    Args:
        es: engine_service 모듈 참조
        skip_codes: execute_unified_rolling_and_save에서 이미 처리한 종목 코드 집합
        eligible_codes: 매매적격 종목 코드 집합 (이 외 종목은 저장하지 않음)

    Returns:
        저장 성공 여부.
    """
    # _pending_stock_details 제거: _master_stocks_cache 사용
    import backend.app.services.engine_state as _st
    pending: dict = _st._master_stocks_cache
    if not pending:
        _log.warning("[타이머] 저장할 데이터(_master_stocks_cache)가 비어있음 — 데이터 저장 생략")
        return False

    # 종목명 보정 제거: _master_stocks_cache에 이미 name 필드 포함됨

    all_target_codes = set(pending.keys())
    # eligible_codes가 주어지면 confirmed_codes 외 종목 저장 방지 (단일 소스 진리)
    if eligible_codes:
        all_target_codes = all_target_codes & eligible_codes

    rows = [
        (cd, dict(detail))
        for cd, detail in pending.items()
        if cd in all_target_codes and detail.get("status") in ("active", "exited")
    ]
    if not rows:
        _log.warning("[타이머] 저장 가능한 종목 없음 — 저장데이터 저장 생략")
        return False

    try:
        # DB 저장 전 avg_5d 유효성 체크
        if sum(1 for stock in pending.values() if int(stock.get("avg_5d_trade_amount", 0) or 0) > 0) < 100:
            _log.warning("[타이머] DB 저장 전 avg_5d_trade_amount 비정상 -- 백그라운드 갱신 예정")

        # ── master_stocks_table 저장 (Phase 1.2) ──
        try:
            from backend.app.db.database import get_db_connection

            conn = await get_db_connection()
            date_str = get_current_trading_day_str()

            # master_stocks_table에서 각 종목의 market 정보 가져오기
            cursor = await conn.execute("SELECT code, market FROM master_stocks_table")
            mkt_rows = await cursor.fetchall()
            mkt_map = {r["code"]: r["market"] for r in mkt_rows}

            # 대상 종목: pending 종목 중 skip_codes 제외 (execute_unified_rolling_and_save에서 이미 처리)
            _skip = skip_codes or set()
            all_target_codes = set(pending.keys()) - _skip

            if not all_target_codes:
                _log.info("[타이머] skip_codes로 인해 저장할 종목 없음 — 저장 생략")
                return True

            for base_cd in all_target_codes:
                detail = pending.get(base_cd) or {}
                cd = base_cd

                stk_nm = detail.get("name")
                if not stk_nm or stk_nm == cd:
                    if name_map:
                        stk_nm = name_map.get(_base_stk_cd(cd), cd)
                    else:
                        stk_nm = cd

                # 당일 고가 추출 (pending detail 또는 cur_price)
                today_high = detail.get("high_price") or detail.get("cur_price") or 0

                # 1) master_stocks_table에 저장 (UPSERT 적용 - 기존 사용자 커스텀 업종 보존)
                await conn.execute("""
                    INSERT INTO master_stocks_table
                    (code, name, market, sector, cur_price, change, change_rate,
                     trade_amount, high_price, avg_5d_trade_amount, high_5d_price, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        market = excluded.market,
                        sector = CASE WHEN master_stocks_table.sector IS NOT NULL AND master_stocks_table.sector != '' AND master_stocks_table.sector != '기타' THEN master_stocks_table.sector ELSE excluded.sector END,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        high_price = excluded.high_price,
                        avg_5d_trade_amount = excluded.avg_5d_trade_amount,
                        high_5d_price = excluded.high_5d_price,
                        date = excluded.date
                """, (
                    cd,
                    stk_nm,
                    mkt_map.get(_base_stk_cd(cd), ""),
                    detail.get("sector", "기타"),
                    detail.get("cur_price", 0),
                    detail.get("change", 0),
                    detail.get("change_rate", 0.0),
                    detail.get("trade_amount", 0),
                    today_high,
                    detail.get("avg_5d_trade_amount", 0),
                    detail.get("high_5d_price", 0),
                    date_str
                ))

            await conn.commit()
            _log.info("[타이머] master_stocks_table 통합 저장 완료 -- %d종목 (date=%s, skip=%d)", len(all_target_codes), date_str, len(_skip))
        except Exception as e:
            if 'conn' in locals():
                await conn.rollback()
            _log.warning("[타이머] DB 저장 실패 (master_stocks_table): %s", e, exc_info=True)

        return True
    except Exception as exc:
        _log.warning("[타이머] 확정 데이터 DB 저장 실패: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 통합 확정 데이터 조회 (20:30)
# ---------------------------------------------------------------------------

async def fetch_unified_confirmed_data(es: ModuleType) -> dict:
    """20:30 통합 확정 조회 — 전종목 대상 ka10099 + ka10081 + 후처리.

    1단계 ka10099: 전종목 목록 갱신 (레이아웃 캐시 + 종목명 캐시 + 신규 종목 섹터 매핑)
    2단계 ka10081: 전종목 확정 시세 순차 호출 (interval_sec=0.33) → 메모리 + 디스크 갱신
       - 이어받기 지원: 20종목마다 진행 저장, 재기동 시 중단 지점부터 계속
    3단계 후처리: 스냅샷 및 캐시 저장 (롤링 갱신 생략)

    Args:
        es: engine_service 모듈 참조

    Returns:
        {"fetched": int, "failed": int, "cached": bool}
    """
    from backend.app.core.broker_factory import get_router
    from backend.app.db.stock_tables import (
        load_progress_cache,
        clear_progress_cache,
    )
    from backend.app.core.trading_calendar import get_kst_today_str

    # 단일 소스 진리: _integrated_system_settings_cache 직접 사용

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running_confirmed", False):
        _log.info("[타이머] 확정 조회 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running_confirmed = True
    es._confirmed_refresh_message = ""

    import backend.app.services.engine_state as _es_state
    _kiwoom_token_registered = False

    try:
        # 0) 캐시 제거로 더 이상 복원 필요 없음 - stock_5d_array 테이블에서 직접 읽도록 대체

        # ── 메모리 전체 초기화 — 새 데이터로 완전 교체 (정합성 보장) ──────────
        # _pending_stock_details 제거: clear() 제거
        # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
        es._integrated_system_settings_cache["sector_stock_layout"] = []
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        _log.info("[타이머] 메모리 전체 초기화 완료 — 새 데이터로 교체 시작")
    
        # 스케줄러 토글 OFF 시 전체 갱신 스킵
        if not es._integrated_system_settings_cache.get("scheduler_market_close_on", True):
            _log.info("[타이머] scheduler_market_close_on=OFF — 전체 갱신 생략")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    


        from backend.app.core.kiwoom_providers import KiwoomStockProvider, KiwoomAuthProvider
        _kiwoom_auth = KiwoomAuthProvider()
        _kiwoom_token = await _kiwoom_auth.get_access_token()
        if _kiwoom_token and "kiwoom" not in _es_state._broker_tokens:
            _es_state._broker_tokens["kiwoom"] = _kiwoom_token
            _kiwoom_token_registered = True
        _sector = KiwoomStockProvider(auth_provider=_kiwoom_auth)

        # ── Pipeline events ──────────────────────────────────────────────────
        data_fetched_event = asyncio.Event()
        parsing_done_event = asyncio.Event()
        filtering_done_event = asyncio.Event()
        save_done_event = asyncio.Event()
    
        # ── Step 1: API 호출 (raw data 수집) ─────────────────────────────────
        _log.info("[타이머] Step 1 시작 — ka10099 전종목 리스트 다운로드 (코스피+코스닥)")
        _broadcast_confirmed_progress(0, 0, message="전종목 목록 갱신 중...", step=1)
        try:
            from backend.app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await _sector.fetch_all_stocks()
            if not records:
                _log.warning("[타이머] ka10099 결과 비어있음 — 통합 확정 조회 중단")
                es._confirmed_refresh_running_confirmed = False
                es._confirmed_refresh_message = ""
                return {"fetched": 0, "failed": 0, "cached": False}
            # marketCode 분포 카운트 ("0"=코스피, "10"=코스닥, 나머지=ETF/ETN 등)
            kospi_count = sum(1 for r in records if r.market_code == "0")
            kosdaq_count = sum(1 for r in records if r.market_code == "10")
            other_count = len(records) - kospi_count - kosdaq_count
            data_fetched_event.set()
            _log.info(
                "[타이머] Step 1 완료 — ka10099 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)",
                len(records), kospi_count, kosdaq_count, other_count
            )
        except Exception as exc:
            _log.warning("[타이머] ka10099 통합 조회 실패: %s", exc, exc_info=True)
            # data_fetched_event 미발행 → Step 2 타임아웃으로 자동 중단
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 2: 적격 종목 필터링 (매매부적격 종목 제외) ─────────────────
        _log.info("[타이머] Step 2 시작 — 적격 종목 필터링 (매매부적격 종목 제외)")
        _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
        try:
            await asyncio.wait_for(data_fetched_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 2 대기 타임아웃 — data_fetched_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            from backend.app.core.stock_filter import is_excluded
            for r in records:
                excluded, reason = is_excluded(r.raw_item, r.code)
                if excluded:
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                else:
                    confirmed_codes.add(r.code)

            excluded_count = len(records) - len(confirmed_codes)
            pct = (excluded_count / len(records) * 100) if records else 0
            _log.info(
                "[타이머] Step 2 완료 — 대상: %d종목, 필터링 통과: %d종목, 제외 사유: %s",
                len(records), len(confirmed_codes), filter_reasons,
            )
            _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {len(records)}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)
            await asyncio.sleep(1.5)

            summary_str = f"전체 {len(records)}종목 → 적격 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct:.1f}%)"
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("[타이머] 주요 부적격 사유 (Top 5): %s", dict(top_reasons))

                reason_strs = []
                for k, v in top_reasons:
                    if "(" in k:
                        k_clean = k.split("(")[-1].replace(")", "")
                    else:
                        k_clean = k.split("=")[-1]
                    reason_strs.append(f"{k_clean} {v}개")
                summary_str += " | 주요 부적격: " + ", ".join(reason_strs)

            es._latest_filter_summary = summary_str

            # DB 캐시 저장
            try:
                from backend.app.core.sector_stock_cache import save_filter_summary_cache
                asyncio.create_task(save_filter_summary_cache(summary_str))
            except Exception as e:
                _log.warning("Failed to save filter summary cache: %s", e)

            try:
                from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
                await broadcast_stock_classification_changed()
            except Exception as e:
                _log.warning("Failed to broadcast filter summary: %s", e)

            filtering_done_event.set()
        except Exception as exc:
            _log.warning("[타이머] Step 2 필터링 실패: %s — filtering_done_event 미발행", exc, exc_info=True)
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── Step 3: 적격 종목만 파싱/매칭 (종목명/시장구분) ───────────────────
        _log.info("[타이머] Step 3 시작 — 적격 종목 파싱 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="종목 정보 파싱 중...", step=3)
        try:
            await asyncio.wait_for(filtering_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 3 대기 타임아웃 — filtering_done_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        try:
            name_map: dict[str, str] = {}
            market_map: dict[str, str] = {}
            for r in records:
                if r.code in confirmed_codes:
                    name_map[r.code] = r.name
                    market_map[r.code] = r.market_code
            parsing_done_event.set()
            _log.info("[타이머] Step 3 완료 — %d종목 파싱/매칭 (종목명/시장구분)", len(name_map))
        except Exception as exc:
            _log.warning("[타이머] Step 3 파싱/매칭 실패: %s — parsing_done_event 미발행", exc, exc_info=True)
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── Step 4: 동일 종목 집합으로 4개 캐시 저장 + 레이아웃 ──────────────
        _log.info("[타이머] Step 4 시작 — 종목명/업종/시장구분 캐시 저장 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="캐시 저장 중...", step=4)
        try:
            await asyncio.wait_for(parsing_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 4 대기 타임아웃 — parsing_done_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        try:
            # eligible_stocks_cache 저장 제거: confirmed_codes가 단일 소스
            # market/nxt_enable 정보를 master_stocks_table에 직접 업데이트 (단일 진실 공급원)
            from backend.app.db.database import get_db_connection as _get_conn
            _conn = await _get_conn()

            if confirmed_codes:
                placeholders = ",".join("?" for _ in confirmed_codes)
                confirmed_codes_list = list(confirmed_codes)

                # 1) 이번 적격 종목(confirmed_codes)에 없는 불필요 종목 DELETE (DB)
                await _conn.execute(
                    f"DELETE FROM master_stocks_table WHERE code NOT IN ({placeholders})",
                    confirmed_codes_list
                )
                await _conn.execute(
                    f"DELETE FROM stock_5d_array WHERE code NOT IN ({placeholders})",
                    confirmed_codes_list
                )
                await _conn.execute(
                    f"DELETE FROM custom_sectors WHERE stock_code IS NOT NULL AND stock_code NOT IN ({placeholders})",
                    confirmed_codes_list
                )

                # 1-1) 신규상장 종목 감지 및 기타 섹터 추가
                cursor = await _conn.execute("SELECT code FROM master_stocks_table")
                existing_codes = set(row[0] for row in await cursor.fetchall())
                new_listed_codes = confirmed_codes - existing_codes

                if new_listed_codes:
                    insert_values = [("기타", code) for code in new_listed_codes]
                    await _conn.executemany(
                        "INSERT INTO custom_sectors (name, stock_code) VALUES (?, ?)",
                        insert_values
                    )

            # 2) Step2 필터링 결과 종목 UPSERT (기존 데이터 보존하며 추가)
            insert_values = [
                (r.code, r.name, r.market_code, 1 if r.nxt_enable else 0)
                for r in records if r.code in confirmed_codes
            ]
            if insert_values:
                await _conn.executemany("""
                    INSERT INTO master_stocks_table (code, name, market, nxt_enable)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        market = excluded.market,
                        nxt_enable = excluded.nxt_enable
                """, insert_values)
                await _conn.commit()

                # 3) 메모리 캐시도 동기화 및 불필요 종목 제거
                import backend.app.services.engine_state as _st
                async with es._shared_lock:
                    keys_to_delete = [cd for cd in list(_st._master_stocks_cache.keys()) if cd not in confirmed_codes]
                    for cd in keys_to_delete:
                        _st._master_stocks_cache.pop(cd, None)

                    for r in records:
                        if r.code in confirmed_codes:
                            if r.code in _st._master_stocks_cache:
                                _st._master_stocks_cache[r.code]["market"] = r.market_code
                                _st._master_stocks_cache[r.code]["nxt_enable"] = bool(r.nxt_enable)
    
            all_codes = list(confirmed_codes)
            await _update_layout_cache(es, all_codes, name_map)
            save_done_event.set()
            _log.info("[타이머] Step 4 완료 — 3개 저장데이터 저장 (%d종목)", len(confirmed_codes))
        except Exception as exc:
            _log.warning("[타이머] Step 4 저장데이터 저장 실패: %s — save_done_event 미발행", exc, exc_info=True)
            # save_done_event 미발행 → 후속 단계 진행 불가
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── 2단계 ka10081: 전종목 확정 시세 순차 호출 (이어받기 지원) ───────
        # 20:30 이전 시간 가드 (Phase 2.1 단계 3)
        from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed
        if not await is_heavy_operation_allowed():
            _log.info("[타이머] 안전 구역(20:30~연결시작전) 외 시간대 진입으로 인한 Step 5 ka10081 전종목 확정 시세 다운로드 스킵")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        _log.info("[타이머] Step 5 시작 — ka10081 전종목 확정 시세 다운로드 (%d종목)", len(all_codes))
        qry_dt = get_kst_today_str()
        total = len(all_codes)
        _main_loop = asyncio.get_running_loop()

        # 사용자 설정의 ws_subscribe_start 시간 확인 (진행 파일 유효 기간용)
        ws_subscribe_start = str(es._integrated_system_settings_cache.get("ws_subscribe_start") or "07:50")

        # 이어받기: 진행 파일 로드 (다음 거래일 ws_subscribe_start까지 유효)
        resume_codes = await load_progress_cache(qry_dt, all_codes, ws_subscribe_start)
        starting_count = len(resume_codes)

        if starting_count > 0:
            _log.info("[타이머] 이어받기 — %d/%d종목부터 계속", starting_count, total)
            _broadcast_confirmed_progress(
                starting_count, total,
                message=f"전종목 확정시세 데이터 다운로드 중 ({starting_count}/{total:,}, {int(starting_count/total*100)}%) - 이어받기",
                step=5
            )
        else:
            _broadcast_confirmed_progress(0, total, message=f"전종목 확정시세 데이터 다운로드 중 (0/{total:,}, 0%)", step=5)

        def _on_progress(cur: int, tot: int) -> None:
            remaining = total - cur
            eta = remaining * 1.0
            _pct = int(cur / total * 100) if total > 0 else 0
            # 중복 로그 제거: kiwoom_stock_rest.py에서 1종목 단위 실시간 로그 출력 중
            _broadcast_confirmed_progress(
                cur, total,
                message=f"전종목 확정시세 데이터 다운로드 중 ({cur:,}/{total:,}, {_pct}%)",
                eta_sec=eta,
                step=5,
                _loop=_main_loop,
            )

        try:
            confirmed = await _sector.fetch_all_stocks_daily_confirmed(
                all_codes, qry_dt, interval_sec=0.33, on_progress=_on_progress,
                resume_codes=resume_codes,  # 이어받기 지원
            )
        except Exception as exc:
            _log.warning("[타이머] ka10081 전종목 조회 실패: %s", exc, exc_info=True)
            confirmed = {}

        fetched = len(confirmed)
        failed = total - fetched
        success_rate = (fetched / total * 100) if total else 0
        _log.info(
            "[타이머] Step 5 완료 — ka10081 확정 시세 다운로드: 성공 %d종목, 실패 %d종목 (%.1f%% 성공)",
            fetched, failed, success_rate
        )
        # 실패율이 1% 이상이면 경고 로그 (디버깅용)
        if failed > 0 and success_rate < 99.0:
            _log.warning(
                "[타이머] ka10081 실패율 높음: %d/%d종목 (%.1f%%) — custom_sector 로그에서 실패 원인 확인",
                failed, total, 100 - success_rate
            )

        # 메모리 반영 (확정시세만)
        if confirmed:
            await _apply_confirmed_to_memory(es, confirmed, {}, name_map=name_map)

        # ── 단일 벌크 트랜잭션으로 5일봉 롤링 및 DB 저장 통합 ──
        if confirmed:
            _log.info("[타이머] 단일 벌크 트랜잭션으로 5일봉 롤링 및 DB 저장 시작")
            await execute_unified_rolling_and_save(es, confirmed, name_map=name_map)
            _log.info("[타이머] 단일 벌크 트랜잭션 완료")

        # custom_sectors 기반 master_stocks_table.sector 동기화
        try:
            from backend.app.core.stock_classification_data import sync_sector_from_custom_sectors
            await sync_sector_from_custom_sectors()
        except Exception as _sync_err:
            _log.warning("[타이머] custom_sectors 기반 동기화 실패: %s", _sync_err, exc_info=True)

        # 디스크 캐시 저장 (execute_unified_rolling_and_save에서 이미 처리한 종목 제외)
        cached = await _save_confirmed_cache(es, skip_codes=set(confirmed.keys()) if confirmed else None, eligible_codes=confirmed_codes)

        # 완료 후 진행 파일 삭제
        if cached:
            await clear_progress_cache()

        # ── 종목분류 페이지 갱신 브로드캐스트 (캐시 갱신 완료 후 전송) ────────
        try:
            from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
            await broadcast_stock_classification_changed()
            _log.info("[타이머] 종목분류 페이지 갱신 브로드캐스트 완료")
        except Exception as _bc_err:
            _log.warning("[타이머] 종목분류 페이지 갱신 브로드캐스트 실패(무시): %s", _bc_err)

        _broadcast_confirmed_progress(total, total, message=f"전종목 확정시세 데이터 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # ── 3단계 후처리: v2 캐시 롤링 (업종순위 재계산 안 함) ────────────────
        _broadcast_confirmed_progress(total, total, message="5일 거래대금 계산 중...", step=5)
        await _run_post_confirmed_pipeline(es)
    
        # ── Step 6: 완전한 매핑 단계 (적격종목 × 시세 데이터 매핑) ────────────
        if cached:
            # eligible_stocks_cache 제거: confirmed_codes가 단일 소스
            final_eligible = confirmed_codes
            if not final_eligible:
                _log.warning("[타이머] Step 6 — 적격종목 비어있음, 메모리 교체 생략")
            else:
                # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed" 필터링
                async with es._shared_lock:
                    to_remove = [cd for cd, entry in es._master_stocks_cache.items() if entry.get("_subscribed", False) and cd not in final_eligible]
                    for cd in to_remove:
                        if cd in es._master_stocks_cache:
                            es._master_stocks_cache[cd].pop("_subscribed", None)

                subscribed_count = sum(1 for entry in es._master_stocks_cache.values() if entry.get("_subscribed", False))
                _log.info(
                    "[타이머] Step 7 원자적 메모리 교체 완료 — subscribed=%d종목",
                    subscribed_count,
                )
        else:
            _log.warning("[타이머] cached=False — 메모리 교체 생략 (기존 상태 유지)")

        # ── 4단계: 업종순위 재계산 + WS 브로드캐스트 (화면 자동 갱신) ────────
        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_scores,
                notify_desktop_sector_stocks_refresh,
            )
            await recompute_sector_summary_now()
            notify_desktop_sector_scores(force=True)
            await notify_desktop_sector_stocks_refresh()
            _log.info("[타이머] 확정 조회 후 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[타이머] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)
            _log.warning("[타이머] 확정 조회 후 실시간 화면전송 실패(무시): %s", _ws_err)

        # 파이프라인 전체 완료 로그
        if cached:
            _log.info(
                "[타이머] === 전체 완료 === 총 %d단계 | ka10099: %d종목 | 적격: %d종목 | ka10081: %d/%d종목 | 저장데이터: %s",
                5, len(all_codes), len(final_eligible) if 'final_eligible' in locals() else 0, fetched, total, "성공"
            )
        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        if _kiwoom_token_registered:
            _es_state._broker_tokens.pop("kiwoom", None)
        es._confirmed_refresh_running_confirmed = False
        es._confirmed_refresh_message = ""


# ---------------------------------------------------------------------------
# 통합 확정 조회 헬퍼
# ---------------------------------------------------------------------------

async def _update_layout_cache(
    es: ModuleType,
    all_codes: list[str],
    name_map: dict[str, str],
) -> None:
    """confirmed_codes 기준으로 레이아웃 캐시를 완전 재구성.

    - 부적격이 된 종목은 레이아웃에서 제거된다.
    - stock_classification.json의 최신 업종 매핑이 전체 종목에 적용된다.
    - 섹터 헤더가 없는 종목("기타")도 레이아웃에 포함된다.
    """
    # sector_layout 캐시 저장 삭제 (master_stocks_table sector 컬럼으로 대체)

    # SQLite DB에서 한 번에 모든 매핑 조회 (1회 쿼리 수행)
    from backend.app.db.database import get_db_connection
    db_mapping = {}
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()
        await cursor.execute("SELECT code, sector FROM master_stocks_table")
        rows = await cursor.fetchall()
        for r in rows:
            if r["code"] and r["sector"]:
                db_mapping[r["code"]] = r["sector"]
    except Exception as e:
        _log.warning("[레이아웃] 전체 매핑 DB 조회 실패: %s", e)

    # 전체 종목을 섹터별로 그룹핑 (stock_classification.json 최신 매핑 적용)
    sector_groups: dict[str, list[str]] = {}
    for cd in all_codes:
        # _pending_stock_details 제거: _master_stocks_cache 사용
        sec = None
        import backend.app.services.engine_state as _st
        entry = _st._master_stocks_cache.get(cd)
        if entry and "sector" in entry:
            sec = entry["sector"]
        # 2) DB 매핑 확인
        if not sec:
            sec = db_mapping.get(_base_stk_cd(cd))
        # 3) 기본값
        if not sec:
            sec = "기타"

        sector_groups.setdefault(sec, []).append(cd)

    # 섹터 내 종목 정렬 (재현성 보장)
    for sec in sector_groups:
        sector_groups[sec].sort()

    # 섹터 순서: 기존 레이아웃의 섹터 순서를 최대한 유지하고 신규 섹터는 뒤에 추가
    # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
    old_layout: list[tuple[str, str]] = es._integrated_system_settings_cache.get("sector_stock_layout", [])
    old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))

    new_sectors = [s for s in sector_groups if s not in old_sector_order]
    final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

    # 레이아웃 재구성
    new_layout: list[tuple[str, str]] = []
    for sec in final_sector_order:
        new_layout.append(("sector", sec))
        for cd in sector_groups[sec]:
            new_layout.append(("code", cd))

    # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
    es._integrated_system_settings_cache["sector_stock_layout"] = new_layout
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache(new_layout)
    # sector_layout 캐시 저장 삭제 (master_stocks_table sector 컬럼으로 대체)
    _log.info(
        "[타이머] 레이아웃 저장데이터 완전 재구성 — %d종목, %d업종",
        len(all_codes), len(final_sector_order),
    )


# ---------------------------------------------------------------------------
# 수동 확정시세 및 5일봉 다운로드
# ---------------------------------------------------------------------------

async def fetch_confirmed_data_only() -> dict:
    """수동 매매적격종목 확정시세 다운로드 파이프라인.
    
    진행 과정 (Step 1 ~ Step 5) 및 브로드캐스트를 지원하며,
    다운로드 완료 시 5일봉 배열 롤링 갱신을 적용하고 DB에 저장합니다.
    """
    from backend.app.services import engine_service as es
    from backend.app.core.broker_factory import get_router
    from backend.app.db.stock_tables import (
        load_progress_cache,
        clear_progress_cache,
    )
    from backend.app.core.trading_calendar import get_kst_today_str

    # 단일 소스 진리: _integrated_system_settings_cache 직접 사용

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running_confirmed", False):
        _log.info("[수동 확정시세] 다운로드 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running_confirmed = True
    es._confirmed_refresh_message = ""

    import backend.app.services.engine_state as _es_state
    _kiwoom_token_registered = False

    try:
        # ── 메모리 전체 초기화 — 새 데이터로 완전 교체 (정합성 보장) ──────────
        # _pending_stock_details 제거: clear() 제거
        # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
        es._integrated_system_settings_cache["sector_stock_layout"] = []
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        # _avg_amt_5d 제거: _master_stocks_cache에서 직접 사용
        # _high_5d_cache 제거: _master_stocks_cache의 high_5d_price 사용
        _log.info("[수동 확정시세] 메모리 전체 초기화 완료 — 새 데이터로 교체 시작")



        from backend.app.core.kiwoom_providers import KiwoomStockProvider, KiwoomAuthProvider
        _kiwoom_auth = KiwoomAuthProvider()
        _kiwoom_token = await _kiwoom_auth.get_access_token()
        if _kiwoom_token and "kiwoom" not in _es_state._broker_tokens:
            _es_state._broker_tokens["kiwoom"] = _kiwoom_token
            _kiwoom_token_registered = True
        _sector = KiwoomStockProvider(auth_provider=_kiwoom_auth)

        # ── Pipeline events ──────────────────────────────────────────────────
        data_fetched_event = asyncio.Event()
        parsing_done_event = asyncio.Event()
        filtering_done_event = asyncio.Event()
        save_done_event = asyncio.Event()

        # ── Step 1: API 호출 (raw data 수집) ─────────────────────────────────
        _log.info("[수동 확정시세] Step 1 시작 — ka10099 전종목 리스트 다운로드 (코스피+코스닥)")
        _broadcast_confirmed_progress(0, 0, message="1단계: 코스피/코스닥 전종목 목록 수집 중...", step=1)
        try:
            from backend.app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await _sector.fetch_all_stocks()
            if not records:
                _log.warning("[수동 확정시세] 전종목 목록 수집 결과 비어있음 — 중단")
                es._confirmed_refresh_running_confirmed = False
                es._confirmed_refresh_message = ""
                return {"fetched": 0, "failed": 0, "cached": False}
            kospi_count = sum(1 for r in records if r.market_code == "0")
            kosdaq_count = sum(1 for r in records if r.market_code == "10")
            other_count = len(records) - kospi_count - kosdaq_count
            data_fetched_event.set()
            _log.info(
                "[수동 확정시세] Step 1 완료 — ka10099 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)",
                len(records), kospi_count, kosdaq_count, other_count
            )
        except Exception as exc:
            _log.warning("[수동 확정시세] ka10099 통합 조회 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 2: 적격 종목 필터링 (매매부적격 종목 제외) ─────────────────
        _log.info("[수동 확정시세] Step 2 시작 — 적격 종목 필터링")
        _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
        try:
            await asyncio.wait_for(data_fetched_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 확정시세] Step 2 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            from backend.app.core.stock_filter import is_excluded
            for r in records:
                excluded, reason = is_excluded(r.raw_item, r.code)
                if excluded:
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                else:
                    confirmed_codes.add(r.code)

            excluded_count = len(records) - len(confirmed_codes)
            pct = (excluded_count / len(records) * 100) if records else 0
            _log.info(
                "[수동 확정시세] Step 2 완료 — 대상: %d종목, 필터링 통과: %d종목, 제외 사유: %s",
                len(records), len(confirmed_codes), filter_reasons,
            )
            _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {len(records)}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)
            await asyncio.sleep(1.5)

            summary_str = f"전체 {len(records)}종목 → 적격 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct:.1f}%)"
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("[수동 확정시세] 주요 부적격 사유 (Top 5): %s", dict(top_reasons))

                reason_strs = []
                for k, v in top_reasons:
                    if "(" in k:
                        k_clean = k.split("(")[-1].replace(")", "")
                    else:
                        k_clean = k.split("=")[-1]
                    reason_strs.append(f"{k_clean} {v}개")
                summary_str += " | 주요 부적격: " + ", ".join(reason_strs)

            es._latest_filter_summary = summary_str

            # DB 캐시 저장
            try:
                from backend.app.core.sector_stock_cache import save_filter_summary_cache
                asyncio.create_task(save_filter_summary_cache(summary_str))
            except Exception as e:
                _log.warning("Failed to save filter summary cache: %s", e)

            try:
                from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
                await broadcast_stock_classification_changed()
            except Exception as e:
                _log.warning("Failed to broadcast filter summary: %s", e)

            filtering_done_event.set()
        except Exception as exc:
            _log.warning("[수동 확정시세] Step 2 필터링 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 3: 적격 종목만 파싱/매칭 (종목명/시장구분) ───────────────────
        _log.info("[수동 확정시세] Step 3 시작 — 적격 종목 파싱 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="3단계: 종목 정보 파싱 중...", step=3)
        try:
            await asyncio.wait_for(filtering_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 확정시세] Step 3 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            name_map: dict[str, str] = {}
            market_map: dict[str, str] = {}
            for r in records:
                if r.code in confirmed_codes:
                    name_map[r.code] = r.name
                    market_map[r.code] = r.market_code
            parsing_done_event.set()
            _log.info("[수동 확정시세] Step 3 완료 — %d종목 파싱/매칭 완료", len(name_map))
        except Exception as exc:
            _log.warning("[수동 확정시세] Step 3 파싱/매칭 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 4: 동일 종목 집합으로 4개 캐시 저장 + 레이아웃 ──────────────
        _log.info("[수동 확정시세] Step 4 시작 — 종목명/업종/시장구분 캐시 저장 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="4단계: 디스크 캐시 저장 중...", step=4)
        try:
            await asyncio.wait_for(parsing_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 확정시세] Step 4 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            # eligible_stocks_cache 저장 제거: confirmed_codes가 단일 소스
            # master_stocks_table 스냅샷 구조로 변경: DELETE 후 INSERT
            from backend.app.db.database import get_db_connection as _get_conn, get_db_lock
            _conn = await _get_conn()

            placeholders = ",".join("?" for _ in confirmed_codes)
            confirmed_codes_list = list(confirmed_codes)

            async with get_db_lock():
                # 1) master_stocks_table 전체 DELETE (실행 전 row count 로그)
                cursor = await _conn.execute("SELECT COUNT(*) FROM master_stocks_table")
                before_count = (await cursor.fetchone())[0]
                _log.info("[수동 확정시세] Step4 — master_stocks_table 초기화 전 row count: %d", before_count)
                await _conn.execute("DELETE FROM master_stocks_table")

                # 2) custom_sectors 유령 종목 DELETE (정합성 동기화)
                await _conn.execute(
                    f"DELETE FROM custom_sectors WHERE stock_code IS NOT NULL AND stock_code NOT IN ({placeholders})",
                    confirmed_codes_list
                )

                # 3) Step2 필터링 결과 종목만 INSERT
                insert_values = [
                    (r.code, r.name, r.market_code, 1 if r.nxt_enable else 0)
                    for r in records if r.code in confirmed_codes
                ]
                if insert_values:
                    await _conn.executemany(
                        "INSERT INTO master_stocks_table (code, name, market, nxt_enable) VALUES (?, ?, ?, ?)",
                        insert_values
                    )
                await _conn.commit()

            # 3) 실행 후 row count 로그
            cursor = await _conn.execute("SELECT COUNT(*) FROM master_stocks_table")
            after_count = (await cursor.fetchone())[0]
            _log.info("[수동 확정시세] Step4 — master_stocks_table 초기화 후 row count: %d", after_count)

            # 메모리 캐시 업데이트
            import backend.app.services.engine_state as _st
            for r in records:
                if r.code in confirmed_codes and r.code in _st._master_stocks_cache:
                    _st._master_stocks_cache[r.code]["market"] = r.market_code
                    _st._master_stocks_cache[r.code]["nxt_enable"] = bool(r.nxt_enable)

            all_codes = list(confirmed_codes)
            await _update_layout_cache(es, all_codes, name_map)
            save_done_event.set()
            _log.info("[수동 확정시세] Step 4 완료 — 저장데이터 저장 완료 (%d종목)", len(confirmed_codes))
        except Exception as exc:
            _log.warning("[수동 확정시세] Step 4 저장데이터 저장 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running_confirmed = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 5: 개별 확정 시세 다운로드 ───────
        _log.info("[수동 확정시세] Step 5 시작 — 전종목 확정 시세 다운로드 (%d종목)", len(all_codes))
        qry_dt = get_kst_today_str()
        total = len(all_codes)
        _main_loop = asyncio.get_running_loop()

        # 이어받기
        ws_subscribe_start = str(es._integrated_system_settings_cache.get("ws_subscribe_start") or "07:50")
        resume_codes = await load_progress_cache(qry_dt, all_codes, ws_subscribe_start)
        starting_count = len(resume_codes)

        if starting_count > 0:
            _log.info("[수동 확정시세] 이어받기 — %d/%d종목부터 계속", starting_count, total)
            _broadcast_confirmed_progress(
                starting_count, total,
                message=f"5단계: 개별 확정시세 데이터 다운로드 중 ({starting_count}/{total:,}, {int(starting_count/total*100)}%) - 이어받기",
                step=5
            )
        else:
            _broadcast_confirmed_progress(0, total, message=f"5단계: 개별 확정시세 데이터 다운로드 중 (0/{total:,}, 0%)", step=5)

        def _on_progress(cur: int, tot: int) -> None:
            remaining = total - cur
            eta = remaining * 1.0
            _pct = int(cur / total * 100) if total > 0 else 0
            # 중복 로그 제거: kiwoom_stock_rest.py에서 1종목 단위 실시간 로그 출력 중
            _broadcast_confirmed_progress(
                cur, total,
                message=f"5단계: 개별 확정시세 데이터 다운로드 중 ({cur:,}/{total:,}, {_pct}%)",
                eta_sec=eta,
                step=5,
                _loop=_main_loop,
            )

        try:
            confirmed = await _sector.fetch_all_stocks_daily_confirmed(
                all_codes, qry_dt, interval_sec=0.33, on_progress=_on_progress,
                resume_codes=resume_codes,
            )
        except Exception as exc:
            _log.warning("[수동 확정시세] ka10081 전종목 조회 실패: %s", exc, exc_info=True)
            confirmed = {}

        fetched = len(confirmed)
        failed = total - fetched
        success_rate = (fetched / total * 100) if total else 0
        _log.info(
            "[수동 확정시세] Step 5 완료 — ka10081 확정 시세 다운로드: 성공 %d종목, 실패 %d종목 (%.1f%% 성공)",
            fetched, failed, success_rate
        )

        # 메모리 반영 (확정시세 반영 + 5일 배열 롤링)
        if confirmed:
            normalized_confirmed = {}
            for cd, val in confirmed.items():
                normalized_confirmed[cd] = {
                    "cur_price": val.get("close") or val.get("cur_price") or 0,
                    "trade_amount": val.get("value") or val.get("trade_amount") or 0,
                    "high_price": val.get("high") or val.get("high_price") or 0,
                    "volume": val.get("volume") or 0,
                    "change": val.get("change") or 0,
                    "change_rate": val.get("rate") or val.get("change_rate") or 0.0,
                    "sign": val.get("sign") or "3",
                }
            await _apply_confirmed_to_memory(es, normalized_confirmed, {}, name_map=name_map)

        # ── 단일 벌크 트랜잭션으로 5일봉 롤링 및 DB 저장 통합 ──
        if confirmed:
            _log.info("[수동 확정시세] 단일 벌크 트랜잭션으로 5일봉 롤링 및 DB 저장 시작")
            await execute_unified_rolling_and_save(es, normalized_confirmed, name_map=name_map)
            _log.info("[수동 확정시세] 단일 벌크 트랜잭션 완료")

        # 디스크 캐시 저장 (execute_unified_rolling_and_save에서 이미 처리한 종목 제외)
        cached = await _save_confirmed_cache(es, skip_codes=set(confirmed.keys()) if confirmed else None, eligible_codes=confirmed_codes)

        # 완료 후 진행 파일 삭제
        if cached:
            await clear_progress_cache()

        # ── 종목분류 페이지 갱신 브로드캐스트 (캐시 갱신 완료 후 전송) ────────
        try:
            from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
            await broadcast_stock_classification_changed()
            _log.info("[수동 확정시세] 종목분류 페이지 갱신 브로드캐스트 완료")
        except Exception as _bc_err:
            _log.warning("[수동 확정시세] 종목분류 페이지 갱신 브로드캐스트 실패(무시): %s", _bc_err)

        _broadcast_confirmed_progress(total, total, message=f"✅ 확정시세 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # 후처리
        await _run_post_confirmed_pipeline(es)
    
        # Step 6/7/8: 원자적 메모리 교체 및 업종순위 재계산
        if cached:
            # eligible_stocks_cache 제거: confirmed_codes가 단일 소스
            final_eligible = confirmed_codes
            if final_eligible:
                mapped_pending: dict = {}
                # _pending_stock_details 제거: _radar_cnsr_order만 필터링
                import backend.app.services.engine_state as _st
                new_avg = {cd: _st._master_stocks_cache[cd].get("avg_5d_trade_amount", 0) for cd in final_eligible if cd in _st._master_stocks_cache}
                # _high_5d_cache 제거: _master_stocks_cache의 high_5d_price 사용

                async with es._shared_lock:
                    # _master_stocks_cache에서 직접 업데이트
                    for cd, v in new_avg.items():
                        if cd in _st._master_stocks_cache:
                            _st._master_stocks_cache[cd]["avg_5d_trade_amount"] = v
                    # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed" 필터링
                    to_remove = [cd for cd, entry in es._master_stocks_cache.items() if entry.get("_subscribed", False) and cd not in final_eligible]
                    for cd in to_remove:
                        if cd in es._master_stocks_cache:
                            es._master_stocks_cache[cd].pop("_subscribed", None)

                _log.info(
                    "[수동 확정시세] Step 7 원자적 메모리 교체 완료 — pending=%d종목, avg=%d",
                    len(mapped_pending), len(new_avg),
                )

        # custom_sectors 기반 master_stocks_table.sector 동기화
        try:
            from backend.app.core.stock_classification_data import sync_sector_from_custom_sectors
            await sync_sector_from_custom_sectors()
        except Exception as _sync_err:
            _log.warning("[수동 확정시세] custom_sectors 기반 동기화 실패: %s", _sync_err, exc_info=True)

        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_scores,
                notify_desktop_sector_stocks_refresh,
            )
            await recompute_sector_summary_now()
            notify_desktop_sector_scores(force=True)
            await notify_desktop_sector_stocks_refresh()
            _log.info("[수동 확정시세] 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[수동 확정시세] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)

        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        if _kiwoom_token_registered:
            _es_state._broker_tokens.pop("kiwoom", None)
        es._confirmed_refresh_running_confirmed = False
        es._confirmed_refresh_message = ""


async def fetch_5d_data_only() -> dict:
    """수동 5일봉 거래대금,고가 다운로드 파이프라인.
    
    DB의 master_stocks_table에 등록된 매매적격종목을 대상으로
    개별 종목의 5일 고가 및 거래대금 데이터를 다운로드하여 DB 및 메모리에 저장합니다.
    """
    from backend.app.services import engine_service as es
    from backend.app.core.broker_factory import get_router
    from backend.app.core.trading_calendar import get_kst_today_str, get_current_trading_day_str

    # 단일 소스 진리: _integrated_system_settings_cache 직접 사용

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running_5d", False):
        _log.info("[수동 5일봉] 다운로드 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running_5d = True
    es._confirmed_refresh_message = ""

    import backend.app.services.engine_state as _es_state
    _kiwoom_token_registered = False

    try:
        from backend.app.core.kiwoom_providers import KiwoomStockProvider, KiwoomAuthProvider
        _kiwoom_auth = KiwoomAuthProvider()
        _kiwoom_token = await _kiwoom_auth.get_access_token()
        if _kiwoom_token and "kiwoom" not in _es_state._broker_tokens:
            _es_state._broker_tokens["kiwoom"] = _kiwoom_token
            _kiwoom_token_registered = True
        _sector = KiwoomStockProvider(auth_provider=_kiwoom_auth)

        # ── DB에서 매매적격종목 코드 리스트 직접 로드 ──────────────────────────
        _log.info("[수동 5일봉] master_stocks_table에서 매매적격종목 목록 로드 시작")
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT code FROM master_stocks_table")
        rows = await cursor.fetchall()
        all_codes = [r["code"] for r in rows]
        total = len(all_codes)
        
        _log.info("[수동 5일봉] 대상 적격 종목 수: %d", total)
        if total == 0:
            _log.warning("[수동 5일봉] 대상 종목 없음 — 중단")
            es._confirmed_refresh_running_5d = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 5: 개별 5일봉 데이터 다운로드 ───────
        _log.info("[수동 5일봉] Step 5 시작 — 개별 5일봉 다운로드 (%d종목)", total)
        _broadcast_confirmed_progress(0, total, message=f"5단계: 개별 5일봉 데이터 다운로드 중 (0/{total:,}, 0%)", step=5)

        # stock_5d_array 전체 삭제 (수동 다운로드는 무조건 재다운로드)
        # master_stocks_table과 데이터 정합성 보장을 위해 전체 삭제 후 재구성
        try:
            from backend.app.db.database import get_db_lock
            async with get_db_lock():
                await conn.execute("DELETE FROM stock_5d_array")
                await conn.commit()
            _log.info("[수동 5일봉] stock_5d_array 전체 삭제 후 재다운로드")
        except Exception as e:
            _log.warning("[수동 5일봉] 전체 데이터 삭제 실패: %s", e)

        downloaded_codes = set()  # 빈 세트로 초기화 (이어받기 비활성화)
        # 전체 삭제로 변경했으므로 이어받기 로직 제거

        fetched = 0
        failed = 0
        skipped = 0
        
        # 20종목마다 저장을 위한 임시 버퍼
        pending_5d_save: dict[str, tuple[list[int], list[int]]] = {}
        
        def _compute_avg_from_5d_array(amts: list[int]) -> int:
            """불완전 배열의 평균 계산 (0 값 제외)"""
            valid_amts = [a for a in amts if a > 0]
            if not valid_amts:
                return 0
            return sum(valid_amts) // len(valid_amts)
        
        async def _save_5d_array_batch(buffer: dict[str, tuple[list[int], list[int]]]) -> None:
            """5일봉 데이터 배치 저장 (20종목마다 호출)"""
            if not buffer:
                return
            
            try:
                from backend.app.db.database import get_db_lock
                date_str = get_current_trading_day_str()
                
                async with get_db_lock():
                    for cd, (amts_5d, highs_5d) in buffer.items():
                        # 빈 배열(0개)은 저장하지 않음
                        if not amts_5d or not highs_5d:
                            _log.warning("[수동 5일봉] 빈 데이터 — 저장 건너뜀: %s", cd)
                            continue
                        
                        # 있는 배열만큼만 채움 (신규 종목 지원)
                        day1_amt = amts_5d[0] if len(amts_5d) > 0 else 0
                        day2_amt = amts_5d[1] if len(amts_5d) > 1 else 0
                        day3_amt = amts_5d[2] if len(amts_5d) > 2 else 0
                        day4_amt = amts_5d[3] if len(amts_5d) > 3 else 0
                        day5_amt = amts_5d[4] if len(amts_5d) > 4 else 0
                        
                        day1_high = highs_5d[0] if len(highs_5d) > 0 else 0
                        day2_high = highs_5d[1] if len(highs_5d) > 1 else 0
                        day3_high = highs_5d[2] if len(highs_5d) > 2 else 0
                        day4_high = highs_5d[3] if len(highs_5d) > 3 else 0
                        day5_high = highs_5d[4] if len(highs_5d) > 4 else 0
                        
                        # stock_5d_array에 원본 데이터 저장
                        await conn.execute("""
                            INSERT OR REPLACE INTO stock_5d_array
                            (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                             day1_high, day2_high, day3_high, day4_high, day5_high)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            cd, date_str,
                            day1_amt, day2_amt, day3_amt, day4_amt, day5_amt,
                            day1_high, day2_high, day3_high, day4_high, day5_high
                        ))
                        
                        # master_stocks_table에 계산값 업데이트
                        avg5d = _compute_avg_from_5d_array(amts_5d)
                        high5d = max(highs_5d) if highs_5d else 0
                        
                        await conn.execute("""
                            UPDATE master_stocks_table
                            SET avg_5d_trade_amount = ?, high_5d_price = ?
                            WHERE code = ?
                        """, (avg5d, high5d, cd))
                    
                    await conn.commit()
                _log.info("[수동 5일봉] 배치 저장 완료 — %d종목 (stock_5d_array + master_stocks_table)", len(buffer))
            except Exception as e:
                _log.warning("[수동 5일봉] 배치 저장 실패: %s", e, exc_info=True)

        for idx, base_cd in enumerate(all_codes):
            # 중단 요청 확인
            if not getattr(es, "_confirmed_refresh_running_5d", True):
                _log.info("[수동 5일봉] 중단 요청 수신 — 다운로드 중단")
                break

            nk = _format_kiwoom_reg_stk_cd(base_cd)
            if not nk:
                failed += 1
                continue

            try:
                # 5일치 고가(high)와 거래대금(value) 다운로드
                qry_dt = get_kst_today_str()
                res = await _sector.fetch_stock_5day_data(base_cd, qry_dt)
                amounts_5d = res.get("amts_5d_array") or [] if res else []
                highs_5d = res.get("highs_5d_array") or [] if res else []

                if amounts_5d and highs_5d and len(amounts_5d) > 0 and len(highs_5d) > 0:
                    # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed"에 추가
                    import backend.app.services.engine_state as _st
                    if nk in _st._master_stocks_cache:
                        _st._master_stocks_cache[nk]["_subscribed"] = True

                    # 메모리 캐시 제거: stock_5d_array 테이블에 직접 저장
                    avg5d = _compute_avg_from_5d_array(amounts_5d)
                    high5d = max(highs_5d)

                    import backend.app.services.engine_state as _st
                    if nk in _st._master_stocks_cache:
                        _st._master_stocks_cache[nk]["status"] = "active"
                        if avg5d > 0:
                            _st._master_stocks_cache[nk]["avg_5d_trade_amount"] = avg5d
                        if high5d > 0:
                            _st._master_stocks_cache[nk]["high_5d_price"] = high5d

                    # 배치 저장 버퍼에 추가
                    pending_5d_save[nk] = (amounts_5d, highs_5d)

                    fetched += 1
                    _log.info("[ka10081] 적격종목 5일봉 다운로드 완료 [%d/%d] %s", idx + 1, total, base_cd)
                else:
                    failed += 1
                    _log.warning("[ka10081] 적격종목 5일봉 데이터 비어있음 [%d/%d] %s", idx + 1, total, base_cd)

            except Exception as e:
                failed += 1
                _log.warning("[ka10081] 적격종목 5일봉 예외 발생 [%d/%d] %s: %s", idx + 1, total, base_cd, e)

            # 진행률 브로드캐스트 (10종목 단위 스로틀링)
            if (idx + 1) % 10 == 0 or (idx + 1) == total:
                pct = int((idx + 1) / total * 100)
                remaining = total - (idx + 1)
                eta = remaining * 0.33
                _broadcast_confirmed_progress(
                    idx + 1, total,
                    message=f"5단계: 개별 5일봉 데이터 다운로드 중 ({idx + 1:,}/{total:,}, {pct}%)",
                    eta_sec=eta,
                    step=5
                )

            # 20종목마다 배치 저장
            if len(pending_5d_save) >= 20:
                await _save_5d_array_batch(pending_5d_save)
                pending_5d_save.clear()

            # Rate limiting
            await asyncio.sleep(0.33)

        # 루프 종료 후 남은 버퍼 저장 (중단 시에도 보장)
        if pending_5d_save:
            await _save_5d_array_batch(pending_5d_save)
            pending_5d_save.clear()

        success_rate = (fetched / total * 100) if total else 0
        _log.info("[수동 5일봉] Step 5 완료 — 성공 %d종목, 실패 %d종목, 건너뜀 %d종목 (%.1f%% 성공)", fetched, failed, skipped, success_rate)

        # 디스크 캐시 저장 (name_map=None 명시)
        cached = await _save_confirmed_cache(es, name_map=None)

        _broadcast_confirmed_progress(total, total, message=f"✅ 5일봉 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # 후처리 및 업종순위 재계산
        await _run_post_confirmed_pipeline(es)

        # custom_sectors 기반 master_stocks_table.sector 동기화
        try:
            from backend.app.core.stock_classification_data import sync_sector_from_custom_sectors
            await sync_sector_from_custom_sectors()
        except Exception as _sync_err:
            _log.warning("[수동 5일봉] custom_sectors 기반 동기화 실패: %s", _sync_err, exc_info=True)

        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_scores,
                notify_desktop_sector_stocks_refresh,
            )
            await recompute_sector_summary_now()
            notify_desktop_sector_scores(force=True)
            await notify_desktop_sector_stocks_refresh()
            _log.info("[수동 5일봉] 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[수동 5일봉] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)

        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        if _kiwoom_token_registered:
            _es_state._broker_tokens.pop("kiwoom", None)
        es._confirmed_refresh_running_5d = False
        es._confirmed_refresh_message = ""




async def _restore_5d_arrays_from_db(es: ModuleType):
    """캐시 제거로 더 이상 사용하지 않음 - stock_5d_array 테이블에서 직접 읽도록 대체."""
    pass
