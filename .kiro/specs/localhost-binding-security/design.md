# Localhost Binding Security Bugfix Design

## Overview

백엔드 서버(`main.py`)가 `host="0.0.0.0"`으로, 프론트엔드 Vite 개발 서버(`vite.config.ts`)가 `host: true`로 설정되어 모든 네트워크 인터페이스에서 외부 접근이 가능한 보안 취약점이다. 수정은 두 파일의 호스트 바인딩을 각각 `127.0.0.1`과 `localhost`로 변경하여 로컬 루프백 인터페이스에서만 접속을 허용하도록 제한한다.

## Glossary

- **Bug_Condition (C)**: 서버가 `0.0.0.0`에 바인딩되어 외부 IP에서의 요청을 수락하는 조건
- **Property (P)**: 외부 IP에서의 요청이 OS 네트워크 스택 레벨에서 거부되는 동작
- **Preservation**: 로컬 접근(`localhost`, `127.0.0.1`)을 통한 모든 기존 기능이 동일하게 동작
- **uvicorn**: `main.py`에서 FastAPI 앱을 실행하는 ASGI 서버 (포트 8000)
- **Vite dev server**: `frontend/vite.config.ts`에서 설정된 프론트엔드 개발 서버 (포트 5173)
- **루프백 인터페이스**: `127.0.0.1` / `localhost` — 로컬 머신에서만 접근 가능한 네트워크 인터페이스

## Bug Details

### Bug Condition

서버가 `0.0.0.0`(모든 인터페이스)에 바인딩되어 있어, 외부 네트워크의 임의 IP에서 포트 8000 또는 5173으로 접속이 가능하다. 실제 공격 로그에서 외부 IP(66.132.195.78)의 접근 시도가 확인되었다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type NetworkRequest
  OUTPUT: boolean
  
  RETURN input.source_ip ≠ "127.0.0.1"
         AND input.destination_port IN [8000, 5173]
         AND server_bind_address = "0.0.0.0"
END FUNCTION
```

### Examples

- 외부 IP `66.132.195.78`에서 `http://<server-ip>:8000/` 요청 → 현재: 200 OK 응답 / 기대: 연결 거부
- 외부 IP `192.168.1.100`에서 `http://<server-ip>:8000/api/health` 요청 → 현재: 정상 응답 / 기대: 연결 거부
- 외부 IP에서 `http://<server-ip>:5173` 요청 → 현재: 프론트엔드 페이지 노출 / 기대: 연결 거부
- 로컬 `http://localhost:8000/health` 요청 → 현재: 정상 응답 / 기대: 동일하게 정상 응답 (변경 없음)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `http://localhost:8000`을 통한 모든 API 요청이 정상 동작해야 한다
- `http://localhost:5173`을 통한 프론트엔드 접근이 정상 동작해야 한다
- Vite 프록시(`/api` → `http://localhost:8000`)가 정상 동작해야 한다
- `SectorFlow.command`의 헬스체크(`http://localhost:8000/health`)가 성공해야 한다
- WebSocket 연결(`localhost:8000`)을 통한 실시간 데이터 전송이 정상 동작해야 한다

**Scope:**
`source_ip = "127.0.0.1"` (로컬 루프백)인 모든 요청은 수정 전후 동일하게 동작한다. 영향받는 것은 오직 외부 IP에서의 접근뿐이다.

## Hypothesized Root Cause

명확한 설정 오류이다:

1. **`main.py` line 62**: `uvicorn.run()`의 `host="0.0.0.0"` 설정이 모든 네트워크 인터페이스에서 리스닝하도록 지정함
2. **`frontend/vite.config.ts` line 7**: `host: true` 설정이 Vite에서 `0.0.0.0` 바인딩과 동일하게 동작하여 외부 접근을 허용함

두 설정 모두 개발 편의를 위해 의도적으로 열어둔 것이나, 운영 환경에서는 보안 취약점이 된다.

## Correctness Properties

Property 1: Bug Condition - 외부 접근 차단

_For any_ network request where the source IP is not `127.0.0.1` and the destination port is 8000 or 5173, the fixed server configuration SHALL refuse the connection at the OS network stack level (server not listening on external interfaces).

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - 로컬 접근 유지

