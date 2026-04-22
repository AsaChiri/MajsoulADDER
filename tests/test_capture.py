import pytest
from pynput import keyboard as pk
from pynput import mouse as pm

from MajsoulAdder import CaptureController, Position, PositionModel


class FakeListener:
    def __init__(self, callback):
        self.callback = callback
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeListenerStore:
    def __init__(self):
        self.mouse: FakeListener | None = None
        self.keyboard: FakeListener | None = None

    def mouse_factory(self, on_click):
        self.mouse = FakeListener(on_click)
        return self.mouse

    def keyboard_factory(self, on_press):
        self.keyboard = FakeListener(on_press)
        return self.keyboard


def _make(model=None):
    m = model if model is not None else PositionModel()
    s = FakeListenerStore()
    c = CaptureController(
        m,
        mouse_listener_factory=s.mouse_factory,
        keyboard_listener_factory=s.keyboard_factory,
    )
    return m, c, s


def test_append_mode_records_left_press():
    m, c, s = _make()
    c.start_append()
    assert s.mouse.started and s.keyboard.started
    s.mouse.callback(100, 200, pm.Button.left, True)
    assert len(m) == 1
    assert m[0] == Position(100, 200, 0.0)
    assert c.active  # still capturing — append mode allows multiple clicks
    c.stop()


def test_append_ignores_releases():
    m, c, s = _make()
    c.start_append()
    s.mouse.callback(100, 200, pm.Button.left, False)
    assert len(m) == 0
    c.stop()


def test_append_ignores_right_and_middle_buttons_and_stops_capture():
    m, c, s = _make()
    c.start_append()
    s.mouse.callback(50, 50, pm.Button.right, True)
    assert len(m) == 0
    assert not c.active
    # A subsequent click does nothing
    s.mouse.callback(70, 70, pm.Button.left, True)
    assert len(m) == 0


def test_replace_mode_replaces_selected_and_auto_stops():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    m.add(3, 3)
    _, c, s = _make(m)
    c.start_replace(1)
    s.mouse.callback(7, 7, pm.Button.left, True)
    assert m[0] == Position(1, 1, 0.0)
    assert m[1] == Position(7, 7, 0.0)
    assert m[2] == Position(3, 3, 0.0)
    assert not c.active
    # Further clicks ignored
    s.mouse.callback(99, 99, pm.Button.left, True)
    assert m[1] == Position(7, 7, 0.0)


def test_esc_key_ends_append_capture():
    m, c, s = _make()
    c.start_append()
    s.keyboard.callback(pk.Key.esc)
    assert not c.active
    # Clicks after Esc are ignored
    s.mouse.callback(10, 10, pm.Button.left, True)
    assert len(m) == 0


def test_double_start_is_rejected():
    _, c, _ = _make()
    c.start_append()
    with pytest.raises(RuntimeError):
        c.start_append()
    c.stop()


def test_start_replace_validates_index():
    _, c, _ = _make()
    with pytest.raises(IndexError):
        c.start_replace(0)  # empty model
