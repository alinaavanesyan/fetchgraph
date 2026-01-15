from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Dict

from prometheus_client import Counter, Gauge, Histogram

from llm.models.chat import ChatCompletionRequest

HISTOGRAM_BUCKETS_SECONDS = [
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
]

_REQUESTS_TOTAL = Counter(
    "llm_proxy_requests_total",
    "Total chat requests handled by priority queue",
    labelnames=["endpoint", "priority", "status", "error_code"],
)
_QUEUE_OVERFLOW = Counter(
    "llm_proxy_queue_overflow_total",
    "Total chat requests rejected due to queue overflow",
    labelnames=["priority"],
)
_QUEUE_WAIT_SECONDS = Histogram(
    "llm_proxy_queue_wait_seconds",
    "Chat queue wait time in seconds",
    labelnames=["endpoint", "priority"],
    buckets=HISTOGRAM_BUCKETS_SECONDS,
)
_PROVIDER_LATENCY_SECONDS = Histogram(
    "llm_proxy_provider_latency_seconds",
    "Chat provider latency in seconds",
    labelnames=["endpoint", "priority"],
    buckets=HISTOGRAM_BUCKETS_SECONDS,
)
_QUEUE_LENGTH = Gauge(
    "llm_proxy_queue_length",
    "Current number of queued chat requests per priority",
    labelnames=["priority"],
)
_INFLIGHT = Gauge(
    "llm_proxy_in_flight",
    "Current number of inflight chat requests per priority",
    labelnames=["priority"],
)


@dataclass
class QueueMetrics:
    queue_wait_ms: int
    provider_latency_ms: int
    priority: str
    endpoint: str


@dataclass
class QueueResult:
    response_body: dict[str, Any]
    metrics: QueueMetrics


