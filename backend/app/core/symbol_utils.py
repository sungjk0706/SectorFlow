# -*- coding: utf-8 -*-
"""
종목코드 정규화 순수 함수 — 엔진 전 경로의 단일 진실 소스 (P10 SSOT).

`_base_stk_cd`는 services/engine_symbol_utils.py에서 core로 이동됨 (C-06 core→services
역참조 해소). engine_symbol_utils.py는 본 모듈에서 재수출하여 기존 호출부·테스트 patch
경로를 유지 (P16 살아있는 경로).

의미 경계 (coupling-stock-code-normalization.md 참조):
- _base_stk_cd: 엔진 전 경로 종목코드 정규화 (_AL/_NX 접미사 제거 + zfill(6)[-6:] truncate)
- normalize_stk_cd_key (core/settings_store.py): 설정 키 정규화 (접미사 제거·truncate 없음)
- normalizeStockCode (frontend/stores/hotStore.ts): 프론트 Store 정규화 (A 접두사 제거)
"""
from __future__ import annotations


def _base_stk_cd(stk_cd: str) -> str:
    """순수 종목코드 반환 (_AL/_NX 접미사 제거).

    NXT 중복상장 슬롯 의미: _AL/_NX 접미사는 KRX+NXT 통합 구독 슬롯 1개를 의미.
    zfill(6)[-6:] truncate는 7자리+ 계좌번호 오입력 방지 (_real_item_stk_cd 연계).
    """
    s = str(stk_cd or "").strip().upper()
    for suffix in ("_AL", "_NX"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s
