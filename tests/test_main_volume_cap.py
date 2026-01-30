import sys
import types


def test_volume_repeat_cap_constant():
    """Ensure volume hold repeat cap is present and set to 10."""
    # Stub hardware-specific modules so main can import
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

    import main  # noqa: WPS433

    assert getattr(main, "VOL_REPEAT_MAX", None) == 10

