# select_port.py — PlatformIO pre-script: resolve the CrowPanel's CH340
# (USB VID:PID 1A86:7523) to whatever COM port it holds right now.
#
# Why: the COM number moves between sessions, and a stale fixed default
# could aim a flash at whichever device now owns it — the BM83 audio
# board's CircuitPython console (303A:7003) must NEVER be a fallback
# target. So this script only ever selects an exact 1A86:7523 match:
#   - exactly one match  -> upload_port is set to it
#   - none, or ambiguous -> upload_port stays unset and `pio run -t upload`
#                           stops with "Please specify upload_port" instead
#                           of auto-detecting another board.
# An explicit --upload-port on the command line is left untouched.

Import("env")  # noqa: F821 — provided by PlatformIO's SCons runtime
from serial.tools import list_ports

CROWPANEL_HWID = "1A86:7523"

if env.get("UPLOAD_PORT"):  # noqa: F821
    print("select_port.py: upload_port already set (%s) - leaving it"
          % env.get("UPLOAD_PORT"))  # noqa: F821
else:
    matches = [p.device for p in list_ports.comports()
               if CROWPANEL_HWID in (p.hwid or "")]
    if len(matches) == 1:
        print("select_port.py: CrowPanel CH340 at %s" % matches[0])
        env.Replace(UPLOAD_PORT=matches[0])  # noqa: F821
    elif not matches:
        print("select_port.py: no CH340 (%s) attached - upload will refuse"
              % CROWPANEL_HWID)
    else:
        print("select_port.py: multiple CH340s (%s) - pass --upload-port"
              % ", ".join(matches))
