"""engine_state.py 속성 그룹 분류 회귀 테스트 — 세션 10 + 세션 11.

엔진 전역 상태 70개 속성을 6개 그룹(A~F)으로 분류하고, 분류 계약을 회귀 테스트로 고정.
세션 10: 분류 주석 + 매핑 테이블 일치성 + fallback/산재/dead code 인벤토리.
세션 11: D/E/F 비거래 상태 소유권 계약 — 3종 단일화 + 자연스러운 산재 문서화 + dead code 3종.

검증 항목:
  1. 속성 → 그룹 매핑 (70개 전부, 누락/중복 없음)
  2. 6개 그룹 속성 수 합계 = 전체 속성 수
  3. 실제 EngineState 인스턴스 속성과 매핑 테이블 일치
  4. fallback 패턴 인벤토리 (세션 12 인계 — 7개 파일 20곳)
  5. 갱신 분산 주의 속성 명시 (향후 단일화 후보)
  6. dead code 후보 (shutdown_requested — 참조 0건, MIN_CACHE_LIFETIME_SEC — 읽기 0건)
  7. D/E/F 소유권 계약 (세션 11 — 3종 단일화 + 자연스러운 산재 + confirmed_refresh_running 미구현)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from backend.app.services.engine_state import EngineState


# ── 그룹 정의 (세션 10 분류 — engine_state.py docstring과 동일) ────────────────
GROUP_A_BROKER = {
    "connector_manager",
    "active_connector",
    "broker_tokens",
    "access_token",
    "login_ok",
    "broker_spec",
}
GROUP_B_ACCOUNT = {
    "engine_user_id",
    "ws_account_subscribed",
    "ws_connection_status",
    "quote_subscribed",
    "account_rest_bootstrapped",
    "broker_rest_totals",
    "auto_trade",
    "broker_rest_apis",
    "account_rest_lock",
    "account_snapshot",
    "positions",
}
GROUP_C_SECTOR = {
    "sector_summary_cache",
    "master_stocks_cache",
    "index_data_cache",
    "market_phase",
    "krx_circuit_breaker_active",
    "news_boost_cache",
    "news_keywords_cache",
    "news_boost_score",
    "news_boost_ttl_sec",
}
GROUP_D_SCHEDULER = {
    "last_reset_date",
    "krx_remove_done",
    "confirmed_done",
    "auto_trade_timer_handles",
    "midnight_timer_handle",
    "timetable_timer_handle",
    "last_jif_received_at",
    "krx_countdown_override",
    "nxt_countdown_override",
    "last_realtime_reset_date",
    "last_ws_subscribe_start_date",
    "last_krx_pre_subscribe_date",
    "last_confirmed_download_date",
}
GROUP_E_EVENT_LOCK = {
    "data_ready_event",
    "token_ready_event",
    "ws_reg_pipeline_done",
    "bootstrap_event",
    "sector_summary_ready_event",
    "engine_ready_event",
    "server_ready_event",
    "preboot_ready_event",
    "engine_stop_event",
    "ws_window_changed_event",
    "reg_seq_lock",
    "reg_ack_event",
    "reg_ack_return_code",
    "rest_api_thread_sem",
    "_last_global_buy_ts",
    "_last_global_sell_ts",
    "MIN_CACHE_LIFETIME_SEC",
    "REG_POST_ACK_GAP_SEC",
}
GROUP_F_SAFETY = {
    "running",
    "shutdown_requested",
    "engine_task",
    "engine_loop_ref",
    "realtime_latency_exceeded",
    "position_build_failed",
    "degraded_mode",
    "preboot_cache_loaded",
    "confirmed_refresh_running",
    "confirmed_refresh_running_confirmed",
    "confirmed_refresh_running_5d",
    "latest_filter_summary_meta",
    "integrated_system_settings_cache",
}

ALL_GROUPS = {
    "A": GROUP_A_BROKER,
    "B": GROUP_B_ACCOUNT,
    "C": GROUP_C_SECTOR,
    "D": GROUP_D_SCHEDULER,
    "E": GROUP_E_EVENT_LOCK,
    "F": GROUP_F_SAFETY,
}


# ── 1. 그룹 분류 계약 ──────────────────────────────────────────────────────────
class TestGroupClassification:
    """70개 속성이 6개 그룹으로 정확히 분류되었는지 검증."""

    def test_group_sizes_match_docstring(self):
        """docstring에 명시된 그룹별 속성 수와 일치."""
        expected_sizes = {"A": 6, "B": 11, "C": 9, "D": 13, "E": 18, "F": 13}
        for name, group in ALL_GROUPS.items():
            assert len(group) == expected_sizes[name], (
                f"그룹 {name} 속성 수 불일치: 예상 {expected_sizes[name]}, 실제 {len(group)}"
            )

    def test_total_attribute_count_is_70(self):
        """6개 그룹 합계 = 70 (누락/중복 없음)."""
        all_attrs = set()
        for group in ALL_GROUPS.values():
            all_attrs |= group
        assert len(all_attrs) == 70, f"전체 속성 수: {len(all_attrs)} (예상 70)"

    def test_no_overlap_between_groups(self):
        """어떤 속성도 두 그룹에 중복 분류되지 않음."""
        for name_a, group_a in ALL_GROUPS.items():
            for name_b, group_b in ALL_GROUPS.items():
                if name_a >= name_b:
                    continue
                overlap = group_a & group_b
                assert not overlap, (
                    f"그룹 {name_a}·{name_b} 중복 속성: {overlap}"
                )

    def test_engine_state_instance_attrs_match_mapping(self):
        """실제 EngineState 인스턴스 속성이 매핑 테이블과 정확히 일치."""
        instance = EngineState()
        # 인스턴스 속성 추출 (메서드 제외)
        instance_attrs = {
            attr for attr in vars(instance)
            if not attr.startswith("__") and not callable(getattr(instance, attr, None))
        }
        # on_filter_settings_changed는 메서드이므로 제외 대상이나 vars에 포함되지 않음
        mapped_attrs = set()
        for group in ALL_GROUPS.values():
            mapped_attrs |= group
        # 인스턴스에만 있고 매핑에 없는 속성
        only_in_instance = instance_attrs - mapped_attrs
        assert not only_in_instance, (
            f"인스턴스에만 존재 (매핑 누락): {only_in_instance}"
        )
        # 매핑에만 있고 인스턴스에 없는 속성
        only_in_mapping = mapped_attrs - instance_attrs
        assert not only_in_mapping, (
            f"매핑에만 존재 (인스턴스 누락): {only_in_mapping}"
        )


# ── 2. 외부 참조 무결성 ────────────────────────────────────────────────────────
class TestExternalReferences:
    """backend/app + backend/tests의 state.<attr> 참조가 모두 선언된 속성인지 검증."""

    @pytest.fixture(scope="class")
    def all_state_refs(self):
        """코드베이스에서 state.<attr> 패턴 전수 추출."""
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        tests_dir = repo_root / "backend" / "tests"
        pattern = re.compile(r"\bstate\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
        refs: set[str] = set()
        for base in (app_dir, tests_dir):
            for py_file in base.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                refs |= set(pattern.findall(text))
        return refs

    def test_all_state_refs_are_declared_attrs(self, all_state_refs):
        """모든 state.<attr> 참조가 EngineState 선언 속성 또는 헬퍼 메서드."""
        mapped_attrs = set()
        for group in ALL_GROUPS.values():
            mapped_attrs |= group
        # engine_state.py 전역 헬퍼/메서드도 state 접근 가능 (on_filter_settings_changed 등)
        instance = EngineState()
        allowed = mapped_attrs | {
            attr for attr in dir(instance)
            if not attr.startswith("_") and callable(getattr(instance, attr))
        }
        # state.get 은 일반적인 딕셔너리 접근 패턴 (state.integrated_system_settings_cache.get)
        # 실제로는 state.<attr>.get 형태이므로 state.get으로 오인되지 않음.
        # 단, grep 패턴이 state.get을 잡을 수 있으므로 허용 목록에서 제외 확인.
        unknown = all_state_refs - allowed
        # state.get 은 .get 메서드 호출이 아니라 오타/허위 매칭 — 허용 목록에서 제외
        unknown.discard("get")
        unknown.discard("last_")  # state.last_<date> 패턴의 접두사 오인
        assert not unknown, (
            f"선언되지 않은 state.<attr> 참조 (오타 또는 신규 속성 누락): {unknown}"
        )


# ── 3. Fallback 패턴 인벤토리 (세션 12 인계) ────────────────────────────────────
class TestFallbackPatternInventory:
    """`state.connector_manager or state.active_connector` fallback 패턴 인벤토리.

    세션 12 (active_connector 정리)에서 단일화 대상. 현재 7개 파일 15곳.
    회귀: fallback 패턴 수가 변경되면 테스트 실패 → 의도적 변경인지 감지.
    """

    @pytest.fixture(scope="class")
    def fallback_locations(self):
        """fallback 패턴이 등장하는 파일별 위치."""
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        pattern = re.compile(
            r"engine_state\.state\.connector_manager\s+or\s+engine_state\.state\.active_connector"
        )
        locations: dict[str, list[int]] = {}
        for py_file in sorted(app_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            # engine_state.py 자신의 docstring에 fallback 패턴 설명이 포함되어 있으므로 제외
            if py_file.name == "engine_state.py":
                continue
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            match_lines = [
                i + 1 for i, line in enumerate(lines) if pattern.search(line)
            ]
            if match_lines:
                locations[str(py_file.relative_to(repo_root))] = match_lines
        return locations

    def test_fallback_pattern_file_count(self, fallback_locations):
        """fallback 패턴이 7개 파일에 존재."""
        assert len(fallback_locations) == 7, (
            f"fallback 패턴 파일 수: {len(fallback_locations)} (예상 7). "
            f"파일: {list(fallback_locations.keys())}"
        )

    def test_fallback_pattern_total_count(self, fallback_locations):
        """fallback 패턴 총 출현 수 = 20."""
        total = sum(len(lines) for lines in fallback_locations.values())
        assert total == 20, (
            f"fallback 패턴 총 수: {total} (예상 20). "
            f"위치: {fallback_locations}"
        )

    def test_fallback_pattern_expected_files(self, fallback_locations):
        """예상된 7개 파일에만 fallback 존재."""
        expected_files = {
            "backend/app/services/engine_ws_reg.py",
            "backend/app/services/engine_ws.py",
            "backend/app/services/engine_lifecycle.py",
            "backend/app/services/daily_time_scheduler.py",
            "backend/app/services/engine_sector_confirm.py",
            "backend/app/services/market_close_pipeline.py",
            "backend/app/services/engine_bootstrap.py",
        }
        actual_files = set(fallback_locations.keys())
        assert actual_files == expected_files, (
            f"fallback 파일 불일치. 예상: {expected_files}, 실제: {actual_files}"
        )


# ── 4. 갱신 분산 주의 속성 (향후 단일화 후보) ──────────────────────────────────
class TestUpdateScatterInventory:
    """여러 파일에서 갱신되는 속성 명시적 인벤토리.

    세션 10 조사 결과. 향후 단일화 시 회귀 감지용.
    """

    @pytest.fixture(scope="class")
    def write_locations_by_attr(self):
        """각 속성별 state.<attr> = (쓰기) 위치를 가진 파일 집합."""
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        # state.<attr> = ... 패턴 (== 비교 제외, 딕셔너리 mutation 제외)
        pattern = re.compile(
            r"engine_state\.state\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=(?!=)"
        )
        # state.<attr> 직접 대입 (engine_state import 없이 state로 접근하는 파일도 포함)
        pattern_short = re.compile(r"(?<!\w)state\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=(?!=)")
        locations: dict[str, set[str]] = {}
        for py_file in sorted(app_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel = str(py_file.relative_to(repo_root))
            for line in lines:
                for pat in (pattern, pattern_short):
                    for m in pat.finditer(line):
                        attr = m.group(1)
                        locations.setdefault(attr, set()).add(rel)
        return locations

    def test_login_ok_scatter_5_locations(self, write_locations_by_attr):
        """login_ok: 5곳에서 갱신 (kiwoom/ls connector + lifecycle + loop + ws_dispatch)."""
        locs = write_locations_by_attr.get("login_ok", set())
        assert len(locs) == 5, (
            f"login_ok 갱신 위치 수: {len(locs)} (예상 5). 위치: {locs}"
        )

    def test_sector_summary_cache_scatter(self, write_locations_by_attr):
        """sector_summary_cache: 6~7곳에서 갱신 (가장 분산도 높음)."""
        locs = write_locations_by_attr.get("sector_summary_cache", set())
        # engine_lifecycle, daily_time_scheduler, engine_sector_confirm,
        # sector_data_provider, engine_snapshot
        assert len(locs) >= 5, (
            f"sector_summary_cache 갱신 위치 수: {len(locs)} (예상 ≥5). 위치: {locs}"
        )

    def test_positions_scatter_3_locations(self, write_locations_by_attr):
        """positions: 3곳에서 갱신 (engine_account, engine_lifecycle, settings route)."""
        locs = write_locations_by_attr.get("positions", set())
        assert len(locs) == 3, (
            f"positions 갱신 위치 수: {len(locs)} (예상 3). 위치: {locs}"
        )

    def test_broker_rest_totals_scatter_3_locations(self, write_locations_by_attr):
        """broker_rest_totals: 3곳에서 갱신."""
        locs = write_locations_by_attr.get("broker_rest_totals", set())
        assert len(locs) == 3, (
            f"broker_rest_totals 갱신 위치 수: {len(locs)} (예상 3). 위치: {locs}"
        )


# ── 5. Dead code 후보 ──────────────────────────────────────────────────────────
class TestDeadCodeCandidate:
    """참조 0건 속성 명시 — 별도 승인 시 제거 검토 대상."""

    @pytest.fixture(scope="class")
    def all_state_refs(self):
        """backend/app + backend/tests의 state.<attr> 참조 전수 추출 (읽기+쓰기)."""
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        tests_dir = repo_root / "backend" / "tests"
        pattern = re.compile(r"\bstate\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
        refs: set[str] = set()
        for base in (app_dir, tests_dir):
            for py_file in base.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                refs |= set(pattern.findall(text))
        return refs

    def test_shutdown_requested_is_dead_code(self, all_state_refs):
        """shutdown_requested: 선언만 존재, 외부 참조 0건 (dead code 후보).

        본 테스트는 dead code 상태를 고정 — 향후 참조가 추가되면 회귀 감지.
        제거는 별도 승인 필요 (AGENTS.md 규칙 0 — 승인 전 수정 금지).
        """
        assert "shutdown_requested" not in all_state_refs, (
            "shutdown_requested 참조가 발견됨 — dead code 상태에서 변경됨. "
            "본 테스트를 갱신하거나 속성 제거 검토 필요."
        )

    def test_min_cache_lifetime_sec_has_no_refs(self, all_state_refs):
        """MIN_CACHE_LIFETIME_SEC: 읽기 참조 0건 (사용 안 함 — 세션 11 조사).

        상수 선언만 존재. 참조가 추가되면 사용 안 함 상태에서 변경됨을 감지.
        제거는 별도 승인 필요.
        """
        assert "MIN_CACHE_LIFETIME_SEC" not in all_state_refs, (
            "MIN_CACHE_LIFETIME_SEC 참조가 발견됨 — 사용 안 함 상태에서 변경됨. "
            "본 테스트를 갱신하거나 속성 제거 검토 필요."
        )


# ── 6. D/E/F 소유권 계약 (세션 11 — 비거래 상태 단일화) ──────────────────────────
class TestOwnershipContractSession11:
    """세션 11에서 단일화한 3종 속성의 소유권 계약 회귀 테스트.

    단일화 완료 속성의 쓰기가 단일 소유자 모듈에만 존재하는지 검증.
    외부 모듈의 직접 쓰기가 추가되면 회귀 감지.
    """

    @pytest.fixture(scope="class")
    def write_locations_by_attr_v2(self):
        """각 속성별 state.<attr> = (쓰기) 위치를 가진 파일 집합 (세션 11 재사용)."""
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        pattern = re.compile(
            r"engine_state\.state\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=(?!=)"
        )
        pattern_short = re.compile(r"(?<!\w)state\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=(?!=)")
        locations: dict[str, set[str]] = {}
        for py_file in sorted(app_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel = str(py_file.relative_to(repo_root))
            for line in lines:
                for pat in (pattern, pattern_short):
                    for m in pat.finditer(line):
                        attr = m.group(1)
                        locations.setdefault(attr, set()).add(rel)
        return locations

    def test_last_realtime_reset_date_single_owner(self, write_locations_by_attr_v2):
        """last_realtime_reset_date (D): 쓰기는 engine_snapshot.py에만 존재 (세션 11 단일화).

        헬퍼: engine_snapshot._mark_realtime_reset_done()
        호출부 (engine_cache, daily_time_scheduler)는 헬퍼를 경유하므로 직접 쓰기 없음.
        """
        locs = write_locations_by_attr_v2.get("last_realtime_reset_date", set())
        expected = {"backend/app/services/engine_snapshot.py"}
        assert locs == expected, (
            f"last_realtime_reset_date 쓰기 위치 불일치.\n"
            f"예상: {expected}\n실제: {locs}\n"
            f"외부 직접 쓰기가 발견되면 _mark_realtime_reset_done() 헬퍼 경유로 변경 필요."
        )

    def test_confirmed_refresh_running_confirmed_single_owner(self, write_locations_by_attr_v2):
        """confirmed_refresh_running_confirmed (F): 쓰기는 market_close_pipeline.py에만 존재 (세션 11 단일화).

        소유 모듈 내 3곳 (True 시작 + False finally + _reset_confirmed_refresh_running 헬퍼).
        외부 (daily_time_scheduler)는 _reset_confirmed_refresh_running() 헬퍼 경유.
        """
        locs = write_locations_by_attr_v2.get("confirmed_refresh_running_confirmed", set())
        expected = {"backend/app/services/market_close_pipeline.py"}
        assert locs == expected, (
            f"confirmed_refresh_running_confirmed 쓰기 위치 불일치.\n"
            f"예상: {expected}\n실제: {locs}\n"
            f"외부 직접 쓰기가 발견되면 _reset_confirmed_refresh_running() 헬퍼 경유로 변경 필요."
        )

    def test_latest_filter_summary_meta_single_owner(self, write_locations_by_attr_v2):
        """latest_filter_summary_meta (F): 쓰기는 market_close_pipeline.py에만 존재 (세션 11 단일화).

        헬퍼: market_close_pipeline._set_latest_filter_summary_meta()
        호출부 (market_close_pipeline 4단계, web/app.py 기동 로드)는 헬퍼 경유.
        """
        locs = write_locations_by_attr_v2.get("latest_filter_summary_meta", set())
        expected = {"backend/app/services/market_close_pipeline.py"}
        assert locs == expected, (
            f"latest_filter_summary_meta 쓰기 위치 불일치.\n"
            f"예상: {expected}\n실제: {locs}\n"
            f"외부 직접 쓰기가 발견되면 _set_latest_filter_summary_meta() 헬퍼 경유로 변경 필요."
        )

    def test_running_natural_scatter_documented(self, write_locations_by_attr_v2):
        """running (F): 자연스러운 산재 — engine_lifecycle + engine_loop (라이프사이클 협업).

        단일화 대상 아님 — 시작/중지는 lifecycle, 실행/종료는 loop가 담당.
        산재 파일 수가 변경되면 문서화 갱신 필요.
        """
        locs = write_locations_by_attr_v2.get("running", set())
        expected = {
            "backend/app/services/engine_lifecycle.py",
            "backend/app/services/engine_loop.py",
        }
        assert locs == expected, (
            f"running 쓰기 위치 불일치.\n"
            f"예상: {expected}\n실제: {locs}\n"
            f"자연스러운 산재 패턴에서 변경됨 — 문서화 갱신 또는 단일화 검토 필요."
        )

    def test_degraded_mode_natural_scatter_documented(self, write_locations_by_attr_v2):
        """degraded_mode (F): 자연스러운 산재 — engine_lifecycle(초기화) + engine_loop(오류 설정).

        단일화 대상 아님 — init/오류 패턴.
        """
        locs = write_locations_by_attr_v2.get("degraded_mode", set())
        expected = {
            "backend/app/services/engine_lifecycle.py",
            "backend/app/services/engine_loop.py",
        }
        assert locs == expected, (
            f"degraded_mode 쓰기 위치 불일치.\n"
            f"예상: {expected}\n실제: {locs}\n"
            f"자연스러운 산재 패턴에서 변경됨 — 문서화 갱신 또는 단일화 검토 필요."
        )

    def test_preboot_cache_loaded_natural_scatter_documented(self, write_locations_by_attr_v2):
        """preboot_cache_loaded (F): 자연스러운 산재 — engine_cache(성공) + engine_loop(초기화).

        단일화 대상 아님 — init/성공 패턴.
        """
        locs = write_locations_by_attr_v2.get("preboot_cache_loaded", set())
        expected = {
            "backend/app/services/engine_cache.py",
            "backend/app/services/engine_loop.py",
        }
        assert locs == expected, (
            f"preboot_cache_loaded 쓰기 위치 불일치.\n"
            f"예상: {expected}\n실제: {locs}\n"
            f"자연스러운 산재 패턴에서 변경됨 — 문서화 갱신 또는 단일화 검토 필요."
        )

    def test_confirmed_refresh_running_has_no_writes(self, write_locations_by_attr_v2):
        """confirmed_refresh_running (F): 쓰기 0건 (미구현 플래그 — 세션 11 조사).

        읽기만 2건 존재. 쓰기가 추가되면 미구현 상태에서 변경됨을 감지.
        제거는 별도 승인 필요.
        """
        locs = write_locations_by_attr_v2.get("confirmed_refresh_running", set())
        assert not locs, (
            f"confirmed_refresh_running 쓰기 발견: {locs} — "
            "미구현 플래그 상태에서 변경됨. 본 테스트 갱신 또는 구현 검토 필요."
        )
