# -*- coding: utf-8 -*-
"""Conflation 압축 로직 단위 테스트"""
import sys
sys.path.insert(0, '/Users/sungjk0706/Desktop/SectorFlow/backend')

import time
from app.services.engine_account_notify import _should_conflate, _conflate_cache


def reset():
    _conflate_cache.clear()


def make_item(type_code, item_code, price):
    return {
        "type": type_code,
        "item": item_code,
        "values": {"10": str(price)}
    }


def test_conflate_same_price_within_50ms():
    """동일 종목·동일 가격·50ms 이내 → 압축"""
    reset()
    item1 = make_item("01", "005930", 70000)
    item2 = make_item("01", "005930", 70000)
    r1 = _should_conflate(item1)
    time.sleep(0.01)  # 10ms
    r2 = _should_conflate(item2)
    assert r1 is False, f"첫 틱은 압축되면 안 됨: {r1}"
    assert r2 is True, f"50ms 이내 중복 틱은 압축돼야 함: {r2}"
    print("[PASS] 동일 가격 50ms 이내 압축")


def test_conflate_different_price():
    """가격 변화 → 통과"""
    reset()
    item1 = make_item("01", "005930", 70000)
    item2 = make_item("01", "005930", 70100)
    r1 = _should_conflate(item1)
    r2 = _should_conflate(item2)
    assert r1 is False
    assert r2 is False, "가격 변화 시 압축되면 안 됨"
    print("[PASS] 가격 변화 시 통과")


def test_conflate_after_50ms():
    """50ms 이후 동일 가격 → 통과"""
    reset()
    item1 = make_item("01", "005930", 70000)
    item2 = make_item("01", "005930", 70000)
    r1 = _should_conflate(item1)
    time.sleep(0.06)  # 60ms
    r2 = _should_conflate(item2)
    assert r1 is False
    assert r2 is False, "50ms 이후 동일 가격도 통과해야 함"
    print("[PASS] 50ms 이후 동일 가격 통과")


def test_conflate_ignored_types():
    """00, 0J 타입은 압축 대상 아님 → 통과"""
    reset()
    item00 = make_item("00", "005930", 70000)
    item0j = make_item("0J", "005930", 70000)
    item0d = make_item("0D", "005930", 70000)
    assert _should_conflate(item00) is False, "00은 압축 대상 아님"
    assert _should_conflate(item0j) is False, "0J는 압축 대상 아님"
    assert _should_conflate(item0d) is False, "0D는 압축 대상 아님"
    print("[PASS] 00/0J/0D 타입 압축 대상 아님")


def test_conflate_0b_type():
    """0B 타입도 압축 대상"""
    reset()
    item1 = make_item("0B", "005930", 70000)
    item2 = make_item("0B", "005930", 70000)
    r1 = _should_conflate(item1)
    time.sleep(0.01)
    r2 = _should_conflate(item2)
    assert r1 is False
    assert r2 is True, "0B 타입도 압축돼야 함"
    print("[PASS] 0B 타입 압축")


def test_conflate_stress():
    """1ms 간격 20건 동일 종목·동일 가격(총 20ms) → 첫 1건만 통과, 나머지 19건 압축"""
    reset()
    code = "005930"
    price = 70000
    passed = 0
    for i in range(20):
        item = make_item("01", code, price)
        if not _should_conflate(item):
            passed += 1
        time.sleep(0.001)
    assert passed == 1, f"20건(20ms) 중 1건만 통과해야 함, 실제={passed}"
    print(f"[PASS] 스트레스 테스트: 20건 중 {passed}건 통과, 19건 압축")


if __name__ == "__main__":
    test_conflate_same_price_within_50ms()
    test_conflate_different_price()
    test_conflate_after_50ms()
    test_conflate_ignored_types()
    test_conflate_0b_type()
    test_conflate_stress()
    print("\n=== 모든 테스트 통과 ===")
