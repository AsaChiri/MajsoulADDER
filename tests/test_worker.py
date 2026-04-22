import threading
import time

from MajsoulAdder import ClickWorker, Position


class FakeClicker:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls: list[tuple[int, int]] = []
        self.step_event = threading.Event()

    def __call__(self, x, y):
        with self._lock:
            self.calls.append((x, y))
            self.step_event.set()

    @property
    def count(self):
        with self._lock:
            return len(self.calls)


class TimingClicker:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls: list[tuple[int, int, float]] = []

    def __call__(self, x, y):
        with self._lock:
            self.calls.append((x, y, time.perf_counter()))

    @property
    def count(self):
        with self._lock:
            return len(self.calls)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    return predicate()


def test_runs_through_positions_in_order():
    fake = FakeClicker()
    snap = [Position(10, 20), Position(30, 40), Position(50, 60)]
    w = ClickWorker(snap, interval_ms=5, loop_delay_ms=5, click_fn=fake)
    w.start()
    try:
        assert _wait_until(lambda: fake.count >= 3)
    finally:
        w.stop()
    assert fake.calls[:3] == [(10, 20), (30, 40), (50, 60)]


def test_loop_repeats_until_stop():
    fake = FakeClicker()
    snap = [Position(1, 1), Position(2, 2)]
    w = ClickWorker(snap, interval_ms=5, loop_delay_ms=5, click_fn=fake)
    w.start()
    try:
        assert _wait_until(lambda: fake.count >= 4, timeout=2.0)
    finally:
        t0 = time.monotonic()
        w.stop(join_timeout=0.5)
        assert time.monotonic() - t0 < 0.5
    assert w.state == ClickWorker.IDLE


def test_pause_blocks_further_clicks():
    fake = FakeClicker()
    snap = [Position(1, 1)]
    w = ClickWorker(snap, interval_ms=30, loop_delay_ms=10, click_fn=fake)
    w.start()
    try:
        assert fake.step_event.wait(timeout=1.0)
        w.pause()
        time.sleep(0.2)  # generous; > 4x interval+loop
        count_while_paused = fake.count
        time.sleep(0.15)
        assert fake.count == count_while_paused, "clicks happened while paused"
        w.resume()
        assert _wait_until(lambda: fake.count > count_while_paused, timeout=1.0)
    finally:
        w.stop()


def test_stop_from_paused_state_returns():
    """Regression: stop() must unblock a paused run.wait() to avoid deadlock."""
    fake = FakeClicker()
    snap = [Position(1, 1), Position(2, 2)]
    w = ClickWorker(snap, interval_ms=5, click_fn=fake)
    w.start()
    try:
        assert fake.step_event.wait(timeout=1.0)
        w.pause()
        time.sleep(0.05)  # let worker hit run.wait()
        t0 = time.monotonic()
        w.stop(join_timeout=0.5)
        elapsed = time.monotonic() - t0
        assert elapsed < 0.4, f"stop blocked for {elapsed:.3f}s"
    finally:
        w.stop()
    assert w.state == ClickWorker.IDLE


def test_extra_delay_applied_between_steps():
    fake = TimingClicker()
    snap = [Position(1, 1, extra_delay=0.10), Position(2, 2)]
    w = ClickWorker(snap, interval_ms=10, loop_delay_ms=10, click_fn=fake)
    w.start()
    try:
        assert _wait_until(lambda: fake.count >= 3, timeout=2.0)
    finally:
        w.stop()
    gap_after_extra = fake.calls[1][2] - fake.calls[0][2]
    gap_after_normal = fake.calls[2][2] - fake.calls[1][2]
    # position 0 has extra_delay=0.10 → expect ≥ ~0.10 + 0.01 interval
    assert gap_after_extra >= 0.08, f"gap_after_extra={gap_after_extra:.3f}"
    # position 1 has no extra delay → expect ~interval + loop_delay = 0.02
    assert gap_after_normal < 0.08, f"gap_after_normal={gap_after_normal:.3f}"


def test_empty_positions_list_is_no_op():
    fake = FakeClicker()
    w = ClickWorker([], interval_ms=5, click_fn=fake)
    w.start()
    # Worker should exit _loop almost immediately; give it time.
    time.sleep(0.05)
    t0 = time.monotonic()
    w.stop(join_timeout=0.5)
    assert time.monotonic() - t0 < 0.5
    assert fake.count == 0
    assert w.state == ClickWorker.IDLE
