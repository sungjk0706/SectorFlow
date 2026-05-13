/**
 * Property 11: WS Message Round-Trip (인코딩/디코딩 왕복)
 *
 * Feature: hts-level-optimization, Property 11: WS Message Round-Trip
 *
 * **Validates: Requirements 14.2, 14.5**
 *
 * For any valid real-data message with fields {type, item, values},
 * encoding (FID filter → key shorten → optional zlib compress) followed by
 * decoding (optional zlib decompress → key expand) SHALL produce a message
 * semantically equivalent to the original (with only allowed FIDs retained).
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { deflate, inflate } from 'pako'

// ─── Replicate backend encoder logic ───────────────────────────────────────

const ALLOWED_FIDS = new Set(['10', '11', '12', '14', '228'])

const COMPRESS_THRESHOLD = 512

/**
 * Simulates backend _encode_realdata:
 * FID filter → key shorten → JSON serialize → optional zlib compress
 *
 * Returns: { text: string | null, binary: Uint8Array | null }
 */
function encodeRealData(data: { type: string; item: string; values: Record<string, string> }): {
  text: string | null
  binary: Uint8Array | null
} {
  // FID filtering
  const filteredValues: Record<string, string> = {}
  for (const [k, v] of Object.entries(data.values)) {
    if (ALLOWED_FIDS.has(k)) {
      filteredValues[k] = v
    }
  }

  // Key shortening
  const shortened: Record<string, unknown> = {
    t: data.type,
    i: data.item,
    v: filteredValues,
    _v: 1,
  }

  const payload = JSON.stringify({ event: 'real-data', data: shortened })
  const payloadBytes = new TextEncoder().encode(payload)

  if (payloadBytes.length > COMPRESS_THRESHOLD) {
    // zlib compress → binary frame
    const compressed = deflate(payloadBytes)
    return { text: null, binary: compressed }
  }

  return { text: payload, binary: null }
}

// ─── Replicate frontend decoder logic ──────────────────────────────────────

const KEY_MAP: Record<string, string> = { t: 'type', i: 'item', v: 'values' }

function expandKeys(data: Record<string, unknown>): Record<string, unknown> {
  const expanded: Record<string, unknown> = {}
  for (const key of Object.keys(data)) {
    const fullKey = KEY_MAP[key] || key
    expanded[fullKey] = data[key]
  }
  return expanded
}

/**
 * Simulates frontend decoding:
 * binary → zlib decompress → JSON parse → key expand
 * text → JSON parse → key expand
 */
function decodeRealData(encoded: { text: string | null; binary: Uint8Array | null }): {
  type: string
  item: string
  values: Record<string, string>
} {
  let msg: { event: string; data: Record<string, unknown> }

  if (encoded.binary !== null) {
    // Binary frame: zlib decompress → JSON parse
    const decompressed = inflate(encoded.binary, { to: 'string' })
    msg = JSON.parse(decompressed)
  } else {
    // Text frame: direct JSON parse
    msg = JSON.parse(encoded.text!)
  }

  // Key expansion on data
  const expanded = expandKeys(msg.data as Record<string, unknown>)

  return {
    type: expanded.type as string,
    item: expanded.item as string,
    values: expanded.values as Record<string, string>,
  }
}

// ─── Generators ────────────────────────────────────────────────────────────

/** Generator: stock type code (01 = 주식체결, 02 = 주식호가 등) */
const typeArb = fc.stringMatching(/^[0-9]{2}$/)

/** Generator: 6-digit stock code */
const itemArb = fc.stringMatching(/^[0-9]{6}$/)

/** Generator: FID key — mix of allowed and disallowed FIDs */
const fidKeyArb = fc.oneof(
  // Allowed FIDs
  fc.constantFrom('10', '11', '12', '14', '228'),
  // Disallowed FIDs (should be filtered out)
  fc.constantFrom('15', '16', '17', '18', '20', '25', '30', '31', '32', '50', '100', '200'),
)

/** Generator: FID value (numeric string representing price/volume/rate) */
const fidValueArb = fc.oneof(
  fc.integer({ min: 0, max: 9999999 }).map(String),
  fc.float({ min: Math.fround(-99.99), max: Math.fround(99.99), noNaN: true }).map((v) =>
    v.toFixed(2),
  ),
)

/** Generator: values dict with arbitrary FID keys */
const valuesArb = fc.dictionary(fidKeyArb, fidValueArb, { minKeys: 1, maxKeys: 12 })

