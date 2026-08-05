"""의존성 방향 회귀 검사 — 업종 계산 영역 (전역 상태 참조 분리 4단계).

업종 계산·업종 필터 영역이 서비스·엔진 상태·핵심 연결 영역을 직접 참조하지
않는지 정적 검사. 계산 영역은 명시 입력만 사용해야 하며, 외부 상태·조회가
다시 끌어들여지지 않도록 막는 자물쇠 역할 (P10 SSOT, P16 살아있는 경로,
P20 폴백 금지, P24 단순성).

검사 대상 (계산 영역):
  - backend/app/domain/sector_calculator.py
  - backend/app/domain/sector_filter.py

금지 참조 방향:
  - backend.app.services.*       (서비스 영역 — 엔진 상태·매매·조회 등)
  - backend.app.services.engine_state.* (엔진 상태 — 서비스 영역 중 별도 명시)
  - backend.app.core.*           (핵심 연결 영역 — 증권사 연결·설정·상수)

허용 참조 방향:
  - backend.app.domain.* (도메인 내부)
  - 표준 라이브러리

본 검사는 소스 파일을 직접 읽어 ast로 분석한다. 다른 테스트가 mock/patch로
이 정적 검사를 우회할 수 없다 (검사 대상 = 디스크 상의 생산 코드).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# tests/ 폴더의 부모 = backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# 검사 대상 — 업종 계산·업종 필터 영역 (계산 영역)
TARGET_FILES = [
    BACKEND_ROOT / "app" / "domain" / "sector_calculator.py",
    BACKEND_ROOT / "app" / "domain" / "sector_filter.py",
]

# 금지된 참조 방향 (접두사 매칭 — 방향성 검사)
FORBIDDEN_SERVICES_PREFIX = "backend.app.services"
FORBIDDEN_ENGINE_STATE_PREFIX = "backend.app.services.engine_state"
FORBIDDEN_CORE_PREFIX = "backend.app.core"


def _imported_modules(path: Path) -> list[str]:
    """파일에서 import 되는 모듈 경로 전체 수집 (ast 기반).

    `import a.b.c` 와 `from a.b.c import x` 모두 `a.b.c` 형태로 수집한다.
    상대 import(level>0)는 계산 영역이 사용하지 않으므로 절대 import만 취급한다.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # level==0(절대 import)만 취급 — 계산 영역은 절대 import 사용
            if (node.level or 0) == 0 and node.module:
                modules.append(node.module)
    return modules


@pytest.fixture(scope="module")
def target_imports() -> dict[Path, list[str]]:
    """검사 대상 파일별 import 모듈 목록.

    대상 파일이 없으면 조용히 통과되지 않도록 FileNotFoundError를 발생시킨다
    (P20 — 빈 결과로 폴백 금지).
    """
    result: dict[Path, list[str]] = {}
    for path in TARGET_FILES:
        if not path.exists():
            pytest.fail(f"검사 대상 파일이 없음: {path} (파일 이동/삭제 시 본 검사 갱신 필요)")
        result[path] = _imported_modules(path)
    return result


def _violating(imported: list[str], prefix: str) -> list[str]:
    """접두사로 시작하는 금지된 import 모듈 목록 반환."""
    return [m for m in imported if m == prefix or m.startswith(prefix + ".")]


class TestSectorCalculationDependencyDirection:
    """업종 계산 영역의 의존성 방향 회귀 검사."""

    def test_target_files_exist(self, target_imports: dict[Path, list[str]]) -> None:
        """검사 대상 파일이 모두 존재하는지 확인 (빈 결과로 조용히 통과 금지)."""
        # fixture에서 이미 pytest.fail 처리 — 여기 도달하면 존재 확인 완료
        assert len(target_imports) == len(TARGET_FILES)

    def test_no_services_import(self, target_imports: dict[Path, list[str]]) -> None:
        """계산 영역이 서비스 영역(backend.app.services.*)을 참조하지 않는다."""
        for path, imported in target_imports.items():
            violations = _violating(imported, FORBIDDEN_SERVICES_PREFIX)
            assert not violations, (
                f"{path.name}: 서비스 영역 참조 발견 (계산 영역은 명시 입력만 사용해야 함) "
                f"-> {violations}"
            )

    def test_no_engine_state_import(self, target_imports: dict[Path, list[str]]) -> None:
        """계산 영역이 엔진 상태(backend.app.services.engine_state.*)를 참조하지 않는다."""
        for path, imported in target_imports.items():
            violations = _violating(imported, FORBIDDEN_ENGINE_STATE_PREFIX)
            assert not violations, (
                f"{path.name}: 엔진 상태 참조 발견 (계산 영역은 엔진 내부 상태를 직접 읽지 않음) "
                f"-> {violations}"
            )

    def test_no_core_import(self, target_imports: dict[Path, list[str]]) -> None:
        """계산 영역이 핵심 연결 영역(backend.app.core.*)을 참조하지 않는다.

        핵심 연결 영역 = 증권사 연결·설정 저장소·상수·로깅 설정 등.
        계산 영역은 이 영역을 직접 참조하지 않고 호출 서비스가 자료를 전달한다.
        """
        for path, imported in target_imports.items():
            violations = _violating(imported, FORBIDDEN_CORE_PREFIX)
            assert not violations, (
                f"{path.name}: 핵심 연결 영역 참조 발견 (계산 영역은 외부 조회/연결을 직접 사용하지 않음) "
                f"-> {violations}"
            )

    def test_only_domain_and_stdlib_imports(self, target_imports: dict[Path, list[str]]) -> None:
        """계산 영역은 도메인 내부(backend.app.domain.*)와 표준 라이브러리만 허용.

        허용 접두사: backend.app.domain
        그 외 backend.app.* (services·core·web·pipelines 등)는 모두 금지.
        """
        for path, imported in target_imports.items():
            for module in imported:
                if module.startswith("backend.app."):
                    assert module.startswith("backend.app.domain"), (
                        f"{path.name}: 허용되지 않은 backend.app.* 참조 "
                        f"(도메인 내부만 허용) -> {module}"
                    )

    def test_static_check_not_bypassable_by_tests(self) -> None:
        """본 정적 검사는 디스크 상 생산 코드를 읽어 분석하므로 다른 테스트가 우회할 수 없다.

        확인 항목:
          - 검사 대상 경로가 실제 파일을 가리킨다 (존재 확인)
          - 분석 대상이 생산 코드 소스(읽기 전용)이다
        """
        for path in TARGET_FILES:
            assert path.is_file(), f"검사 대상이 파일 아님: {path}"
            # 소스 파일을 직접 읽어 ast 분석 — mock/patch 불가
            modules = _imported_modules(path)
            assert isinstance(modules, list)