_For any_ network request where the source IP is `127.0.0.1` (localhost), the fixed server SHALL produce the same response as the original server, preserving all API, WebSocket, proxy, and static file serving functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

**File**: `main.py`

**Line**: 62 (uvicorn.run의 host 파라미터)

**Change**:
- `host="0.0.0.0"` → `host="127.0.0.1"`

---

**File**: `frontend/vite.config.ts`

**Line**: 7 (server.host 설정)

**Change**:
- `host: true` → `host: 'localhost'`

---

두 변경 모두 단일 라인 수정이며, 로직 변경 없이 바인딩 주소만 제한한다.

## Testing Strategy

### Validation Approach

네트워크 바인딩 변경은 OS 레벨 동작이므로, 단위 테스트보다는 실제 서버 기동 후 연결 테스트가 핵심이다. 설정값 자체의 정적 검증과 실제 바인딩 동작 검증을 병행한다.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 외부 접근이 가능함을 확인하여 버그 존재를 입증한다.

**Test Plan**: 설정 파일의 호스트 바인딩 값을 정적으로 검사하여 `0.0.0.0` 또는 `true`가 사용되고 있음을 확인한다.

**Test Cases**:
1. **Backend Host Check**: `main.py`에서 uvicorn.run의 host 파라미터가 `"0.0.0.0"`인지 확인 (수정 전 실패)
2. **Frontend Host Check**: `vite.config.ts`에서 server.host가 `true`인지 확인 (수정 전 실패)

**Expected Counterexamples**:
- `main.py`: `host="0.0.0.0"` — 모든 인터페이스에서 리스닝
- `vite.config.ts`: `host: true` — 모든 인터페이스에서 리스닝

### Fix Checking

**Goal**: 수정 후 서버가 로컬 루프백에만 바인딩되어 외부 접근이 불가능함을 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := attemptConnection(input.source_ip, input.destination_port)
  ASSERT result = CONNECTION_REFUSED
END FOR
```

**Verification**:
- `main.py`의 host 값이 `"127.0.0.1"`인지 정적 검증
- `vite.config.ts`의 host 값이 `'localhost'`인지 정적 검증
- 서버 기동 후 `netstat`/`lsof`로 바인딩 주소가 `127.0.0.1`임을 확인

### Preservation Checking

**Goal**: 로컬 접근이 수정 전후 동일하게 동작함을 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT server_response_before(input) = server_response_after(input)
END FOR
```

**Testing Approach**: 로컬 루프백 바인딩은 `localhost`/`127.0.0.1` 접근을 보장하므로, 기존 `SectorFlow.command`의 헬스체크 패턴(`curl http://localhost:8000/health`)이 그대로 동작하는지 확인한다.

**Test Cases**:
1. **Backend Local Access**: `http://localhost:8000/health` 요청이 정상 응답하는지 확인
2. **Frontend Local Access**: `http://localhost:5173` 요청이 정상 응답하는지 확인
3. **Proxy Preservation**: Vite 프록시(`/api` → `localhost:8000`)가 정상 동작하는지 확인
4. **WebSocket Preservation**: `ws://localhost:8000/ws` 연결이 정상 수립되는지 확인

### Unit Tests

- `main.py`의 uvicorn.run host 파라미터 값 정적 검증
- `vite.config.ts`의 server.host 값 정적 검증
- `SectorFlow.command`가 `localhost`만 참조하는지 확인 (이미 충족)

### Property-Based Tests

- 임의의 로컬 루프백 주소(`127.0.0.1`, `localhost`, `::1`)에서의 요청이 모두 정상 처리되는지 검증
- 임의의 비-루프백 IP에서의 요청이 모두 거부되는지 검증 (네트워크 바인딩 특성상 설정값 검증으로 대체)

### Integration Tests

- `SectorFlow.command` 스크립트 실행 시 백엔드/프론트엔드 헬스체크 성공 확인
- 브라우저에서 `http://localhost:5173` 접근 후 API 프록시 동작 확인
- WebSocket 연결 수립 및 실시간 데이터 수신 확인
