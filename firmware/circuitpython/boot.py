"""Set the controller's workflow policy before USB and BLE start."""
import supervisor

# A host write to CIRCUITPY can interrupt the active radio runtime during
# teardown. Keep the drive available and restart explicitly after updates.
supervisor.runtime.autoreload = False

# The maintenance workflow otherwise advertises CIRCUITPYxxxx before main.py
# gives the HID remote its stable name, and can advertise again after a user
# pauses HID. This leaves USB, Wi-Fi, the BLE adapter and saved bonds intact.
try:
    supervisor.runtime.ble_workflow = False
except Exception as exc:
    print("[BLE] Background workflow control unavailable:", exc)
