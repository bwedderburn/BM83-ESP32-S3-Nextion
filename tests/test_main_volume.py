import sys
from unittest import mock

# Mock CircuitPython modules for CI/testing
# These mocks are required because main.py imports board and busio,
# which are CircuitPython-specific hardware modules not available in CI
sys.modules['board'] = mock.MagicMock()
sys.modules['busio'] = mock.MagicMock()

import main  # noqa: E402


def test_main_imports():
    """Test that main module can be imported with mocked CircuitPython modules.

    This test verifies that the mocking approach allows main.py to be imported
    in CI environments without CircuitPython hardware. Volume-specific functional
    tests can be added here as needed.
    """
    # Verify that main module has expected attributes. Volume now flows through
    # the BM83 UART (Set_Overall_Gain 0x23) instead of BLE HID, so we assert
    # against the BM83-side constants rather than the old BLE_* shims.
    assert hasattr(main, 'main')
    assert callable(main.main)
    assert hasattr(main, 'VOL_REPEAT_MAX')
