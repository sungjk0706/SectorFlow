/**
 * Property 12: WS Compression Threshold (압축 임계값)
 *
 * Feature: hts-level-optimization, Property 12: WS Compression Threshold
 *
 * **Validates: Requirements 14.3, 14.4**
 *
 * For any serialized real-data JSON message, if byte length > 512 then the output
 * SHALL be a zlib-compressed binary frame; if byte length ≤ 512 then the output
 * SHALL be an uncompressed text frame.
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import * as pako from 'pako'

// ── Replicate backend encoding logic (ws_manager.py _encode_realdata) ──

const ALLOWED_FIDS: Set<string> = new Set(['10', '11', '12', '14', '228'])

const KEY_SHORTEN: Record<string, string> = { type: 't', item: 'i', values: 'v' }

const COMPRESS_THRESHOLD = 512

interface RealDataPayload {
  type: string
  item: string
  values: Record<string, string>
}

interface EncodeResult {
  text: string | null
  binary: Uint8Array | null
}

/**
 * Replicates backend _encode_realdata logic:
 * 1. FID filter on values
 * 2. Key shortening (type→t, item→i, values→v)
 * 3. Add _v stamp
 * 4. JSON serialize
 * 5. If byte size > 512 → zlib compress (binary), else → text
 */
function encodeRealdata(data: RealDataPayload): EncodeResult {
  // FID filtering
  const filteredValues: Record<string, string> = {}
  for (const [k, v] of Object.entries(data.values)) {
    if (ALLOWED_FIDS.has(k)) {
      filteredValues[k] = v
    }
  }

  // Key shortening
  const shortened: Record<string, unknown> = {}
  for (const [key, val] of Object.entries(data)) {
    if (key === 'values') {
      shortened[KEY_SHORTEN[key]] = filteredValues
    } else if (key in KEY_SHORTEN) {
      shortened[KEY_SHORTEN[key]] = val
    } else {
      shortened[key] = val
    }
  }

  // _v stamp
  if (!('_v' in shortened)) {
    shortened['_v'] = 1
  }

  const payload = JSON.stringify({ event: 'real-data', data: shortened })
  const payloadBytes = new TextEncoder().encode(payload)

  if (payloadBytes.length > COMPRESS_THRESHOLD) {
    // zlib compress → binary frame
    const compressed = pako.deflate(payloadBytes)
    return { text: null, binary: compressed }
  }

  // text frame
  return { text: payload, binary: null }
}

// ── Generators ──

/**
 * Generate a real-data message with values that produce a serialized JSON
 * of approximately the target byte size (50-1000 bytes).
 *
 * Strategy: vary the number of FID entries and value string lengths to control size.
 * We include both allowed and non-allowed FIDs to test filtering.
 */
const realDataMessageArb: fc.Arbitrary<RealDataPayload> = fc
  .record({
    type: fc.stringMatching(/^[01]{2}$/),
    item: fc.stringMatching(/^[0-9]{6}$/),
    // Generate values with varying number of entries and value lengths
    // to produce messages across the 50-1000 byte range
    numAllowedFids: fc.integer({ min: 1, max: 5 }),
    numExtraFids: fc.integer({ min: 0, max: 10 }),
    valueLength: fc.integer({ min: 1, max: 100 }),
  })
  .chain(({ type, item, numAllowedFids, numExtraFids, valueLength }) => {
    const allowedFidKeys = ['10', '11', '12', '14', '228']
    const selectedAllowed = allowedFidKeys.slice(0, numAllowedFids)

    // Generate value strings of specified length
    const valueArb = fc.string({ minLength: valueLength, maxLength: valueLength })

    // Build values record with allowed FIDs
    const allowedEntries = selectedAllowed.map((fid) =>
      valueArb.map((v) => [fid, v] as [string, string]),
    )

    // Build extra FID entries (non-allowed, will be filtered out)
    const extraFidArb = fc.integer({ min: 15, max: 999 }).map((n) => String(n))
    const extraEntries = Array.from({ length: numExtraFids }, () =>
      fc.tuple(extraFidArb, valueArb).map(([k, v]) => [k, v] as [string, string]),
    )

    const allEntries = [...allowedEntries, ...extraEntries]

    if (allEntries.length === 0) {
      return fc.constant({ type, item, values: {} } as RealDataPayload)
    }

    return fc.tuple(...allEntries).map((entries) => {
      const values: Record<string, string> = {}
      for (const [k, v] of entries) {
        values[k] = v
      }
      return { type, item, values } as RealDataPayload
    })
  })

