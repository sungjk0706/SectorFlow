"""engine_ws_reg.py 단위 테스트 — REG/UNREG/REMOVE 페이로드 빌더 순수 함수 검증.

async 구독 함수(subscribe_*)는 state/connector mock이 필요하여 핵심 payload 빌더만 검증.
"""
from __future__ import annotations

from backend.app.services.engine_ws_reg import (
    build_0b_reg_payloads,
    build_0b_remove_payloads,
    build_0d_reg_payloads,
    build_0d_remove_payloads,
    build_index_reg_payload,
    build_account_reg_payload,
)


# ── build_0b_reg_payloads ───────────────────────────────────────────────────────

class TestBuild0bRegPayloads:
    def test_empty_stocks(self):
        assert build_0b_reg_payloads([]) == []

    def test_invalid_chunk_size(self):
        assert build_0b_reg_payloads(["005930"], chunk_size=0) == []

    def test_single_chunk(self):
        payloads = build_0b_reg_payloads(["005930", "000660"])
        assert len(payloads) == 1
        p = payloads[0]
        assert p["trnm"] == "REG"
        assert p["grp_no"] == "4"
        assert p["refresh"] == "0"
        assert p["data"] == [{"item": ["005930", "000660"], "type": ["0B"]}]

    def test_multiple_chunks(self):
        payloads = build_0b_reg_payloads(["005930", "000660"], chunk_size=1)
        assert len(payloads) == 2
        assert payloads[0]["refresh"] == "0"
        assert payloads[1]["refresh"] == "1"
        assert payloads[0]["data"][0]["item"] == ["005930"]
        assert payloads[1]["data"][0]["item"] == ["000660"]

    def test_reset_first_false(self):
        payloads = build_0b_reg_payloads(["005930", "000660"], chunk_size=1, reset_first=False)
        assert payloads[0]["refresh"] == "1"
        assert payloads[1]["refresh"] == "1"

    def test_large_list_chunking(self):
        stocks = [f"{i:06d}" for i in range(250)]
        payloads = build_0b_reg_payloads(stocks, chunk_size=100)
        assert len(payloads) == 3
        assert len(payloads[0]["data"][0]["item"]) == 100
        assert len(payloads[1]["data"][0]["item"]) == 100
        assert len(payloads[2]["data"][0]["item"]) == 50


# ── build_0b_remove_payloads ────────────────────────────────────────────────────

class TestBuild0bRemovePayloads:
    def test_empty(self):
        assert build_0b_remove_payloads([]) == []

    def test_invalid_chunk_size(self):
        assert build_0b_remove_payloads(["005930"], chunk_size=-1) == []

    def test_single_chunk(self):
        payloads = build_0b_remove_payloads(["005930"])
        assert len(payloads) == 1
        p = payloads[0]
        assert p["trnm"] == "REMOVE"
        assert p["grp_no"] == "4"
        assert p["refresh"] == "1"
        assert p["data"] == [{"item": ["005930"], "type": ["0B"]}]

    def test_multiple_chunks(self):
        payloads = build_0b_remove_payloads(["005930", "000660"], chunk_size=1)
        assert len(payloads) == 2
        assert all(p["trnm"] == "REMOVE" for p in payloads)
        assert all(p["refresh"] == "1" for p in payloads)


# ── build_0d_reg_payloads ───────────────────────────────────────────────────────

class TestBuild0dRegPayloads:
    def test_empty(self):
        assert build_0d_reg_payloads([]) == []

    def test_invalid_chunk_size(self):
        assert build_0d_reg_payloads(["005930"], chunk_size=0) == []

    def test_single_chunk(self):
        payloads = build_0d_reg_payloads(["005930", "000660"])
        assert len(payloads) == 1
        p = payloads[0]
        assert p["trnm"] == "REG"
        assert p["grp_no"] == "7"
        assert p["refresh"] == "1"
        assert p["data"] == [{"item": ["005930", "000660"], "type": ["0D"]}]

    def test_multiple_chunks_default_50(self):
        stocks = [f"{i:06d}" for i in range(75)]
        payloads = build_0d_reg_payloads(stocks)
        assert len(payloads) == 2
        assert len(payloads[0]["data"][0]["item"]) == 50
        assert len(payloads[1]["data"][0]["item"]) == 25


# ── build_0d_remove_payloads ────────────────────────────────────────────────────

class TestBuild0dRemovePayloads:
    def test_empty(self):
        assert build_0d_remove_payloads([]) == []

    def test_single_chunk(self):
        payloads = build_0d_remove_payloads(["005930"])
        assert len(payloads) == 1
        p = payloads[0]
        assert p["trnm"] == "REMOVE"
        assert p["grp_no"] == "7"
        assert p["refresh"] == "1"
        assert p["data"] == [{"item": ["005930"], "type": ["0D"]}]


# ── build_index_reg_payload ─────────────────────────────────────────────────────

class TestBuildIndexRegPayload:
    def test_structure(self):
        p = build_index_reg_payload()
        assert p["trnm"] == "REG"
        assert p["grp_no"] == "2"
        assert p["refresh"] == "0"
        assert p["data"] == [{"item": ["001", "101"], "type": ["0J"]}]


# ── build_account_reg_payload ───────────────────────────────────────────────────

class TestBuildAccountRegPayload:
    def test_structure(self):
        p = build_account_reg_payload()
        assert p["trnm"] == "REG"
        assert p["grp_no"] == "10"
        assert p["refresh"] == "0"
        assert p["data"] == [
            {"item": [""], "type": ["00"]},
            {"item": [""], "type": ["04"]},
        ]
