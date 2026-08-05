# -*- coding: utf-8 -*-
"""장마감 확정데이터 저장 전담 모듈 — 단일 트랜잭션 경계.

저장만 담당한다. 메모리 반영(``master_stocks_cache`` 갱신)·업종 계산·화면 전송은
호출자(``market_close_pipeline``)가 저장 성공 후 순서대로 호출한다 (설계 5.4).

계약 (설계 4.3 · 태스크 세션 2):
- 성공·검증 완료 집합 전체를 하나의 트랜잭션으로 저장
- 저장 중 오류 발생 시 전체 롤백
- 저장 성공 결과(파생값 포함)를 호출자에게 반환
- 저장 실패를 성공으로 바꾸는 빈값 대체 금지 (P20)

관련 원칙: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P22(데이터 정합성) · P24(단순성)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date

from backend.app.core.trading_calendar import (
    get_current_trading_day_str,
    get_recent_trading_days,
)
from backend.app.db.database import get_db_connection, get_db_lock
from backend.app.services.engine_symbol_utils import _base_stk_cd
from backend.app.services.market_close_calc import (
    compute_5d_derived,
    verify_5d_completeness,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 반환 구조 — 저장 성공 결과 + 파생값
# ---------------------------------------------------------------------------

def _empty_result() -> dict:
    """저장 실패/입력 없음 결과 — 빈 파생값 (P20 폴백 금지, 빈값을 성공으로 위장 금지)."""
    return {"success": False, "saved_codes": [], "derived": {}}


def _expected_5d_days(qry_dt: str) -> list[str]:
    """qry_dt 기준 최근 5거래일 리스트 반환 (YYYYMMDD 문자열, 오래된 순 — 설계서 4.5, 세션 4).

    자동 일봉·수동 5일 경로가 같은 예상 거래일 기준을 사용한다 (설계서 4.5).
    """
    if not qry_dt:
        return []
    qry_date = _date(int(qry_dt[:4]), int(qry_dt[4:6]), int(qry_dt[6:8]))
    recent_5 = get_recent_trading_days(5, from_date=qry_date)
    return [d.strftime("%Y%m%d") for d in recent_5]


# ---------------------------------------------------------------------------
# 5일 보관 정책 — qry_dt 기준 최근 5거래일 외 행 정리 (설계 7, P22/P24)
# ---------------------------------------------------------------------------
# 자동 일봉·수동 5일이 같은 보관 규칙을 사용하도록 통합 (설계 7, 세션 4).
# - 최근 확정 거래일(qry_dt) 기준 최근 5거래일 원본만 보존
# - 기준일보다 미래인 자료(미확정 당일) 삭제
# - 오래된 자료(5거래일 이전) 삭제 — 자동 경로에 빠져 있던 과거 정리 채움
# - 저장 트랜잭션 안에서 수행 (설계 7, 태스크 세션 4)

async def _prune_5d_bars(conn, qry_dt: str) -> None:
    """qry_dt 기준 최근 5거래일 외 행(과거·미래)을 정리 (설계 7, P22/P24).

    자동 일봉(``save_daily_confirmed``)·수동 5일(``save_5d_bars``) 모두 본 함수로
    보관 정책을 통일한다 (세션 4 — 기존 자동 경로는 미래 행만 지우고 과거 정리가 누락됨).

    Args:
        conn: 트랜잭션 진행 중인 aiosqlite 연결.
        qry_dt: 가장 최근 확정된 거래일 (YYYYMMDD). 보관 기준.
    """
    if not qry_dt:
        return
    qry_date = _date(int(qry_dt[:4]), int(qry_dt[4:6]), int(qry_dt[6:8]))
    recent_5 = get_recent_trading_days(5, from_date=qry_date)
    if not recent_5:
        return
    oldest_dt = recent_5[0].strftime("%Y%m%d")
    await conn.execute(
        "DELETE FROM stock_5d_bars WHERE dt < ? OR dt > ?",
        (oldest_dt, qry_dt),
    )


# ---------------------------------------------------------------------------
# 자동 일봉 확정시세 저장 — 단일 트랜잭션
# ---------------------------------------------------------------------------

async def save_daily_confirmed(
    confirmed: dict[str, dict],
    *,
    qry_dt: str = "",
    name_map: dict[str, str] | None = None,
) -> dict:
    """자동 일봉 확정시세 단일 트랜잭션 저장.

    거래일별 일봉 원본(``stock_5d_bars``) + 마스터 확정시세(``master_stocks_table``) +
    5일 파생값(평균 거래대금·최고가) + 보관 정리를 하나의 트랜잭션으로 처리.

    메모리 캐시(``master_stocks_cache``)를 직접 갱신하지 않는다 (설계 5.4).
    파생값은 반환값 ``derived`` 로 전달하며, 호출자가 저장 성공 후 메모리에 반영한다.

    Args:
        confirmed: {종목코드: {dt, cur_price, change, change_rate, trade_amount, high_price}}
        qry_dt: API 조회일 (YYYYMMDD) = 가장 최근 확정된 거래일.
            ``stock_5d_bars.dt`` 및 ``master_stocks_table.date`` 기준 (P10/P22).
        name_map: {6자리 종목코드: 종목명} — 종목명 보정용.

    Returns:
        ``{"success": bool, "saved_codes": list[str], "derived": {code: (avg_5d, high_5d)}}``.
        실패 시 ``success=False`` 와 빈 파생값.
    """
    # date_str = "데이터 기준일" — qry_dt 우선 (P10/P22).
    # qry_dt는 항상 직전 거래일이므로, 장 전/장 후 실행 모두 date=직전 거래일.
    # retry_pipeline_catchup_after_bootstrap 스킵 판단도 동일 기준(직전 거래일)으로 비교 (P10 SSOT).
    date_str = qry_dt or get_current_trading_day_str()
    _nm = name_map or {}

    if not date_str:
        logger.warning("[데이터] 저장 실패 — 현재 거래일 확인 불가 (P20 폴백 금지)")
        return _empty_result()

    if not confirmed:
        logger.info("[데이터] 저장 입력 없음 — 트랜잭션 생략")
        return _empty_result()

    master_bulk_params: list[tuple] = []
    bars_bulk_params: list[tuple] = []
    codes_to_recalc: list[str] = []

    for raw_cd, detail in confirmed.items():
        nk = _base_stk_cd(raw_cd)
        if not nk:
            continue

        # 당일 데이터 추출
        today_amt = int(detail["trade_amount"]) if detail.get("trade_amount") is not None else None
        today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)
        cur_price = int(detail.get("cur_price") or 0)
        change = int(detail.get("change") or 0)
        change_rate = float(detail["change_rate"]) if detail.get("change_rate") is not None else None

        # stock_5d_bars.dt는 API가 반환한 일봉의 실제 거래일을 우선 사용 (P10/P22)
        # 장마감 전 실행 시 API가 어제 일봉을 latest로 반환하므로, 달력 오늘(qry_dt)을 dt로 쓰면
        # 어제 값을 오늘 행으로 기록하는 중복이 발생함.
        bar_dt = str(detail.get("dt") or "").strip() or qry_dt or date_str
        if not bar_dt:
            logger.warning("[데이터] %s 행 저장 생략 — dt 누락 (P20 폴백 금지)", nk)
            continue
        # 안전망: 소속 거래일 자체(미확정 당일) 행은 저장 차단 (P22 데이터 정합성)
        current_td = get_current_trading_day_str()
        if bar_dt == current_td:
            logger.warning(
                "[데이터] %s 행 저장 생략 — 소속 거래일(미확정) 행 감지 (bar_dt=%s, P22)",
                nk, bar_dt,
            )
            continue

        # 당일 세로 행 파라미터 (INSERT OR REPLACE — 같은 날 재실행 시 자동 덮어쓰기 P22)
        bars_bulk_params.append((nk, bar_dt, today_amt, today_high))
        codes_to_recalc.append(nk)

        stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)
        master_bulk_params.append((
            nk, stk_nm, cur_price, change, change_rate,
            today_amt, 0, 0, date_str  # avg_5d/high_5d는 아래에서 재계산 후 갱신
        ))

    async with get_db_lock():
        conn = await get_db_connection()
        try:
            # 보관 정책 통합 — qry_dt 기준 최근 5거래일 외 과거·미래 행 정리 (설계 7, 세션 4).
            # 미확정 당일(미래) 행이 잔존하면 avg_5d/high_5d 재계산이 왜곡되므로 INSERT OR REPLACE 전에 먼저 정리.
            # 과거 행 정리는 기존 자동 경로에 빠져 있던 항목 — 수동 5일과 동일 정책 적용 (P22/P24).
            await _prune_5d_bars(conn, qry_dt)
            # 5거래일 일봉 세로 행 적재 (당일 1행씩 INSERT OR REPLACE)
            if bars_bulk_params:
                await conn.executemany("""
                    INSERT OR REPLACE INTO stock_5d_bars
                    (code, dt, trade_amount, high_price)
                    VALUES (?, ?, ?, ?)
                """, bars_bulk_params)

            # avg_5d_trade_amount, high_5d_price 재계산 — stock_5d_bars에서 종목당 최근 5행 (P10 SSOT)
            # 순수 계산은 market_close_calc.compute_5d_derived 로 통합 (설계 5.6, 세션 4)
            # 5일 완전성 검증 추가 (설계서 4.5, 세션 4) — 자동·수동 같은 규칙
            # 5일 부족 시 파생값을 0이 아닌 None으로 저장 (P20 폴백 금지)
            recalc_params: list[tuple] = []
            derived: dict[str, tuple[int | None, int | None]] = {}
            expected_days = _expected_5d_days(qry_dt)
            if codes_to_recalc:
                placeholders = ",".join("?" for _ in codes_to_recalc)
                cursor = await conn.execute(f"""
                    SELECT code, dt, trade_amount, high_price
                    FROM stock_5d_bars
                    WHERE code IN ({placeholders})
                    ORDER BY dt DESC
                """, codes_to_recalc)
                rows = await cursor.fetchall()
                by_code: dict[str, list] = defaultdict(list)
                for r in rows:
                    by_code[r["code"]].append(r)

                for nk in codes_to_recalc:
                    recent = by_code.get(nk, [])[:5]
                    dts = [str(r["dt"]) for r in recent if r["dt"]]
                    amts = [r["trade_amount"] for r in recent]
                    highs = [r["high_price"] for r in recent]

                    # 5일 완전성 검증 (설계서 4.5 — 세션 4)
                    is_complete, _problems = verify_5d_completeness(
                        dts, amts, highs, expected_days,
                    )

                    if is_complete:
                        avg_5d, high_5d = compute_5d_derived(
                            [(r["trade_amount"], r["high_price"]) for r in recent]
                        )
                    else:
                        # 5일 부족 — 파생값을 None으로 저장 (P20 폴백 금지, 설계서 4.5)
                        avg_5d, high_5d = None, None

                    recalc_params.append((avg_5d, high_5d, nk))
                    derived[nk] = (avg_5d, high_5d)

            # 마스터 테이블 적재 (UPSERT) — 기존 market 정보 보존
            if master_bulk_params:
                cursor = await conn.execute("SELECT code, market FROM master_stocks_table")
                mkt_rows = await cursor.fetchall()
                mkt_map = {r["code"]: r["market"] for r in mkt_rows}

                recalc_map = {p[2]: (p[0], p[1]) for p in recalc_params}
                updated_params = []
                for params in master_bulk_params:
                    code = params[0]
                    avg_5d, high_5d = recalc_map.get(code, (None, None))
                    market = mkt_map.get(code, "")
                    updated_params.append((params[0], params[1], params[2], params[3], params[4],
                                           params[5], avg_5d, high_5d, params[8], market))

                await conn.executemany("""
                    INSERT INTO master_stocks_table
                    (code, name, cur_price, change, change_rate, trade_amount, avg_5d_trade_amount, high_5d_price, date, market)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        avg_5d_trade_amount = excluded.avg_5d_trade_amount,
                        high_5d_price = excluded.high_5d_price,
                        date = excluded.date,
                        market = excluded.market
                """, updated_params)

            await conn.commit()
            logger.info(
                "[데이터] 저장 — 5거래일 일봉: %d종목, 전종목 마스터 테이블: %d종목",
                len(bars_bulk_params), len(master_bulk_params),
            )
            return {
                "success": True,
                "saved_codes": [p[0] for p in master_bulk_params],
                "derived": derived,
            }

        except Exception as e:
            await conn.rollback()
            logger.warning("[데이터] 저장 실패: %s", e, exc_info=True)
            return _empty_result()


# ---------------------------------------------------------------------------
# 수동 5일 일봉 저장 — 단일 트랜잭션
# ---------------------------------------------------------------------------

async def save_5d_bars(
    confirmed_5d: dict[str, dict],
    *,
    qry_dt: str = "",
) -> dict:
    """수동 5거래일 일봉 단일 트랜잭션 저장.

    5일치 일봉 원본(``stock_5d_bars``) + 마스터 평균/최고가(``master_stocks_table``) +
    보관 정리(과거·미래 행 삭제)를 하나의 트랜잭션으로 처리.

    메모리 캐시(``master_stocks_cache``)를 직접 갱신하지 않는다 (설계 5.4).
    파생값은 반환값 ``derived`` 로 전달하며, 호출자가 저장 성공 후 메모리에 반영한다.

    Args:
        confirmed_5d: {종목코드: {amts_5d_array, highs_5d_array, dts_5d_array}}
        qry_dt: 가장 최근 확정된 거래일 (YYYYMMDD). 보관 정리 기준.

    Returns:
        ``{"success": bool, "saved_codes": list[str], "derived": {code: (avg_5d, high_5d)}}``.
        실패 시 ``success=False`` 와 빈 파생값.
    """
    if not confirmed_5d:
        logger.info("[데이터] 5일 저장 입력 없음 — 트랜잭션 생략")
        return _empty_result()

    if not qry_dt:
        logger.warning("[데이터] 5일 저장 실패 — qry_dt 누락 (P20 폴백 금지)")
        return _empty_result()

    bars_params: list[tuple] = []
    master_update_params: list[tuple] = []
    derived: dict[str, tuple[int | None, int | None]] = {}
    current_td = get_current_trading_day_str()
    expected_days = _expected_5d_days(qry_dt)

    for cd, data in confirmed_5d.items():
        amts_5d = data.get("amts_5d_array") or []
        highs_5d = data.get("highs_5d_array") or []
        dts_5d = data.get("dts_5d_array") or []

        # 세로 행 파라미터 — 각 일봉을 (code, dt, trade_amount, high_price) 1행으로 저장
        # 안전망: 소속 거래일 자체(미확정 당일) 행은 저장 차단 (P22 데이터 정합성)
        saved_dts: list[str] = []
        saved_amts: list[int | None] = []
        saved_highs: list[int | None] = []
        for i in range(min(len(amts_5d), len(highs_5d), len(dts_5d))):
            dt = dts_5d[i]
            if not dt:
                continue
            if str(dt) == current_td:
                logger.warning(
                    "[데이터] %s 행 저장 생략 — 소속 거래일(미확정) 행 감지 (dt=%s, P22)",
                    cd, dt,
                )
                continue
            bars_params.append((cd, str(dt), amts_5d[i], highs_5d[i]))
            saved_dts.append(str(dt))
            saved_amts.append(amts_5d[i])
            saved_highs.append(highs_5d[i])

        # 5일 완전성 검증 (설계서 4.5 — 세션 4, 자동·수동 같은 규칙)
        is_complete, _problems = verify_5d_completeness(
            saved_dts, saved_amts, saved_highs, expected_days,
        )

        if is_complete:
            # 5일 완전 — 파생값 계산 (설계서 4.5)
            avg_5d, high_5d = compute_5d_derived(
                [(saved_amts[i], saved_highs[i]) for i in range(len(saved_amts))]
            )
            master_update_params.append((avg_5d, high_5d, cd))
            derived[cd] = (avg_5d, high_5d)
        else:
            # 5일 부족 — 파생값을 None으로 저장 (P20 폴백 금지, 설계서 4.5)
            avg_5d, high_5d = None, None
            master_update_params.append((avg_5d, high_5d, cd))
            derived[cd] = (avg_5d, high_5d)
            logger.warning("[데이터] %s 5일 완전성 실패 — 파생값 None 저장", cd)

    async with get_db_lock():
        conn = await get_db_connection()
        try:
            if bars_params:
                await conn.executemany(
                    """INSERT OR REPLACE INTO stock_5d_bars
                    (code, dt, trade_amount, high_price)
                    VALUES (?, ?, ?, ?)""",
                    bars_params,
                )

            # 마스터 테이블 업데이트 — avg_5d·high_5d (설계서 4.5, 세션 4)
            if master_update_params:
                await conn.executemany(
                    """UPDATE master_stocks_table
                    SET avg_5d_trade_amount = ?, high_5d_price = ?
                    WHERE code = ?""",
                    [(p[0], p[1], p[2]) for p in master_update_params],
                )

            # 행 정리 — 보관 정책 헬퍼로 통합 (설계 7, 세션 4 — 자동·수동 같은 정책)
            await _prune_5d_bars(conn, qry_dt)
            await conn.commit()
            logger.info("[데이터] 5일 저장 — %d종목, %d행", len(confirmed_5d), len(bars_params))
            return {
                "success": True,
                "saved_codes": [p[2] for p in master_update_params],
                "derived": derived,
            }

        except Exception as e:
            await conn.rollback()
            logger.warning("[데이터] 5일 저장 실패: %s", e, exc_info=True)
            return _empty_result()
