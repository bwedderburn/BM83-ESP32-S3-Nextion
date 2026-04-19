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
    # Verify that main exposes the expected top-level attributes. Current volume
    # routing is split: A2DP volume uses BLE HID, while AUX uses BM83 MMI
    # Line-In gain commands (0x82/0x83). This test is only an import smoke test.
    assert hasattr(main, 'main')
    assert callable(main.main)
    assert hasattr(main, 'VOL_REPEAT_MAX')
