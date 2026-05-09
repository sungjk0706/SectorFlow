# -*- coding: utf-8 -*-
"""
단일 진실 공급원 (Single Source of Truth) -- 증권사 URL 레지스트리

모든 WebSocket / REST / Token 엔드포인트는 이 파일에서만 정의한다.
다른 파일에서는 이 모듈의 상수·함수를 import 해서 사용한다.

증권사 추가 시: _BROKER_URL_DEFAULTS dict에 한 줄만 추가하면 됨.
settings.json의 broker_urls 섹션으로 런타임 오버라이드 가능.
"""

# ── 증권사별 기본 URL (코드 내 유일한 정의 지점) ──────────────────────────
_BROKER_URL_DEFAULTS: dict[str, dict[str, str]] = {
    "kiwoom": {
        "rest_base":  "https://api.kiwoom.com",
        "ws_uri":     "wss://api.kiwoom.com:10000/api/dostk/websocket",
        "token_path": "/oauth2/token",
    },
}

# ── 하위 호환 상수 (기존 import 깨지지 않도록 유지) ───────────────────────
KIWOOM_REST_BASE  = _BROKER_URL_DEFAULTS["kiwoom"]["rest_base"]
KIWOOM_WS_URI     = _BROKER_URL_DEFAULTS["kiwoom"]["ws_uri"]
KIWOOM_TOKEN_PATH = _BROKER_URL_DEFAULTS["kiwoom"]["token_path"]
KIWOOM_REST_REAL  = KIWOOM_REST_BASE

# ── 증권사별 표시 이름 ────────────────────────────────────────────────────
BROKER_DISPLAY_NAMES: dict[str, str] = {
    "kiwoom": "키움증권",
}


def build_broker_urls(broker: str, settings: dict | None = None) -> dict:
    """
    증권사의 모든 통신 URL을 반환한다.

    우선순위:
    1. settings["broker_urls"][broker] (런타임 오버라이드)
    2. _BROKER_URL_DEFAULTS[broker] (코드 기본값)

    반환 딕셔너리 키:
        rest_base  : REST API 기본 도메인 (프로토콜 포함, 말미 슬래시 없음)
        ws_uri     : WebSocket 접속 URI (wss://...)
        token_url  : OAuth2 토큰 발급 전체 URL
    """
    broker = (broker or "kiwoom").strip().lower()

    # 1. settings에서 오버라이드 확인
    urls = None
    if settings:
        broker_urls_cfg = settings.get("broker_urls") or {}
        urls = broker_urls_cfg.get(broker)

    # 2. 코드 기본값 폴백
    if not urls:
        urls = _BROKER_URL_DEFAULTS.get(broker)

    if not urls:
        raise ValueError(f"[broker_urls] 지원하지 않는 증권사: {broker!r}")

    rest_base  = urls["rest_base"]
    ws_uri     = urls["ws_uri"]
    token_path = urls.get("token_path", "/oauth2/token")

    return {
        "rest_base": rest_base,
        "ws_uri":    ws_uri,
        "token_url": rest_base + token_path,
    }
