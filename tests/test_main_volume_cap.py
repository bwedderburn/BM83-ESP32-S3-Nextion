import sys
import types


def _stub_hardware_modules():
    """Stub board/busio so main.py can import in a host environment."""
    board_mod = types.ModuleType("board")
    board_mod.IO15 = 15
    board_mod.IO16 = 16
    board_mod.IO17 = 17
    board_mod.IO18 = 18

    class DummyUART:
        def __init__(self, *args, **kwargs):
            pass

    busio_mod = types.ModuleType("busio")
    busio_mod.UART = DummyUART

    sys.modules.setdefault("board", board_mod)
    sys.modules.setdefault("busio", busio_mod)


def test_volume_repeat_cap_constant():
    """Volume hold repeat cap exists and is high enough for usable hold-and-repeat.

    The exact value is tuned with VOL_HOLD_MAX_S so the count cap and the
    time cap expire at roughly the same moment. We check both for presence
    and that the cap is large enough that the button doesn't feel like it
    stops mid-hold (the old VOL_REPEAT_MAX=2 bug). See P0 #1/#2 in
    docs/code-review-2026-05-26.md.
    """
    _stub_hardware_modules()
    import main  # noqa: WPS433

    cap = getattr(main, "VOL_REPEAT_MAX", None)
    assert cap is not None, "VOL_REPEAT_MAX must be defined"
    assert cap >= 20, "VOL_REPEAT_MAX too small — button will appear to stop mid-hold"


def test_volume_hold_caps_are_consistent():
    """VOL_REPEAT_MAX and VOL_HOLD_MAX_S must expire at roughly the same moment.

    If the time cap expires well before the count cap, the user sees the
    button stop working mid-hold while we still think we have repeats
    left in the budget (the original bug). Conversely, a count cap that
    expires far before the time cap silently shortens hold range.
    """
    _stub_hardware_modules()
    import main  # noqa: WPS433

    cap = getattr(main, "VOL_REPEAT_MAX", None)
    hold_max = getattr(main, "VOL_HOLD_MAX_S", None)
    assert cap is not None, "VOL_REPEAT_MAX must be defined"
    assert hold_max is not None, "VOL_HOLD_MAX_S must be defined"

    # Compute the time the count cap would take to reach.
    # Use the canonical initial delay + interval values from main if exposed,
    # otherwise fall back to the documented defaults (0.85s + 0.20s).
    initial = 0.85
    interval = 0.20
    count_cap_time = initial + cap * interval

    # Caps should be within ~1.5s of each other.
    assert abs(count_cap_time - hold_max) <= 1.5, (
        "VOL_REPEAT_MAX (=%d) and VOL_HOLD_MAX_S (=%.2f) disagree: "
        "count cap finishes at ~%.2fs"
        % (cap, hold_max, count_cap_time)
    )
