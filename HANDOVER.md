# HANDOVER.md

> 세션 간 작업 연속성을 위한 진행 상태 문서

---

## 직전 완료 작업

- **architecture_audit_plan.md 작성 완료** (1037줄, 30세션)
  - 파일: `docs/architecture_audit_plan.md`
  - 내용: SectorFlow 전체 코드베이스(백엔드 107파일 + 프론트엔드 56파일) 아키텍처 전수 점검 계획서
  - 22개 불변 원칙 평가 기준표, 세션 진행 가이드, 30개 세션 체크리스트, 추천 세션 순서, 발견된 문제 기록 섹션 포함
  - 우선순위: P0(자금 손실 직결) → P1(시스템 가동 필수) → P2(데이터 기반) → P3(부가 기능)

---

## 현재 상태

- 아키텍처 전수 점검 계획서 작성 완료
- 실제 점검은 아직 시작하지 않음 (30세션 중 0/30 완료)
- 점검 진행 현황: `docs/architecture_audit_plan.md` 섹션 8 참조

---

## 진행 중 작업

### 아키텍처 전수 점검 — 0/30 세션 완료

| 세션 ID | 우선순위 | 내용 | 상태 |
|---------|----------|------|------|
| B-01 | P0 | 주문 실행 경로 | ☐ 미시작 |
| B-02 | P0 | 리스크 관리 및 서킷 브레이커 | ☐ 미시작 |
| B-03 | P0 | Dry Run (테스트 모드 가상 주문) | ☐ 미시작 |
| B-04 | P0 | 정산 엔진 및 거래 이력 | ☐ 미시작 |
| B-05 | P0 | 자동매매 유효성 및 코어 큐 | ☐ 미시작 |
| F-01 | P0 | 통신 계층 및 상태 관리 | ☐ 미시작 |
| B-06~B-11 | P1 | 엔진 루프/WS/부트스트랩/섹터/계좌/파이프라인 | ☐ 미시작 |
| B-12~B-19 | P2 | DB/설정/Broker/증권사/Domain/스케줄러 | ☐ 미시작 |
| B-20~B-23 | P3 | 알림/유틸/Web API/테스트 | ☐ 미시작 |
| F-02~F-07 | P1~P3 | 진입점/핵심페이지/설정/수익/컴포넌트/타입 | ☐ 미시작 |

---

## 다음 단계

### 1순위: 아키텍처 전수 점검 P0 세션 (B-01~B-05, F-01)

다음 세션에서 `docs/architecture_audit_plan.md`의 추천 세션 순서에 따라 P0 세션부터 시작:

1. **B-01**: 주문 실행 경로 (`services/trading.py`, `services/buy_order_executor.py`)
2. **B-02**: 리스크 관리 및 서킷 브레이커 (`services/risk_manager.py`, `services/circuit_breaker.py`)
3. **B-03**: Dry Run (`services/dry_run.py`)
4. **B-04**: 정산 엔진 및 거래 이력 (`services/settlement_engine.py`, `services/trade_history.py`)
5. **B-05**: 자동매매 유효성 및 코어 큐 (`services/auto_trading_effective.py`, `services/core_queue.py`)
6. **F-01**: 통신 계층 및 상태 관리 (`stores/hotStore.ts`, `api/ws.ts`, `binding.ts` 등)

각 세션 진행 시:
- `docs/architecture_audit_plan.md`의 해당 세션 체크리스트 사용
- 발견된 문제를 계획서 섹션 7 "발견된 문제 기록"에 등록
- 세션 완료 시 계획서 섹션 8 "점검 진행 현황 요약" 갱신
- 세션 종료 시 본 `HANDOVER.md` 진행 상태 갱신

### 2순위: P1 세션 (B-06~B-11, F-02)

P0 세션 완료 후 진행.

### 3순위: P2 세션 (B-12~B-19, F-03~F-04)

P1 세션 완료 후 진행.

### 4순위: P3 세션 (B-20~B-23, F-05~F-07)

P2 세션 완료 후 진행.
