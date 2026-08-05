"""JSON 직렬화/역직렬화 단일 소스 (P10 SSOT, P23 일관성)

범용 함수:
- dumps(obj): Python 객체 → JSON 문자열 (ensure_ascii=False 기본, sort_keys 옵션)
- loads(text): JSON 문자열 → Python 객체 (타입 검증 없음, WS 수신/파일 파싱용)

DB 전용 함수 (타입 계약 강제):
- encode_json_field(value): DB 저장용 인코딩 (dumps의 별칭)

사용 규칙:
- 모든 json.dumps/json.loads 직접 호출 금지 → 본 모듈 함수 사용
- DB 저장은 encode_json_field 사용
- WS 메시지·파일 파싱 등 범용 처리는 dumps/loads 사용
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def dumps(obj: Any, *, ensure_ascii: bool = False, sort_keys: bool = False) -> str:
    """Python 객체를 JSON 문자열로 인코딩 (범용).

    ensure_ascii=False 기본 — 한글 데이터 유니코드 이스케이프 방지 (P23 일관성).
    에러 발생 시 로깅 후 재발생 (silent fallback 금지, P20).
    """
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
    except (TypeError, ValueError) as e:
        logger.error("[시스템] JSON 인코딩 실패: %s", e)
        raise


def loads(text: str) -> Any:
    """JSON 문자열을 Python 객체로 디코딩 (범용, 타입 검증 없음).

    WS 수신·파일 파싱 등 타입이 가변적인 경우 사용.
    에러 발생 시 로깅 후 재발생 (silent fallback 금지, P20).
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("[시스템] JSON 해석 실패: %s (본문=%s)", e, text[:100])
        raise


def encode_json_field(value: Any) -> str:
    """DB 저장용 JSON 인코딩 (encode 계약). dumps의 별칭."""
    return dumps(value)
