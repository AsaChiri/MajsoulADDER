# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Run the app: `uv run python MajsoulAdder.py`
- Run all tests: `uv run pytest`
- Run a single test file: `uv run pytest tests/test_worker.py`
- Run a single test: `uv run pytest tests/test_worker.py::test_pause_blocks_further_clicks`

`pyproject.toml` pins `testpaths = ["tests"]` and `pythonpath = ["."]`, so tests import directly from the top-level `MajsoulAdder` module.

## Architecture

The entire application lives in a single file, `MajsoulAdder.py`, and is deliberately layered so the pure logic can be unit-tested without Tk, pynput, or Win32 dependencies. Tests import and drive those pure layers; the Tk/pynput glue is exercised only by manual runs.

Layers, from pure to side-effectful:

1. **`_compute_ex_style`** — pure bit-twiddling for the Win32 `WS_EX_LAYERED | WS_EX_TRANSPARENT` flags used to make the overlay click-through. The only Win32 logic that's unit-tested; the `ctypes` call site in `OverlayWindow._apply_clickthrough` wraps it.
2. **`Position` / `PositionModel`** — dataclass + in-memory list with a listener callback pattern. `snapshot()` returns independent copies so consumers (worker, overlay) cannot mutate model state. All mutations call `_notify()`, which the UI subscribes to via `root.after(0, ...)` to marshal back to the Tk thread.
3. **`ClickWorker`** — replays a `Position` snapshot on a background daemon thread. Uses two `threading.Event`s: `_run` (set = running, clear = paused) and `_stop` (terminate). `stop()` sets `_run` before `_stop` to unblock a paused `_run.wait()` — the `test_stop_from_paused_state_returns` regression test guards this. `click_fn` and `sleep_fn` are injected so tests can substitute fakes; production path calls `pynput.mouse.Controller`.
4. **`CaptureController`** — owns the "add position" / "re-record" flows. Takes `mouse_listener_factory` and `keyboard_listener_factory` as injected callables so tests replace `pynput.Listener` with `FakeListener`. Append mode keeps listening until Esc or a non-left click; replace mode auto-stops after one left click. A `threading.Lock` guards mode transitions.
5. **`OverlayWindow`** — transparent full-screen `Toplevel` that draws numbered red circles on a magenta (`#ff00fe`) `-transparentcolor` background. Click-through is applied by calling `_compute_ex_style` and `SetWindowLongW` via `ctypes`. Redraws on model-change notifications.
6. **`HotkeyBinder`** — thin wrapper around `pynput.keyboard.GlobalHotKeys` for F7/F8/F9/F10.
7. **`App`** — Tk UI and wiring. All cross-thread callbacks (worker, capture, hotkeys) funnel through `self.root.after(0, ...)` before touching widgets.

### Threading model

- Tk main thread owns all widgets.
- `ClickWorker` runs in its own daemon thread and emits `on_step` / `on_state` callbacks — the `App` bridges them back to Tk with `root.after(0, ...)`.
- `pynput` listeners (mouse, keyboard, hotkeys) run in their own threads and likewise bridge back via `root.after`.
- `PositionModel` is only mutated from the Tk thread; the worker reads a `snapshot()` taken at `start()` time, so subsequent model edits don't affect an in-flight loop.

### Testing conventions

- `test_model.py`, `test_worker.py`, `test_capture.py`, and `test_overlay_clickthrough.py` each cover one pure layer. No test touches Tk or real input devices.
- `ClickWorker` tests inject a `FakeClicker` / `TimingClicker` callable and use `_wait_until` polling on `threading.Event`s — do not add real `time.sleep` waits that exceed a few hundred ms.
- `CaptureController` tests inject `FakeListener` factories and call `.callback(...)` directly to simulate input events.
- When adding a feature that crosses layers, add the test at the lowest layer where the logic lives and keep the Tk glue thin enough that it doesn't need coverage.
