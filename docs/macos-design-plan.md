# macOS 스타일 UI 디자인 설계

> **목적**: SectorFlow 프론트엔드(Vanilla TS)의 시각적 스타일을 macOS 앱 스타일로 전환하기 위한 설계 문서.
> **범위**: 디자인 토큰 정의 + 적용 범위 + 의미 색 보존 + 아키텍처 원칙 부합 검증.
> **제외**: 코드 구현(별도 태스크 문서에서 단계별 진행).

---

## 0. 전제 및 제약

- **기술 스택 유지**: TypeScript + Vanilla, Vite 빌드, 프레임워크 도입 없음.
- **SSOT 존중**: `frontend/src/components/common/ui-styles.ts`가 폰트·색상·폰트 크기·굵기의 단일 진실 소스. 신규 토큰(`RADIUS`/`SHADOW`/`BLUR`)도 동일 파일에 추가.
- **인라인 스타일 유지**: CSS 파일 신설 없이 기존 패턴(`Object.assign(el.style, {...})`) 준수. macOS 효과(`backdrop-filter`/`box-shadow`/`border-radius`)는 모두 표준 CSS 속성이므로 순수 DOM API로 적용 가능.
- **의미 색 불변 (P21 사용자 투명성)**: 빨강=상승/매수/위험/에러, 파랑=하락/매도/정보/활성, 초록=성공/통과/연결, 주황=경고. 이 의미 체계는 macOS 톤 적용 후에도 보존. 색 톤(채도/명도)만 조정하고 의미 매핑은 유지.
- **용어 통일 유지 (P23)**: UI 텍스트 "업종"/"종목"/"매수 후보"/"보유 종목"은 스타일 변경과 무관하게 유지.

---

## 1. 디자인 토큰 정의

> 모든 토큰은 `ui-styles.ts`에 추가. 기존 상수(`FONT_FAMILY`/`FONT_SIZE`/`FONT_WEIGHT`/`COLOR`)와 동일한 `as const` 패턴.

### 1.1 폰트 (FONT_FAMILY 교체)

```ts
// 기존: "Tahoma, '굴림', Gulim, sans-serif"
// 신규: macOS 시스템 폰트 스택 (SF Pro → 폴백)
export const FONT_FAMILY =
  "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', " +
  "'Helvetica Neue', 'Segoe UI', system-ui, sans-serif"
```

- **폰트 크기(`FONT_SIZE`) 유지**: 현재 11~18px 체계는 macOS 앱 가이드라인과 충돌 없음. 다만 본문 13px는 macOS 표준 13px와 일치하므로 변경 불필요.
- **숫자 탭ular 정렬**: 금융 데이터이므로 `font-variant-numeric: 'tabular-nums'`는 이미 settings-common.ts에서 적용 중. 테이블 셀에도 확장 적용 권장(별도 토큰 불필요, 스타일 적용 시점에서 처리).

### 1.2 둥근 모서리 (RADIUS 신설)

> 현재 76곳에 하드코딩(3/4/6/8/10/12px 혼재). 토큰화로 일관성 확보 (P24 단순성).

```ts
export const RADIUS = {
  xs:   '4px',   // 칩, 스핀 버튼, 슬라이더 핸들, 행 내부 요소
  sm:   '6px',   // 버튼, 입력란, 카드 내부 요소, 태그
  md:   '8px',   // 카드, 드롭다운, 팝업, 컨텍스트 메뉴
  lg:   '10px',  // 토스트, 브로커 배지, 헤더 칩
  xl:   '12px',  // 다이얼로그, 사이드바 활성 항, 큰 카드
  pill: '9999px', // 원형 배지, 토글
} as const
```

**매핑표 (기존 → 신규 토큰)**:

| 현재 값 | 적용처 | 신규 토큰 |
|---------|--------|-----------|
| 3px | 슬라이더 트랙, 순위 배지 | `RADIUS.xs` (4px로 통일) |
| 4px | 입력, 칩, 스핀, 행 요소 | `RADIUS.xs` |
| 6px | 버튼, 카드, 섹션, 드롭다운 항목 | `RADIUS.sm` |
| 8px | 카드, 드롭다운, 컨텍스트 팝업 | `RADIUS.md` |
| 10px | 토스트, 브로커 배지, 헤더 칩 | `RADIUS.lg` |
| 12px | 다이얼로그, 사이드바 활성 항 | `RADIUS.xl` |
| 50% | 원형 배지, 스피너 | `RADIUS.pill` 또는 `'50%'` 유지 |

