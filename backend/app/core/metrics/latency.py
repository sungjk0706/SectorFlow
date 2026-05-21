"""
Latency metrics collector for real-time performance monitoring.
Tracks latency across the system and provides summary statistics.
"""

import time
import logging
from collections import defaultdict, deque
from typing import Dict, List, Optional
import statistics

_log = logging.getLogger(__name__)


class LatencyMetrics:
    """Collects and analyzes latency metrics with percentile calculations."""
    
    # Metric thresholds (ms)
    THRESHOLDS = {
        "broker_to_backend_ms": 100,
        "coalescing_ms": 50,
        "backend_to_frontend_ms": 50,
        "frontend_to_ui_ms": 50,
        "order_to_fill_ms": 1000,
        "fill_to_sync_ms": 200,
        "end_to_end_ms": 200,  # broker_recv_ts부터 ui_render_ts까지 전체 지연
    }
    
    def __init__(self, max_samples: int = 10000, max_alerts: int = 100):
        """
        Initialize LatencyMetrics collector.
        
        Args:
            max_samples: Maximum number of samples to keep per metric
            max_alerts: Maximum number of alerts to keep in history
        """
        self._samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_samples))
        self._alerts: deque = deque(maxlen=max_alerts)
        self._max_samples = max_samples
        
    def record(self, metric_name: str, value: float) -> None:
        """
        Record a latency metric value.
        
        Args:
            metric_name: Name of the metric (e.g., "broker_to_backend_ms")
            value: Latency value in milliseconds
        """
        if value < 0:
            _log.warning(f"[LatencyMetrics] Invalid negative value for {metric_name}: {value}")
            return
            
        self._samples[metric_name].append(value)
        
        # Check threshold
        threshold = self.THRESHOLDS.get(metric_name)
        if threshold and value > threshold:
            alert = {
                "timestamp": time.time(),
                "metric_name": metric_name,
                "value": value,
                "threshold": threshold,
            }
            self._alerts.append(alert)
            _log.warning(
                f"[LatencyMetrics] Threshold exceeded: {metric_name}={value:.2f}ms "
                f"(threshold={threshold}ms)"
            )
    
    def get_percentile(self, metric_name: str, percentile: float) -> Optional[float]:
        """
        Calculate percentile for a metric.
        
        Args:
            metric_name: Name of the metric
            percentile: Percentile to calculate (0-100)
            
        Returns:
            Percentile value or None if no samples
        """
        samples = list(self._samples.get(metric_name, []))
        if not samples:
            return None
            
        if not 0 <= percentile <= 100:
            raise ValueError("Percentile must be between 0 and 100")
            
        samples_sorted = sorted(samples)
        k = (len(samples_sorted) - 1) * (percentile / 100)
        f = int(k)
        c = f + 1 if f + 1 < len(samples_sorted) else f
        
        if f == c:
            return samples_sorted[f]
        
        return samples_sorted[f] + (k - f) * (samples_sorted[c] - samples_sorted[f])
    
    def get_summary(self, metric_name: str) -> Optional[Dict]:
        """
        Get summary statistics for a metric.
        
        Args:
            metric_name: Name of the metric
            
        Returns:
            Dictionary with count, min, max, avg, p50, p95, p99 or None if no samples
        """
        samples = list(self._samples.get(metric_name, []))
        if not samples:
            return None
            
        return {
            "count": len(samples),
            "min": min(samples),
            "max": max(samples),
            "avg": statistics.mean(samples),
            "p50": self.get_percentile(metric_name, 50),
            "p95": self.get_percentile(metric_name, 95),
            "p99": self.get_percentile(metric_name, 99),
        }
    
    def get_all_summaries(self) -> Dict[str, Dict]:
        """
        Get summary statistics for all metrics.
        
        Returns:
            Dictionary mapping metric names to their summaries
        """
        summaries = {}
        for metric_name in self._samples:
            summary = self.get_summary(metric_name)
            if summary:
                summaries[metric_name] = summary
        return summaries
    
    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        """
        Get recent alerts.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of alert dictionaries (most recent first)
        """
        return list(self._alerts)[-limit:][::-1]
    
    def clear(self) -> None:
        """Clear all samples and alerts."""
        self._samples.clear()
        self._alerts.clear()
        _log.info("[LatencyMetrics] All metrics cleared")


# Global instance
_latency_metrics: Optional[LatencyMetrics] = None


def get_latency_metrics() -> LatencyMetrics:
    """Get or create the global LatencyMetrics instance."""
    global _latency_metrics
    if _latency_metrics is None:
        _latency_metrics = LatencyMetrics()
    return _latency_metrics
