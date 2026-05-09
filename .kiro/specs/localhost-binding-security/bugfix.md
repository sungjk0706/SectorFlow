# Bugfix Requirements Document

## Introduction

백엔드 서버(`main.py`)가 `host="0.0.0.0"`으로 바인딩되어 모든 네트워크 인터페이스에서 접근 가능한 상태이며, 프론트엔드 Vite 개발 서버(`vite.config.ts`)도 `host: true` 설정으로 외부에 노출되어 있다. 실제 공격 로그에서 외부 IP(예: 66.132.195.78)가 `/`, `/login` 등 엔드포인트에 접근을 시도한 것이 확인되었다. 이는 로컬 개발/운영 환경에서 심각한 보안 취약점이다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN uvicorn이 `host="0.0.0.0"`으로 실행될 때 THEN the system은 모든 네트워크 인터페이스(외부 IP 포함)에서 포트 8000으로의 접속을 수락한다
1.2 WHEN Vite 개발 서버가 `host: true`로 설정될 때 THEN the system은 모든 네트워크 인터페이스(외부 IP 포함)에서 포트 5173으로의 접속을 수락한다
1.3 WHEN 외부 IP에서 백엔드 API 또는 프론트엔드에 요청이 도달할 때 THEN the system은 해당 요청을 정상적으로 처리하여 응답한다

### Expected Behavior (Correct)

2.1 WHEN uvicorn이 실행될 때 THEN the system SHALL `host="127.0.0.1"`로 바인딩하여 로컬 루프백 인터페이스에서만 접속을 수락한다
2.2 WHEN Vite 개발 서버가 실행될 때 THEN the system SHALL `host: 'localhost'`로 바인딩하여 로컬 루프백 인터페이스에서만 접속을 수락한다
2.3 WHEN 외부 IP에서 포트 8000 또는 5173으로 요청이 시도될 때 THEN the system SHALL 연결을 거부한다 (서버가 해당 인터페이스에서 리스닝하지 않으므로)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 로컬 머신에서 `http://localhost:8000`으로 요청할 때 THEN the system SHALL CONTINUE TO 정상적으로 API 응답을 반환한다
3.2 WHEN 로컬 머신에서 `http://localhost:5173`으로 요청할 때 THEN the system SHALL CONTINUE TO 프론트엔드 페이지를 정상적으로 제공한다
3.3 WHEN 프론트엔드 Vite 프록시가 `/api` 요청을 `http://localhost:8000`으로 전달할 때 THEN the system SHALL CONTINUE TO 프록시가 정상 동작한다
3.4 WHEN `SectorFlow.command` 스크립트가 `http://localhost:8000/health`로 헬스체크할 때 THEN the system SHALL CONTINUE TO 헬스체크가 성공한다
3.5 WHEN WebSocket 연결이 `localhost:8000`을 통해 수립될 때 THEN the system SHALL CONTINUE TO 실시간 데이터 전송이 정상 동작한다

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type NetworkRequest
  OUTPUT: boolean
  
  // Returns true when the request originates from a non-loopback address
  // and the server accepts it because it listens on 0.0.0.0
  RETURN X.source_ip ≠ "127.0.0.1" AND server_is_listening_on(X.destination_port, "0.0.0.0")
END FUNCTION
```

```pascal
// Property: Fix Checking - External access is impossible
FOR ALL X WHERE isBugCondition(X) DO
  result ← attemptConnection'(X)
  ASSERT result = CONNECTION_REFUSED
END FOR
```

```pascal
// Property: Preservation Checking - Local access unchanged
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

**핵심:** 수정 후 서버가 `127.0.0.1`에만 바인딩되므로, 외부 IP에서의 요청은 OS 네트워크 스택 레벨에서 거부된다. 로컬 접근(`localhost`, `127.0.0.1`)은 동일하게 동작한다.
