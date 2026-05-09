# -*- coding: utf-8 -*-
"""
업종분류 커스텀 데이터 관리 모듈.

사용자가 커스텀한 업종 분류 데이터를 `sector_custom.json`에 별도 저장/관리.
Coalesce_Save 패턴(threading.Lock + snapshot copy + executor thread)으로
메인 asyncio 이벤트 루프 블로킹 없이 파일 저장.

책임:
  1. load_custom_data()  -- JSON 파싱 + 스키마 검증
  2. save_custom_data()  -- Coalesce_Save 패턴 저장
  3. rename_sector()     -- 업종명 변경
  4. create_sector()     -- 신규 업종 등록
  5. delete_sector()     -- 업종 삭제
  6. move_stock()        -- 종목 업종 이동
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CUSTOM_FILE = _DATA_DIR / "sector_custom.json"

_lock = threading.Lock()

# ── Coalesce_Save 플래그 ──────────────────────────────────────────────
_save_pending: bool = False
_save_running: bool = False


# ── 데이터 모델 ──────────────────────────────────────────────────────
@dataclass
class SectorCustomData:
    """사용자 커스텀 업종 분류 데이터."""
    sectors: dict[str, str] = field(default_factory=dict)
    """업종명 변경 매핑 {원래이름: 새이름}"""
    stock_moves: dict[str, str] = field(default_factory=dict)
    """종목코드 → 대상 업종 (커스텀 이동) {stock_code: target_sector}"""
    deleted_sectors: list[str] = field(default_factory=list)
    """삭제된 업종명 목록"""


# ── 인메모리 캐시 ────────────────────────────────────────────────────
_custom_data: SectorCustomData = SectorCustomData()
_loaded: bool = False


# ── 직렬화 / 역직렬화 ────────────────────────────────────────────────

def _serialize(data: SectorCustomData) -> dict:
    """SectorCustomData → JSON-serializable dict."""
    return {
        "sectors": dict(data.sectors),
        "stock_moves": dict(data.stock_moves),
        "deleted_sectors": list(data.deleted_sectors),
    }


def _deserialize(raw: dict) -> SectorCustomData:
    """dict → SectorCustomData. 스키마 검증 포함.

    필수 키 누락 또는 타입 오류 시 경고 로그 + 빈 데이터 폴백.
    """
    if not isinstance(raw, dict):
        _log.warning("[커스텀업종] 스키마 오류: 최상위가 dict가 아님 → 빈 데이터 폴백")
        return SectorCustomData()

    sectors = raw.get("sectors")
    stock_moves = raw.get("stock_moves")
    deleted_sectors = raw.get("deleted_sectors")

    # 필수 키 존재 검증
    missing = []
    if "sectors" not in raw:
        missing.append("sectors")
    if "stock_moves" not in raw:
        missing.append("stock_moves")
    if "deleted_sectors" not in raw:
        missing.append("deleted_sectors")
    if missing:
        _log.warning("[커스텀업종] 스키마 오류: 필수 키 누락 %s → 빈 데이터 폴백", missing)
        return SectorCustomData()

    # 타입 검증
    if not isinstance(sectors, dict):
        _log.warning("[커스텀업종] 스키마 오류: sectors가 dict가 아님 → 빈 데이터 폴백")
        return SectorCustomData()
    if not isinstance(stock_moves, dict):
        _log.warning("[커스텀업종] 스키마 오류: stock_moves가 dict가 아님 → 빈 데이터 폴백")
        return SectorCustomData()
    if not isinstance(deleted_sectors, list):
        _log.warning("[커스텀업종] 스키마 오류: deleted_sectors가 list가 아님 → 빈 데이터 폴백")
        return SectorCustomData()

    # 값 타입 검증 (dict 내부 key/value가 str인지)
    for k, v in sectors.items():
        if not isinstance(k, str) or not isinstance(v, str):
            _log.warning("[커스텀업종] 스키마 오류: sectors 내부 타입 오류 → 빈 데이터 폴백")
            return SectorCustomData()
    for k, v in stock_moves.items():
        if not isinstance(k, str) or not isinstance(v, str):
            _log.warning("[커스텀업종] 스키마 오류: stock_moves 내부 타입 오류 → 빈 데이터 폴백")
            return SectorCustomData()
    for item in deleted_sectors:
        if not isinstance(item, str):
            _log.warning("[커스텀업종] 스키마 오류: deleted_sectors 내부 타입 오류 → 빈 데이터 폴백")
            return SectorCustomData()

    return SectorCustomData(
        sectors=dict(sectors),
        stock_moves=dict(stock_moves),
        deleted_sectors=list(deleted_sectors),
    )


# ── 파일 I/O ─────────────────────────────────────────────────────────

def _load_from_file() -> SectorCustomData:
    """JSON 파일에서 커스텀 데이터 로드. 파일 없음/파싱 실패 시 빈 데이터 반환."""
    if not _CUSTOM_FILE.exists():
        return SectorCustomData()
    try:
        with open(_CUSTOM_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return _deserialize(raw)
    except json.JSONDecodeError as e:
        _log.warning("[커스텀업종] JSON 파싱 실패: %s → 빈 데이터 폴백", e)
        return SectorCustomData()
    except Exception as e:
        _log.warning("[커스텀업종] 파일 로드 실패: %s → 빈 데이터 폴백", e)
        return SectorCustomData()


def _save_to_file(data_dict: dict) -> None:
    """dict → JSON 파일 저장. executor thread에서 호출."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CUSTOM_FILE, "w", encoding="utf-8") as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log.error("[커스텀업종] 파일 저장 실패: %s", e)