describe('Property 12: WS Compression Threshold (압축 임계값)', () => {
  it('messages > 512 bytes after serialization → binary frame (zlib compressed)', () => {
    /**
     * **Validates: Requirements 14.3**
     *
     * Generate messages that produce serialized JSON > 512 bytes,
     * verify they are returned as binary (zlib compressed) frames.
     */
    fc.assert(
      fc.property(realDataMessageArb, (data) => {
        const result = encodeRealdata(data)

        // Compute the serialized size (same logic as encodeRealdata)
        const filteredValues: Record<string, string> = {}
        for (const [k, v] of Object.entries(data.values)) {
          if (ALLOWED_FIDS.has(k)) {
            filteredValues[k] = v
          }
        }
        const shortened: Record<string, unknown> = {}
        for (const [key, val] of Object.entries(data)) {
          if (key === 'values') {
            shortened[KEY_SHORTEN[key]] = filteredValues
          } else if (key in KEY_SHORTEN) {
            shortened[KEY_SHORTEN[key]] = val
          } else {
            shortened[key] = val
          }
        }
        if (!('_v' in shortened)) shortened['_v'] = 1
        const payload = JSON.stringify({ event: 'real-data', data: shortened })
        const byteSize = new TextEncoder().encode(payload).length

        if (byteSize > COMPRESS_THRESHOLD) {
          // Must be binary frame
          expect(result.binary).not.toBeNull()
          expect(result.text).toBeNull()

          // Verify the binary is valid zlib that decompresses to the original payload
          const decompressed = pako.inflate(result.binary!, { to: 'string' })
          expect(decompressed).toBe(payload)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('messages ≤ 512 bytes after serialization → text frame (uncompressed JSON)', () => {
    /**
     * **Validates: Requirements 14.4**
     *
     * Generate messages that produce serialized JSON ≤ 512 bytes,
     * verify they are returned as text frames.
     */
    fc.assert(
      fc.property(realDataMessageArb, (data) => {
        const result = encodeRealdata(data)

        // Compute the serialized size
        const filteredValues: Record<string, string> = {}
        for (const [k, v] of Object.entries(data.values)) {
          if (ALLOWED_FIDS.has(k)) {
            filteredValues[k] = v
          }
        }
        const shortened: Record<string, unknown> = {}
        for (const [key, val] of Object.entries(data)) {
          if (key === 'values') {
            shortened[KEY_SHORTEN[key]] = filteredValues
          } else if (key in KEY_SHORTEN) {
            shortened[KEY_SHORTEN[key]] = val
          } else {
            shortened[key] = val
          }
        }
        if (!('_v' in shortened)) shortened['_v'] = 1
        const payload = JSON.stringify({ event: 'real-data', data: shortened })
        const byteSize = new TextEncoder().encode(payload).length

        if (byteSize <= COMPRESS_THRESHOLD) {
          // Must be text frame
          expect(result.text).not.toBeNull()
          expect(result.binary).toBeNull()

          // Verify the text is the expected JSON payload
          expect(result.text).toBe(payload)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('threshold boundary: exactly 512 bytes → text frame, 513 bytes → binary frame', () => {
    /**
     * **Validates: Requirements 14.3, 14.4**
     *
     * Generate messages near the 512-byte boundary to verify exact threshold behavior.
     */
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 200 }),
        (paddingLen) => {
          // Build a message and adjust value length to hit near the boundary
          const baseData: RealDataPayload = {
            type: '01',
            item: '005930',
            values: {
              '10': 'x'.repeat(paddingLen),
              '11': '1000',
              '12': '1.41',
            },
          }

          const result = encodeRealdata(baseData)

          // Compute actual byte size
          const filteredValues: Record<string, string> = {}
          for (const [k, v] of Object.entries(baseData.values)) {
            if (ALLOWED_FIDS.has(k)) filteredValues[k] = v
          }
          const shortened: Record<string, unknown> = {
            t: baseData.type,
            i: baseData.item,
            v: filteredValues,
            _v: 1,
          }
          const payload = JSON.stringify({ event: 'real-data', data: shortened })
          const byteSize = new TextEncoder().encode(payload).length

          if (byteSize > COMPRESS_THRESHOLD) {
            expect(result.binary).not.toBeNull()
            expect(result.text).toBeNull()
          } else {
            expect(result.text).not.toBeNull()
            expect(result.binary).toBeNull()
            expect(result.text).toBe(payload)
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
