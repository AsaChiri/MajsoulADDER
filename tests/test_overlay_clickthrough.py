from MajsoulAdder import (
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    _compute_ex_style,
)


def test_sets_layered_and_transparent_bits():
    result = _compute_ex_style(0)
    assert result & WS_EX_LAYERED
    assert result & WS_EX_TRANSPARENT


def test_preserves_existing_bits():
    existing = 0x00000008  # some unrelated bit
    result = _compute_ex_style(existing)
    assert result & 0x00000008
    assert result & WS_EX_LAYERED
    assert result & WS_EX_TRANSPARENT


def test_idempotent():
    once = _compute_ex_style(0x00000008)
    twice = _compute_ex_style(once)
    assert once == twice