def _schedule_save(snapshot: dict) -> None:
    """Coalesce_Save: 파일 저장을 asyncio executor thread로 위임.

    _lock 밖에서 호출. snapshot은 이미 복사된 dict.
    동시 실행 방지 (coalesce): pending 플래그로 최신 snapshot만 저장.
    """
    global _save_pending, _save_running, _pending_snapshot
    with _lock:
        _save_pending = True
        _pending_snapshot = snapshot
        if _save_running:
            return
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _coalesced_save)
    except RuntimeError:
        # asyncio 루프 없음 (테스트 등) → 동기 저장
        with _lock:
            _save_pending = False
        _save_to_file(snapshot)


_pending_snapshot: dict = {}


def _coalesced_save() -> None:
    """pending 플래그가 True인 동안 반복 저장. 동시 실행 1개 보장."""
    global _save_pending, _save_running, _pending_snapshot
    with _lock:
        _save_running = True
    try:
        while True:
            with _lock:
                if not _save_pending:
                    break
                _save_pending = False
                snap = _pending_snapshot
            _save_to_file(snap)
    finally:
        with _lock:
            _save_running = False


# ── 공개 API ─────────────────────────────────────────────────────────

def load_custom_data() -> SectorCustomData:
    """커스텀 데이터 로드 (캐시 우선). 스키마 검증 포함."""
    global _custom_data, _loaded
    with _lock:
        if _loaded:
            return copy.deepcopy(_custom_data)
    # lock 밖에서 파일 I/O (블로킹 최소화)
    data = _load_from_file()
    with _lock:
        _custom_data = data
        _loaded = True
        return copy.deepcopy(_custom_data)


def load_custom_data_readonly() -> SectorCustomData:
    """커스텀 데이터 읽기 전용 참조 반환 (deepcopy 없음).

    반환된 객체를 절대 수정하지 말 것. 읽기 전용 조회(get_merged_sector 등)에서만 사용.
    """
    global _custom_data, _loaded
    with _lock:
        if _loaded:
            return _custom_data
    data = _load_from_file()
    with _lock:
        _custom_data = data
        _loaded = True
        return _custom_data


def save_custom_data(data: SectorCustomData) -> None:
    """커스텀 데이터 저장 (Coalesce_Save 패턴).

    1. _lock 획득 → 인메모리 갱신 + snapshot 복사
    2. _lock 해제 → executor thread에서 파일 저장
    메인 asyncio 이벤트 루프 블로킹 없음.
    """
    with _lock:
        global _custom_data, _loaded
        _custom_data = copy.deepcopy(data)
        _loaded = True
        snapshot = _serialize(_custom_data)
    _schedule_save(snapshot)


def _get_all_known_sectors() -> set[str]:
    """Custom_Data에서 알려진 모든 업종명 집합.

    수집 소스: sectors keys + sectors values + stock_moves values
    → deleted_sectors 제거.
    중복 검증용. _lock 내부에서 호출하지 않음.
    """
    with _lock:
        data = copy.deepcopy(_custom_data) if _loaded else SectorCustomData()

    result: set[str] = set()
    result.update(data.sectors.keys())
    result.update(data.sectors.values())
    result.update(data.stock_moves.values())

    # deleted_sectors 제외
    result -= set(data.deleted_sectors)

    return result


# ── 비즈니스 로직 ────────────────────────────────────────────────────

