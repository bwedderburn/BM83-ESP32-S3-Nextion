# Hardware Test Limitations (Host Simulation)

These automated tests intentionally focus on host-simulatable behavior and avoid claiming full end-to-end hardware validation.

## Covered in host tests

- String sanitization and formatting behavior in `utils.common`.
- Parser/tokenization behavior for Nextion token streams, including noisy burst inputs.
- BM83 frame assembly/parsing behavior, including fragmentation and checksum recovery.
- Build-output checks that `.mpy` artifacts are generated when `RUN_MPY_TESTS=1` and `mpy-cross` is present.

## Not fully testable in host simulation

- Real UART timing jitter and electrical-layer framing faults.
- BM83 radio behavior (pairing, reconnect timing, RF coexistence, codec negotiation).
- Nextion display firmware differences across panel versions.
- CircuitPython runtime memory-pressure behavior on the actual MCU.
- Latency and interaction effects across ISR/load patterns on the ESP32-S3 target.

## Practical guidance

Treat host tests as regression protection for deterministic logic, not as proof of full device behavior. Run a hardware validation checklist before releases that touch UART timing, power sequencing, or UI event throughput.
