"""Opt-in, bounded Phase 1 observations; no controls or acceptance verdicts.

Disabled unless main(phase1_timing=True) is explicitly selected. Timing describes
observed calls, not a guarantee that Python can preempt a blocking native call.
UART capacity/headroom is nominal: driver/FIFO reservations remain unverified.
"""

import gc
import time

from utils.ticks import ticks_diff, ticks_ms


LOOP = 0
BM_POLL = 1
NX_POLL = 2
BM_READ = 3
NX_READ = 4
BM_WRITE = 5
NX_WRITE = 6
ESPNOW_SEND = 7
ESPNOW_COMPLETION = 8
SHA256 = 9
HMAC = 10
GC = 11
REPORT = 12
METRICS = ("loop_gap", "bm_uart_queue_poll_gap", "nx_uart_queue_poll_gap", "bm_uart_read",
           "nx_uart_read", "bm_uart_write", "nx_uart_write", "espnow_send_call",
           "espnow_completion_observed", "sha256", "hmac", "gc", "report")
BUCKET_NS = (1000000, 2000000, 5000000, 10000000, 20000000, 50000000,
             100000000, 200000000, 500000000, 1000000000, 2000000000)
EVENTS = ("uart_read_error", "uart_write_error", "espnow_send_error",
          "espnow_pending_cancelled", "heap_sample_error", "clock_regression", "report_error",
          "uart_observation_unavailable", "bm83_parser_overflow", "bm83_parser_dropped_bytes",
          "bm83_invalid_length", "bm83_checksum_error", "bm83_resync_discarded_bytes",
          "nextion_parser_overflow", "nextion_parser_dropped_bytes",
          "espnow_counter_read_error", "espnow_counter_unavailable",
          "espnow_counter_discontinuity", "espnow_counter_baseline_reset")


def heap_observation():
    """Public Python GC/native 8-bit observations, without forcing collection."""
    result = {"python_gc_free": None, "python_gc_alloc": None,
              "native_8bit_free": None, "native_8bit_largest": None}
    for field, attribute in (("python_gc_free", "mem_free"),
                             ("python_gc_alloc", "mem_alloc")):
        method = getattr(gc, attribute, None)
        if callable(method):
            result[field] = method()
    try:
        import espidf
    except ImportError:
        return result
    for field, attribute in (("native_8bit_free", "heap_caps_get_free_size"),
                             ("native_8bit_largest", "heap_caps_get_largest_free_block")):
        method = getattr(espidf, attribute, None)
        if callable(method):
            # These CP bindings report MALLOC_CAP_8BIT; no DMA-only inference.
            result[field] = method()
    return result