/** Generator: complete real-data message */
const realDataMessageArb = fc.record({
  type: typeArb,
  item: itemArb,
  values: valuesArb,
})

/**
 * Generator: large real-data message (forces compression path by having many FID entries)
 * Uses long alphanumeric value strings to ensure payload exceeds 512 bytes threshold.
 */
const largeValuesArb = fc.record({
  '10': fc.stringMatching(/^[0-9a-zA-Z]{80,120}$/),
  '11': fc.stringMatching(/^[0-9a-zA-Z]{80,120}$/),
  '12': fc.stringMatching(/^[0-9a-zA-Z]{80,120}$/),
  '14': fc.stringMatching(/^[0-9a-zA-Z]{80,120}$/),
  '228': fc.stringMatching(/^[0-9a-zA-Z]{80,120}$/),
})

const largeRealDataMessageArb = fc.record({
  type: typeArb,
  item: itemArb,
  values: largeValuesArb,
})

// ─── Tests ─────────────────────────────────────────────────────────────────

describe('Property 11: WS Message Round-Trip (인코딩/디코딩 왕복)', () => {
  it('encode → decode produces semantically equivalent message (allowed FIDs only preserved)', () => {
    /**
     * **Validates: Requirements 14.2, 14.5**
     */
    fc.assert(
      fc.property(realDataMessageArb, (original) => {
        // Encode (backend)
        const encoded = encodeRealData(original)

        // Decode (frontend)
        const decoded = decodeRealData(encoded)

        // Verify type and item are preserved
        expect(decoded.type).toBe(original.type)
        expect(decoded.item).toBe(original.item)

        // Verify only allowed FIDs are preserved
        const expectedValues: Record<string, string> = {}
        for (const [k, v] of Object.entries(original.values)) {
          if (ALLOWED_FIDS.has(k)) {
            expectedValues[k] = v
          }
        }
        expect(decoded.values).toEqual(expectedValues)

        // Verify no disallowed FIDs leak through
        for (const key of Object.keys(decoded.values)) {
          expect(ALLOWED_FIDS.has(key)).toBe(true)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('large messages (>512 bytes) round-trip correctly via zlib compression', () => {
    /**
     * **Validates: Requirements 14.2, 14.5**
     *
     * Tests the binary frame path: messages exceeding 512 bytes are
     * zlib-compressed by the encoder and decompressed by the decoder.
     */
    fc.assert(
      fc.property(largeRealDataMessageArb, (original) => {
        // Encode (backend)
        const encoded = encodeRealData(original)

        // Verify compression was applied (binary frame)
        expect(encoded.binary).not.toBeNull()
        expect(encoded.text).toBeNull()

        // Decode (frontend)
        const decoded = decodeRealData(encoded)

        // Verify type and item are preserved
        expect(decoded.type).toBe(original.type)
        expect(decoded.item).toBe(original.item)

        // Verify only allowed FIDs are preserved
        const expectedValues: Record<string, string> = {}
        for (const [k, v] of Object.entries(original.values)) {
          if (ALLOWED_FIDS.has(k)) {
            expectedValues[k] = v
          }
        }
        expect(decoded.values).toEqual(expectedValues)
      }),
      { numRuns: 100 },
    )
  })

  it('text frame path (≤512 bytes) round-trips correctly without compression', () => {
    /**
     * **Validates: Requirements 14.2, 14.5**
     *
     * Tests the text frame path: small messages are sent as-is without compression.
     */
    // Use a minimal message that stays under 512 bytes
    const smallMessageArb = fc.record({
      type: typeArb,
      item: itemArb,
      values: fc.dictionary(
        fc.constantFrom('10', '11', '12', '14', '228'),
        fc.integer({ min: 0, max: 99999 }).map(String),
        { minKeys: 1, maxKeys: 3 },
      ),
    })

    fc.assert(
      fc.property(smallMessageArb, (original) => {
        const encoded = encodeRealData(original)

        // Small messages should use text frame
        if (encoded.text !== null) {
          expect(encoded.binary).toBeNull()

          const decoded = decodeRealData(encoded)

          expect(decoded.type).toBe(original.type)
          expect(decoded.item).toBe(original.item)

          const expectedValues: Record<string, string> = {}
          for (const [k, v] of Object.entries(original.values)) {
            if (ALLOWED_FIDS.has(k)) {
              expectedValues[k] = v
            }
          }
          expect(decoded.values).toEqual(expectedValues)
        }
      }),
      { numRuns: 100 },
    )
  })
})
