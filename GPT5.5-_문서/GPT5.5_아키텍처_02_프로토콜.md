# WebSocket 프로토콜 문서

## 개요

SectorFlow의 WebSocket 통신은 두 개의 채널로 분리되어 있습니다:
- **Control/State 채널**: JSON text 기반, 제어 및 상태 이벤트 전송
- **Market Tick 채널**: Length-prefixed Protobuf batch binary 기반, 실시간 시세 데이터 전송

---

## Control/State 채널 (JSON Text)

### 목적
- 클라이언트-서버 간 제어 메시지 교환
- 상태 이벤트 전송 (진행률, 알림 등)

### 포맷
- WebSocket text frame
- JSON 형식

### 메시지 구조
```json
{
  "event": "이벤트타입",
  "data": { /* 이벤트 데이터 */ }
}
```

### 이벤트 타입

#### 클라이언트 → 서버
- `ping`: 연결 유지 확인
- `page-active`: 페이지 활성 알림 (per-client 필터링)
- `page-inactive`: 페이지 비활성 알림 (per-client 필터링 해제)
- `subscribe-fids`: FID 구독 설정 (per-client FID 필터링)

#### 서버 → 클라이언트
- `download-progress`: 다운로드 진행률
- 기타 상태 이벤트

### 예시
```json
// 클라이언트 → 서버
{ "type": "ping" }
{ "type": "page-active", "page": "watchlist" }
{ "type": "subscribe-fids", "fids": ["10", "11"] }

// 서버 → 클라이언트
{ "event": "download-progress", "data": { "progress": 50 } }
```

---

## Market Tick 채널 (Length-prefixed Protobuf Batch Binary)

### 목적
- 실시간 시세 데이터 대량 전송
- Coalescing된 이벤트 효율적 전송

### 포맷
- WebSocket binary frame
- Length-prefixed Protobuf batch

### 바이너리 구조
```
[4바이트 길이][Protobuf Event][4바이트 길이][Protobuf Event]...
```

- 각 이벤트 앞에 4바이트 big-endian 길이 접두사
- 여러 이벤트가 하나의 binary frame에 패킹되어 전송

### Protobuf Event 메시지 정의
```protobuf
message Event {
  string type = 1;
  map<string, string> data = 2;
  double timestamp = 3;
}
```

### 이벤트 타입
- `raw_data`: 원본 JSON 데이터 (백엔드에서 브로커별 원본 데이터 저장)

### raw_data 처리 흐름
1. 백엔드: 브로커에서 수신한 원본 JSON을 `event.data["raw"]`에 저장
2. 프론트엔드: Protobuf 디코딩 후 `data["raw"]`를 JSON 파싱
3. 프론트엔드: 종목코드 추출 후 `real-data` 이벤트로 변환하여 디스패치

### 종목코드 추출 로직
- 키움증권 형식: `data["code"]`
- LS증권 형식: `data["header"]["tr_key"][1:7]`

---

## 채널 분리 이유

1. **성능 최적화**: 실시간 시세는 binary batch로 압축 전송, 제어 메시지는 JSON으로 가독성 유지
2. **디버깅 용이성**: 제어 채널은 JSON으로 사람이 읽기 쉬움
3. **확장성**: 각 채널 독립적 개선 가능
4. **프로토콜 통일**: 기존 4가지 프로토콜 혼재 제거

---

## 구현 파일

### 백엔드
- `backend/infrastructure/coalescing/backend_coalescing.py`: Length-prefixed Protobuf batch 직렬화

### 프론트엔드
- `frontend/src/infrastructure/api/api/ws.ts`: Control/State 채널(JSON) + Market Tick 채널(Protobuf batch) 디코더
- `frontend/src/infrastructure/websocket/client.ts`: Control/State 채널(JSON) + Market Tick 채널(Protobuf batch) 디코더

---

## 버전
- 작성일: 2026-05-18
- 버전: 1.0
