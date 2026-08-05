# -*- coding: utf-8 -*-
"""장마감 5일 파생값 순수 계산 모듈 — 평균 거래대금·5일 최고가 (설계 5.6).

본 모듈은 순수 계산만 담당한다 (설계 5.6).
- 입력: 거래일별 거래대금·고가 쌍
- 출력: 평균 거래대금·5일 최고가
- DB·메모리·화면 직접 접근 금지
- 자동 일봉·수동 5일 경로가 같은 계산 결과 사용 (P10 SSOT, P24 단순성)

업종 계산은 5일 지표 계산과 다른 업무 책임이므로 본 모듈에 넣지 않는다 (설계 5.6).

관련 원칙: P10(SSOT) · P20(폴백 금지) · P22(데이터 정합성) · P24(단순성)
"""
from __future__ import annotations

# 5일 완전성 기준 거래일 수 (설계서 4.5)
EXPECTED_5D_DAYS = 5


def compute_5d_derived(pairs: list[tuple[int | None, int | None]]) -> tuple[int | None, int | None]:
    """(거래대금, 고가) 쌍 리스트에서 5일 평균 거래대금·5일 최고가 계산.

    자동 일봉(``stock_5d_bars`` 최근 5행)과 수동 5일(다운로드 배열)이 모두 본 함수를 호출하여
    같은 공식을 사용한다 (설계 5.6, P10 SSOT).

    빈값·0·None 은 valid 집합에서 제외한다 (P22 데이터 정합성 — 빈값이 평균·최고가를 왜곡하지 않도록).
    valid 집합이 비어 있으면 (None, None) 반환 (P20 — 빈값을 0으로 위장하지 않고 명시적 None).

    Args:
        pairs: [(trade_amount, high_price), ...]. 최근 5거래일 분량. 순서 무관.

    Returns:
        (avg_5d_trade_amount, high_5d_price). valid 없으면 (None, None).
    """
    valid_amts = [a for a, _ in pairs if a is not None and a > 0]
    valid_highs = [h for _, h in pairs if h is not None and h > 0]
    avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else None
    high_5d = max(valid_highs) if valid_highs else None
    return avg_5d, high_5d


def verify_5d_completeness(
    dts: list[str],
    amts: list[int | None],
    highs: list[int | None],
    expected_days: list[str],
) -> tuple[bool, list[str]]:
    """5일 원자료의 완전성 검증 (설계서 4.5 — 세션 4).

    자동 일봉(``stock_5d_bars`` 행)·수동 5일(다운로드 배열) 모두 본 함수로
    동일한 완전성 기준을 적용한다 (설계서 4.5 — 자동·수동 같은 규칙).

    검증 항목:
    1. 실제 행 수가 EXPECTED_5D_DAYS(5)인지 확인
    2. 실제 거래일이 예상 최근 5거래일과 일치하는지 확인
    3. 거래대금·고가 누락(None·0)이 없는지 확인

    Args:
        dts: 실제 수신된 거래일 리스트 (YYYYMMDD 문자열).
        amts: 실제 수신된 거래대금 리스트 (None 허용).
        highs: 실제 수신된 고가 리스트 (None 허용).
        expected_days: 예상 최근 5거래일 리스트 (YYYYMMDD 문자열, 오래된 순).

    Returns:
        (is_complete, problems)
        - is_complete: True면 5일 완전, False면 부족·누락
        - problems: 문제 설명 리스트 (빈 리스트면 문제 없음)
    """
    problems: list[str] = []

    # 1. 행 수 확인 — 5일 미만이면 "준비 중" (아직 모이는 중, 자료 오류 아님)
    if len(dts) < EXPECTED_5D_DAYS:
        problems.append(f"행 수 부족: {len(dts)}/{EXPECTED_5D_DAYS}")
        return False, problems

    # 2. 거래일 일치 확인 — 예상 5거래일과 실제 거래일이 같아야 완전
    expected_set = set(str(d) for d in expected_days)
    actual_set = set(str(d) for d in dts if d)
    missing_days = expected_set - actual_set
    extra_days = actual_set - expected_set
    if missing_days:
        problems.append(f"누락 거래일: {sorted(missing_days)}")
    if extra_days:
        problems.append(f"예상 외 거래일: {sorted(extra_days)}")
    if missing_days or extra_days:
        return False, problems

    # 3. 숫자값 누락 확인 — 거래대금·고가가 None 또는 0이면 누락
    missing_amts = sum(1 for a in amts[:EXPECTED_5D_DAYS] if a is None or a <= 0)
    missing_highs = sum(1 for h in highs[:EXPECTED_5D_DAYS] if h is None or h <= 0)
    if missing_amts > 0 or missing_highs > 0:
        if missing_amts > 0:
            problems.append(f"거래대금 누락: {missing_amts}일")
        if missing_highs > 0:
            problems.append(f"고가 누락: {missing_highs}일")
        return False, problems

    return True, problems