class Phase1Metrics:
    """Fixed metric/event inventory; cumulative counters never retain samples."""

    def __init__(self, clock=None, clock_kind=None, heap_sampler=heap_observation,
                 report_period_ns=10000000000, heap_period_ns=5000000000):
        if clock is None:
            clock = getattr(time, "monotonic_ns", None)
            clock_kind = "monotonic_ns" if callable(clock) else "ticks_ms"
            if not callable(clock):
                clock = ticks_ms
        elif clock_kind is None:
            clock_kind = "injected_ns"
        if clock_kind not in ("monotonic_ns", "injected_ns", "ticks_ms"):
            raise ValueError("unsupported measurement clock")
        if report_period_ns < 10000000000 or heap_period_ns < 5000000000:
            raise ValueError("observation periods must remain bounded")
        self._clock = clock
        self.clock_kind = clock_kind
        # Nanosecond units do not establish nanosecond hardware resolution.
        self.resolution_ns = 1000000 if clock_kind == "ticks_ms" else None
        self._heap_sampler = heap_sampler
        self._report_period_ns = report_period_ns
        self._heap_period_ns = heap_period_ns
        self._started = self.now()
        self._last_loop = None
        self._last_report = self._started
        self._last_heap = None
        self._counts = [0] * len(METRICS)
        self._totals = [0] * len(METRICS)
        self._maxima = [0] * len(METRICS)
        self._histograms = [[0] * (len(BUCKET_NS) + 1) for _ in METRICS]
        self._events = [0] * len(EVENTS)
        self._uart_last = [None, None]
        self._uart_qmax = [0, 0]
        self._uart_qsamples = [0, 0]
        self._uart_rx = [0, 0]
        self._uart_tx = [0, 0]
        self._uart_read_max = [0, 0]
        self._parser_pre_samples = [0, 0]
        self._parser_pre_max = [0, 0]
        self._parser_post_samples = [0, 0]
        self._parser_post_max = [0, 0]
        self._parser_post_latest = [None, None]
        self._parser_input = [0, 0]
        self._parser_items = [0, 0]
        self._parser_item_max = [0, 0]
        self._heap_count = 0
        self._heap = None
        self._heap_minima = {}
        self._heap_maxima = {}
        self._sha_bytes = 0
        self._hmac_bytes = 0
        self._sha_max_bytes = 0
        self._hmac_max_bytes = 0
        self._espnow_counts = None
        self._espnow_samples = 0
        self._espnow_success = 0
        self._espnow_failure = 0
        self._espnow_available = False

    def now(self):
        return self._clock()

    def elapsed_ns(self, start, end=None):
        if end is None:
            end = self.now()
        elapsed = (ticks_diff(end, start) * 1000000 if self.clock_kind == "ticks_ms"
                   else end - start)
        if elapsed < 0:
            self.event("clock_regression")
            return None
        return elapsed

    def event(self, name, amount=1):
        self._events[EVENTS.index(name)] += amount

    def espnow_counter_unavailable(self, read_error=False):
        """Unknown is explicit; later valid samples establish a fresh baseline."""
        if read_error:
            self.event("espnow_counter_read_error")
        self.event("espnow_counter_unavailable")
        self._espnow_available = False
        self._espnow_counts = None

    def espnow_counter_reset(self):
        """Native ESPNow reconstruction starts a new counter generation."""
        if self._espnow_samples:
            self.event("espnow_counter_baseline_reset")
        self._espnow_counts = None
        self._espnow_available = False

    def espnow_counters(self, counts):
        """Aggregate observed native callback outcomes, never per-frame inference.

        Native counters are uint32. Modular deltas below 2**31 include ordinary
        uint32 wrap; larger changes are ambiguous (reset/backward observation),
        so retain only the new baseline and explicitly flag the missing delta.
        """
        if any(type(value) is not int or not 0 <= value <= 0xFFFFFFFF for value in counts):
            self.espnow_counter_unavailable()
            return
        previous = self._espnow_counts
        self._espnow_counts = counts
        self._espnow_samples += 1
        self._espnow_available = True
        if previous is None:
            return
        success = (counts[0] - previous[0]) & 0xFFFFFFFF
        failure = (counts[1] - previous[1]) & 0xFFFFFFFF
        if success >= 0x80000000 or failure >= 0x80000000:
            self.event("espnow_counter_discontinuity")
            return
        self._espnow_success += success
        self._espnow_failure += failure

    def finish(self, metric, start, payload_bytes=0, end=None):
        elapsed = self.elapsed_ns(start, end)
        if elapsed is None:
            return
        self._counts[metric] += 1
        self._totals[metric] += elapsed
        if elapsed > self._maxima[metric]:
            self._maxima[metric] = elapsed
        bucket = 0
        while bucket < len(BUCKET_NS) and elapsed > BUCKET_NS[bucket]:
            bucket += 1
        self._histograms[metric][bucket] += 1
        if metric == SHA256:
            self._sha_bytes += payload_bytes
            self._sha_max_bytes = max(self._sha_max_bytes, payload_bytes)
        elif metric == HMAC:
            self._hmac_bytes += payload_bytes
            self._hmac_max_bytes = max(self._hmac_max_bytes, payload_bytes)

    def loop_begin(self):
        now = self.now()
        if self._last_loop is not None:
            self.finish(LOOP, self._last_loop, end=now)
        self._last_loop = now

    def uart_poll(self, index, waiting, observed_at=None):
        if type(waiting) is not int or waiting < 0:
            self.event("uart_observation_unavailable")
            return
        now = self.now() if observed_at is None else observed_at
        previous = self._uart_last[index]
        if previous is not None:
            self.finish(BM_POLL + index, previous, end=now)
        self._uart_last[index] = now
        self._uart_qsamples[index] += 1
        self._uart_qmax[index] = max(self._uart_qmax[index], waiting)

    def uart_read(self, index, byte_count):
        self._uart_rx[index] += byte_count
        self._uart_read_max[index] = max(self._uart_read_max[index], byte_count)

    def uart_write(self, index, byte_count):
        self._uart_tx[index] += byte_count

    def parser_observe(self, index, active_bytes, events=None, input_bytes=0):
        """Pretrim backlog/input or postparse backlog/items; retain no payload."""
        if events is None:
            self._parser_pre_samples[index] += 1
            self._parser_pre_max[index] = max(self._parser_pre_max[index], active_bytes)
            self._parser_input[index] += input_bytes
        else:
            self._parser_post_samples[index] += 1
            self._parser_post_max[index] = max(self._parser_post_max[index], active_bytes)
            self._parser_post_latest[index] = active_bytes
            self._parser_items[index] += events
            self._parser_item_max[index] = max(self._parser_item_max[index], events)

    def sample_heap_if_due(self):
        now = self.now()
        if self._last_heap is not None:
            elapsed = self.elapsed_ns(self._last_heap, now)
            if elapsed is None or elapsed < self._heap_period_ns:
                return
        self._last_heap = now
        try:
            observed = self._heap_sampler()
            self._heap = {}
            self._heap_count += 1
            for name in ("python_gc_free", "python_gc_alloc", "native_8bit_free", "native_8bit_largest"):
                value = observed.get(name)
                self._heap[name] = value if type(value) is int and value >= 0 else None
                if type(value) is int and value >= 0:
                    self._heap_minima[name] = min(self._heap_minima.get(name, value), value)
                    self._heap_maxima[name] = max(self._heap_maxima.get(name, value), value)
        except Exception:
            self.event("heap_sample_error")
            self._heap = None

    def snapshot(self):
        timing = {}
        for index, name in enumerate(METRICS):
            timing[name] = {"samples": self._counts[index],
                            "total_ns": self._totals[index],
                            "max_ns": self._maxima[index] if self._counts[index] else None,
                            "histogram": list(self._histograms[index])}
        uart = []
        parsers = []
        for index, (name, baud, capacity) in enumerate((("bm83", 115200, 8192), ("nextion", 9600, 1024))):
            qmax = self._uart_qmax[index]
            uart.append({"name": name, "baud_8n1": baud, "configured_rx_buffer_bytes": capacity,
                         "capacity_verified": False, "driver_fifo_reserve_bytes": None,
                         "queue_observation": "in_waiting_before_conditional_read_not_full_drain",
                         "native_overflow_events": None,
                         "queue_samples": self._uart_qsamples[index], "max_observed_waiting": qmax,
                         "rx_bytes": self._uart_rx[index], "tx_bytes": self._uart_tx[index],
                         "max_single_read_bytes": self._uart_read_max[index],
                         "nominal_min_wire_headroom_ns": (max(0, capacity - qmax) * 10000000000 // baud
                                                          if self._uart_qsamples[index] else None)})
            parsers.append({"name": name, "item_kind": "event" if index == 0 else "token",
                            "pretrim_samples": self._parser_pre_samples[index],
                            "max_pretrim_active_bytes": self._parser_pre_max[index] if self._parser_pre_samples[index] else None,
                            "postparse_samples": self._parser_post_samples[index],
                            "max_postparse_active_bytes": self._parser_post_max[index] if self._parser_post_samples[index] else None,
                            "latest_postparse_active_bytes": self._parser_post_latest[index],
                            "input_bytes": self._parser_input[index],
                            "returned_items": self._parser_items[index],
                            "max_returned_per_poll": self._parser_item_max[index]})
        return {"schema": 1, "kind": "bm83-phase1-measurements", "clock": self.clock_kind,
                "clock_unit_ns": 1000000 if self.clock_kind == "ticks_ms" else 1,
                "resolution_ns": self.resolution_ns, "elapsed_ns": self.elapsed_ns(self._started),
                "acceptance_budget": "not_derived", "histogram_upper_bounds_ns": BUCKET_NS,
                "timing": timing, "uart": uart, "parsers": parsers,
                "events": dict(zip(EVENTS, self._events)),
                "espnow_callbacks": {"counter_width_bits": 32,
                                     "samples": self._espnow_samples,
                                     "latest_observation_available": self._espnow_available,
                                     "success_observed": self._espnow_success if self._espnow_samples else None,
                                     "failure_observed": self._espnow_failure if self._espnow_samples else None,
                                     "scope": "valid_observed_deltas_not_per_frame_delivery"},
                "heap": {"samples": self._heap_count, "latest": self._heap,
                         "minima": dict(self._heap_minima), "maxima": dict(self._heap_maxima),
                         "native_capability": "MALLOC_CAP_8BIT", "native_dma_only": None,
                         "native_internal_only": None, "native_tx_queue_depth": None,
                         "system_socket_count": None, "gc_forced_by_observer": False},
                "sha256": {"input_bytes": self._sha_bytes, "max_input_bytes": self._sha_max_bytes},
                "hmac": {"input_bytes": self._hmac_bytes, "max_input_bytes": self._hmac_max_bytes}}

    def report_if_due(self, emit=print):
        self.sample_heap_if_due()
        now = self.now()
        elapsed = self.elapsed_ns(self._last_report, now)
        if elapsed is None or elapsed < self._report_period_ns:
            return False
        self._last_report = now
        import json
        started = self.now()
        try:
            emit("[PHASE1] " + json.dumps(self.snapshot()))
        except Exception:
            self.event("report_error")
            return False
        finally:
            self.finish(REPORT, started)
        return True