### 1.3 그림자 (SHADOW 신설)

> 현재 거의 없음(sidebar 활성 1곳, 차트 툴팁 2곳, dialog 1곳). macOS는 은은한 다층 그림자가 핵심.

```ts
export const SHADOW = {
  // 카드/패널용 — 매우 은은한 1층
  card:    '0 1px 2px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.06)',
  // 호버/활성 카드 — 약간 더 깊이
  cardHover: '0 2px 6px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06)',
  // 팝업/드롭다운 — 중간 깊이
  popup:   '0 4px 16px rgba(0, 0, 0, 0.12), 0 1px 4px rgba(0, 0, 0, 0.06)',
  // 모달/다이얼로그 — 가장 깊이
  modal:   '0 12px 36px rgba(0, 0, 0, 0.16), 0 2px 8px rgba(0, 0, 0, 0.08)',
  // 사이드바 활성 항 — 좌측 책갈피용 (기존 2px 2px 6px 대체)
  sidebarActive: '2px 2px 8px rgba(0, 0, 0, 0.06)',
  // 없음
  none:    'none',
} as const
```

### 1.4 반투명 블러 (BLUR 신설)

> 현재 dialog.ts 1곳만. macOS 핵심 효과. `backdrop-filter` + 반투명 배경 조합.

```ts
export const BLUR = {
  // 헤더/사이드바 툴바 — 강한 블러 (macOS 툴바 표준)
  toolbar:  'blur(20px) saturate(180%)',
  // 카드/패널 — 중간 블러
  panel:    'blur(16px) saturate(150%)',
  // 모달 오버레이 — 약한 블러 (기존 4px → 8px로 약간 강화)
  overlay:  'blur(8px) saturate(120%)',
  // 없음
  none:     'none',
} as const

// 반투명 배경색 (블러와 함께 사용)
export const SURFACE_ALPHA = {
  // 헤더/사이드바 툴바 배경 — 흰색 72%
  toolbar:  'rgba(255, 255, 255, 0.72)',
  // 카드/패널 배경 — 흰색 80%
  panel:    'rgba(255, 255, 255, 0.80)',
  // 모달 오버레이 — 검정 40% (기존 유지)
  overlay:  'rgba(0, 0, 0, 0.40)',
} as const
```

**주의**: `backdrop-filter`는 Safari/WebKit에서 `-webkit-backdrop-filter` 접두사 필요. dialog.ts에 이미 접두사 패턴이 있으므로 동일 패턴 적용.

### 1.5 색상 매핑 (COLOR 조정)

> 의미 색 보존하면서 macOS 톤으로 미세 조정. **의미 매핑은 불변**, 톤(채도/명도)만 조정.

#### 1.5.1 의미 색 (보존 — 톤만 미세 조정)

| 키 | 현재 | 신규(제안) | 비고 |
|----|------|-----------|------|
| `up` (상승/매수/위험/에러) | `#f44336` | `#d64545` | macOS 시스템 레드 톤 (약간 낮은 채도) |
| `down` (하락/매도/정보/활성) | `#1e88e5` | `#2563eb` 또는 `#0a6cff` | macOS 시스템 블루 톤 |
| `success` | `#2e7d32` | `#248a3d` | macOS 시스템 그린 톤 |
| `warning` | `#e65100` | `#c93400` 또는 `#d97706` | macOS 시스템 오렌지 톤 |
| `upLight`/`downLight`/`successLight`/`warningLight` | 기존 | 대응 톤으로 미세 조정 | 배경용 light 변형 |
| `upBg`/`downBg`/`successBg`/`warningBg` | 기존 pastel | macOS 톤 pastel (약간 더 중성화) | 배경용 — 채도 낮춤 |

**의미 색 보존 원칙 (P21)**:
- 빨강 계열 → 상승/양수/매수/위험/에러 (한국 증권 관례 유지)
- 파랑 계열 → 하락/음수/매도/정보/활성
- 초록 계열 → 성공/통과/연결/장중
- 주황 계열 → 경고/주의
- 의미 매핑 변경 금지. `rateColor()`/`pnlColor()`/`strengthColor()` 함수 로직 불변.

