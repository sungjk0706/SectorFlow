# 진행 중인 작업 인계서

## 날짜: 2026-05-12 15:59 KST

## 완료된 작업
1. 상단 헤더 KRX/NXT 상태 배지 시간대 경계 수정 (`daily_time_scheduler.py`)
2. market-phase 브로드캐스트 타이머 누락 시점 추가 (15:20, 15:30, 15:40, 16:00, 18:00)
3. PHASE_STYLE/지수 배지 색상 통일 (header.ts)
4. git push 완료 (ecf307b)

## 진행 중: 실시간 구독 지연 근본 원인 분석

### 현재까지 발견한 가능성
- **가능성 A (높음)**: 보유종목 REG가 배치 청크 뒤로 밀림
  - `engine_ws_reg.py:subscribe_sector_stocks_0b()` — 보유종목+필터통과종목을 한꺼번에 청크 분할
  - 보유종목이 100개 초과하면 2번째 청크로 넘어감 → 1번째 청크 ACK(10s) 대기
- **가능성 B (높음)**: 보유종목 단건 REG가 배치 파이프라인 완료까지 대기
  - `engine_service.py:1859` — `_ws_reg_pipeline_done.wait(timeout=120)`
- **가능성 C**: WS 브로드캐스트 큐 병목
  - `engine_ws_dispatch.py:513` — `notify_raw_real_data()` 매 틱마다 전체 클라이언트 전송
- **가능성 D**: 프론트엔드 수신/렌더링 지연
  - coalesce나 큐 잠재적 병목

### 다음 세션에서 해야 할 일
1. **보유종목 선행 REG 적용** — `engine_ws_reg.py:subscribe_sector_stocks_0b()`에서 보유종목을 별도 먼저 REG
2. **로그 확인** — 백엔드 로그에서 `032830`(삼성생명) REG 청크 위치/시각 확인
3. **브로드캐스트 coalesce 검토** — `notify_raw_real_data()` 0.1초 배치 전송 검토
4. **프론트엔드 WS 수신 시각 측정** — 브라우저 콘솔로 수신→화면까지 시간 측정

### 수정 대상 파일
- `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_reg.py`
- `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py` (선택)
