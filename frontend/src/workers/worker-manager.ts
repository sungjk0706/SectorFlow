// frontend/src/workers/worker-manager.ts
// Web Worker 관리자 - request ID 추적 및 Worker 풀 관리

export interface WorkerRequest {
  type: string
  requestId: string
  data: any
}

export interface WorkerResponse {
  type: string
  requestId: string
  result?: any
  error?: string
}

class WorkerManager {
  private workers: Map<string, Worker> = new Map()
  private pendingRequests: Map<string, (response: WorkerResponse) => void> = new Map()
  private requestIdCounter = 0

  constructor() {
    this.initializeWorkers()
  }

  private initializeWorkers(): void {
    // 업종 계산 Worker
    const sectorCalcWorker = new Worker(
      new URL('./sector-calc.worker.ts', import.meta.url),
      { type: 'module' }
    )
    
    sectorCalcWorker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      this.handleWorkerResponse(event.data)
    }
    
    this.workers.set('sector-calc', sectorCalcWorker)
  }

  private generateRequestId(): string {
    return `req_${Date.now()}_${this.requestIdCounter++}`
  }

  private handleWorkerResponse(response: WorkerResponse): void {
    const { requestId } = response
    const resolver = this.pendingRequests.get(requestId)
    
    if (resolver) {
      resolver(response)
      this.pendingRequests.delete(requestId)
    }
  }

  async sendToWorker(
    workerName: string,
    message: Omit<WorkerRequest, 'requestId'>
  ): Promise<WorkerResponse> {
    const worker = this.workers.get(workerName)
    if (!worker) {
      throw new Error(`Worker not found: ${workerName}`)
    }

    const requestId = this.generateRequestId()
    const request: WorkerRequest = {
      ...message,
      requestId,
    }

    return new Promise((resolve, reject) => {
      this.pendingRequests.set(requestId, resolve)
      
      // 타임아웃 설정 (10초)
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(requestId)
        reject(new Error(`Worker request timeout: ${requestId}`))
      }, 10000)

      worker.postMessage(request)
      
      // 응답 시 타임아웃 제거
      this.pendingRequests.set(requestId, (response) => {
        clearTimeout(timeout)
        resolve(response)
      })
    })
  }

  terminateAll(): void {
    for (const [name, worker] of this.workers) {
      worker.terminate()
      this.workers.delete(name)
    }
  }
}

// 전역 싱글톤
let workerManagerInstance: WorkerManager | null = null

export function getWorkerManager(): WorkerManager {
  if (!workerManagerInstance) {
    workerManagerInstance = new WorkerManager()
  }
  return workerManagerInstance
}

export function terminateWorkerManager(): void {
  if (workerManagerInstance) {
    workerManagerInstance.terminateAll()
    workerManagerInstance = null
  }
}
