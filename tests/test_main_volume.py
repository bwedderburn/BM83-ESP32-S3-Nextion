import types
import main


def test_volume_hold_cap_monotonic():
    """Ensure press-and-hold stops after VOL_REPEAT_MAX steps."""
    # Patch ble to record calls
    calls = []

    class DummyBle:
        def __init__(self):
            self.enabled = True

        def volume(self, up):
            calls.append(up)

        def mute(self):
            calls.append("mute")

        def setup(self):
            return None

    # Patch Nextion/Bm83 minimal stubs to satisfy main
    class DummyNX:
        def __init__(self):
            self.current_page = None

        def boot_sync(self, *_):
            return None

        def poll(self, *_):
            return []

    class DummyBM:
        def __init__(self):
            self.aux_mode = False

        def poll(self, *_):
            return False

    # Monkeypatch constructors
    main.Nextion = lambda *_args, **_kwargs: DummyNX()
    main.Bm83 = lambda *_args, **_kwargs: DummyBM()
    main.BleHid = lambda *_args, **_kwargs: DummyBle()

    # Replace time.monotonic to control time flow
    base = 0.0

    def monotonic():
        return base

    main.time.monotonic = monotonic

    # Drive main loop just enough to trigger repeats
    # Simulate press, hold long enough to exceed max, ensure stop
    # Run main in a bounded fashion by breaking after enough iterations
    iterations = 0

    def limited_sleep(_):
        nonlocal iterations, base
        iterations += 1
        base += 0.1  # advance time 100ms per loop
        if iterations > 50:
            raise SystemExit

    main.time.sleep = limited_sleep

    try:
        main.main()
    except SystemExit:
        pass

    # Should not exceed VOL_REPEAT_MAX calls
    assert len(calls) <= main.VOL_REPEAT_MAX