class TimingUART:
    """Delegate the existing UART unchanged; observe only actual calls/bytes."""

    def __init__(self, uart, metrics, index):
        if index not in (0, 1):
            raise ValueError("UART index must be BM83(0) or Nextion(1)")
        self._uart = uart
        self._metrics = metrics
        self._index = index

    def __getattr__(self, name):
        return getattr(self._uart, name)

    @property
    def in_waiting(self):
        # Begin before the native query: its own cost stays inside the next gap.
        started = self._metrics.now()
        try:
            waiting = self._uart.in_waiting
        except Exception:
            self._metrics.event("uart_observation_unavailable")
            raise
        self._metrics.uart_poll(self._index, waiting, observed_at=started)
        return waiting

    def read(self, size=None):
        started = self._metrics.now()
        try:
            result = self._uart.read(size)
            self._metrics.uart_read(self._index, len(result) if result else 0)
            return result
        except Exception:
            self._metrics.event("uart_read_error")
            raise
        finally:
            self._metrics.finish(BM_READ + self._index, started)

    def write(self, data):
        started = self._metrics.now()
        try:
            result = self._uart.write(data)
            self._metrics.uart_write(self._index, result if type(result) is int and result > 0 else 0)
            return result
        except Exception:
            self._metrics.event("uart_write_error")
            raise
        finally:
            self._metrics.finish(BM_WRITE + self._index, started)
