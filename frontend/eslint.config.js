// SectorFlow ESLint 설정 — 하네스 엔지니어링 자동 강제 (프론트엔드)
// AGENTS.md 금지 패턴 + 아키텍처 원칙을 프론트엔드 코드 수준에서 자동 차단
// P24 단순성: 핵심 규칙만 활성화, 기존 코드베이스와 충돌하지 않는 규칙만 선택

import js from '@eslint/js'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // 기본 무시 패턴
  {
    ignores: ['dist/', 'node_modules/', '*.config.ts', 'vitest.setup.ts'],
  },

  // TypeScript 파일에 적용
  {
    files: ['src/**/*.ts'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
    ],
    rules: {
      // P25 격리된 실패 — empty catch block 금지 (silent pass 금지)
      'no-empty': ['error', { allowEmptyCatch: false }],

      // 타입 안전성 — any 타입 금지 (런타임 에러 방지)
      // 기존 1건은 별도 정리 태스크에서 처리
      '@typescript-eslint/no-explicit-any': 'warn',

      // P23 일관성 — unused 변수 금지 (dead code 방지)
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],

      // P10 SSOT — 재정의 금지
      'no-redeclare': 'error',

      // P23 일관성 — 선언 전 사용 금지 (함수/변수 호이스팅은 허용, 클래스만 금지)
      'no-use-before-define': ['error', { functions: false, classes: true, variables: false }],
    },
  },

  // 테스트 파일은 일부 규칙 완화
  {
    files: ['tests/**/*.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
)
