/**
 * Property 13: WS FID Filtering (불필요 필드 제거)
 *
 * Feature: hts-level-optimization, Property 13: WS FID Filtering
 *
 * **Validates: Requirements 14.1**
 *
 * For any real-data message with arbitrary FID keys in values,
 * the transmitted message SHALL contain only FIDs in the set {10, 11, 12, 14, 228},
 * and any FID not present in the original SHALL be omitted (not set to null).
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ── FID Filtering Logic (mirrors backend ws_manager.py _encode_realdata) ──

/** Allowed FIDs — only these are transmitted to the frontend */
const ALLOWED_FIDS = new Set(['10', '11', '12', '14', '228'])

/**
 * Filters a values dictionary to only include allowed FIDs.
 * This replicates the backend filtering logic in _encode_realdata:
 *   filtered_values = {k: v for k, v in values.items() if k in ALLOWED_FIDS}
 */
function filterFids(values: Record<string, string>): Record<string, string> {
  const filtered: Record<string, string> = {}
  for (const [k, v] of Object.entries(values)) {
    if (ALLOWED_FIDS.has(k)) {
      filtered[k] = v
    }
  }
  return filtered
}

// ── Generators ──

/** Generator: arbitrary FID key (mix of allowed and disallowed) */
const fidKeyArb: fc.Arbitrary<string> = fc.oneof(
  // Allowed FIDs
  fc.constantFrom('10', '11', '12', '14', '228'),
  // Common disallowed FIDs (realistic HTS FID numbers)
  fc.constantFrom('15', '16', '17', '18', '19', '20', '25', '30', '31', '32', '41', '61', '71', '81'),
  // Arbitrary numeric string FIDs
  fc.integer({ min: 1, max: 999 }).map(String),
)

/** Generator: arbitrary values dict with random FID keys */
const valuesDictArb: fc.Arbitrary<Record<string, string>> = fc.dictionary(
  fidKeyArb,
  fc.string({ minLength: 1, maxLength: 20 }),
  { minKeys: 0, maxKeys: 30 },
)

describe('Property 13: WS FID Filtering (불필요 필드 제거)', () => {
  it('filtered values contain only allowed FIDs {10, 11, 12, 14, 228}', () => {
    /**
     * **Validates: Requirements 14.1**
     *
     * For any arbitrary values dict, after filtering, every key in the result
     * must be a member of ALLOWED_FIDS.
     */
    fc.assert(
      fc.property(valuesDictArb, (values) => {
        const filtered = filterFids(values)

        // All keys in filtered result must be in ALLOWED_FIDS
        for (const key of Object.keys(filtered)) {
          expect(ALLOWED_FIDS.has(key)).toBe(true)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('allowed FIDs present in original are preserved in filtered output', () => {
    /**
     * **Validates: Requirements 14.1**
     *
     * For any values dict, if an allowed FID exists in the original,
     * it must appear in the filtered result with the same value.
     */
    fc.assert(
      fc.property(valuesDictArb, (values) => {
        const filtered = filterFids(values)

        for (const fid of ALLOWED_FIDS) {
          if (fid in values) {
            expect(filtered[fid]).toBe(values[fid])
          }
        }
      }),
      { numRuns: 200 },
    )
  })

  it('disallowed FIDs are never present in filtered output', () => {
    /**
     * **Validates: Requirements 14.1**
     *
     * For any values dict containing FIDs not in ALLOWED_FIDS,
     * those FIDs must not appear in the filtered result.
     */
    fc.assert(
      fc.property(valuesDictArb, (values) => {
        const filtered = filterFids(values)

        for (const key of Object.keys(values)) {
          if (!ALLOWED_FIDS.has(key)) {
            expect(key in filtered).toBe(false)
          }
        }
      }),
      { numRuns: 200 },
    )
  })

  it('missing FIDs are omitted, not set to null', () => {
    /**
     * **Validates: Requirements 14.1**
     *
     * FIDs not present in the original values dict must not appear
     * in the filtered output (no null/undefined padding).
     */
    fc.assert(
      fc.property(valuesDictArb, (values) => {
        const filtered = filterFids(values)

        // No key in filtered should have null or undefined value
        for (const [_key, val] of Object.entries(filtered)) {
          expect(val).not.toBeNull()
          expect(val).not.toBeUndefined()
        }

        // Keys not in original should not appear in filtered
        for (const fid of ALLOWED_FIDS) {
          if (!(fid in values)) {
            expect(fid in filtered).toBe(false)
          }
        }
      }),
      { numRuns: 200 },
    )
  })

  it('filtered output size is at most the number of allowed FIDs present in original', () => {
    /**
     * **Validates: Requirements 14.1**
     *
     * The number of keys in the filtered result equals the count of
     * allowed FIDs that exist in the original values dict.
     */
    fc.assert(
      fc.property(valuesDictArb, (values) => {
        const filtered = filterFids(values)

        const expectedCount = Object.keys(values).filter((k) => ALLOWED_FIDS.has(k)).length
        expect(Object.keys(filtered).length).toBe(expectedCount)
        expect(Object.keys(filtered).length).toBeLessThanOrEqual(5)
      }),
      { numRuns: 200 },
    )
  })
})
