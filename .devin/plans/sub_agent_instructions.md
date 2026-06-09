# SectorFlow 하위 코딩 에이전트용 상세 리팩토링 실행서 (Sub-Agent Instructions)

본 문서는 하위 코딩 에이전트가 SectorFlow의 아키텍처 불변 원칙을 준수하며 버그 수정 및 리팩토링 작업을 안전하게 진행할 수 있도록 작성된 단계별 지침서입니다. 각 단계를 순서대로 수행하고 검증하십시오.

---

## 🏗️ SectorFlow 아키텍처 불변 원칙 (반드시 준수)

1.  **단일 asyncio 이벤트 루프**: 모든 비동기 작업은 단일 루프 내에서 협동적으로 처리되어야 함.
2.  **모든 I/O는 비동기 처리**: 동기 I/O 함수 사용 금지. 외부 요청은 `httpx.AsyncClient` 등을 활용하고 DB 작업은 `aiosqlite`를 통할 것.
3.  **EventBus/발행구독 패턴 사용 금지**: 제어 흐름과 데이터 전달은 명시적인 직접 호출 및 `asyncio.Queue` 파이프라인으로 일원화할 것.
4.  **증권사 하드코딩 금지**: 핵심 비즈니스 로직에 특정 증권사 이름(`kiwoom`, `ls` 등)이 하드코딩되어 나타나지 않도록 `BrokerInterface` 및 `BrokerRegistry`로 완전 추상화할 것.
5.  **단일 소스 진리 (Single Source of Truth)**: 동일 설정 및 상태는 한 곳에서만 관리 및 갱신되어야 함.

---

## 🛠️ 단계별 작업 지시서

### [1단계] 치명적 버그 (P0) 및 잠재적 오류 (P1) 수정

#### 1.1 `daily_time_scheduler.py` 임포트 오류 수정 (P0 #1)
*   **대상 파일**: [daily_time_scheduler.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py)
*   **수정 사항**: `_login_post_pipeline`은 `engine_service`가 아닌 `engine_bootstrap`에 존재함.
*   **변경 코드**:
    ```python
    # 기존 (L814 부근)
    from backend.app.services.engine_service import _login_post_pipeline
    
    # 변경 후
    from backend.app.services.engine_bootstrap import _login_post_pipeline
    ```

#### 1.2 민감 정보 마스킹 및 None 가드 추가 (P0 #2, #3, P1 #4)
*   **대상 파일 1**: [engine_lifecycle.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_lifecycle.py)
*   **수정 사항**: 토큰 평문 로깅을 지양하고 `new_token`이 `None`일 경우의 예외를 가드함.
*   **변경 코드**:
    ```python
    # 기존 (L418 부근)
    _log(f"[연결] 증권사 토큰 재발급 성공! (토큰: {new_token[:10]}...)")
    
    # 변경 후
    if new_token is not None:
        masked = new_token[:4] + "****" + new_token[-2:] if len(new_token) > 6 else "****"
        _log(f"[연결] 증권사 토큰 재발급 성공! (토큰: {masked})")
    else:
        _log("[연결] 증권사 토큰 재발급 성공했으나 토큰 값이 빈 문자열입니다.")
    ```
*   **대상 파일 2**: [engine_account.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account.py)
*   **수정 사항**: 225라인의 토큰 로깅 마스킹 처리.
*   **변경 코드**:
    ```python
    # 기존 (L225 부근)
    token_preview = (_rest_api._token_info.token[:10] + "...") if _rest_api._token_info else "?"
    
    # 변경 후
    if _rest_api._token_info and _rest_api._token_info.token:
        t = _rest_api._token_info.token
        token_preview = t[:4] + "****" + t[-2:] if len(t) > 6 else "****"
    else:
        token_preview = "?"
    ```

#### 1.3 텔레그램 메시지 전송 예외 로깅 추가 (P1 #6)
*   **대상 파일**: [telegram.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/telegram.py)
*   **수정 사항**: 동기 전송 함수 `send_msg`에서 예외 발생 시 디버깅을 위해 로깅을 남기도록 변경.
*   **변경 코드**:
    ```python
    # 기존 (L41 부근)
    except Exception:
        return False
        
    # 변경 후
    except Exception as e:
        logger.warning("[텔레그램] 메시지 동기 전송 실패: %s", e, exc_info=True)
        return False
    ```

#### 1.4 설정 로드 실패 시 명시적 거부 (P1 #7)
*   **대상 파일**: [config.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/config.py)
*   **수정 사항**: 환경 변수 로드에 완전 실패했을 때 빈 설정 객체로 계속 진행하는 위험을 차단하고, 로깅 레벨을 `error`로 높이며 시스템 기동 실패를 명시함.
*   **변경 코드**:
    ```python
    # 기존 (L74 부근)
    @lru_cache()
    def get_settings() -> Settings:
        try:
            return Settings()
        except Exception as e:
            logger.error("[설정] 설정값 로드 실패함: %s", e)
            return Settings.model_construct(ENCRYPTION_KEY="")
            
    # 변경 후
    @lru_cache()
    def get_settings() -> Settings:
        try:
            return Settings()
        except Exception as e:
            logger.critical("[설정] 시스템 설정값 로드에 실패하여 구동을 일시 중단합니다: %s", e)
            raise RuntimeError("시스템 필수 환경 변수(.env) 로드 실패") from e
    ```

---

