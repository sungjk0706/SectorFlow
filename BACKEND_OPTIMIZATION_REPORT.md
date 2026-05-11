# Backend Optimization Analysis Report

**Date:** 2025-01-XX  
**Project:** SectorFlow  
**Scope:** Backend Performance Optimization Investigation

---

## Executive Summary

This report presents a comprehensive analysis of the SectorFlow backend's performance characteristics, covering real-time data processing, caching strategies, async processing patterns, memory management, and resource usage. The investigation reveals a well-architected system with strong async patterns and effective caching, but identifies several areas for optimization.

---

## 1. Real-time Data Processing Engine

### Files Analyzed
- `engine_service.py` (2260 lines)
- `engine_account_notify.py`
- `engine_ws_dispatch.py` (546 lines)

### What's Done Well ✅

**1. Efficient WebSocket Message Dispatching**
- `engine_ws_dispatch.py` uses a clean dispatch pattern for WebSocket message types (`LOGIN`, `REG`, `UNREG`, `REMOVE`, `REAL`)
- Real-time data handlers (`_handle_real_01`, `_handle_real_00`, `_handle_real_balance`, etc.) are well-separated
- Direct dictionary operations without locks where safe (GIL-protected single-key assignments)

**2. Sector Recalculation Coalescing**
- `engine_sector_confirm.py` implements 0.3-second coalescing for sector recomputation
- Dirty flag pattern (`_dirty_codes`) to batch updates
- Prevents excessive REG/REMOVE WebSocket operations

**3. Trade Amount Caching**
- `_latest_trade_amounts` dictionary for fast lookups
- `_rest_radar_quote_cache` for REST quote data caching
- Atomic single-key assignments without locks (safe under GIL)

### Issues Identified ⚠️

**1. Potential Event Loop Blocking**
- Multiple `time.sleep()` calls in REST API modules (kiwoom_rest.py, kiwoom_providers.py)
- These blocking sleeps can block the entire event loop during API rate limiting
- Found in: `kiwoom_rest.py` (lines 151, 165, 192, 201, 284, 292, 326, 342, 528, 599)

**2. Undefined `_TICK_FIELDS`**
- `engine_account_notify.py:340` references undefined `_TICK_FIELDS`
- Could cause AttributeError during runtime

**3. Sequential Processing in Hot Paths**
- Some real-time handlers process data sequentially without batching
- Could benefit from batched processing for high-frequency updates

### Recommendations 🔧

**1. Replace Blocking `time.sleep()` with `asyncio.sleep()`**
```python
# Before (blocking):
time.sleep(0.3)

# After (async):
await asyncio.sleep(0.3)
```

**2. Define `_TICK_FIELDS` Constant**
```python
# In engine_account_notify.py
_TICK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")
```

**3. Consider Batched Real-time Processing**
- Group incoming ticks within small time windows (e.g., 50ms)
- Process batches instead of individual messages for high-volume periods

---

## 2. Caching Strategies and Data I/O

### Files Analyzed
- `engine_cache.py` (141 lines)
- `avg_amt_cache.py` (476 lines)
- `sector_stock_cache.py` (415 lines)
- `market_close_pipeline.py` (772 lines)
- `industry_map.py` (556 lines)
- `sector_custom_data.py` (405 lines)
- `settings_file.py` (301 lines)

### What's Done Well ✅

**1. Multi-Layer Caching Architecture**
- JSON file caches for persistence (layout, snapshot, 5-day average, market map)
- In-memory caches for fast access (`_avg_amt_5d`, `_high_5d_cache`, `_latest_trade_amounts`)
- LRU cache decorators for frequently accessed functions (`@lru_cache` in config.py, trading_calendar.py)

**2. Parallel Cache Loading**
- `engine_cache.py` uses `asyncio.gather()` to load 5 caches in parallel
- `asyncio.to_thread()` to offload blocking file I/O from event loop
- Reduces startup time significantly

**3. Cache Invalidation Strategy**
- Date-based cache validation via `is_cache_valid()`
- Trading calendar integration for cache freshness
- Progress/resume files for interrupted downloads

**4. Coalesce_Save Pattern**
- `sector_custom_data.py` implements Coalesce_Save with threading.Lock
- Executor thread for file saves to avoid blocking asyncio loop
- Snapshot copying to ensure data consistency

**5. Rolling Window Caching**
- `avg_amt_cache.py` implements 5-day rolling average
- Efficient updates via `rolling_update_v2_from_trade_amounts()`
- Versioning support (v1/v2) for backward compatibility