#### 1.5.2 중성 색 (macOS 톤으로 조정)

| 키 | 현재 | 신규(제안) | 비고 |
|----|------|-----------|------|
| `neutral` (기본 텍스트) | `#333` | `#1d1d1f` | macOS 라벨 컬러 (거의 검정) |
| `tertiary` (라벨/설명) | `#666` | `#6e6e73` | macOS 세컨더리 라벨 |
| `code` (종목코드) | `#555` | `#515154` | macOS 터셔너리 라벨 |
| `disabled` | `#9e9e9e` | `#a1a1a6` | macOS 쿼터너리 라벨 |
| `muted` | `#adb5bd` | `#c7c7cc` | macOS 플레이스홀더 |
| `border` | `#ccc` | `#d2d2d7` | macOS 세퍼레이터 |
| `borderDark` | `#ddd` | `#e5e5ea` | macOS 세퍼레이터 (연함) |
| `borderLight` | `#eee` | `#f2f2f7` | macOS 그룹 배경 경계 |
| `borderGrid` | `#d0d0d0` | `#e5e5ea` | 테이블 그리드 — 더 연하게 |
| `borderRow` | `#e5e7eb` | `#f2f2f7` | 행 보더 — 거의 안 보이게 |
| `surface` | `#f8f9fa` | `#f5f5f7` | macOS 그룹 배경 백그라운드 |
| `surfaceLight` | `#fafafa` | `#fbfbfd` | macOS secondary 백그라운드 |
| `neutralBg` | `#f5f5f5` | `#f2f2f7` | 비활성 배경 |
| `zebra` | `#f9f9f9` | `#fafafa` | 제브라 — 매우 연함 |
| `hoverBg` | `#f0f0f0` | `#ececef` | 호버 하이라이트 |
| `inactiveBg` | `#e0e0e0` | `#e5e5ea` | 비활성 토글 배경 |
| `toggleOff` | `#6c757d` | `#8e8e93` | macOS 토글 OFF |
| `white` | `#fff` | `#fff` 유지 | 컬러 배경 위 텍스트 |

#### 1.5.3 기간 구분 카드 전용 색 (유지)

`periodPrev`/`period5day`/`periodMonth`/`periodTotal` 및 대응 Bg는 의미 충돌 회피 목적의 신규 색이므로 macOS 톤으로 미세 조정만. (별도 매핑표는 구현 단계에서 작성)

---

## 2. 적용 범위

### 2.1 레이아웃 뼈대 (1순위)

#### 2.1.1 shell.ts (루트 컨테이너)

| 요소 | 현재 | 변경 |
|------|------|------|
| root | `height:100vh; flex column` | 배경 `COLOR.surface` 적용 (macOS 윈도우 배경) |
| contentWrapper | `position:relative` | 변경 없음 |
| overlay (로딩) | `background:rgba(255,255,255,0.92)` | `SURFACE_ALPHA.overlay` + `BLUR.overlay` 적용 검토 |
| leftPanel | `border-right:1px solid` | 보더 색 `COLOR.borderDark` 유지, 패딩 미세 조정 |
| rightPanel | `padding:8px` | `padding:12px` (macOS 콘텐츠 여백) |
| tripleHeader | `border-bottom:1px solid` | 보더 색 조정 + 블러 툴바 적용 검토 |

#### 2.1.2 sidebar.ts (사이드바)

| 요소 | 현재 | 변경 |
|------|------|------|
| nav 배경 | `COLOR.surface` (불투명) | `SURFACE_ALPHA.toolbar` + `BLUR.toolbar` (반투명 블러) |
| nav 보더 | `border-right:1px solid ${COLOR.borderDark}` | 보더 색 `COLOR.borderDark`(신규 톤) 유지 |
| 메뉴 항목 | `padding:14px 0; text-align:center` | `padding:8px 12px; text-align:left; border-radius:RADIUS.sm` (macOS 사이드바 항목 스타일) |
| 활성 항목 | `border-left:3px solid; border-top-right-radius:12px; box-shadow` | `border-radius:RADIUS.sm; background:downBg; box-shadow:SHADOW.sidebarActive` (책갈피 → 둥근 캡슐) |
| 아이콘+라벨 | 한 줄 텍스트 | 아이콘 + 라벨 좌측 정렬 (macOS Finder 패턴) |
| footer shimmer | 그라데이션 텍스트 | 유지 (개인적 시그니처) |

