"""Exercise App actions without Tk windows, input hooks, or real mouse clicks."""

from unittest.mock import Mock

import pytest
from pynput import keyboard, mouse

import MajsoulAdder as adder
from tests.test_capture import FakeListenerStore


class ManualWorker(adder.ClickWorker):
    """Use the real worker state transitions, but advance clicks explicitly."""

    def start(self):
        self._stop.clear()
        self._run.set()
        self._set_state(self.RUNNING)

    def emit_click(self):
        if self.state == self.RUNNING:
            pos = self._snapshot[0]
            self._click(pos.x, pos.y)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(adder, "ClickWorker", ManualWorker)
    # Bypass GUI construction; exercise the same handlers used by buttons/hotkeys.
    app = adder.App.__new__(adder.App)
    app.root = Mock()
    app.overlay = Mock()
    app.var_overlay = Mock()
    app.var_interval = Mock(get=lambda: 20)
    app.var_loop = Mock(get=lambda: 100)
    app.status_var = Mock()
    app.btn_start = Mock()
    app.btn_pause = Mock()
    app.btn_stop = Mock()
    app.tree = Mock(selection=lambda: ("1",))
    app.model = adder.PositionModel()
    app.model.add(10, 20)
    app.model.add(30, 40, extra_delay=0.5)
    app.model.add(50, 60)
    app._worker = None
    app.listeners = FakeListenerStore()
    app.capture = adder.CaptureController(
        app.model,
        mouse_listener_factory=app.listeners.mouse_factory,
        keyboard_listener_factory=app.listeners.keyboard_factory,
    )

    def deliver_playback_press(button):
        # Model receipt of a playback press by capture, not OS event delivery.
        listener = app.listeners.mouse
        if listener and listener.started and not listener.stopped:
            listener.callback(*app._controller.position, button, True)

    app._controller = Mock(click=Mock(side_effect=deliver_playback_press))
    yield app
    app._stop()
    app.capture.stop()


@pytest.mark.parametrize("capture_action", ["_add", "_re_record"])
def test_playback_cannot_start_capture(app, capture_action):
    app._start()  # F7
    before = app.model.snapshot()
    getattr(app, capture_action)()  # F10 or Re-record
    app._worker.emit_click()

    assert app.model.snapshot() == before
    assert not app.capture.active
    assert app.listeners.mouse is None
    app.root.withdraw.assert_not_called()
    app.overlay.show.assert_not_called()
    app._controller.click.assert_called_once_with(mouse.Button.left)


@pytest.mark.parametrize("capture_action", ["_add", "_re_record"])
def test_paused_playback_cannot_capture_then_resume(app, capture_action):
    app._start()
    app._toggle_pause()  # F8
    before = app.model.snapshot()
    getattr(app, capture_action)()
    app._toggle_pause()  # F8 again
    app._worker.emit_click()

    assert app.model.snapshot() == before
    assert not app.capture.active
    assert app.listeners.mouse is None
    assert app._worker.state == adder.ClickWorker.RUNNING
    app.root.withdraw.assert_not_called()


@pytest.mark.parametrize("capture_action", ["_add", "_re_record"])
def test_capture_cannot_start_playback_while_window_hidden(app, capture_action):
    getattr(app, capture_action)()
    app.root.withdraw.assert_called_once()
    before = app.model.snapshot()
    app._start()  # F7 still reaches this handler while the window is hidden.
    if app._worker:
        app._worker.emit_click()

    assert app.model.snapshot() == before
    assert app.capture.active
    assert app._worker is None
    app._controller.click.assert_not_called()


def test_resume_is_guarded_even_if_paused_worker_and_capture_coexist(app):
    app._start()
    app._toggle_pause()
    # Set up the formerly reachable state directly to cover the resume guard.
    app.capture.start_append()
    before = app.model.snapshot()
    app._toggle_pause()
    app._worker.emit_click()

    assert app._worker.state == adder.ClickWorker.PAUSED
    assert app.model.snapshot() == before
    app._controller.click.assert_not_called()


@pytest.mark.parametrize("finish", ["escape", "right_click"])
def test_stopped_playback_allows_continuous_append_until_finished(app, finish):
    app._start()
    app._toggle_pause()
    app._stop()  # F9 releases playback before F10.
    app._add()
    listener = app.listeners.mouse
    before = app.model.snapshot()
    listener.callback(70, 80, mouse.Button.left, True)
    listener.callback(70, 80, mouse.Button.left, False)
    assert app.capture.active
    listener.callback(90, 100, mouse.Button.left, True)
    assert app.capture.active
    assert app.model.snapshot() == before + [
        adder.Position(70, 80), adder.Position(90, 100)
    ]
    app._add()  # Repeated F10 must leave the current capture in place.
    assert app.listeners.mouse is listener

    if finish == "escape":
        app.listeners.keyboard.callback(keyboard.Key.esc)
    else:
        listener.callback(0, 0, mouse.Button.right, True)
    assert not app.capture.active
    assert listener.stopped and app.listeners.keyboard.stopped
    listener.callback(999, 999, mouse.Button.left, True)
    assert len(app.model) == len(before) + 2
    app._start()
    app._worker.emit_click()
    app._controller.click.assert_called_once_with(mouse.Button.left)


def test_stopped_playback_allows_one_replacement_then_playback(app):
    app._start()
    app._stop()
    before = app.model.snapshot()
    app._re_record()
    listener = app.listeners.mouse
    listener.callback(70, 80, mouse.Button.left, True)

    assert not app.capture.active
    assert listener.stopped and app.listeners.keyboard.stopped
    listener.callback(999, 999, mouse.Button.left, True)
    assert app.model.snapshot() == [
        before[0], adder.Position(70, 80, extra_delay=0.5), before[2]
    ]
    app._start()
    app._worker.emit_click()
    app._controller.click.assert_called_once_with(mouse.Button.left)


@pytest.mark.parametrize("paused", [False, True])
def test_playback_buttons_follow_capture_guard(app, paused):
    if paused:
        app._start()
        app._toggle_pause()
    app.capture.start_append()
    app._update_buttons()
    app.btn_start.configure.assert_called_with(state="disabled")
    app.btn_pause.configure.assert_called_with(
        text="Resume" if paused else "Pause", state="disabled"
    )

    app.capture.stop()
    app._update_buttons()
    if paused:
        app.btn_pause.configure.assert_called_with(text="Resume", state="normal")
    else:
        app.btn_start.configure.assert_called_with(state="normal")