### [2단계] 계층 역전 (core ➔ services) 해소 및 상태 통합

#### 2.1 `settings_store.py` 의존성 역전 수정 (P1 #20)
*   **대상 파일**: [settings_store.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/core/settings_store.py)
*   **해결 아이디어**: `settings_store.py`가 직접 `engine_service` 모듈을 임포트하는 의존성 관계를 끊습니다. 설정 변경 이벤트를 발생시키고, 서비스 계층에서 콜백을 등록하는 옵서버 패턴과 유사하게 수정합니다.
*   **구현 방법**:
    1.  `settings_store.py` 상단의 `from backend.app.services import engine_service` 임포트를 제거합니다.
    2.  `settings_store.py` 모듈 내에 콜백 리스트를 선언합니다:
        ```python
        from typing import Callable, Any, Coroutine
        
        _on_settings_changed_callbacks: list[Callable[[dict, set[str]], Coroutine[Any, Any, None]]] = []
        
        def register_settings_change_callback(cb: Callable[[dict, set[str]], Coroutine[Any, Any, None]]):
            """서비스 계층에서 설정 갱신 콜백을 등록하기 위한 함수"""
            if cb not in _on_settings_changed_callbacks:
                _on_settings_changed_callbacks.append(cb)
        ```
    3.  `update_settings` 또는 설정 수정 시점의 기존 `engine_service` 호출 블록들을 모두 `_on_settings_changed_callbacks` 순회 호출로 치환합니다.
        ```python
        # 예시
        for cb in _on_settings_changed_callbacks:
            asyncio.create_task(cb(settings_dict, changed_keys))
        ```
    4.  [engine_bootstrap.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_bootstrap.py)의 초기화 단계에서 콜백 함수를 등록해 줍니다.
        ```python
        from backend.app.core.settings_store import register_settings_change_callback
        
        async def handle_settings_changed(new_settings: dict, changed_keys: set[str]):
            # 기존 settings_store.py에서 호출하던 로직들을 engine_service 내의 로직으로 매핑
            pass
            
        # 부트스트랩 시점에 등록
        register_settings_change_callback(handle_settings_changed)
        ```

#### 2.2 전역 상태 `EngineState` 단일 객체화 (P1 #21)
*   **대상 파일**: [engine_state.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_state.py) ➔ [engine_state_holder.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_state_holder.py) [NEW]
*   **수정 사항**: `engine_state.py`의 수십 개 전역 변수를 클래스 기반 Singleton 인스턴스로 바인딩합니다.
*   **구현 예시**:
    ```python
    # backend/app/services/engine_state_holder.py
    class EngineStateHolder:
        _instance = None
        
        def __new__(cls, *args, **kwargs):
            if not cls._instance:
                cls._instance = super().__new__(cls, *args, **kwargs)
                cls._instance._init_state()
            return cls._instance
            
        def _init_state(self):
            self.running = False
            self.login_ok = False
            self.access_token = None
            self.integrated_settings = {}
            self.positions = []
            # ...기존 engine_state.py의 변수들을 인스턴스 변수로 마이그레이션
    
    engine_state = EngineStateHolder()
    ```
*   기존 다른 모듈들(`engine_lifecycle.py`, `daily_time_scheduler.py` 등)의 `from backend.app.services.engine_state import _running` 참조 코드들을 `from backend.app.services.engine_state_holder import engine_state` 및 `engine_state.running` 형식으로 정밀하게 전환하십시오.

---

### [3단계] 중복 제거 및 미사용 코드 삭제

#### 3.1 `engine_account_notify.py` 브로드캐스트 패턴 중복 해결 (P1 #9)
*   **대상 파일**: [engine_account_notify.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py)
*   **수정 사항**: 각 `notify_*` 함수마다 들어가는 `try-except-log` 중복 코드를 리팩토링합니다.
*   **구현 방법**:
    ```python
    def safe_broadcast(event_type: str):
        """안전한 브로드캐스트 전송을 보장하는 데코레이터"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                try:
                    payload = func(*args, **kwargs)
                    if payload is not None:
                        _broadcast(event_type, payload)
                except Exception as e:
                    logger.warning(f"[데이터] {event_type} 화면전송 실패: {e}", exc_info=True)
            return wrapper
        return decorator
    ```
    이 데코레이터를 사용하여 중복 예외 스 swallow 패턴을 일관되게 제거하십시오.

#### 3.2 미사용 레거시 파일 영구 삭제 (P1 #13, P2 #18)
*   **삭제 대상 파일**:
    1.  [events.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/core/events.py) (내부의 `EventType` 및 `BrokerType`은 `state_manager.py`로 마이그레이션한 후 파일 삭제)
    2.  [drop_legacy_settings_tables.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/db/drop_legacy_settings_tables.py) (일회성 마이그레이션 완료 파일이므로 완전 제거)

---

## 🧪 검증 및 빌드 단계

각 수정 단계를 완수할 때마다 아래 명령을 실행하여 구문 오류가 유입되지 않았는지 철저하게 테스트하십시오.

```bash
# 1. 수정한 파이썬 소스 코드들의 문법 오류(Syntax Error) 검사
python -m py_compile backend/app/services/daily_time_scheduler.py
python -m py_compile backend/app/services/engine_lifecycle.py
python -m py_compile backend/app/core/settings_store.py

# 2. 전체 백엔드 테스트 실행
pytest backend/tests/
```