### Issues Identified ⚠️

**1. Mixed Synchronous/Asynchronous I/O**
- Some file operations still use synchronous `open()` without `asyncio.to_thread()`
- `settings_file.py` uses synchronous `json.load()`/`json.dump()`
- `debug_session_log.py` uses synchronous file append

**2. Cache Size Unbounded**
- `_rest_radar_quote_cache` has no size limit
- `_latest_trade_amounts` grows unbounded during trading session
- No cache eviction policy for rarely accessed entries

**3. Redundant Cache Copies**
- `load_custom_data()` returns `deepcopy()` even for read-only operations
- `sector_custom_data.py` has both `load_custom_data()` (deepcopy) and `load_custom_data_readonly()` (no copy)
- Inconsistent usage patterns could cause unnecessary memory overhead

**4. No Cache Compression**
- Large JSON caches stored without compression
- Could reduce disk I/O and storage requirements

### Recommendations 🔧

**1. Wrap All Blocking I/O with `asyncio.to_thread()`**
```python
# Before (blocking):
with open(path, "r") as f:
    data = json.load(f)

# After (async):
data = await asyncio.to_thread(json.load, open(path, "r"))
```

**2. Implement Cache Size Limits with LRU Eviction**
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_quote_cache(key: str) -> dict:
    return _rest_radar_quote_cache.get(key)
```

**3. Standardize on Read-Only References**
- Use `load_custom_data_readonly()` for read operations
- Reserve `deepcopy()` only for modifications
- Document usage patterns clearly

**4. Add Cache Compression**
```python
import gzip

