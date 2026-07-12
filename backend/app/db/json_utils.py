"""JSON 필드 encode/decode 유틸리티

Repository Boundary 단일화 원칙:
- DB 레이어 밖으로 나가는 순간 이미 Python 타입이어야 한다
- repository 내부에서만 json.loads/json.dumps 사용
- 서비스 레이어는 SQLite 저장 형식 절대 몰라야 함
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def encode_json_field(value: Any) -> str:
    """Python 객체를 JSON 문자열로 인코딩"""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception as e:
        logger.error("[시스템] 인코딩 실패: %s", e)
        raise


def decode_json_field(text: str | None, expected_type: type = dict) -> Any:
    """JSON 문자열을 Python 객체로 디코딩
    
    Repository Boundary: 타입 계약 강제. silent fallback 금지.
    
    Args:
        text: JSON 문자열 (None 불가 - 빈 문자열도 예외 발생)
        expected_type: 기대하는 타입 (dict, list 등)
    
    Returns:
        디코딩된 Python 객체
    
    Raises:
        ValueError: None/빈 문자열 또는 타입 불일치 시
        json.JSONDecodeError: JSON 파싱 실패 시
    """
    if text is None or text == "":
        # None이나 빈 문자열인 경우 즉시 예외 발생 (silent fallback 금지)
        raise ValueError(
            f"[시스템] JSON 데이터가 None 또는 빈 문자열입니다. "
            f"기대 타입: {expected_type.__name__}"
        )
    
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("[시스템] JSON 해석 실패: %s (본문=%s)", e, text[:100])
        raise
    
    # 타입 검증
    if not isinstance(decoded, expected_type):
        raise ValueError(
            f"[시스템] 타입 불일치: 기대 {expected_type.__name__}, "
            f"실제 {type(decoded).__name__} (value={decoded})"
        )
    
    return decoded