**레이아웃 변경 주의**: 사이드바 폭 120px → 160px 조정 검토 (macOS 사이드바 표준). 단, 이는 콘텐츠 영역 폭 변경을 수반하므로 사용자 승인 필요.

#### 2.1.3 header.ts (헤더 툴바)

| 요소 | 현재 | 변경 |
|------|------|------|
| 헤더 배경 | 평면 흰색 | `SURFACE_ALPHA.toolbar` + `BLUR.toolbar` (macOS 툴바) |
| 하단 보더 | `border-bottom:1px solid` | `COLOR.borderDark` 유지, 1px |
| 칩 (CHIP_STYLE) | `border-radius:10px` | `RADIUS.lg` |
| 칩 배경 | pastel bg + 의미 색 텍스트 | 유지 (의미 색 보존), 톤만 조정 |
| 높이 | 40px | 44px 검토 (macOS 툴바 표준) — 콘텐츠 영역 영향 |

### 2.2 공통 컴포넌트 (2순위)

#### 2.2.1 button.ts

- `borderRadius` 기본값 `6px` → `RADIUS.sm`
- `padding` `7px 18px` → `6px 16px` (macOS 버튼 패딩)
- primary/danger variant: 그림자 추가 검토 (`SHADOW.card` 수준)
- secondary variant: 호버 시 `COLOR.hoverBg` 적용 (macOS 버튼 호버 패턴)

#### 2.2.2 dialog.ts

- `applyBoxStyle`: `borderRadius:12px` → `RADIUS.xl`, `boxShadow` → `SHADOW.modal`
- `applyOverlayStyle`: backdrop blur 애니메이션 유지 (이미 macOS 패턴)
- 배경 `COLOR.white` → `SURFACE_ALPHA.panel` + `BLUR.panel` 검토 (단, 모달은 불투명이 가독성에 유리할 수 있음 → 구현 시 A/B 검토)

#### 2.2.3 toast.ts

- `borderRadius:10px` → `RADIUS.lg`
- `boxShadow` 추가 → `SHADOW.popup`
- 배경 → `SURFACE_ALPHA.panel` + `BLUR.panel` (macOS 알림 스타일)

#### 2.2.4 context-popup.ts

- `borderRadius:8px` → `RADIUS.md`
- `boxShadow` → `SHADOW.popup`

#### 2.2.5 card-header.ts / card-title.ts

- 카드 컨테이너에 `RADIUS.md` + `SHADOW.card` 적용
- 카드 배경 `COLOR.white` → `COLOR.surfaceLight`(신규 톤) 또는 `SURFACE_ALPHA.panel` 검토

#### 2.2.6 tag-chip.ts / badge.ts / broker-badge.ts

- `borderRadius:4px` → `RADIUS.xs` (칩), `borderRadius:10px` → `RADIUS.lg` (브로커 배지)
- 의미 색 배경 유지, 톤만 조정

#### 2.2.7 search-input.ts / date-range-input.ts

- `borderRadius:4px` → `RADIUS.sm`
- 포커스 시 링 효과 검토: `box-shadow: 0 0 0 3px rgba(blue, 0.2)` (macOS 포커스 링)

#### 2.2.8 progress-bar.ts / create-slider.ts

- `borderRadius:4px` → `RADIUS.xs`
- 슬라이더 핸들: `RADIUS.pill` (원형)

#### 2.2.9 info-tooltip.ts

- `borderRadius:6px` → `RADIUS.sm`
- `boxShadow` → `SHADOW.popup`

### 2.3 테이블 (3순위)

#### 2.3.1 data-table.ts / data-table-fixed.ts / data-table-virtual.ts

- 헤더 배경: `COLOR.surface` → `COLOR.surfaceLight`(신규 톤), 상단 모서리 `RADIUS.sm`
- 행 보더: `COLOR.borderRow` → 신규 톤 (거의 안 보이게)
- 그리드 셀 보더: `COLOR.borderGrid` → 신규 톤 (더 연하게) 또는 제거 검토
- 호버 행: `COLOR.hoverBg` (신규 톤) — macOS 테이블 호버 패턴
- 제브라: `COLOR.zebra` (신규 톤) — 매우 연함

