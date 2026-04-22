import pytest

from MajsoulAdder import Position, PositionModel


def test_add_appends_and_notifies():
    m = PositionModel()
    calls = []
    m.add_listener(lambda: calls.append(1))
    m.add(10, 20)
    assert len(m) == 1
    assert m[0] == Position(10, 20, 0.0)
    assert len(calls) == 1


def test_replace_updates_only_target_index():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    m.add(3, 3)
    m.replace(1, 99, 99)
    assert m[0] == Position(1, 1, 0.0)
    assert m[1] == Position(99, 99, 0.0)
    assert m[2] == Position(3, 3, 0.0)


def test_replace_preserves_extra_delay():
    m = PositionModel()
    m.add(1, 1, extra_delay=0.5)
    m.replace(0, 10, 20)
    assert m[0].extra_delay == 0.5


def test_delete_shifts_indices():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    m.add(3, 3)
    m.delete(1)
    assert len(m) == 2
    assert m[0] == Position(1, 1, 0.0)
    assert m[1] == Position(3, 3, 0.0)


def test_move_up_swaps_with_previous():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    m.move_up(0)
    assert m[0] == Position(1, 1, 0.0)
    m.move_up(1)
    assert m[0] == Position(2, 2, 0.0)
    assert m[1] == Position(1, 1, 0.0)


def test_move_down_swaps_with_next():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    m.move_down(1)
    assert m[1] == Position(2, 2, 0.0)
    m.move_down(0)
    assert m[0] == Position(2, 2, 0.0)
    assert m[1] == Position(1, 1, 0.0)


def test_clear_empties_and_notifies():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    calls = []
    m.add_listener(lambda: calls.append(1))
    m.clear()
    assert len(m) == 0
    assert len(calls) == 1


def test_set_extra_delay_validates():
    m = PositionModel()
    m.add(1, 1)
    m.set_extra_delay(0, 1.25)
    assert m[0].extra_delay == 1.25
    with pytest.raises(ValueError):
        m.set_extra_delay(0, -0.5)


def test_snapshot_is_independent_copy():
    m = PositionModel()
    m.add(1, 1)
    m.add(2, 2)
    snap = m.snapshot()
    snap[0].x = 999
    snap.append(Position(7, 7))
    assert m[0].x == 1
    assert len(m) == 2
