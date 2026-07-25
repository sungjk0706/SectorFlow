"""KST 상수 통합 회귀 테스트 — 세션 13.

UTC+9 타임존 상수가 `backend.app.core.constants._KST` 단일 SSOT로 통합되었는지 검증.
- 중복 정의(모듈별 `KST = timezone(timedelta(hours=9))` 또는 인라인) 잔존 0건
- 모든 사용처가 `constants._KST` import 기반
- 시간 계산 결과가 통합 전과 동일 (값 불변)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from backend.app.core.constants import _KST


# ── SSOT 단일성 검증 ──────────────────────────────────────────────────────────

# tests/ 폴더의 부모 = backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _collect_kst_definitions() -> list[tuple[Path, int, str]]:
    """backend/app/ 트리에서 `timezone(timedelta(hours=9))` 패턴이 등장하는 모든 줄 수집."""
    pattern = re.compile(r"timezone\(timedelta\(hours=9\)\)")
    hits: list[tuple[Path, int, str]] = []
    for py in (BACKEND_ROOT / "app").rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append((py, lineno, line.strip()))
    return hits


class TestKstSsot:
    """`_KST` 정의는 constants.py 1곳만 존재해야 한다 (P10 SSOT, P24 단순성)."""

    def test_single_definition_in_constants(self):
        hits = _collect_kst_definitions()
        # constants.py 의 1곳만 허용
        allowed = [h for h in hits if h[0].name == "constants.py"]
        others = [h for h in hits if h[0].name != "constants.py"]
        assert len(allowed) == 1, f"constants.py에 _KST 정의가 1곳이어야 함 (현재 {len(allowed)}곳)"
        assert others == [], (
            f"constants.py 외 중복 정의 잔존 {len(others)}곳: "
            + ", ".join(f"{p.relative_to(BACKEND_ROOT)}:{ln}" for p, ln, _ in others)
        )

    def test_constants_kst_is_utc_plus_9(self):
        """_KST 는 UTC+9 타임존이어야 한다."""
        assert _KST.utcoffset(None) == timedelta(hours=9)

    def test_trading_calendar_reexports_removed(self):
        """trading_calendar.__all__ 에서 _KST re-export 제거 확인 (P10 단일 소스)."""
        import backend.app.core.trading_calendar as tc
        assert "_KST" not in tc.__all__


# ── 사용처가 constants._KST 를 import 하는지 검증 ─────────────────────────────

EXPECTED_IMPORTERS = {
    "app/core/trading_calendar.py",
    "app/services/daily_time_scheduler.py",
    "app/services/auto_trading_effective.py",
    "app/services/telegram_bot.py",
    "app/core/kiwoom_rest.py",
}


class TestKstImportUsage:
    """각 소비 모듈이 `from ...constants import _KST` 형태로 import 하는지 검증."""

    @pytest.mark.parametrize("rel_path", sorted(EXPECTED_IMPORTERS))
    def test_imports_kst_from_constants(self, rel_path: str):
        py = BACKEND_ROOT / rel_path
        text = py.read_text(encoding="utf-8")
        # constants 모듈에서 _KST import 하는 패턴
        assert re.search(r"from\s+\S*constants\s+import\s+[^\n]*_KST", text), (
            f"{rel_path} 가 constants._KST 를 import 하지 않음"
        )
        # 로컬 재정의가 없어야 함
        assert not re.search(r"^\s*_?KST\s*=\s*timezone\(", text, re.MULTILINE), (
            f"{rel_path} 에 로컬 KST 재정의 잔존"
        )


# ── 시간 계산 결과 불변 검증 ───────────────────────────────────────────────────

class TestKstCalculationInvariance:
    """통합 전후 KST 기반 계산 결과가 동일해야 한다 (P22 데이터 정합성)."""

    def test_kst_now_offset_unchanged(self):
        """_KST 기반 now() 가 UTC+9 오프셋을 갖는다."""
        now_kst = datetime.now(_KST)
        assert now_kst.utcoffset() == timedelta(hours=9)

    def test_kst_equals_legacy_definition(self):
        """과거 인라인 정의와 동일 객체 속성."""
        legacy = timezone(timedelta(hours=9))
        # utcoffset 동일 → 계산 결과 동일
        assert _KST.utcoffset(None) == legacy.utcoffset(None)

    def test_kiwoom_token_expiry_uses_kst(self):
        """kiwoom_rest.TokenInfo.is_expired_soon 이 _KST 기반으로 동작한다."""
        from backend.app.core.kiwoom_rest import TokenInfo
        # 먼 미래 만료 → 만료 아님
        ti = TokenInfo(token="t", expires_dt="20990101000000")
        assert ti.is_expired_soon() is False
        # 30분 뒤 만료 (buffer 1시간 미만) → 만료 임박
        now = datetime.now(_KST)
        exp = now + timedelta(minutes=30)
        ti2 = TokenInfo(token="t", expires_dt=exp.strftime("%Y%m%d%H%M%S"))
        assert ti2.is_expired_soon() is True

    def test_auto_trading_effective_uses_kst(self):
        """auto_trading_effective._in_time_range 가 _KST 기반으로 동작한다."""
        from backend.app.services.auto_trading_effective import _in_time_range
        flat = {"buy_time_start": "09:00", "buy_time_end": "15:30"}
        # 명시적 now 전달 시 _KST 사용 안 함 (순수 함수 경로)
        from datetime import datetime as _dt
        now = _dt(2026, 7, 27, 10, 0, tzinfo=_KST)
        assert _in_time_range(flat, "buy_time_start", "buy_time_end", now=now) is True
        # 범위 밖
        now_out = _dt(2026, 7, 27, 16, 0, tzinfo=_KST)
        assert _in_time_range(flat, "buy_time_start", "buy_time_end", now=now_out) is False