#### 2.3.2 ui-styles-cells.ts

- 셀 패딩/보더 색상 토큰 참조로 전환
- 숫자 셀 `font-variant-numeric: tabular-nums` 일괄 적용 검토

### 2.4 설정 패널 (4순위)

#### 2.4.1 settings-common.ts

- `sectionTitle`: 하단 보더 `2px solid ${COLOR.borderLight}` → `1px solid ${COLOR.borderDark}` (macOS 섹션 구분선)
- `createTimeSlot`: `borderRadius:6px` → `RADIUS.sm`, 배경 `COLOR.surface` 유지
- `createTimeDropdown`: `borderRadius:8px` → `RADIUS.md`, `boxShadow` → `SHADOW.popup`
- `createGridPanel` 버튼: `borderRadius:6px` → `RADIUS.sm`

#### 2.4.2 setting-row.ts / setting-row-controls.ts / setting-row-inputs.ts

- `borderRadius:4px` → `RADIUS.xs`
- 입력란 포커스 링 검토

#### 2.4.3 general-settings*.ts 페이지

- 카드 컨테이너: `RADIUS.md` + `SHADOW.card`
- 섹션 제목: settings-common.sectionTitle 일관성 적용

### 2.5 페이지 카드 (5순위)

#### 2.5.1 profit-shared.ts / profit-detail-mount.ts / profit-overview-mount.ts

- `SUMMARY_CARD_STYLE` / `STAT_STYLE`: `border-radius:6px` → `RADIUS.sm`, `box-shadow` → `SHADOW.card` 추가
- 카드 배경 `COLOR.surfaceLight` → 신규 톤

#### 2.5.2 sector-stock.ts / sector-ranking-list.ts / stock-classification-*.ts

- 카드/패널: `RADIUS.md` + `SHADOW.card`
- 배지/칩: `RADIUS.xs`

### 2.6 차트 컴포넌트 (6순위)

#### 2.6.1 canvas-profit-chart.ts / canvas-sector-donut.ts

- 툴팁: `border-radius:8px` → `RADIUS.md`, `box-shadow` → `SHADOW.popup`
- 툴팁 배경 `rgba(255,255,255,0.98)` → `SURFACE_ALPHA.panel` + `BLUR.panel` 검토

---

## 3. 의미 색 보존 검증 (P21)

### 3.1 의미 색 매핑 불변 표

| 의미 | 색 계열 | 사용처 | 보존 여부 |
|------|---------|--------|-----------|
| 상승/양수/매수 | 빨강 | `rateColor(+)`, `pnlColor(+)`, 매수 버튼 | ✅ 톤만 조정 |
| 하락/음수/매도 | 파랑 | `rateColor(-)`, `pnlColor(-)`, 매도 버튼, 활성 상태 | ✅ 톤만 조정 |
| 위험/에러 | 빨강 | 에러 메시지, danger 버튼 | ✅ |
| 정보/활성 | 파랑 | info 칩, primary 버튼, 활성 탭 | ✅ |
| 성공/통과/연결/장중 | 초록 | success 칩, 연결 상태, 장중 표시 | ✅ |
| 경고/주의 | 주황 | warning 칩, warning 버튼 | ✅ |
| 코스닥 종목명 | 핑크 | `COLOR.kosdaq` | ✅ 유지 |
| 업종 그룹 헤더 | 다크 인디고 | `COLOR.groupHeader` | ✅ 유지 |

### 3.2 색상 함수 불변

- `computeWeightedRate()`: 로직 변경 없음
- `rateColor()`: `COLOR.up`/`COLOR.down`/`COLOR.neutral` 참조 — 토큰 값만 바뀌고 로직 불변
- `pnlColor()`: 동일
- `strengthColor()`: 동일

### 3.3 P21 사용자 투명성 검증

- 의미 색 체계가 보존되므로 사용자가 "왜 이 종목이 빨간가?" 혼동하지 않음
- 단, 톤 조정 후 대비(contrast)가 충분한지 WCAG AA 기준(본문 4.5:1) 검증 필요 — 구현 단계에서 각 색상별 대비 측정
- pastel 배경(`upBg`/`downBg` 등) 위의 텍스트 가독성 검증 필요