def save_compressed_cache(data: dict, path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
```

---

## 3. Async Processing Patterns and Event Loop

### Files Analyzed
- `engine_loop.py`
- `engine_bootstrap.py`
- `daily_time_scheduler.py`
- `kiwoom_connector.py`
- Multiple service modules

### What's Done Well ✅

**1. Extensive Use of `asyncio.to_thread()`**
- Blocking operations offloaded to thread pool
- Found in: `engine_cache.py`, `engine_bootstrap.py`, `market_close_pipeline.py`, `engine_loop.py`
- Prevents event loop blocking during file I/O and REST API calls

**2. Parallel Operations with `asyncio.gather()`**
- Cache loading parallelized in `engine_cache.py`
- Broker initialization parallelized in `engine_loop.py`
- Reduces overall latency

**3. Proper Task Management**
- `create_task()` for fire-and-forget operations
- `ensure_future()` pattern for deferred execution
- Task cancellation support with `TimerHandle`

**4. Event-Based Synchronization**
- `asyncio.Event` objects for pipeline coordination
- `data_fetched_event`, `parsing_done_event`, `filtering_done_event` in `market_close_pipeline.py`
- Clean async wait patterns with timeouts

**5. Coalescing Patterns**
- Account broadcast coalescing (0.5s window)
- Sector recalculation coalescing (0.3s window)
- Reduces unnecessary operations and WebSocket traffic

### Issues Identified ⚠️

**1. Blocking `time.sleep()` in Async Context**
- Found in: `kiwoom_rest.py`, `kiwoom_providers.py`, `industry_map.py`, `daily_time_scheduler.py`
- Blocks entire event loop during rate limiting
- Critical issue for real-time systems

**2. Mixed Event Loop Access Patterns**
- Some code uses `asyncio.get_event_loop()` (deprecated in 3.10+)
- Should use `asyncio.get_running_loop()` for current loop
- Found in: `engine_bootstrap.py:298`, `engine_loop.py:270`

**3. Potential Task Leaks**
- Many `create_task()` calls without explicit cleanup
- No task group pattern (Python 3.11+ `asyncio.TaskGroup`)
- Could accumulate background tasks over time

**4. No Backpressure Mechanism**
- WebSocket message processing has no rate limiting
- Could overwhelm system during high-volume periods
- No queue depth monitoring

### Recommendations 🔧

**1. Replace All `time.sleep()` with `asyncio.sleep()`**
```python
# Critical - replace all blocking sleeps:
# kiwoom_rest.py, kiwoom_providers.py, industry_map.py, etc.
await asyncio.sleep(delay)  # instead of time.sleep(delay)
```

**2. Update to Modern Event Loop API**
```python
# Before (deprecated):
loop = asyncio.get_event_loop()

# After (modern):
loop = asyncio.get_running_loop()
```

**3. Implement Task Groups (Python 3.11+)**
```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(task1())
    tg.create_task(task2())
# Automatic cleanup on exception
```

**4. Add Backpressure with Semaphores**
```python
_ws_message_sem = asyncio.Semaphore(100)  # Max 100 concurrent messages

async def handle_ws_message(msg: dict):
    async with _ws_message_sem:
        await process_message(msg)
```

---

## 4. Memory Management and Resource Usage

### Files Analyzed
- `engine_service.py` (global state variables)
- `lock_manager.py` (process-level locking)
- Multiple service modules with data structures

### What's Done Well ✅

**1. Explicit Resource Cleanup**
- `_reset_realtime_fields()` clears caches on WS subscribe start
- `.clear()` called on dictionaries: `_latest_trade_amounts`, `_orderbook_cache`, etc.
- Timer handles stored for cancellation: `_account_broadcast_timer`, `_recompute_handle`

**2. Lock-Based Concurrency Control**
- `asyncio.Lock` (`_shared_lock`) for protecting shared state
- `threading.Lock` in `sector_custom_data.py` for Coalesce_Save
- Process-level file lock via `lock_manager.py` to prevent duplicate execution

**3. Dataclass Usage**
- `@dataclass` decorators for structured data
- `@dataclass(frozen=True)` for immutable objects
- Type hints for better memory efficiency

**4. Cache Invalidation**
- Time-based cache invalidation (1s minimum for sector stocks cache)
- Dirty flag pattern for incremental updates
- Explicit `del` and `.pop()` for removing entries

### Issues Identified ⚠️

**1. Unbounded Global Data Structures**
- `_latest_trade_amounts`: grows unbounded during session
- `_rest_radar_quote_cache`: no size limit
- `_pending_stock_details`: accumulates entries
- `_snapshot_history`: grows without limit

**2. No Explicit Garbage Collection**
- No `gc.collect()` calls for memory pressure management
- Relies entirely on Python's automatic GC
- Could cause memory spikes during high-volume periods

**3. Excessive `deepcopy()` Usage**
- `sector_custom_data.py` uses `deepcopy()` for all returns
- Could cause significant memory overhead for large datasets
- No copy-on-write optimization

**4. No Memory Monitoring**
- No metrics for memory usage
- No alerts for memory leaks
- No profiling in production

**5. Timer Handle Accumulation**
- Multiple `call_later()` handles created in `daily_time_scheduler.py`
- Lists of handles: `_ws_subscribe_timer_handles`, `_auto_trade_timer_handles`
- Potential for handle leaks if not properly cancelled

### Recommendations 🔧

**1. Implement Size Limits with LRU Eviction**
```python
from collections import OrderedDict

class LRUCache:
    def __init__(self, maxsize: int = 1000):
        self.cache = OrderedDict()
        self.maxsize = maxsize
    
    def get(self, key: str):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]
    
    def set(self, key: str, value: Any):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)
```

**2. Add Periodic Garbage Collection**
```python
import gc

async def periodic_gc():
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        collected = gc.collect()
        logger.debug(f"GC collected {collected} objects")
```

**3. Optimize Copy Patterns**
```python
# Use copy-on-write for large structures
def get_data_readonly():
    return _custom_data  # Return reference, document as read-only

def get_data_copy():
    return copy.copy(_custom_data)  # Shallow copy when sufficient
```

**4. Add Memory Monitoring**
```python
import psutil
import tracemalloc

def log_memory_usage():
    process = psutil.Process()
    mem_info = process.memory_info()
    logger.info(f"Memory: RSS={mem_info.rss/1024/1024:.1f}MB")
    
    current, peak = tracemalloc.get_traced_memory()
    logger.info(f"Tracemalloc: current={current/1024/1024:.1f}MB, peak={peak/1024/1024:.1f}MB")
```

**5. Timer Handle Cleanup**
```python
# Cancel old handles before creating new ones
def reschedule_timers():
    for handle in _ws_subscribe_timer_handles:
        handle.cancel()
    _ws_subscribe_timer_handles.clear()
    # Create new handles...