class QueueOverflowError(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original


@dataclass
class QueuedChatRequest:
    request_id: str
    priority: str
    payload: ChatCompletionRequest
    enqueue_ts: float
    future: asyncio.Future[QueueResult]
    endpoint: str


class PriorityChatQueue:
    def __init__(
        self,
        handler: Callable[[ChatCompletionRequest], Awaitable[dict[str, Any]]],
        limits: Dict[str, int],
        max_queue: int,
        default_priority: str,
    ):
        self._handler = handler
        self._limits = {k: max(v, 0) for k, v in limits.items()}
        self._max_queue = max_queue
        self._lock = asyncio.Lock()
        self._dispatch_scheduled = False
        self._priorities: list[str] = [pr for pr, slots in self._limits.items() if slots > 0]
        if not self._priorities:
            raise ValueError("At least one priority must have capacity > 0")
        self._queues: Dict[str, Deque[QueuedChatRequest]] = {pr: deque() for pr in self._priorities}
        self._inflight: Dict[str, int] = {pr: 0 for pr in self._priorities}
        self._default_priority = default_priority if default_priority in self._priorities else self._priorities[0]
        self._queue_gauge = _QUEUE_LENGTH

    async def snapshot(self) -> dict[str, dict[str, int]]:
        async with self._lock:
            return {
                "queue_len": {priority: len(queue) for priority, queue in self._queues.items()},
                "in_flight": dict(self._inflight),
            }

    @property
    def default_priority(self) -> str:
        return self._default_priority

    @property
    def priorities(self) -> tuple[str, ...]:
        return tuple(self._priorities)

    async def enqueue(
        self, request_id: str, priority: str, payload: ChatCompletionRequest, endpoint: str
    ) -> QueueResult:
        if priority not in self._priorities:
            raise QueueOverflowError(f"Priority '{priority}' has no available capacity")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[QueueResult] = loop.create_future()
        item = QueuedChatRequest(
            request_id=request_id,
            priority=priority,
            payload=payload,
            enqueue_ts=time.perf_counter(),
            future=future,
            endpoint=endpoint,
        )

        dispatch_immediately = False

        async with self._lock:
            if self._max_queue == 0:
                if self._inflight[priority] >= self._limits[priority]:
                    _REQUESTS_TOTAL.labels(
                        endpoint=endpoint,
                        priority=priority,
                        status="error",
                        error_code="queue_overflow",
                    ).inc()
                    _QUEUE_OVERFLOW.labels(priority=priority).inc()
                    raise QueueOverflowError("Queue capacity exceeded")
                self._inflight[priority] += 1
                _INFLIGHT.labels(priority=priority).inc()
                dispatch_immediately = True
            else:
                queued = self._queued_len_locked()
                if self._max_queue >= 0 and queued >= self._max_queue:
                    _REQUESTS_TOTAL.labels(
                        endpoint=endpoint,
                        priority=priority,
                        status="error",
                        error_code="queue_overflow",
                    ).inc()
                    _QUEUE_OVERFLOW.labels(priority=priority).inc()
                    raise QueueOverflowError("Queue capacity exceeded")
                self._queues[priority].append(item)
                self._queue_gauge.labels(priority=priority).inc()
                self._schedule_dispatch_locked()

        if dispatch_immediately:
            asyncio.create_task(self._execute(item))
        return await future

    def _queued_len_locked(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def _dispatch_locked(self) -> None:
        while True:
            next_priority = self._next_priority_locked()
            if next_priority is None:
                break
            queued_item = self._queues[next_priority].popleft()
            self._queue_gauge.labels(priority=queued_item.priority).dec()
            self._inflight[next_priority] += 1
            _INFLIGHT.labels(priority=queued_item.priority).inc()
            asyncio.create_task(self._execute(queued_item))

    def _schedule_dispatch_locked(self) -> None:
        if self._dispatch_scheduled:
            return
        self._dispatch_scheduled = True
        loop = asyncio.get_running_loop()
        loop.call_soon(asyncio.create_task, self._run_dispatch())

    async def _run_dispatch(self) -> None:
        async with self._lock:
            self._dispatch_scheduled = False
            self._dispatch_locked()

    def _next_priority_locked(self) -> str | None:
        for candidate in self._priorities:
            limit = self._limits[candidate]
            if limit > 0 and self._inflight[candidate] < limit and self._queues[candidate]:
                return candidate
        return None

    async def _execute(self, item: QueuedChatRequest) -> None:
        processing_start = time.perf_counter()
        try:
            response_body = await self._handler(item.payload)
            provider_end = time.perf_counter()
            metrics = QueueMetrics(
                queue_wait_ms=self._ms_delta(processing_start - item.enqueue_ts),
                provider_latency_ms=self._ms_delta(provider_end - processing_start),
                priority=item.priority,
                endpoint=item.endpoint,
            )
            _QUEUE_WAIT_SECONDS.labels(endpoint=item.endpoint, priority=item.priority).observe(
                metrics.queue_wait_ms / 1000.0
            )
            _PROVIDER_LATENCY_SECONDS.labels(endpoint=item.endpoint, priority=item.priority).observe(
                metrics.provider_latency_ms / 1000.0
            )
            if not item.future.done():
                item.future.set_result(QueueResult(response_body=response_body, metrics=metrics))
            _REQUESTS_TOTAL.labels(endpoint=item.endpoint, priority=item.priority, status="success", error_code="none").inc()
        except Exception as exc:  # noqa: BLE001
            if not item.future.done():
                item.future.set_exception(ProviderError(exc))
            error_code = getattr(exc, "__class__", type(exc)).__name__
            _REQUESTS_TOTAL.labels(
                endpoint=item.endpoint,
                priority=item.priority,
                status="error",
                error_code=error_code,
            ).inc()
        finally:
            async with self._lock:
                self._inflight[item.priority] = max(self._inflight[item.priority] - 1, 0)
                _INFLIGHT.labels(priority=item.priority).dec()
                self._schedule_dispatch_locked()

    @staticmethod
    def _ms_delta(delta_seconds: float) -> int:
        return int(max(delta_seconds, 0) * 1000)