---

## 4. 아키텍처 원칙 부합 검증

### 4.1 P10 (SSOT)

- ✅ 모든 토큰이 `ui-styles.ts`에 집중. 65개 파일이 이미 이 파일을 import하므로 토큰 값 변경만으로 전역 반영.
- ✅ `RADIUS`/`SHADOW`/`BLUR`/`SURFACE_ALPHA` 신규 토큰도 동일 파일에 추가 → SSOT 유지.
- ⚠️ 주의: 일부 파일(header.ts, profit-shared.ts 등)에 하드코딩된 색상/반경이 존재. 이를 토큰 참조로 전환해야 SSOT 완전성 확보. 구현 단계에서 스캔.

### 4.2 P21 (사용자 투명성)

- ✅ 의미 색 체계 보존 → 상태 표시(매수 차단, 리스크 초과, 장 상태 등)의 시각적 의미 유지.
- ✅ 색상 변경이 사용자 모르는 의사결정이 아님 — 본 설계 문서로 사전 공개.
- ⚠️ 블러 효과로 인해 배경 텍스트가 비쳐 보여 가독성이 떨어지지 않는지 검증 필요 (구현 시 블러 강도/배경 투명도 튜닝).

### 4.3 P23 (일관된 통일성)

- ✅ 용어 통일: UI 텍스트 "업종"/"종목"/"매수 후보"/"보유 종목" 유지 (스타일 변경과 무관).
- ✅ 공통 자산 재사용: 신규 토큰은 기존 `ui-styles.ts`에 추가, 신규 컴포넌트 신설 없음.
- ✅ 네이밍 일관성: `RADIUS`/`SHADOW`/`BLUR`/`SURFACE_ALPHA` — 기존 `COLOR`/`FONT_SIZE`/`FONT_WEIGHT`와 동일한 `UPPER_SNAKE_CASE` `as const` 패턴.
- ✅ UI 패턴 일관성: 혼재된 `borderRadius` 값을 토큰화하여 일관성 확보.

### 4.4 P24 (단순성)

- ✅ 중복 제거: 76곳의 `borderRadius` 하드코딩 → `RADIUS` 토큰 참조로 중복 제거.
- ✅ 불필요한 추상화 금지: 신규 토큰은 상수 객체만 추가, 래퍼 함수/클래스 없음.
- ✅ 더 단순한 대체: CSS 파일 신설 없이 기존 인라인 스타일 패턴 유지.
- ⚠️ 함수/파일 길이: `ui-styles.ts` 현재 268줄 → 토큰 추가 후 약 320줄 예상. 500줄 미만으로 P24 기준 충족.

### 4.5 P25 (격리된 실패)

- ✅ 스타일 토큰 변경은 런타임 로직과 무관 → 한 컴포넌트 스타일 실패가 다른 컴포넌트에 영향 없음.
- ✅ `backdrop-filter` 미지원 브라우저(구형)에서는 효과만 없고 배경색은 적용되므로 기능 저하 없음 (우아한 degradation).

---

## 5. 구현 순서 (세션 단위 — AGENTS.md 섹션3 규칙 0-1 준수)

> 세션당 1단계 원칙. 다단계 워크플로우(설계→태스크→구현) 적용.

| 세션 | 단계 | 내용 | 검증 |
|------|------|------|------|
| 1 | 설계 | 본 문서 작성 | — (완료) |
| 2 | 태스크 | 단계별 수정 목록 + 검증 기준 문서화 (`docs/macos-design-tasks.md`) | — |
| 3 | 구현 1 | `ui-styles.ts` 토큰 신설(`FONT_FAMILY` 교체, `RADIUS`/`SHADOW`/`BLUR`/`SURFACE_ALPHA` 추가, `COLOR` 톤 조정) | typecheck + build + test |
| 4 | 구현 2 | `shell.ts` + `sidebar.ts` + `header.ts` (레이아웃 뼈대) | typecheck + build + 브라우저 |
| 5 | 구현 3 | 공통 컴포넌트(button, dialog, toast, context-popup, card-header, tag-chip, badge, search-input, info-tooltip) | typecheck + build + 브라우저 |
| 6 | 구현 4 | 테이블(data-table*, ui-styles-cells.ts) | typecheck + build + 브라우저 |
| 7 | 구현 5 | 설정 패널(settings-common, setting-row*) + 페이지 카드(profit-shared 등) | typecheck + build + 브라우저 |
| 8 | 구현 6 | 잔존 하드코딩 스캔 + 일관성 점검 + 차트 컴포넌트 | typecheck + build + test + 브라우저 |