```

---

## 5. Concurrency and Locking

### Files Analyzed
- `engine_service.py` (`_shared_lock`)
- `engine_strategy_core.py`
- `market_close_pipeline.py`
- `sector_custom_data.py` (threading.Lock)

### What's Done Well ✅

**1. Shared State Protection**
- `_shared_lock` (asyncio.Lock) protects critical sections
- Used in: `engine_strategy_core.py`, `market_close_pipeline.py`, `engine_cache.py`
- Atomic memory swaps under lock

**2. Thread-Safe File Operations**
- `threading.Lock` in `sector_custom_data.py` for Coalesce_Save
- Executor thread pattern for file I/O
- Prevents race conditions in file saves

**3. Lock Granularity**
- Fine-grained locking (only protect critical sections)
- Lock held for minimal duration
- No nested lock patterns (deadlock-safe)

### Issues Identified ⚠️

**1. Potential Lock Contention**
- `_shared_lock` used for multiple unrelated operations
- Could become bottleneck under high concurrency
- No lock contention monitoring

**2. No Lock Timeout**
- Lock acquisitions have no timeout
- Could hang indefinitely if lock holder crashes
- No deadlock detection

**3. Mixed Lock Types**
- `asyncio.Lock` and `threading.Lock` used in different contexts
- Potential for confusion in async/threaded hybrid code

### Recommendations 🔧

**1. Use Specialized Locks for Different Resources**
```python
_positions_lock = asyncio.Lock()  # For positions
_cache_lock = asyncio.Lock()      # For caches
_trade_lock = asyncio.Lock()      # For trading operations
```

**2. Add Lock Timeouts**
```python
try:
    async with asyncio.timeout(5.0):
        async with _shared_lock:
            # Critical section
except TimeoutError:
    logger.error("Lock acquisition timeout")
```

**3. Monitor Lock Contention**
```python
import time

class MonitoredLock:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.wait_times = []
    
    async def __aenter__(self):
        start = time.monotonic()
        await self.lock.acquire()
        wait = time.monotonic() - start
        self.wait_times.append(wait)
        if wait > 0.1:  # Log if wait > 100ms
            logger.warning(f"Lock contention: {wait:.3f}s")
        return self
    
    async def __aexit__(self, *args):
        self.lock.release()
```

---

## 6. File I/O and Data Persistence

### Files Analyzed
- `settings_file.py`
- `debug_session_log.py`
- `avg_amt_cache.py`
- `sector_stock_cache.py`

### What's Done Well ✅

**1. Atomic File Operations**
- `settings_file.py` uses `mkdir(parents=True, exist_ok=True)`
- Safe file writes with proper encoding
- Error handling with fallback to defaults

**2. Schema Validation**
- `sector_custom_data.py` validates JSON schema on load
- Type checking for dict keys/values
- Fallback to empty data on error

**3. Migration Support**
- `settings_file.py` has multiple migration functions
- Handles legacy field names and structure changes
- Automatic migration on load

### Issues Identified ⚠️

**1. Synchronous File I/O**
- Most file operations are synchronous
- Blocks event loop during large file reads/writes
- No async file I/O library (aiofiles) used

**2. No File Handle Pooling**
- Each file operation opens/closes file handle
- Could benefit from handle reuse
- No buffered I/O optimization

**3. No Compression**
- Large JSON files stored uncompressed
- Increases disk I/O and storage
- Could use gzip for better performance

### Recommendations 🔧

**1. Use aiofiles for Async File I/O**
```python
import aiofiles

async def load_json_async(path: Path) -> dict:
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return json.loads(content)
```

**2. Add Compression**
```python
import gzip

async def save_compressed(data: dict, path: Path):
    async with aiofiles.open(path.with_suffix(".json.gz"), "wb") as f:
        compressed = gzip.compress(json.dumps(data).encode())
        await f.write(compressed)
```

**3. Implement Buffered Writes**
```python
from io import BufferedWriter

def buffered_write(path: Path, data: str):
    with open(path, "w", encoding="utf-8", buffering=8192) as f:
        f.write(data)
```

---

## 7. Overall Architecture

### What's Done Well ✅

**1. Clean Separation of Concerns**
- Engine logic separated from WebSocket handling
- Cache management isolated in dedicated modules
- Clear module boundaries

**2. Event-Driven Design**
- Async events for coordination
- Observer pattern for notifications
- Loose coupling between components

**3. Extensive Logging**
- Structured logging throughout
- Performance-relevant log messages
- Debug levels for troubleshooting

### Issues Identified ⚠️

**1. Global State Heavy**
- Many global variables in `engine_service.py`
- Makes testing difficult
- Limits scalability to multiple instances

**2. No Circuit Breakers**
- REST API calls have no circuit breaker pattern
- Could cascade failures during API outages
- No fallback mechanisms

**3. Limited Observability**
- No metrics collection
- No distributed tracing
- Limited performance monitoring

### Recommendations 🔧

**1. Reduce Global State**
```python
# Move to class-based state management
class EngineState:
    def __init__(self):
        self._latest_trade_amounts: dict[str, int] = {}
        self._positions: list = []
        # ... other state
    
    async def get_trade_amount(self, code: str) -> int:
        return self._latest_trade_amounts.get(code, 0)
