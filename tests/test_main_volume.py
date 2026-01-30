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
    # Verify that main module has expected attributes
    assert hasattr(main, 'main')
    assert callable(main.main)
    assert hasattr(main, 'BLE_ENABLED')
    assert hasattr(main, 'BLE_NAME')
