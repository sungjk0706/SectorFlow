"""httpx Mock 공통 테스트 헬퍼.

키움·LS REST 클라이언트 테스트(test_kiwoom_rest/test_ls_rest/test_kiwoom_order)에서
공통으로 사용하던 _mock_httpx_response/_mock_httpx_client 중복 정의를 통합 (D-03, P10/P23/P24).

- mock_httpx_response: httpx.Response mock 생성
- mock_httpx_client: httpx.AsyncClient mock 생성 (post/get 사이드 이펙트·반환값, is_closed, 컨텍스트 매니저 옵션)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def mock_httpx_response(status_code=200, json_data=None, text="", headers=None):
    """httpx.Response mock 생성.

    - status_code: HTTP 응답 코드 (기본 200)
    - json_data: resp.json() 반환값 (기본 {})
    - text: resp.text 값 (기본: json_data 있으면 "{}", 없으면 "")
    - headers: resp.headers 값 (기본 {})
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or ("{}" if json_data else "")
    resp.headers = headers or {}
    return resp


def mock_httpx_client(
    post_side_effect=None,
    post_return=None,
    get_side_effect=None,
    get_return=None,
    is_closed=False,
    as_context_manager=False,
):
    """httpx.AsyncClient mock 생성.

    - post_side_effect/post_return: client.post 설정 (둘 중 하나만 사용)
    - get_side_effect/get_return: client.get 설정 (둘 중 하나만 사용)
    - is_closed: client.is_closed 속성 값 (기본 False)
    - as_context_manager: True면 __aenter__/__aexit__ 추가 (async with 지원, kiwoom_order _send_request용)
    """
    client = AsyncMock()
    client.is_closed = is_closed
    if post_side_effect:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=post_return)
    if get_side_effect:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return)
    client.aclose = AsyncMock()
    if as_context_manager:
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
    return client
