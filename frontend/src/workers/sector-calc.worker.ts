// frontend/src/workers/sector-calc.worker.ts
// Web Worker - 업종 점수 계산 (백그라운드 계산)

interface SectorCalcMessage {
  type: 'sector-calc'
  requestId: string
  data: {
    sectorStocks: Record<string, any>
    sectorScores: any[]
  }
}

interface SectorCalcResponse {
  type: 'sector-calc-response'
  requestId: string
  result: any
  error?: string
}

self.onmessage = (event: MessageEvent<SectorCalcMessage>) => {
  const { type, requestId, data } = event.data

  if (type === 'sector-calc') {
    try {
      // 업종 점수 계산 로직 (백엔드에서 이동 예정)
      const result = calculateSectorScores(data.sectorScores)
      
      const response: SectorCalcResponse = {
        type: 'sector-calc-response',
        requestId,
        result,
      }
      
      self.postMessage(response)
    } catch (error) {
      const response: SectorCalcResponse = {
        type: 'sector-calc-response',
        requestId,
        result: null,
        error: error instanceof Error ? error.message : String(error),
      }
      
      self.postMessage(response)
    }
  }
}

function calculateSectorScores(sectorScores: any[]): any {
  // 업종 점수 계산 로직 (현재는 더미 구현)
  // 실제 구현은 백엔드 로직을 이동
  return {
    scores: sectorScores,
    timestamp: Date.now(),
  }
}

export {}
