"""Let the application own BLE advertising before workflow startup."""
import supervisor

# The maintenance workflow otherwise advertises CIRCUITPYxxxx before main.py
# gives the HID remote its stable name, and can advertise again after a user
# pauses HID. This leaves USB, Wi-Fi, the BLE adapter and saved bonds intact.
try:
    supervisor.runtime.ble_workflow = False
except Exception as exc:
    print("[BLE] Background workflow control unavailable:", exc)