**추정: 총 8세션** (설계 1 + 태스크 1 + 구현 6)

---

## 6. 검증 기준

### 6.1 정적 검증 (매 세션)

```bash
cd frontend && npm run typecheck   # tsc --noEmit
cd frontend && npm run build       # tsc -b && vite build
cd frontend && npm run test        # vitest, 116 tests
```

### 6.2 브라우저 검증 (사용자 확인)

- 새로고침 후 macOS 스타일 적용 확인
- 캐시/서비스워커 문제 없는지 확인
- 각 페이지(업종순위, 매수후보, 보유종목, 수익현황, 수익상세, 종목분류, 종목상세, 일반설정) 시각적 일관성 확인
- 의미 색 보존 확인 (상승=빨강, 하락=파랑 등)
- 블러 효과 가독성 확인 (배경 텍스트 비침 여부)

### 6.3 일관성 점검 (마지막 세션)

- 하드코딩된 색상/반경/그림자 잔존 스캔: `grep -rn '#[0-9a-fA-F]\{3,6\}' frontend/src` (토큰화 누락 확인)
- `borderRadius` 하드코딩 잔존 스캔: `grep -rn "borderRadius:" frontend/src`
- `box-shadow` 하드코딩 잔존 스캔: `grep -rn "box-shadow:" frontend/src`

---

## 7. 위험 및 완화

| 위험 | 영향 | 완화 |
|------|------|------|
| 블러 효과 가독성 저하 | 배경 텍스트 비쳐 보임 | 블러 강도/배경 투명도 튜닝, 필요시 불투명 폴백 |
| 의미 색 대비 부족 (WCAG AA 미충족) | 색약 사용자 구분 어려움 | 각 색상별 대비 측정, 부족 시 톤 재조정 |
| 사이드바 폭 변경 (120→160px) | 콘텐츠 영역 축소 | 사용자 승인 후 진행 |
| 헤더 높이 변경 (40→44px) | 콘텐츠 영역 축소 | 사용자 승인 후 진행 |
| `backdrop-filter` 구형 브라우저 미지원 | 효과만 없음, 기능 정상 | 우아한 degradation (배경색만 적용) |
| 톤 조정 후 pastel 배경 가독성 | 배경 위 텍스트 대비 저하 | 각 pastel 배경별 텍스트 대비 검증 |

---

## 8. 미해결 문제 (구현 단계에서 결정)

1. **사이드바 폭 변경 여부**: 120px → 160px (macOS 표준). 콘텐츠 영역 영향. 사용자 승인 필요.
2. **헤더 높이 변경 여부**: 40px → 44px (macOS 툴바 표준). 콘텐츠 영역 영향. 사용자 승인 필요.
3. **다이얼로그 배경 블러 적용 여부**: 불투명(`COLOR.white`) vs 반투명 블러(`SURFACE_ALPHA.panel`). 가독성 A/B 검토.
4. **차트 툴팁 블러 적용 여부**: 차트 위 텍스트 비침 가능성. 구현 시 확인.
5. **다크 모드 지원 여부**: 본 설계는 라이트 모드만 다룸. 다크 모드는 별도 설계 필요 (사용자 요청 시).
6. **의미 색 톤 최종 값**: 본 문서의 제안 값은 1차안. 구현 시 브라우저에서 시각 확인 후 미세 조정.

---

## 9. 참조

- SSOT: `frontend/src/components/common/ui-styles.ts` (268줄)
- 공통 컴포넌트: `frontend/src/components/common/` (29파일)
- 레이아웃: `frontend/src/layout/shell.ts`, `sidebar.ts`, `header.ts`
- 아키텍처 원칙: `ARCHITECTURE.md` 제1부 P1~P25
- 검증 명령어: `AGENTS.md` 섹션1 "검증 명령어"
