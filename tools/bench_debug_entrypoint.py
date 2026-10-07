"""Optional, temporary CircuitPython ``code.py`` for hardware debug captures.

Before installing, back up the device's existing code.py and main.py, including
whether either file was absent. Copy this file as code.py alongside the unchanged
production main.py and lib/ modules. CircuitPython prefers code.py over main.py.
A deliberate reload is required to start it; this wrapper disables automatic
reloads during the capture. Restore the previous entrypoint files and reload again
when finished. Never call main.main() a second time in the same interpreter: its
UART/radio resources are initialized by main() and require a reload to restart.

DEBUG output changes allocations, execution timing, and serial output load. Use
these captures to inspect protocol/state transitions, not as a production timing
or performance verdict. The wrapper adds no test actuator, pairing request, bond
erase, or power-cycle sequence; the normal firmware continues to handle inputs.

Each DEBUG line includes the on-device supervisor.ticks_ms() value, avoiding host
serial-read batching as the timestamp source. These integers wrap at 2**29 ms;
use utils.ticks.ticks_diff(new, old) for elapsed times under 2**28 ms. The prefix
is added only to common.dprint; ordinary firmware print() output is untouched.
"""
import time

import supervisor

from utils import common


def _bench_dprint(*args):
    """Keep the DEBUG gate and add an integer device tick to debug messages."""
    if common.DEBUG:
        print("[BENCH ticks_ms=%d]" % supervisor.ticks_ms(), *args)


def run():
    """Enable capture instrumentation and enter the production firmware once."""
    supervisor.runtime.autoreload = False
    # Install before main imports dprint into BM83/Nextion/BLE/remote modules.
    common.dprint = _bench_dprint
    common.DEBUG = True
    print("[BENCH] Debug capture: common.DEBUG=True; autoreload disabled")
    print("[BENCH] Debug output changes allocation/timing; not a performance verdict")
    print("[BENCH] Running production main once; restore entrypoint and reload after capture")

    # Match main.py's boundary: hardware/module import errors are outside its
    # runtime fatal handler. Import only after DEBUG is enabled for startup logs.
    import main as firmware_main

    try:
        firmware_main.main()
    except Exception as e:
        # Keep the production entrypoint's diagnostics and fatal hold behavior.
        # KeyboardInterrupt/SystemExit retain their usual interpreter behavior.
        try:
            import traceback
            print("[FATAL]", e)
            traceback.print_exception(e)
        except Exception:
            print("[FATAL]", e)
        while True:
            time.sleep(1)


if __name__ == "__main__":
    run()
