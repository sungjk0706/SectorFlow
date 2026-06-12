# SectorFlow 작업 인계 문서

## 작업 날짜
2026-06-12

---

## 최신 작업 (2026-06-12) — 업종순위 페이지 수신율 표시 구현 완료

### 핵심
업종순위 페이지에 실시간 데이터 수신율을 표시하는 기능 구현 완료
백엔드에서 수신율 계산 및 전송, 프론트엔드에서 수신 및 표시

### 문제 현상 (초기)
- 프론트엔드 업종순위 페이지에 수신율이 (현재: 0%)로만 표시됨
- 백엔드 로그에는 수신율이 정상적으로 출력됨 (예: 수신율: 100/156 = 64.1%)
- 백엔드에서 수신율 계산은 정상 작동 중
- 백엔드에서 `receive-rate` 이벤트 전송 로그 확인됨 (예: `[Compute] 수신율 변경 감지 전송: 100.0% (156/156)`)
- 프론트엔드 콘솔에서 `uiStore.getState().receiveRate`가 `null`로 확인됨
- 프론트엔드 콘솔에 `receive-rate` 이벤트 로그 없음

### 해결 방안
기존 sector-scores 이벤트를 통한 전송 방식 폐기, broadcast_queue 직접 사용으로 단순화

### 수정 내용

1. **백엔드 pipeline_compute.py 수정**
   - Phase 1 루프에서 `notify_desktop_sector_scores(force=True)` 호출 제거
   - `broadcast_queue.put()`을 사용하여 `receive-rate` 이벤트 직접 전송
   - 포맷: `{"type": "receive-rate", "data": {"pct": current_pct, "received": received_count, "total": total_count}}`
   - Phase 2 루프에서 수신율 변경 시에만 이벤트 전송 (delta 전송, `_receive_rate_dirty` 플래그 사용)
   - 백엔드 ws_manager.py에서 `receive-rate`를 `_STATE_EVENTS`에 추가 (상태형 이벤트로 처리)
   - **수신율 전송 로직 단일화**: `_send_receive_rate()` 함수로 통합
   - **broadcast_queue 전역 변수 할당**: import 구문 뒤에 `broadcast_queue = get_broadcast_queue()` 추가
   - **수신율 로그 중복 제거**: `_send_receive_rate()` 함수 내 로그 제거, Phase 1 로그 유지
   - **Phase 2 수신율 전송 조건 수정**: 임계값 이상 시 전송 중지 (사용자 설정 `sector_start_threshold_pct` 사용)
   - **Phase 2 루프 시작 로그 제거**: 중복 로그 제거

2. **백엔드 engine_account_notify.py 수정**
   - 이전 delta 감지 로직 복원 (prev_receive_rate 필드 추가)
   - 이 수정은 최종 해결책에서 사용되지 않음 (broadcast_queue 직접 사용으로 대체)

3. **프론트엔드 binding.ts 수정**
   - `receive-rate` 이벤트 핸들러 추가
   - uiStore에 receiveRate 직접 갱신