def rename_sector(old_name: str, new_name: str) -> SectorCustomData:
    """업종명 변경. old_name → new_name 매핑을 sectors에 기록.

    검증:
    - new_name이 이미 존재하는 업종명이면 ValueError
    - old_name이 deleted_sectors에 있으면 ValueError

    Returns: 변경 후 SectorCustomData (deepcopy)
    """
    new_name = new_name.strip()
    old_name = old_name.strip()
    if not new_name:
        raise ValueError("새 업종명이 비어있습니다")
    if not old_name:
        raise ValueError("기존 업종명이 비어있습니다")
    if old_name == new_name:
        raise ValueError("기존 업종명과 새 업종명이 동일합니다")

    data = load_custom_data()

    # 삭제된 업종 검증
    if old_name in data.deleted_sectors:
        raise ValueError(f"삭제된 업종은 이름을 변경할 수 없습니다: {old_name}")

    # 중복 검증: new_name이 이미 존재하는지
    known = _get_all_known_sectors()
    if new_name in known:
        raise ValueError(f"이미 존재하는 업종명입니다: {new_name}")

    # deleted_sectors에서 new_name 제거 (삭제된 업종명으로 리네임 시)
    if new_name in data.deleted_sectors:
        data.deleted_sectors.remove(new_name)

    # rename: 원본 key 제거 + 새 이름으로 덮어쓰기
    # 프론트엔드 = 백엔드 거울 원칙: 사용자가 보는 이름만 저장
    for key, val in list(data.sectors.items()):
        if val == old_name:
            del data.sectors[key]
    if old_name in data.sectors:
        del data.sectors[old_name]
    data.sectors[new_name] = new_name

    # stock_moves에서 old_name을 target으로 가진 항목도 new_name으로 갱신
    for code, target in list(data.stock_moves.items()):
        if target == old_name:
            data.stock_moves[code] = new_name

    save_custom_data(data)
    _log.info("[커스텀업종] 업종명 변경: %s → %s", old_name, new_name)
    return load_custom_data()


def create_sector(name: str) -> SectorCustomData:
    """신규 업종 등록.

    검증:
    - name이 이미 존재하는 업종명이면 ValueError

    sectors에 {name: name} 형태로 기록 (자기 자신 매핑 = 신규 생성 마커).

    Returns: 변경 후 SectorCustomData (deepcopy)
    """
    name = name.strip()
    if not name:
        raise ValueError("업종명이 비어있습니다")

    data = load_custom_data()

    # 중복 검증
    known = _get_all_known_sectors()
    if name in known:
        raise ValueError(f"이미 존재하는 업종명입니다: {name}")

    # deleted_sectors에서 name 제거 (삭제된 업종명 재생성 시)
    if name in data.deleted_sectors:
        data.deleted_sectors.remove(name)

    # 신규 업종 마커: sectors에 자기 자신 매핑
    data.sectors[name] = name

    save_custom_data(data)
    _log.info("[커스텀업종] 신규 업종 생성: %s", name)
    return load_custom_data()


def delete_sector(name: str) -> SectorCustomData:
    """업종 삭제. deleted_sectors에 추가.

    검증:
    - 이미 삭제된 업종이면 ValueError

    Returns: 변경 후 SectorCustomData (deepcopy)
    """
    name = name.strip()
    if not name:
        raise ValueError("업종명이 비어있습니다")

    data = load_custom_data()

    if name in data.deleted_sectors:
        raise ValueError(f"이미 삭제된 업종입니다: {name}")

    # 삭제된 업종에 속한 종목들을 stock_moves에서 제거 (데이터 정합성 확보)
    stocks_to_remove = [code for code, sector in data.stock_moves.items() if sector == name]
    for code in stocks_to_remove:
        del data.stock_moves[code]

    data.deleted_sectors.append(name)

    save_custom_data(data)
    _log.info("[커스텀업종] 업종 삭제: %s (종목 %d개 매핑 해제)", name, len(stocks_to_remove))
    return load_custom_data()


def move_stock(stock_code: str, target_sector: str) -> SectorCustomData:
    """종목을 다른 업종으로 이동. stock_moves에 기록.

    검증:
    - target_sector가 deleted_sectors에 있으면 ValueError

    Returns: 변경 후 SectorCustomData (deepcopy)
    """
    stock_code = stock_code.strip()
    target_sector = target_sector.strip()
    if not stock_code:
        raise ValueError("종목코드가 비어있습니다")
    if not target_sector:
        raise ValueError("대상 업종명이 비어있습니다")

    data = load_custom_data()

    # 삭제된 업종으로 이동 거부
    if target_sector in data.deleted_sectors:
        raise ValueError(f"삭제된 업종으로 이동할 수 없습니다: {target_sector}")

    data.stock_moves[stock_code] = target_sector

    save_custom_data(data)
    _log.info("[커스텀업종] 종목 이동: %s → %s", stock_code, target_sector)
    return load_custom_data()