```

**2. Add Circuit Breakers**
```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
async def call_rest_api(url: str) -> dict:
    # API call
    pass
```

**3. Add Metrics Collection**
```python
from prometheus_client import Counter, Histogram

api_calls = Counter('api_calls_total', 'Total API calls')
api_duration = Histogram('api_duration_seconds', 'API call duration')

@api_calls.time()
async def call_api():
    # API call
    pass
```

---

## 8. Priority Recommendations

### Critical (Immediate Action Required)

1. **Replace all `time.sleep()` with `asyncio.sleep()`**
   - Files: `kiwoom_rest.py`, `kiwoom_providers.py`, `industry_map.py`, `daily_time_scheduler.py`
   - Impact: Prevents event loop blocking
   - Effort: Low (find and replace)

2. **Define `_TICK_FIELDS` in `engine_account_notify.py`**
   - Impact: Prevents runtime AttributeError
   - Effort: Trivial

### High Priority (Next Sprint)

3. **Implement Cache Size Limits**
   - Add LRU eviction to unbounded caches
   - Impact: Prevents memory leaks
   - Effort: Medium

4. **Wrap All Blocking I/O with `asyncio.to_thread()`**
   - Files: `settings_file.py`, `debug_session_log.py`
   - Impact: Improves event loop responsiveness
   - Effort: Medium

5. **Add Memory Monitoring**
   - Implement periodic memory usage logging
   - Impact: Early detection of memory issues
   - Effort: Low

### Medium Priority (Future Iterations)

6. **Use aiofiles for Async File I/O**
   - Impact: Better async performance
   - Effort: Medium (requires new dependency)

7. **Add Cache Compression**
   - Impact: Reduced disk I/O and storage
   - Effort: Low

8. **Implement Task Groups**
   - Impact: Better task management and cleanup
   - Effort: Medium (requires Python 3.11+)

### Low Priority (Nice to Have)

9. **Add Circuit Breakers**
   - Impact: Better resilience
   - Effort: High

10. **Add Metrics Collection**
    - Impact: Better observability
    - Effort: High

---

## 9. Conclusion

The SectorFlow backend demonstrates a solid foundation with:
- ✅ Strong async patterns and event loop usage
- ✅ Effective multi-layer caching strategy
- ✅ Clean separation of concerns
- ✅ Good concurrency control with locks

Key areas for improvement:
- ⚠️ Replace blocking `time.sleep()` calls (critical)
- ⚠️ Add cache size limits to prevent memory leaks
- ⚠️ Wrap all blocking I/O with async wrappers
- ⚠️ Add memory monitoring and metrics

Overall, the system is well-architected for real-time trading operations. The recommended optimizations will further improve performance, reliability, and observability.

---

## Appendix: File Inventory

### Core Modules
- `engine_service.py` - Main engine orchestrator (2260 lines)
- `engine_cache.py` - Cache orchestration (141 lines)
- `engine_bootstrap.py` - Bootstrap logic
- `engine_ws_dispatch.py` - WebSocket dispatch (546 lines)
- `engine_sector_confirm.py` - Sector recalculation

### Cache Modules
- `avg_amt_cache.py` - 5-day average cache (476 lines)
- `sector_stock_cache.py` - Sector stock cache (415 lines)
- `industry_map.py` - Industry data (556 lines)
- `sector_custom_data.py` - Custom sector data (405 lines)

### Utility Modules
- `settings_file.py` - Settings I/O (301 lines)
- `debug_session_log.py` - Debug logging (49 lines)
- `lock_manager.py` - Process locking (143 lines)
- `trading_calendar.py` - Calendar utilities

### REST API Modules
- `kiwoom_rest.py` - REST API client
- `kiwoom_connector.py` - WebSocket connector
- `kiwoom_providers.py` - Auth providers

---

**Report Generated By:** Cascade AI Assistant  
**Analysis Date:** 2025-01-XX  
**Version:** 1.0
