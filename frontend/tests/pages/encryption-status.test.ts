import { describe, it, expect, beforeEach } from 'vitest'
import {
  ENCRYPTION_KEY_STATE_MESSAGES,
  SECRET_FIELD_STATUS_MESSAGES,
  ENCRYPTION_ERROR_CODE_MESSAGES,
  ENCRYPTION_KEY_BACKUP_GUIDE,
  mapEncryptionErrorMessage,
  currentEncryptionKeyState,
  currentSecretFieldStatus,
  isEncryptionBlockingSave,
  state,
  resetState,
} from '../../src/pages/general-settings-shared'

describe('B21-01 세션7: 암호화 상태 헬퍼', () => {
  beforeEach(() => {
    resetState()
  })

  describe('ENCRYPTION_KEY_STATE_MESSAGES', () => {
    it('AVAILABLE 상태 메시지 포함', () => {
      expect(ENCRYPTION_KEY_STATE_MESSAGES.AVAILABLE.text).toBe('민감정보 암호화 정상')
      expect(ENCRYPTION_KEY_STATE_MESSAGES.AVAILABLE.color).toBeTruthy()
    })

    it('MISSING 상태 메시지 포함', () => {
      expect(ENCRYPTION_KEY_STATE_MESSAGES.MISSING.text).toContain('암호화 키가 설정되지 않았습니다')
    })

    it('INVALID 상태 메시지 포함', () => {
      expect(ENCRYPTION_KEY_STATE_MESSAGES.INVALID.text).toContain('암호화 키를 사용할 수 없습니다')
    })
  })

  describe('SECRET_FIELD_STATUS_MESSAGES', () => {
    it('PLAINTEXT_LEGACY 메시지 포함 (설계 7.2)', () => {
      expect(SECRET_FIELD_STATUS_MESSAGES.PLAINTEXT_LEGACY.text).toContain('안전하게 암호화되지 않았습니다')
    })

    it('KEY_UNAVAILABLE 메시지 포함', () => {
      expect(SECRET_FIELD_STATUS_MESSAGES.KEY_UNAVAILABLE.text).toContain('암호화 키가 없어')
    })

    it('DECRYPT_FAILED 메시지 포함', () => {
      expect(SECRET_FIELD_STATUS_MESSAGES.DECRYPT_FAILED.text).toContain('복호화할 수 없습니다')
    })

    it('ENCRYPTED 메시지 포함', () => {
      expect(SECRET_FIELD_STATUS_MESSAGES.ENCRYPTED.text).toBe('암호화 저장됨')
    })

    it('EMPTY 메시지는 빈 문자열', () => {
      expect(SECRET_FIELD_STATUS_MESSAGES.EMPTY.text).toBe('')
    })
  })

  describe('ENCRYPTION_KEY_BACKUP_GUIDE', () => {
    it('키 백업 안내 문구 포함 (설계 9.2)', () => {
      expect(ENCRYPTION_KEY_BACKUP_GUIDE).toContain('암호화 키를 잃어버리면')
      expect(ENCRYPTION_KEY_BACKUP_GUIDE).toContain('서로 다른 안전한 장소')
    })
  })

  describe('mapEncryptionErrorMessage', () => {
    it('ENCRYPTION_KEY_MISSING 코드 매핑', () => {
      expect(mapEncryptionErrorMessage('ENCRYPTION_KEY_MISSING')).toBe(
        '암호화 키가 설정되지 않아 저장할 수 없습니다.',
      )
    })

    it('ENCRYPTION_KEY_INVALID 코드 매핑', () => {
      expect(mapEncryptionErrorMessage('ENCRYPTION_KEY_INVALID')).toContain('키 설정을 확인')
    })

    it('ENCRYPTION_FAILED 코드 매핑', () => {
      expect(mapEncryptionErrorMessage('ENCRYPTION_FAILED')).toContain('암호화에 실패')
    })

    it('알 수 없는 코드는 fallback 메시지 사용 (하위 호환)', () => {
      expect(mapEncryptionErrorMessage('UNKNOWN_CODE', '기본 오류')).toBe('기본 오류')
    })

    it('코드 없으면 fallback 사용', () => {
      expect(mapEncryptionErrorMessage(undefined, '서버 오류')).toBe('서버 오류')
    })

    it('코드도 fallback도 없으면 기본 메시지', () => {
      expect(mapEncryptionErrorMessage(undefined)).toBe('저장 실패')
    })
  })

  describe('currentEncryptionKeyState', () => {
    it('vals.encryption_key_state에서 상태 읽기', () => {
      state.vals.encryption_key_state = 'AVAILABLE'
      expect(currentEncryptionKeyState()).toBe('AVAILABLE')
    })

    it('MISSING 상태 읽기', () => {
      state.vals.encryption_key_state = 'MISSING'
      expect(currentEncryptionKeyState()).toBe('MISSING')
    })

    it('상태 없으면 null 반환 (구형 백엔드 응답 — P25 격리)', () => {
      expect(currentEncryptionKeyState()).toBeNull()
    })

    it('잘못된 값이면 null 반환', () => {
      state.vals.encryption_key_state = 'INVALID_VALUE'
      expect(currentEncryptionKeyState()).toBeNull()
    })
  })

  describe('currentSecretFieldStatus', () => {
    it('vals.secret_field_states에서 필드 상태 읽기', () => {
      state.vals.secret_field_states = { kiwoom_app_key: 'PLAINTEXT_LEGACY' }
      expect(currentSecretFieldStatus('kiwoom_app_key')).toBe('PLAINTEXT_LEGACY')
    })

    it('필드 없으면 null 반환', () => {
      state.vals.secret_field_states = { kiwoom_app_key: 'ENCRYPTED' }
      expect(currentSecretFieldStatus('ls_app_key')).toBeNull()
    })

    it('secret_field_states 자체가 없으면 null 반환', () => {
      expect(currentSecretFieldStatus('kiwoom_app_key')).toBeNull()
    })
  })

  describe('isEncryptionBlockingSave', () => {
    it('MISSING 상태 시 true (저장 차단)', () => {
      state.vals.encryption_key_state = 'MISSING'
      expect(isEncryptionBlockingSave()).toBe(true)
    })

    it('INVALID 상태 시 true (저장 차단)', () => {
      state.vals.encryption_key_state = 'INVALID'
      expect(isEncryptionBlockingSave()).toBe(true)
    })

    it('AVAILABLE 상태 시 false (저장 가능)', () => {
      state.vals.encryption_key_state = 'AVAILABLE'
      expect(isEncryptionBlockingSave()).toBe(false)
    })

    it('상태 없으면 false (구형 백엔드 — 저장 허용, 서버가 최종 방어선)', () => {
      expect(isEncryptionBlockingSave()).toBe(false)
    })
  })
})
