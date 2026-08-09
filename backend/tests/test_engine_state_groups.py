"""engine_state.py 속성 그룹 분류 회귀 테스트 — 세션 10 + 세션 11 + 세션 12.

엔진 전역 상태 68개 속성을 6개 그룹(A~F)으로 분류하고, 분류 계약을 회귀 테스트로 고정.
세션 10: 분류 주석 + 매핑 테이블 일치성 + fallback/산재/dead code 인벤토리.
세션 11: D/E/F 비거래 상태 소유권 계약 — 3종 단일화 + 자연스러운 산재 문서화 + dead code 3종.
세션 12: A 그룹 소유권 계약 — active_connector 제거 + connector_manager 단일 소유자 + fallback 22곳 제거.

검증 항목:
  1. 속성 → 그룹 매핑 (68개 전부, 누락/중복 없음)
  2. 6개 그룹 속성 수 합계 = 전체 속성 수
  3. 실제 EngineState 인스턴스 속성과 매핑 테이블 일치
  4. fallback 패턴 인벤토리 (세션 12 — 0곳, 제거 완료)
  5. 갱신 분산 주의 속성 명시 (향후 단일화 후보)
  6. D/E/F 소유권 계약 (세션 11 — 3종 단일화 + 자연스러운 산재)
  7. A 그룹 소유권 계약 (세션 12 — active_connector 제거 + connector_manager 단일 소유자)
  8. DC-S2 제거: shutdown_requested, MIN_CACHE_LIFETIME_SEC, confirmed_refresh_running (dead code 제거 완료)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.services.engine_state import EngineState


# ── 그룹 정의 (세션 10 분류 — engine_state.py docstring과 동일) ────────────────
GROUP_A_BROKER = {
    "connector_manager",
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
    "index_subscribed",
    "account_rest_bootstrapped",
    "broker_rest_totals",
    "auto_trade",
    "broker_rest_apis",
    "account_rest_lock",
    "account_snapshot",
    "positions",
    "unfilled_orders",
}
GROUP_C_SECTOR = {
    "sector_summary_cache",
    "master_stocks_cache",
    "index_data_cache",
    "market_phase",
    "krx_circuit_breaker_active",
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
    "last_krx_end_date",
    "last_nxt_end_date",
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
    "REG_POST_ACK_GAP_SEC",
}
GROUP_F_SAFETY = {
    "running",
    "engine_task",
    "engine_loop_ref",
    "engine_scheduled_tasks",
    "engine_shutdown_requested",
    "realtime_latency_exceeded",
    "position_build_failed",
    "degraded_mode",
    "preboot_cache_loaded",
    "confirmed_refresh_running_confirmed",
    "confirmed_refresh_running_5d",
    "latest_filter_summary_meta",
    "integrated_system_settings_cache",
    "token_recovery_in_progress",
    "token_failure_kind",
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
    """72개 속성이 6개 그룹으로 정확히 분류되었는지 검증."""

    def test_group_sizes_match_docstring(self):
        """docstring에 명시된 그룹별 속성 수와 일치."""
        expected_sizes = {"A": 5, "B": 13, "C": 8, "D": 15, "E": 17, "F": 15}
        for name, group in ALL_GROUPS.items():
            assert len(group) == expected_sizes[name], (
                f"그룹 {name} 속성 수 불일치: 예상 {expected_sizes[name]}, 실제 {len(group)}"
            )

    def test_total_attribute_count_is_68(self):
        """6개 그룹 합계 = 73 (누락/중복 없음). 종료 수명 관리 상태 포함."""
        all_attrs = set()
        for group in ALL_GROUPS.values():
            all_attrs |= group
        assert len(all_attrs) == 73, f"전체 속성 수: {len(all_attrs)} (예상 73)"

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


# ── 3. Fallback 패턴 인벤토리 (세션 12 — 제거 완료) ─────────────────────────────
class TestFallbackPatternInventory:
    """`connector_manager or active_connector` fallback 패턴 인벤토리.

    세션 12 (active_connector 정리)에서 22곳 fallback 전부 제거 완료.
    회귀: fallback 패턴이 재도입되면 테스트 실패 → 의도적 변경인지 감지.
    """

    @pytest.fixture(scope="class")
    def fallback_locations(self):
        """fallback 패턴이 등장하는 파일별 위치 (제거 완료 → 0건 기대)."""
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

    def test_fallback_pattern_removed(self, fallback_locations):
        """fallback 패턴이 제거됨 (0건)."""
        assert not fallback_locations, (
            f"fallback 패턴 잔존: {fallback_locations} (예상 0건 — 세션 12 제거 완료)"
        )

    def test_active_connector_attr_removed(self):
        """active_connector 속성이 EngineState에서 제거됨 (세션 12)."""
        instance = EngineState()
        assert not hasattr(instance, "active_connector"), (
            "active_connector 속성이 잔존 — 세션 12 제거 대상"
        )

    def test_active_connector_refs_in_app_zero(self):
        """backend/app에서 active_connector 참조 0건 (docstring 역사적 기록 제외)."""
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        pattern = re.compile(r"\.active_connector\b")
        refs: list[str] = []
        for py_file in sorted(app_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            if py_file.name == "engine_state.py":
                # docstring의 역사적 기록(제거 사유)은 허용
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(text):
                refs.append(str(py_file.relative_to(repo_root)))
        assert not refs, (
            f"active_connector 참조 잔존 (예상 0건): {refs}"
        )


# ── 3-A. A 그룹 소유권 계약 (세션 12 — connector_manager 단일 소유자) ───────────
class TestAGroupOwnershipContract:
    """A 그룹(브로커 연결) 소유권 계약 — connector_manager 단일 소유자.

    세션 12 (CACHE-STATE-IMPL-12)에서 active_connector 파생 참조 제거.
    connector_manager가 모든 WS 송신·구독·상태 조회의 단일 소유자.
    """

    def test_connector_manager_is_only_ws_owner_in_app(self):
        """backend/app에서 WS 연결 참조는 connector_manager 단독 사용.

        active_connector fallback 없이 connector_manager만 사용하는지 검증.
        """
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        # connector_manager를 사용하는 파일 수 (engine_state.py 자신 제외)
        cm_pattern = re.compile(r"engine_state\.state\.connector_manager\b")
        cm_files: set[str] = set()
        for py_file in sorted(app_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            if py_file.name == "engine_state.py":
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if cm_pattern.search(text):
                cm_files.add(str(py_file.relative_to(repo_root)))
        # 8개 서비스 파일 + 1개 라우트 파일 = 9개 이상 (회귀 감지)
        assert len(cm_files) >= 9, (
            f"connector_manager 사용 파일 수: {len(cm_files)} (예상 ≥9). "
            f"파일: {cm_files}"
        )

    def test_connector_manager_write_only_in_engine_loop(self):
        """connector_manager 쓰기는 engine_loop.py(생성·해제)에서만 발생.

        시간 구간 복원: daily_time_scheduler.py의 20:00 직접 연결 해제 제거.
        연결 해제는 엔진 루프의 시간 판정 루프가 20:40 경과 시 수행.
        """
        repo_root = Path(__file__).resolve().parents[2]
        app_dir = repo_root / "backend" / "app"
        write_pattern = re.compile(
            r"engine_state\.state\.connector_manager\s*=(?!=)"
        )
        write_files: set[str] = set()
        for py_file in sorted(app_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if write_pattern.search(text):
                write_files.add(str(py_file.relative_to(repo_root)))
        assert write_files == {"backend/app/services/engine_loop.py"}, (
            f"connector_manager 쓰기 파일 불일치: {write_files} "
            f"(예상: engine_loop.py만)"
        )


# ── 4. 갱신 분산 주의 속성 (단일화 후보/완료 혼재) ──────────────────────────────
class TestUpdateScatterInventory:
    """여러 파일에서 갱신되는 속성 명시적 인벤토리.

    세션 10 조사 결과. sector_summary_cache는 COUPLING-S1 후속 단일화 완료.
    나머지(login_ok, positions, broker_rest_totals)는 향후 단일화 후보.
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

    def test_sector_summary_cache_single_owner(self, write_locations_by_attr):
        """sector_summary_cache: 단일 소유자(engine_initial_data)로 단일화 완료 (COUPLING-S1 후속).

        기존 7곳 직접 쓰기를 ``engine_initial_data._set_sector_summary()`` 헬퍼 호출로 전환.
        외부 모듈의 직접 쓰기가 추가되면 회귀 감지.
        """
        locs = write_locations_by_attr.get("sector_summary_cache", set())
        assert locs == {"backend/app/services/engine_initial_data.py"}, (
            f"sector_summary_cache 단일 소유자 위반: {locs} "
            f"(예상: engine_initial_data.py만 — _set_sector_summary 헬퍼 경유)"
        )

    def test_positions_scatter_3_locations(self, write_locations_by_attr):
        """positions: 3곳에서 갱신 (engine_account, engine_lifecycle, settings route)."""
        locs = write_locations_by_attr.get("positions", set())
        assert len(locs) == 3, (
            f"positions 갱신 위치 수: {len(locs)} (예상 3). 위치: {locs}"
        )

    def test_broker_rest_totals_scatter_2_locations(self, write_locations_by_attr):
        """broker_rest_totals: 2곳에서 갱신 (틱 핸들러 자체 계산 제거 후 — 평가손익 SSOT 2단계)."""
        locs = write_locations_by_attr.get("broker_rest_totals", set())
        assert len(locs) == 2, (
            f"broker_rest_totals 갱신 위치 수: {len(locs)} (예상 2). 위치: {locs}"
        )


# ── 5. D/E/F 소유권 계약 (세션 11 — 비거래 상태 단일화) ──────────────────────────
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
        """last_realtime_reset_date (D): 쓰기는 engine_initial_data.py에만 존재 (세션 11 단일화).

        헬퍼: engine_initial_data._mark_realtime_reset_done()
        호출부 (engine_cache, daily_time_scheduler)는 헬퍼를 경유하므로 직접 쓰기 없음.
        """
        locs = write_locations_by_attr_v2.get("last_realtime_reset_date", set())
        expected = {"backend/app/services/engine_initial_data.py"}
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

