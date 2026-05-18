# P2-2-7: Dashboard/Alert 구현 수정계획서

## 작업 목표
Latency metrics를 시각화하는 Dashboard UI와 임계치 초과 시 Alert 표시 기능 구현

## 현재 상태
- `backend/infrastructure/metrics/latency.py`: LatencyMetrics collector 구현 완료
  - record(): 메트릭 기록
  - get_percentile(): percentile 계산
  - get_summary(): 요약 통계 (count, min, max, avg, p50, p95, p99)
  - get_recent_alerts(): 최근 alert 목록
  - 임계값 초과 시 로그 출력 구현 완료

## 요구사항

### 1. Backend API 엔드포인트
- `/api/metrics/summary`: 전체 메트릭 요약 조회
- `/api/metrics/alerts`: 최근 alert 목록 조회
- `/api/metrics/clear`: 메트릭 초기화 (개발용)

### 2. Frontend Dashboard UI
- 메트릭 요약 테이블 (broker_to_backend_ms, coalescing_ms, backend_to_frontend_ms, frontend_to_ui_ms, order_to_fill_ms, fill_to_sync_ms)
- 각 메트릭별: count, min, max, avg, p50, p95, p99 표시
- 실시간 갱신 (주기적 폴링 또는 WebSocket)

### 3. Alert 표시
- 최근 alert 목록 표시
- 임계치 초과 시 시각적 강조
- Alert 발생 시점, 메트릭명, 값, 임계값 표시

## 설계

### Backend 구조
```
backend/presentation/api/metrics.py (신규)
  - GET /api/metrics/summary
  - GET /api/metrics/alerts
  - POST /api/metrics/clear
```

### Frontend 구조
```
frontend/src/presentation/pages/metrics-dashboard/ (신규)
  - MetricsDashboard.tsx: 메인 페이지
  - MetricsSummaryTable.tsx: 요약 테이블 컴포넌트
  - AlertsList.tsx: Alert 목록 컴포넌트

frontend/src/infrastructure/api/api/metrics.ts (신규)
  - fetchMetricsSummary()
  - fetchMetricsAlerts()
  - clearMetrics()
```

### 라우팅
- 메인 메뉴에 "Metrics Dashboard" 항목 추가
- `/metrics` 경로로 접근

## 단계별 실행 계획

### 단계 1: Backend API 엔드포인트 구현
- `backend/presentation/api/metrics.py` 생성
- `/api/metrics/summary` 엔드포인트 구현
- `/api/metrics/alerts` 엔드포인트 구현
- `/api/metrics/clear` 엔드포인트 구현
- `backend/main.py`에 router 등록
- 검증: python -m py_compile 성공

### 단계 2: Frontend API 클라이언트 구현
- `frontend/src/infrastructure/api/api/metrics.ts` 생성
- fetchMetricsSummary() 구현
- fetchMetricsAlerts() 구현
- clearMetrics() 구현
- 검증: npm run build 성공

### 단계 3: Dashboard UI 구현
- `frontend/src/presentation/pages/metrics-dashboard/MetricsDashboard.tsx` 생성
- `frontend/src/presentation/pages/metrics-dashboard/MetricsSummaryTable.tsx` 생성
- `frontend/src/presentation/pages/metrics-dashboard/AlertsList.tsx` 생성
- 검증: npm run build 성공

### 단계 4: 라우팅 및 메뉴 연결
- 메인 레이아웃에 메뉴 항목 추가
- 라우터에 `/metrics` 경로 등록
- 검증: npm run build 성공

### 단계 5: 검증 및 인계서 업데이트
- 기능 검증
- HANDOVER.md 업데이트
- 현재진단.md에 완료 표시

## 기술적 결정 사항
- 실시간 갱신: 5초 주기 폴링 (WebSocket은 복잡도 증가로 폴링 선택)
- 스타일: 기존 프로젝트 스타일 준수 (TailwindCSS)
- 타입: TypeScript 엄격 모드 준수

## 검증 기준
- Backend API 엔드포인트 정상 응답
- Frontend UI 정상 렌더링
- 메트릭 데이터 정상 표시
- Alert 정상 표시
- 빌드 성공 (python, npm)