4. **프론트엔드 sector-ranking.ts 수정**
   - 수신율 표시 UI 추가 (파란색 #2196F3)
   - 임계점 도달 시 라벨 자동 숨김 로직 추가 (하이스테리시스 적용: 5% 이상 떨어져야 다시 표시)
   - `updateReceiveRate` 함수에 임계점 체크 로직 추가

### 수정 파일
- `backend/app/pipelines/pipeline_compute.py`
- `backend/app/services/engine_account_notify.py` (delta 감지 로직 추가, 미사용)
- `backend/app/web/ws_manager.py` (`receive-rate`를 `_STATE_EVENTS`에 추가)
- `frontend/src/binding.ts`
- `frontend/src/pages/sector-ranking.ts`

### 검증 결과
- py_compile 문법 검증: 성공
- npm run build: 성공
- 백엔드 수신율 계산: 완료
- 백엔드 수신율 전송: 완료 (broadcast_queue 직접 사용, delta 전송)
- 백엔드 이벤트 타입 등록: 완료 (ws_manager.py _STATE_EVENTS에 추가)
- 프론트엔드 수신율 수신: 완료
- 프론트엔드 수신율 표시: 완료
- 수신율 로그 중복 제거: 완료
- 프론트엔드 수신율 0% 깜빡거림 해결: 완료

### 아키텍처 원칙 준수
- 이벤트 기반 루프: 준수 (틱 수신 시 수신율 계산 및 전송)
- 단일 소스 진리: 준수 (pipeline_compute.py에서 직접 전송)
- EventBus 금지: 준수 (broadcast_queue 사용)
- 단순한 로직: 준수 (별도 이벤트 타입 도입, 기존 로직 손상 없음)
- 트래픽 최적화: 준수 (delta 전송, 변경 시에만 전송)
- 설정 메모리 상주: 준수 (사용자 설정 `sector_start_threshold_pct` 사용)
- 중복 제거: 준수 (불필요한 로그 제거)

### 완료 상태
- 백엔드 수신율 계산: 완료
- 백엔드 수신율 전송: 완료 (broadcast_queue 직접 사용, delta 전송)
- 백엔드 이벤트 타입 등록: 완료 (ws_manager.py _STATE_EVENTS에 추가)
- 프론트엔드 수신율 수신: 완료
- 프론트엔드 수신율 표시: 완료
- 수신율 로그 중복 제거: 완료
- 프론트엔드 수신율 0% 깜빡거림 해결: 완료

---

## 이전 작업 (2026-06-11) — custom_sectors 스키마 변경 완료

### 핵심
custom_sectors 테이블 기본 키 변경으로 중복 종목코드 문제 근본 해결
한 종목은 하나의 업종만 소속한다는 비즈니스 로직을 데이터베이스 레벨에서 강제

### 문제 현상
- custom_sectors 테이블에 14개 종목코드가 각각 2개의 업종으로 매핑됨
- 모든 중복이 "기타" + 다른 업종 조합
- 원인: 복합 기본 키 (name, stock_code)로 인해 INSERT OR REPLACE가 기존 "기타" 매핑을 삭제하지 않음

### 수정 내용

1. **기존 중복 데이터 정리**
   - 14개 중복 종목코드 중 "기타" 업종 삭제
   - 1개 남은 중복(004830) 수동 정리
   - 누락된 2개 종목(069960, 131290) "기타"로 추가

2. **테이블 스키마 변경**
   - 기본 키: (name, stock_code) → stock_code 단일 기본 키
   - 새 테이블 생성 → 데이터 복사 → 기존 테이블 삭제 → 이름 변경

3. **코드 수정** (stock_classification_data.py)
   - create_sector: NotImplementedError (종목 매핑 시 자동 생성)
   - move_stock: INSERT OR REPLACE 순서 변경 (stock_code, name)
   - sync_sector_from_custom_sectors: SELECT 순서 변경 (stock_code, name)

### 수정 파일
- `backend/app/core/stock_classification_data.py`

### 아키텍처 원칙 준수
- 단일 소스 진리: 한 종목은 하나의 업종만 소속
- 데이터 무결성: 데이터베이스 레벨에서 중복 방지
- 비즈니스 로직 반영: 스키마에 비즈니스 로직 반영

### 검증 결과
- py_compile 문법 검증: 성공
- master_stocks_table: 1,373종목
- stock_5d_array: 1,373종목
- custom_sectors: 1,373종목
- 모든 테이블 종목 수 일치
- 중복 종목코드 없음

### 완료 상태
- 기존 중복 데이터 정리: 완료
- 테이블 스키마 변경: 완료
- 관련 코드 수정: 완료
- 종목수 일치 확인: 완료

---

## 이전 작업 (2026-06-11) — 확정시세 다운로드 DB 작업 원자화 완료

### 핵심
확정시세 다운로드 시 DB 작업을 단일 트랜잭션으로 원자화
master_stocks_table 기준으로 stock_5d_array, custom_sectors 동기화
메모리 캐시 증분 갱신 및 프론트엔드 즉시 반영 로직 확인

### 수정 내용

1. **타이머 확정시세 단일 트랜잭션으로 DB 작업 원자화** (market_close_pipeline.py:1041-1112)
   - master_stocks_table DELETE/INSERT
   - stock_5d_array DELETE (master_stocks_table 기준)
   - custom_sectors DELETE (master_stocks_table 기준)
   - 신규상장 종목 기타 섹터 추가
   - sync_sector_from_custom_sectors (트랜잭션 내)
   - 단일 commit (모든 DB 작업 원자화)
   - 메모리 캐시 동기화 (트랜잭션 완료 후)

2. **수동 확정시세 단일 트랜잭션으로 DB 작업 원자화** (market_close_pipeline.py:1556-1608)
   - 동일한 로직 적용
   - 단일 트랜잭션으로 DB 작업 원자화

3. **중복 호출 제거**
   - 타이머 확정시세의 별도 sync_sector_from_custom_sectors 호출 제거
   - 수동 확정시세의 별도 sync_sector_from_custom_sectors 호출 제거

### 수정 파일
- `backend/app/services/market_close_pipeline.py`

### 아키텍처 원칙 준수
- 단일 소스 진리: master_stocks_table 기준으로 stock_5d_array, custom_sectors 동기화
- 원자성: 단일 트랜잭션으로 DB 작업 원자화
- 데이터 일치성: 트랜잭션 완료 후 메모리/프론트엔드 갱신

### 검증 결과
- py_compile 문법 검증: 성공

### 완료 상태
- 타이머 확정시세 단일 트랜잭션: 완료
- 수동 확정시세 단일 트랜잭션: 완료
- 중복 호출 제거: 완료

---

## 미해결 문제

### 장거래시간 확정시세 다운로드 문제
- **문제**: 장거래시간에 확정시세 다운로드가 실행되어 업종순위 계산이 멈춤
- **원인**: 확정시세 다운로드 중에는 master_stocks_cache가 업데이트되지 않아 all_codes가 비어있음
- **현상**: 업종순위 계산이 "부트스트랩 대기" 로그를 1초마다 출력하며 대기
- **아키텍처 원칙**: 실시간 파이프라인과 배치 파이프라인은 독립, 상호 간섭 금지
- **정상 동작**: 장거래시간에는 업종순위 계산이 실시간 데이터로 정상 동작해야 함
- **해결 방안**: 확정시세 다운로드는 장마감 후에만 실행되도록 시간 가드 추가
- **우선순위**: 추후 해결
